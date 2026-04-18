"""
Meeting Analysis Service — Context-Aware Utterance Classification

Takes a diarized transcript (speaker-labeled segments) and:
1. Classifies each utterance by context type
2. Extracts task assignments with full attribution (who assigned to whom)
3. Identifies warnings, completions, and progress updates
4. Returns enriched action items with speaker metadata

Context types:
  - task_assignment  : "John, can you finish the login page by Friday?"
  - task_completion  : "I've completed the API integration."
  - warning          : "We might miss the deadline if we don't fix this."
  - progress_update  : "The frontend is about 70% done."
  - question         : "What's the status of the database migration?"
  - decision         : "We've decided to use PostgreSQL for this."
  - general          : General discussion
"""
import json
import logging
import re
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


async def analyze_meeting_context(
    diarized_segments: List[Dict[str, Any]],
    meeting_title: str,
) -> Dict[str, Any]:
    """
    Perform context-aware analysis on diarized meeting segments.

    Args:
        diarized_segments: List of {speaker, start, end, text} dicts
        meeting_title: Title of the meeting (used as context hint)

    Returns:
        {
          "enriched_segments": [...],   # segments with context_type added
          "action_items": [...],        # structured action items with attribution
          "speakers": [...],            # list of unique speakers detected
          "meeting_stats": {...}        # counts per context type
        }
    """
    from app.services.ai_service import _get_chat_client

    if not diarized_segments:
        return {
            "enriched_segments": [],
            "action_items": [],
            "speakers": [],
            "meeting_stats": {},
        }

    client, model = _get_chat_client()

    # Build a compact transcript for the LLM
    transcript_for_analysis = _build_analysis_input(diarized_segments)
    speakers = list({s["speaker"] for s in diarized_segments if s.get("speaker")})

    prompt = f"""You are analyzing a meeting transcript to extract structured intelligence.

Meeting: "{meeting_title}"
Speakers present: {', '.join(speakers)}

Transcript (with speaker labels):
{transcript_for_analysis}

Your task: Analyze every speaker turn and return a JSON object with:

1. "enriched_segments": Array of all segments with context classification
2. "action_items": Array of extracted action items with full attribution
3. "meeting_stats": Counts of each context type

For each segment in "enriched_segments":
{{
  "speaker": "Speaker A",
  "start": 12.5,
  "text": "The original text",
  "context_type": one of [task_assignment|task_completion|warning|progress_update|question|decision|general],
  "context_details": "Brief explanation of why this classification"
}}

For each item in "action_items":
{{
  "description": "Clear description of the task/action",
  "context_type": "task_assignment|warning|progress_update|task_completion",
  "speaker_label": "Speaker A",         (who said it)
  "assigned_by": "Speaker A",           (who is assigning, null if not an assignment)
  "assigned_to_name": "John",           (name of person being assigned, null if not mentioned)
  "deadline": "YYYY-MM-DD or description like 'by Friday'",  (null if not mentioned)
  "priority": "low|medium|high|urgent",
  "confidence": 0.0-1.0,
  "start_time": 12.5                    (timestamp in seconds)
}}

Context type definitions:
- task_assignment: Someone assigns a task to another person ("Can you...", "Please...", "I need you to...")
- task_completion: Someone reports finishing work ("I've done...", "It's complete", "Finished the...")
- warning: Risk, blocker, concern ("We might fail...", "There's an issue with...", "I'm worried about...")
- progress_update: Status update on ongoing work ("We're 70% done", "Still working on...", "Making progress on...")
- question: Requesting information ("What's the status?", "Did you finish?", "Can someone explain?")
- decision: A decision being made ("We've decided to...", "Let's go with...", "The plan is...")
- general: Small talk, introductions, filler

Return ONLY valid JSON, no markdown, no explanation."""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise meeting intelligence system. Return only valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4000,
        )

        result_text = response.choices[0].message.content.strip()
        result_text = re.sub(r"```(?:json)?", "", result_text).strip().rstrip("`").strip()

        analysis = json.loads(result_text)

        # Merge enriched segment data back with original segments (timestamps etc.)
        enriched = _merge_enriched_with_original(
            analysis.get("enriched_segments", []),
            diarized_segments,
        )

        # Compute stats if not provided
        stats = analysis.get("meeting_stats") or _compute_stats(enriched)

        return {
            "enriched_segments": enriched,
            "action_items": analysis.get("action_items", []),
            "speakers": speakers,
            "meeting_stats": stats,
        }

    except json.JSONDecodeError as e:
        logger.error(f"Context analysis JSON parse failed: {e}")
        # Return segments without enrichment
        return {
            "enriched_segments": [
                {**s, "context_type": "general", "context_details": ""}
                for s in diarized_segments
            ],
            "action_items": [],
            "speakers": speakers,
            "meeting_stats": {"general": len(diarized_segments)},
        }
    except Exception as e:
        logger.error(f"Context analysis failed: {e}")
        return {
            "enriched_segments": diarized_segments,
            "action_items": [],
            "speakers": speakers,
            "meeting_stats": {},
        }


