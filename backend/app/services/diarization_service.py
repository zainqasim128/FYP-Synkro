"""
Speaker Diarization Service

Identifies and labels different speakers in an audio recording.
Uses a 3-tier fallback strategy:
  1. pyannote.audio  — local, free (needs HuggingFace token)
  2. AssemblyAI      — cloud API (needs ASSEMBLYAI_API_KEY)
  3. LLM Inference   — Groq Llama analyzes transcript patterns (always available)

Returns a list of segments: [{speaker, start, end, text}]
"""
import os
import json
import logging
import re
from typing import List, Dict, Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────

async def diarize_audio(
    audio_file_path: str,
    raw_transcript: str,
    whisper_segments: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """
    Perform speaker diarization on an audio file.

    Args:
        audio_file_path: Path to the audio file
        raw_transcript: Plain-text transcript (used by LLM fallback)
        whisper_segments: Optional list of Whisper segments with timestamps

    Returns:
        List of diarized segments:
        [{"speaker": "Speaker A", "start": 0.0, "end": 5.2, "text": "..."}]
    """
    # Tier 1: pyannote.audio (best quality, local, free)
    hf_token = getattr(settings, "HUGGINGFACE_TOKEN", None) or os.getenv("HUGGINGFACE_TOKEN")
    if hf_token:
        try:
            logger.info("Diarization: Attempting pyannote.audio (Tier 1)")
            segments = await _diarize_with_pyannote(audio_file_path, hf_token, whisper_segments)
            if segments:
                logger.info(f"Diarization: pyannote succeeded — {len(segments)} segments")
                return segments
        except Exception as e:
            logger.warning(f"Diarization: pyannote failed ({e}), trying next tier")

    # Tier 2: AssemblyAI (cloud, paid, great quality)
    aai_key = getattr(settings, "ASSEMBLYAI_API_KEY", None) or os.getenv("ASSEMBLYAI_API_KEY")
    if aai_key:
        try:
            logger.info("Diarization: Attempting AssemblyAI (Tier 2)")
            segments = await _diarize_with_assemblyai(audio_file_path, aai_key)
            if segments:
                logger.info(f"Diarization: AssemblyAI succeeded — {len(segments)} segments")
                return segments
        except Exception as e:
            logger.warning(f"Diarization: AssemblyAI failed ({e}), trying LLM fallback")

    # Tier 3: LLM-based inference (always available, uses Groq)
    logger.info("Diarization: Using LLM inference fallback (Tier 3)")
    return await _diarize_with_llm(raw_transcript, whisper_segments)


def format_diarized_transcript(segments: List[Dict[str, Any]]) -> str:
    """
    Format diarized segments into a readable speaker-labeled transcript.

    Output format:
        [00:00] Speaker A: Hello everyone, let's start the meeting.
        [00:05] Speaker B: Sure, I'll begin with the status update.
    """
    lines = []
    for seg in segments:
        speaker = seg.get("speaker", "Unknown")
        start = seg.get("start", 0)
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"[{_fmt_time(start)}] {speaker}: {text}")
    return "\n".join(lines)


def merge_whisper_with_diarization(
    whisper_segments: List[Dict],
    diarization: List[Dict],
) -> List[Dict[str, Any]]:
    """
    Merge Whisper word-level timestamps with pyannote speaker labels.

    For each Whisper segment, find which speaker was active at that timestamp
    using a simple overlap heuristic.
    """
    merged = []
    for w_seg in whisper_segments:
        w_start = w_seg.get("start", 0)
        w_end = w_seg.get("end", w_start + 1)
        w_text = w_seg.get("text", "").strip()

        # Find best matching speaker via max overlap
        best_speaker = "Speaker A"
        best_overlap = 0.0

        for d_seg in diarization:
            d_start = d_seg.get("start", 0)
            d_end = d_seg.get("end", d_start)

            overlap_start = max(w_start, d_start)
            overlap_end = min(w_end, d_end)
            overlap = max(0.0, overlap_end - overlap_start)

            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = d_seg.get("speaker", "Speaker A")

        merged.append({
            "speaker": best_speaker,
            "start": w_start,
            "end": w_end,
            "text": w_text,
        })

    # Consolidate consecutive segments from the same speaker
    return _consolidate_segments(merged)


# ─────────────────────────────────────────────────────────────
# Tier 1: pyannote.audio
# ─────────────────────────────────────────────────────────────

