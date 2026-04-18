"""
Enhanced AI Prompts for Speaker Diarization & Context Analysis

This module contains optimized prompts for:
1. Speaker diarization inference (when pyannote/AssemblyAI unavailable)
2. Context-aware utterance classification
3. Speaker-attributed action item extraction
4. Enhanced meeting summarization with speaker awareness

All prompts are designed for Llama 3.3 70B via Groq (free tier).
"""

# =============================================================================
# SPEAKER DIARIZATION PROMPTS
# =============================================================================

DIARIZATION_INFERENCE_PROMPT = """You are an expert speaker diarization system. Analyze this meeting transcript and identify speaker changes based on linguistic patterns, content flow, and conversational cues.

Transcript with timestamps:
{transcript}

Instructions:
1. Identify natural speaker boundaries based on:
   - Topic shifts or question-answer patterns
   - Direct address ("John, can you...", "Sarah said...")
   - Conversational flow and turn-taking
   - Content ownership ("I implemented...", "My team finished...")

2. Label speakers as Speaker A, Speaker B, Speaker C, etc. in order of first appearance.

3. For each segment, provide:
   - speaker: The speaker label
   - start: Start time in seconds
   - end: End time in seconds
   - text: The spoken text
   - confidence: 0.0-1.0 (your confidence in this speaker assignment)

4. Speaker changes typically occur at:
   - Questions followed by answers
   - Direct addresses to specific people
   - Topic ownership changes
   - Interruptions or clarifications

Return ONLY valid JSON array:
[
  {{
    "speaker": "Speaker A",
    "start": 0.0,
    "end": 12.5,
    "text": "Hello everyone, let's start the meeting",
    "confidence": 0.9
  }},
  {{
    "speaker": "Speaker B",
    "start": 12.5,
    "end": 18.3,
    "text": "Thanks, I have an update on the project",
    "confidence": 0.8
  }}
]

Be conservative with speaker changes - only split when there's clear evidence."""

# =============================================================================
# CONTEXT CLASSIFICATION PROMPTS
# =============================================================================

UTTERANCE_CLASSIFICATION_PROMPT = """You are a meeting intelligence analyst. Classify each speaker utterance by its context and communicative intent.

Meeting: "{meeting_title}"
Speakers: {speakers_list}

Transcript segments:
{transcript_segments}

For each segment, classify into ONE primary context type:

CONTEXT TYPES:
- task_assignment: Assigning work to someone ("John, can you finish...", "Please update the docs", "I need you to...")
- task_completion: Reporting work done ("I've completed the API", "Finished the login page", "The task is done")
- warning: Raising concerns/risks ("We might miss the deadline", "There's an issue with...", "I'm worried about...")
- progress_update: Status on ongoing work ("We're 70% done", "Still working on the database", "Making good progress")
- question: Seeking information ("What's the status?", "Did you finish?", "Can someone explain?")
- decision: Making choices ("We've decided to use React", "Let's go with option B", "The plan is...")
- general: Introductions, small talk, acknowledgments ("Hello", "Thanks", "I agree", "Good point")

For each segment, provide:
- speaker: The speaker label
- start: Start time
- text: Original text
- context_type: One of the types above
- context_details: 1-sentence explanation of classification
- confidence: 0.0-1.0

Return ONLY JSON array."""

# =============================================================================
# ACTION ITEM EXTRACTION PROMPTS
# =============================================================================

SPEAKER_AWARE_ACTION_EXTRACTION_PROMPT = """You are extracting action items from a speaker-diarized meeting transcript. Each action item must be attributed to specific speakers.

Meeting: "{meeting_title}"
Speakers present: {speakers_list}

Speaker-labeled transcript:
{diarized_transcript}

Extract action items with full speaker attribution:

For each action item, identify:
- description: Clear, actionable task description
- context_type: task_assignment|task_completion|warning|progress_update
- speaker_label: Who said this (Speaker A, Speaker B, etc.)
- assigned_by: Who is assigning (same as speaker_label for assignments, null for others)
- assigned_to_name: Person being assigned (extract from text, null if not specified)
- deadline: Specific date/deadline mentioned (YYYY-MM-DD format or descriptive like "by Friday")
- priority: low|medium|high|urgent (infer from urgency cues)
- confidence: 0.0-1.0
- start_time: Timestamp when mentioned

ASSIGNMENT PATTERNS:
- Direct: "John, please finish the login page by Friday"
- Indirect: "Someone needs to update the documentation"
- Questions: "Can you handle the deployment?" (implies assignment)
- Commitments: "I'll take care of the testing" (self-assignment)

COMPLETION PATTERNS:
- "I've finished the API integration"
- "The database migration is complete"
- "Done with the frontend updates"

WARNING PATTERNS:
- "We might miss the deadline if..."
- "There's a blocker with the payment system"
- "I'm concerned about the server capacity"

Return ONLY JSON array of action items."""