async def generate_speaker_aware_summary(
    diarized_transcript: str,
    enriched_action_items: List[Dict],
    meeting_title: str,
    speakers: List[str],
) -> Dict[str, Any]:
    """
    Generate a meeting summary that is speaker-aware.

    Unlike the basic summarize_meeting(), this version:
    - References speakers by label (Speaker A, Speaker B)
    - Attributes decisions and actions to specific speakers
    - Groups action items by who assigned them and who was assigned

    Returns:
        {"summary": str, "action_items": list}
    """
    from app.services.ai_service import _get_chat_client

    client, model = _get_chat_client()

    # Format action items for context
    action_items_text = ""
    if enriched_action_items:
        action_items_text = "\n\nPre-extracted Action Items:\n"
        for item in enriched_action_items:
            assigned_by = item.get("assigned_by", "Unknown")
            assigned_to = item.get("assigned_to_name") or "unspecified"
            ctx = item.get("context_type", "general")
            action_items_text += (
                f"- [{ctx.upper()}] {item.get('description', '')} "
                f"(by {assigned_by} → to {assigned_to})\n"
            )

    prompt = f"""You are a professional meeting summarizer with speaker-awareness.

Meeting: "{meeting_title}"
Speakers: {', '.join(speakers)}

Speaker-labeled transcript:
{diarized_transcript[:5000]}
{action_items_text}

Write a comprehensive meeting summary with these sections:

## PARTICIPANTS
List each speaker and their apparent role/contributions in 1 sentence.

## KEY TOPICS
Main discussion points (2-3 sentences each).

## DECISIONS MADE
Decisions reached, with which speaker(s) made or agreed to them.

## ACTION ITEMS
Format each as:
- [ ] Task description (Assigned by: Speaker X → To: Person/Speaker Y, Deadline: date if mentioned, Type: assignment/warning/completion)

## WARNINGS & BLOCKERS
Any risks or blockers raised, attributed to the speaker who raised them.

## PROGRESS UPDATES
Status updates given by speakers on ongoing work.

## NEXT STEPS
What happens after this meeting.

Be specific about WHO said WHAT. Use "Speaker A", "Speaker B" etc. for unidentified speakers."""

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a speaker-aware meeting summarizer who attributes all points to specific participants.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=2500,
    )

    summary_text = response.choices[0].message.content

    return {
        "summary": summary_text,
        "action_items": enriched_action_items,
    }


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _build_analysis_input(segments: List[Dict], max_chars: int = 6000) -> str:
    """Build a compact transcript string for LLM analysis."""
    lines = []
    total = 0
    for seg in segments:
        speaker = seg.get("speaker", "Unknown")
        start = seg.get("start", 0)
        text = seg.get("text", "").strip()
        if not text:
            continue
        line = f"[{_fmt_time(start)}] {speaker}: {text}"
        total += len(line)
        if total > max_chars:
            lines.append("[... transcript truncated ...]")
            break
        lines.append(line)
    return "\n".join(lines)


def _merge_enriched_with_original(
    enriched: List[Dict],
    original: List[Dict],
) -> List[Dict]:
    """
    Merge LLM-enriched segments back with original to restore timestamps.
    Matches by speaker + text similarity.
    """
    # Build a quick lookup from original by speaker
    orig_by_speaker: Dict[str, List[Dict]] = {}
    for seg in original:
        spk = seg.get("speaker", "Unknown")
        orig_by_speaker.setdefault(spk, []).append(seg)

    result = []
    usage_counters: Dict[str, int] = {}

    for e_seg in enriched:
        spk = e_seg.get("speaker", "Unknown")
        idx = usage_counters.get(spk, 0)
        originals_for_spk = orig_by_speaker.get(spk, [])

        if idx < len(originals_for_spk):
            orig = originals_for_spk[idx]
            merged = {
                **orig,
                "context_type": e_seg.get("context_type", "general"),
                "context_details": e_seg.get("context_details", ""),
            }
            usage_counters[spk] = idx + 1
        else:
            # No original match — use enriched as-is
            merged = {
                "speaker": spk,
                "start": 0,
                "end": 0,
                "text": e_seg.get("text", ""),
                "context_type": e_seg.get("context_type", "general"),
                "context_details": e_seg.get("context_details", ""),
            }

        result.append(merged)

    return result


def _compute_stats(segments: List[Dict]) -> Dict[str, int]:
    """Count occurrences of each context_type."""
    stats: Dict[str, int] = {}
    for seg in segments:
        ct = seg.get("context_type", "general")
        stats[ct] = stats.get(ct, 0) + 1
    return stats


def _fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"