async def _diarize_with_pyannote(
    audio_file_path: str,
    hf_token: str,
    whisper_segments: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """Use pyannote.audio for speaker diarization."""
    try:
        from pyannote.audio import Pipeline
        import torch
    except ImportError:
        raise ImportError(
            "pyannote.audio not installed. Run: pip install pyannote.audio torch"
        )

    device = "cuda" if _cuda_available() else "cpu"
    logger.info(f"pyannote: loading pipeline on {device}")

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )
    if device == "cuda":
        import torch
        pipeline = pipeline.to(torch.device("cuda"))

    # Run diarization
    diarization = pipeline(audio_file_path)

    # Convert pyannote output to our segment format
    raw_segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        raw_segments.append({
            "speaker": _normalize_speaker(speaker),
            "start": turn.start,
            "end": turn.end,
            "text": "",  # text comes from Whisper
        })

    # If we have Whisper segments, merge for text
    if whisper_segments:
        return merge_whisper_with_diarization(whisper_segments, raw_segments)

    return raw_segments


# ─────────────────────────────────────────────────────────────
# Tier 2: AssemblyAI
# ─────────────────────────────────────────────────────────────

async def _diarize_with_assemblyai(
    audio_file_path: str,
    api_key: str,
) -> List[Dict[str, Any]]:
    """Use AssemblyAI for speaker diarization."""
    try:
        import assemblyai as aai
    except ImportError:
        raise ImportError(
            "assemblyai not installed. Run: pip install assemblyai"
        )

    aai.settings.api_key = api_key

    config = aai.TranscriptionConfig(speaker_labels=True)
    transcriber = aai.Transcriber()

    logger.info("AssemblyAI: uploading and transcribing audio")
    transcript = transcriber.transcribe(audio_file_path, config=config)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI error: {transcript.error}")

    segments = []
    if transcript.utterances:
        for utt in transcript.utterances:
            segments.append({
                "speaker": f"Speaker {utt.speaker}",
                "start": utt.start / 1000.0,  # AssemblyAI uses ms
                "end": utt.end / 1000.0,
                "text": utt.text,
            })

    return segments


# ─────────────────────────────────────────────────────────────
# Tier 3: LLM-based inference
# ─────────────────────────────────────────────────────────────

