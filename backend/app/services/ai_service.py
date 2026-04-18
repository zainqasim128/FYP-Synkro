"""
AI services using Groq (free) with OpenAI fallback.
Includes transcription, summarization, intent classification, and entity extraction.

Groq provides FREE access to:
- Whisper Large v3 Turbo (transcription)
- Llama 3.3 70B (summarization, classification, extraction)

Get a free key at: https://console.groq.com/keys
"""
import os
import json
import logging
from typing import Optional, Dict, Any, List
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# Initialize clients - prefer Groq (free), fall back to OpenAI (paid)
groq_client = None
openai_client = None

if settings.GROQ_API_KEY:
    groq_client = AsyncOpenAI(
        api_key=settings.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )
    logger.info("AI Service: Using Groq (FREE)")

if settings.OPENAI_API_KEY:
    openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    if not groq_client:
        logger.info("AI Service: Using OpenAI (paid)")


def _get_transcription_client():
    """Get client for transcription (Groq preferred)."""
    if groq_client:
        return groq_client, "whisper-large-v3-turbo"
    if openai_client:
        return openai_client, "whisper-1"
    raise RuntimeError("No AI API key configured. Set GROQ_API_KEY (free) or OPENAI_API_KEY in .env")


def _get_chat_client():
    """Get client for chat/summarization (Groq preferred)."""
    if groq_client:
        return groq_client, "llama-3.3-70b-versatile"
    if openai_client:
        return openai_client, "gpt-4"
    raise RuntimeError("No AI API key configured. Set GROQ_API_KEY (free) or OPENAI_API_KEY in .env")


async def transcribe_meeting(audio_file_path: str) -> str:
    """
    Transcribe audio file using Whisper API.

    Returns:
        Formatted transcript string with timestamps.
    """
    text, _ = await transcribe_meeting_with_segments(audio_file_path)
    return text


async def transcribe_meeting_with_segments(audio_file_path: str):
    """
    Transcribe audio file using Whisper API (Groq free or OpenAI paid).

    Returns:
        (formatted_transcript: str, whisper_segments: list)
        whisper_segments is a list of {"start", "end", "text"} dicts — empty list if unavailable.
    """
    try:
        client, model = _get_transcription_client()

        file_size = os.path.getsize(audio_file_path)
        max_size = 25 * 1024 * 1024  # 25MB
        if file_size > max_size:
            raise ValueError(f"File size {file_size} exceeds maximum of {max_size} bytes")

        logger.info(f"Transcribing with {model} via {'Groq' if client == groq_client else 'OpenAI'}")

        with open(audio_file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                response_format="verbose_json",
                language="en",
            )

        raw_segments = getattr(transcript, 'segments', None) or []

        # Normalise to plain dicts
        whisper_segments = []
        for seg in raw_segments:
            if isinstance(seg, dict):
                whisper_segments.append({
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                    "text": seg.get("text", "").strip(),
                })
            else:
                whisper_segments.append({
                    "start": getattr(seg, "start", 0),
                    "end": getattr(seg, "end", 0),
                    "text": getattr(seg, "text", "").strip(),
                })

        if whisper_segments:
            lines = [
                f"[{format_timestamp(s['start'])}] {s['text']}"
                for s in whisper_segments if s["text"]
            ]
            return "\n".join(lines), whisper_segments

        return transcript.text, []

    except Exception as e:
        raise Exception(f"Transcription failed: {str(e)}")


def format_timestamp(seconds: float) -> str:
    """Format seconds into MM:SS format"""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


async def summarize_meeting(transcript: str, title: str) -> Dict[str, Any]:
    """
    Generate structured summary from meeting transcript.
    Uses Groq (free Llama 3.3 70B) or OpenAI GPT-4.
    """
    try:
        client, model = _get_chat_client()

        prompt = f"""You are a professional meeting summarizer. Analyze this meeting transcript and provide a comprehensive summary.

Meeting Title: {title}

Transcript:
{transcript}

Please provide a structured summary with the following sections:

## KEY TOPICS
Summarize the main discussion points (2-3 sentences each).

## DECISIONS MADE
List important decisions made during the meeting (bullet points).

## ACTION ITEMS
Extract specific action items in this format:
- [ ] Task description (Assignee: @name, Deadline: YYYY-MM-DD if mentioned)

## BLOCKERS
List any issues, blockers, or concerns raised.

## NEXT STEPS
Describe what happens next and any follow-up needed.

Use professional tone and be concise but capture all critical details."""

        logger.info(f"Summarizing with {model} via {'Groq' if client == groq_client else 'OpenAI'}")

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a professional meeting summarizer who creates clear, actionable summaries."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )

        summary_text = response.choices[0].message.content

        # Extract action items from the summary
        action_items = await extract_action_items_from_summary(summary_text)

        return {
            "summary": summary_text,
            "action_items": action_items
        }

    except Exception as e:
        raise Exception(f"Summarization failed: {str(e)}")