# =============================================================================
# ENHANCED SUMMARIZATION PROMPTS
# =============================================================================

SPEAKER_AWARE_SUMMARY_PROMPT = """You are a professional meeting summarizer with advanced speaker awareness. Create a comprehensive summary that attributes all key points, decisions, and actions to specific speakers.

Meeting Title: "{meeting_title}"
Speakers Identified: {speakers_list}
Total Duration: {duration_minutes} minutes

Speaker-labeled transcript:
{diarized_transcript}

Pre-analyzed action items:
{action_items_context}

Create a structured summary with these sections:

## PARTICIPANTS & ROLES
For each speaker, describe their apparent role and key contributions in 1-2 sentences.
- Speaker A: [description]
- Speaker B: [description]

## KEY TOPICS DISCUSSED
Summarize main discussion points, attributing ideas to speakers:
- [Topic]: Discussed by Speaker X, with input from Speaker Y...

## DECISIONS MADE
List decisions reached, with who made/proposed them:
- [Decision]: Proposed by Speaker X, agreed by Speaker Y and Speaker Z

## ACTION ITEMS
Format each with full attribution:
- [ ] [Task description] (Assigned by: Speaker X → To: [Person/Speaker Y], Deadline: [date], Priority: [level], Context: [assignment/completion/warning])

## WARNINGS & BLOCKERS
Risks/concerns raised, attributed to speakers:
- [Warning]: Raised by Speaker X - [details]

## PROGRESS UPDATES
Status reports given by speakers:
- Speaker X: [progress update]
- Speaker Y: [progress update]

## NEXT STEPS & FOLLOW-UP
What happens after this meeting, who is responsible.

Be precise about WHO said WHAT. Use speaker labels consistently. Focus on actionable insights."""

# =============================================================================
# VOICE PATTERN ANALYSIS PROMPTS (FUTURE ENHANCEMENT)
# =============================================================================

VOICE_PATTERN_ANALYSIS_PROMPT = """You are analyzing voice patterns to improve speaker diarization consistency.

Audio characteristics: {audio_features}
Transcript segments: {transcript_segments}

Based on linguistic patterns, speaking style, and content ownership, suggest speaker consistency mappings.

Consider:
- Topic ownership ("I implemented the API" suggests same speaker)
- Direct addresses ("John, what do you think?")
- Question-answer patterns
- Technical expertise shown
- Personal anecdotes or references

Return speaker mapping suggestions with confidence scores."""

# =============================================================================
# SENTIMENT ANALYSIS PROMPTS (FUTURE ENHANCEMENT)
# =============================================================================

UTTERANCE_SENTIMENT_PROMPT = """Analyze the sentiment and emotional tone of each speaker utterance.

For each segment, classify:
- sentiment: positive|negative|neutral
- intensity: low|medium|high
- confidence: 0.0-1.0

Consider linguistic cues, urgency, and emotional language."""

# =============================================================================
# PROMPT UTILITIES
# =============================================================================

def format_diarization_inference_prompt(transcript: str) -> str:
    """Format the diarization inference prompt with transcript."""
    return DIARIZATION_INFERENCE_PROMPT.format(transcript=transcript)

def format_context_classification_prompt(
    meeting_title: str,
    speakers_list: str,
    transcript_segments: str
) -> str:
    """Format the utterance classification prompt."""
    return UTTERANCE_CLASSIFICATION_PROMPT.format(
        meeting_title=meeting_title,
        speakers_list=speakers_list,
        transcript_segments=transcript_segments
    )

def format_action_extraction_prompt(
    meeting_title: str,
    speakers_list: str,
    diarized_transcript: str
) -> str:
    """Format the speaker-aware action extraction prompt."""
    return SPEAKER_AWARE_ACTION_EXTRACTION_PROMPT.format(
        meeting_title=meeting_title,
        speakers_list=speakers_list,
        diarized_transcript=diarized_transcript
    )

def format_speaker_aware_summary_prompt(
    meeting_title: str,
    speakers_list: str,
    duration_minutes: int,
    diarized_transcript: str,
    action_items_context: str
) -> str:
    """Format the enhanced summarization prompt."""
    return SPEAKER_AWARE_SUMMARY_PROMPT.format(
        meeting_title=meeting_title,
        speakers_list=speakers_list,
        duration_minutes=duration_minutes,
        diarized_transcript=diarized_transcript,
        action_items_context=action_items_context
    )</content>
<parameter name="filePath">c:\Users\centu\OneDrive\Documents\GitHub\FYP-SynkroYashaal\backend\app\services\ai_prompts.py