async def _diarize_with_llm(
    raw_transcript: str,
    whisper_segments: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """
    Use Groq Llama to infer speaker turns from transcript patterns.
    This works without any extra API keys.

    The LLM looks for:
    - Question/answer patterns
    - Topic shifts
    - Addressing patterns ("John, can you...")
    - Conversational turn markers
    """
    from openai import AsyncOpenAI
    from app.config import settings

    # Create a fresh client per call — avoids httpx event-loop binding issues
    # when this coroutine runs inside asyncio.run() from a Celery worker.
    groq_key = getattr(settings, "GROQ_API_KEY", None) or os.getenv("GROQ_API_KEY")
    openai_key = getattr(settings, "OPENAI_API_KEY", None) or os.getenv("OPENAI_API_KEY")

    if groq_key:
        client = AsyncOpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
        model = "llama-3.3-70b-versatile"
    elif openai_key:
        client = AsyncOpenAI(api_key=openai_key)
        model = "gpt-4o-mini"
    else:
        logger.error("Diarization LLM: no API key available")
        return _single_speaker_fallback(raw_transcript, whisper_segments)

    # If we have whisper segments, work at segment level
    if whisper_segments:
        segment_text = "\n".join(
            f"[{_fmt_time(s.get('start', 0))}] {s.get('text', '').strip()}"
            for s in whisper_segments[:80]  # limit to avoid token overflow
        )
    else:
        segment_text = raw_transcript[:4000]

    prompt = f"""You are analyzing a meeting transcript to identify different speakers.

Look for patterns like:
- Questions followed by answers (likely different speakers)
- Someone being addressed by name ("John, can you...")
- Topic shifts suggesting a new person is speaking
- Conversational back-and-forth

Transcript:
{segment_text}

Return a JSON array. For each speaker turn, output:
{{
  "speaker": "Speaker A",   (use A, B, C, D — be consistent)
  "start_marker": "[00:00]",  (the timestamp marker from the transcript, or null)
  "text": "The text they said"
}}

Rules:
- Use the fewest speakers necessary (usually 2-4 for a meeting)
- Be consistent — if "Speaker A" says something, they stay Speaker A throughout
- Return ONLY valid JSON array, no other text
- If you cannot determine speaker changes, return all as "Speaker A"

Example output:
[
  {{"speaker": "Speaker A", "start_marker": "[00:00]", "text": "Let's start the meeting."}},
  {{"speaker": "Speaker B", "start_marker": "[00:05]", "text": "Sure, I'll go first."}}
]"""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a meeting transcript analyst. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=3000,
        )

        result_text = response.choices[0].message.content.strip()

        # Strip markdown code blocks if present
        result_text = re.sub(r"```(?:json)?", "", result_text).strip().rstrip("`").strip()

        llm_segments = json.loads(result_text)

        # Convert to our standard format
        segments = []
        for i, seg in enumerate(llm_segments):
            # Parse timestamp from marker like "[00:05]"
            start = _parse_timestamp(seg.get("start_marker", ""))
            # Estimate end as start of next segment
            end = start + 5.0  # default 5s, will be updated below

            segments.append({
                "speaker": seg.get("speaker", "Speaker A"),
                "start": start,
                "end": end,
                "text": seg.get("text", ""),
            })

        # Fix end times using next segment's start
        for i in range(len(segments) - 1):
            segments[i]["end"] = segments[i + 1]["start"]

        return segments

    except Exception as e:
        logger.error(f"LLM diarization failed: {e}", exc_info=True)
        # Last resort: return entire transcript as single speaker
        return _single_speaker_fallback(raw_transcript, whisper_segments)
    finally:
        try:
            await client.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _single_speaker_fallback(
    raw_transcript: str,
    whisper_segments: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """Return entire transcript labeled as a single speaker."""
    if whisper_segments:
        return [
            {
                "speaker": "Speaker A",
                "start": s.get("start", 0),
                "end": s.get("end", 0),
                "text": s.get("text", "").strip(),
            }
            for s in whisper_segments
        ]
    return [{"speaker": "Speaker A", "start": 0.0, "end": 0.0, "text": raw_transcript}]


def _filter_noise_segments(segments: List[Dict], min_duration: float = 0.5) -> List[Dict]:
    """
    Remove segments shorter than min_duration seconds.

    Very short segments (< 0.5s) are typically diarization noise — brief
    mis-attributed fragments that appear between real speaker turns. Filtering
    them before consolidation prevents spurious speaker-change boundaries.
    """
    return [s for s in segments if (s.get("end", 0) - s.get("start", 0)) >= min_duration]


def _consolidate_segments(segments: List[Dict], max_gap: float = 2.0) -> List[Dict]:
    """
    Merge same-speaker segments that are consecutive or within max_gap seconds.

    A gap of up to 2 seconds between segments from the same speaker is treated
    as a single continuous turn (brief pauses, filler words, breath). Segments
    from a different speaker in between reset the merge boundary.
    """
    if not segments:
        return []

    # Remove noise before consolidating
    segments = _filter_noise_segments(segments)
    if not segments:
        return []

    consolidated = [segments[0].copy()]
    for seg in segments[1:]:
        last = consolidated[-1]
        gap = seg.get("start", 0) - last.get("end", 0)
        if seg["speaker"] == last["speaker"] and gap <= max_gap:
            last["end"] = seg["end"]
            last["text"] = (last["text"] + " " + seg["text"]).strip()
        else:
            consolidated.append(seg.copy())

    return consolidated


def _normalize_speaker(label: str) -> str:
    """Convert pyannote speaker labels to friendly names."""
    # pyannote returns labels like "SPEAKER_00", "SPEAKER_01"
    mapping = {
        "SPEAKER_00": "Speaker A",
        "SPEAKER_01": "Speaker B",
        "SPEAKER_02": "Speaker C",
        "SPEAKER_03": "Speaker D",
        "SPEAKER_04": "Speaker E",
    }
    return mapping.get(label, label.replace("SPEAKER_", "Speaker "))


def _fmt_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def _parse_timestamp(marker: str) -> float:
    """Parse '[MM:SS]' or '[HH:MM:SS]' → seconds."""
    if not marker:
        return 0.0
    cleaned = marker.strip("[]")
    parts = cleaned.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError):
        pass
    return 0.0


def _cuda_available() -> bool:
    """Check if CUDA is available for GPU acceleration."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False