async def extract_action_items_from_summary(summary: str) -> List[Dict[str, Any]]:
    """Extract structured action items from summary text."""
    try:
        client, model = _get_chat_client()

        prompt = f"""Extract action items from this meeting summary and return them as a JSON array.

For each action item, identify:
- description: The task to be done
- assignee: Person mentioned (name or @mention), null if not specified
- deadline: Date mentioned (YYYY-MM-DD format), null if not specified
- confidence: Your confidence in this extraction (0.0 to 1.0)

Summary:
{summary}

Return ONLY a JSON array, no other text. Format:
[
  {{"description": "Task description", "assignee": "John Doe", "deadline": "2024-03-15", "confidence": 0.9}},
  {{"description": "Another task", "assignee": null, "deadline": null, "confidence": 0.7}}
]

If no action items found, return []."""

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a precise task extractor. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1000
        )

        result_text = response.choices[0].message.content.strip()

        # Parse JSON response
        try:
            action_items = json.loads(result_text)
            return action_items if isinstance(action_items, list) else []
        except json.JSONDecodeError:
            return []

    except Exception as e:
        print(f"Action item extraction failed: {str(e)}")
        return []


async def classify_intent(message: str) -> Dict[str, Any]:
    """Classify the intent of a message."""
    try:
        client, model = _get_chat_client()

        prompt = f"""Classify the intent of this message into ONE of these categories:
- task_request: Requesting someone to do something
- blocker: Reporting a problem or blocker
- question: Asking a question
- information: Sharing information or updates
- urgent_issue: Urgent problem requiring immediate attention
- casual: Casual conversation or greeting

Message: "{message}"

Respond with ONLY a JSON object:
{{"intent": "category_name", "confidence": 0.95}}"""

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a message intent classifier. Respond only with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=50
        )

        result_text = response.choices[0].message.content.strip()

        try:
            result = json.loads(result_text)
            return {
                "intent": result.get("intent", "information"),
                "confidence": float(result.get("confidence", 0.5))
            }
        except (json.JSONDecodeError, ValueError):
            return {"intent": "information", "confidence": 0.5}

    except Exception as e:
        print(f"Intent classification failed: {str(e)}")
        return {"intent": "information", "confidence": 0.0}


async def extract_task_entities(message: str) -> Dict[str, Any]:
    """Extract task details from a message."""
    try:
        client, model = _get_chat_client()

        prompt = f"""Extract task details from this message and return a JSON object.

Message: "{message}"

Return ONLY a JSON object with these fields:
{{"description": "Clear task description", "assignee": "Person name or null", "deadline": "YYYY-MM-DD or null", "priority": "low|medium|high|urgent"}}"""

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Extract task information from messages. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=200
        )

        result_text = response.choices[0].message.content.strip()

        try:
            entities = json.loads(result_text)
            entities["confidence"] = 0.8
            return entities
        except json.JSONDecodeError:
            return {"confidence": 0.0}

    except Exception as e:
        print(f"Entity extraction failed: {str(e)}")
        return {"confidence": 0.0}


async def chat_query(query: str, context: Dict[str, Any]) -> str:
    """Process a natural language query about tasks, meetings, or team info."""
    try:
        client, model = _get_chat_client()

        context_text = f"""You are Synkro AI Assistant, helping a software development team with productivity queries.

Available Data:
{json.dumps(context, indent=2, default=str)}

User Query: {query}

Provide a helpful, conversational response based on the data. If suggesting actions, be specific. If data is missing, acknowledge it politely."""

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are Synkro AI Assistant, a helpful productivity assistant for software teams."},
                {"role": "user", "content": context_text}
            ],
            temperature=0.7,
            max_tokens=500
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"I apologize, but I encountered an error processing your query: {str(e)}"
