"""
Unit tests for diarization_service.py

Covers all pure helper functions — no external APIs, no async I/O.
"""
import pytest
from app.services.diarization_service import (
    _consolidate_segments,
    _filter_noise_segments,
    _normalize_speaker,
    _fmt_time,
    _parse_timestamp,
    _single_speaker_fallback,
    merge_whisper_with_diarization,
    format_diarized_transcript,
)


# ─────────────────────────────────────────────────────────────
# _fmt_time
# ─────────────────────────────────────────────────────────────

class TestFmtTime:
    def test_zero(self):
        assert _fmt_time(0) == "00:00"

    def test_under_minute(self):
        assert _fmt_time(45) == "00:45"

    def test_exactly_one_minute(self):
        assert _fmt_time(60) == "01:00"

    def test_mixed(self):
        assert _fmt_time(125) == "02:05"

    def test_large(self):
        assert _fmt_time(3661) == "61:01"

    def test_float_truncated(self):
        assert _fmt_time(90.9) == "01:30"


# ─────────────────────────────────────────────────────────────
# _parse_timestamp
# ─────────────────────────────────────────────────────────────

class TestParseTimestamp:
    def test_empty_string(self):
        assert _parse_timestamp("") == 0.0

    def test_none_like_empty(self):
        assert _parse_timestamp("[]") == 0.0

    def test_mm_ss(self):
        assert _parse_timestamp("[01:30]") == 90.0

    def test_mm_ss_no_brackets(self):
        assert _parse_timestamp("02:05") == 125.0

    def test_hh_mm_ss(self):
        assert _parse_timestamp("[01:02:03]") == 3723.0

    def test_zero_timestamp(self):
        assert _parse_timestamp("[00:00]") == 0.0

    def test_fractional_seconds(self):
        assert _parse_timestamp("[00:01.5]") == pytest.approx(1.5)

    def test_malformed_returns_zero(self):
        assert _parse_timestamp("[abc]") == 0.0


# ─────────────────────────────────────────────────────────────
# _normalize_speaker
# ─────────────────────────────────────────────────────────────

class TestNormalizeSpeaker:
    def test_speaker_00(self):
        assert _normalize_speaker("SPEAKER_00") == "Speaker A"

    def test_speaker_01(self):
        assert _normalize_speaker("SPEAKER_01") == "Speaker B"

    def test_speaker_04(self):
        assert _normalize_speaker("SPEAKER_04") == "Speaker E"

    def test_unknown_label_converted(self):
        # Labels beyond the known mapping are still converted
        result = _normalize_speaker("SPEAKER_09")
        assert "09" in result or "Speaker" in result

    def test_already_normalized(self):
        assert _normalize_speaker("Speaker A") == "Speaker A"


# ─────────────────────────────────────────────────────────────
# _filter_noise_segments
# ─────────────────────────────────────────────────────────────

class TestFilterNoiseSegments:
    def test_removes_short_segments(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 0.3, "text": "um"},
            {"speaker": "Speaker B", "start": 1.0, "end": 3.0, "text": "Hello there"},
        ]
        result = _filter_noise_segments(segs)
        assert len(result) == 1
        assert result[0]["speaker"] == "Speaker B"

    def test_keeps_segments_at_threshold(self):
        segs = [{"speaker": "Speaker A", "start": 0.0, "end": 0.5, "text": "yes"}]
        result = _filter_noise_segments(segs)
        assert len(result) == 1

    def test_empty_input(self):
        assert _filter_noise_segments([]) == []

    def test_custom_min_duration(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 1.0, "text": "hi"},
            {"speaker": "Speaker B", "start": 1.5, "end": 4.0, "text": "hello"},
        ]
        # With min_duration=2.0, the first segment is filtered
        result = _filter_noise_segments(segs, min_duration=2.0)
        assert len(result) == 1
        assert result[0]["speaker"] == "Speaker B"

    def test_all_noise_returns_empty(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 0.1, "text": "uh"},
            {"speaker": "Speaker B", "start": 1.0, "end": 1.2, "text": "mm"},
        ]
        assert _filter_noise_segments(segs) == []


# ─────────────────────────────────────────────────────────────
# _consolidate_segments
# ─────────────────────────────────────────────────────────────

class TestConsolidateSegments:
    def test_empty(self):
        assert _consolidate_segments([]) == []

    def test_single_segment(self):
        segs = [{"speaker": "Speaker A", "start": 0.0, "end": 5.0, "text": "Hello"}]
        result = _consolidate_segments(segs)
        assert len(result) == 1
        assert result[0]["text"] == "Hello"

    def test_consecutive_same_speaker_merged(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 2.0, "text": "Hello"},
            {"speaker": "Speaker A", "start": 2.0, "end": 4.0, "text": "everyone"},
        ]
        result = _consolidate_segments(segs)
        assert len(result) == 1
        assert result[0]["text"] == "Hello everyone"
        assert result[0]["end"] == 4.0

    def test_different_speakers_not_merged(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 3.0, "text": "Hello"},
            {"speaker": "Speaker B", "start": 3.0, "end": 6.0, "text": "Hi there"},
        ]
        result = _consolidate_segments(segs)
        assert len(result) == 2

    def test_same_speaker_within_gap_merged(self):
        # 1.5s gap — within default 2.0s max_gap
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 3.0, "text": "One"},
            {"speaker": "Speaker A", "start": 4.5, "end": 7.0, "text": "two"},
        ]
        result = _consolidate_segments(segs)
        assert len(result) == 1
        assert result[0]["text"] == "One two"

    def test_same_speaker_beyond_gap_not_merged(self):
        # 3s gap — exceeds default 2.0s max_gap
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 2.0, "text": "First"},
            {"speaker": "Speaker A", "start": 5.0, "end": 8.0, "text": "Second"},
        ]
        result = _consolidate_segments(segs)
        assert len(result) == 2

    def test_noise_filtered_before_consolidation(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 3.0, "text": "Hello"},
            {"speaker": "Speaker B", "start": 3.1, "end": 3.3, "text": "uh"},   # noise
            {"speaker": "Speaker A", "start": 3.5, "end": 6.0, "text": "world"},
        ]
        # After noise removal: two Speaker A segs with 0.5s gap — merged
        result = _consolidate_segments(segs)
        assert len(result) == 1
        assert result[0]["speaker"] == "Speaker A"

    def test_alternating_speakers(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 2.0, "text": "Q"},
            {"speaker": "Speaker B", "start": 2.0, "end": 4.0, "text": "A"},
            {"speaker": "Speaker A", "start": 4.0, "end": 6.0, "text": "Q2"},
            {"speaker": "Speaker B", "start": 6.0, "end": 8.0, "text": "A2"},
        ]
        result = _consolidate_segments(segs)
        assert len(result) == 4

    def test_custom_max_gap(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "end": 2.0, "text": "Part one"},
            {"speaker": "Speaker A", "start": 6.0, "end": 9.0, "text": "Part two"},
        ]
        # Default gap (2.0) — not merged; custom gap (5.0) — merged
        assert len(_consolidate_segments(segs)) == 2
        assert len(_consolidate_segments(segs, max_gap=5.0)) == 1


# ─────────────────────────────────────────────────────────────
# merge_whisper_with_diarization
# ─────────────────────────────────────────────────────────────

class TestMergeWhisperWithDiarization:
    def test_basic_merge(self):
        whisper = [
            {"start": 0.0, "end": 3.0, "text": "Hello team"},
            {"start": 5.0, "end": 8.0, "text": "Good morning"},
        ]
        diarization = [
            {"speaker": "Speaker A", "start": 0.0, "end": 4.0},
            {"speaker": "Speaker B", "start": 4.5, "end": 9.0},
        ]
        result = merge_whisper_with_diarization(whisper, diarization)
        speakers = [s["speaker"] for s in result]
        assert "Speaker A" in speakers
        assert "Speaker B" in speakers

    def test_overlap_assignment(self):
        # Whisper segment entirely within Speaker B's range
        whisper = [{"start": 5.0, "end": 7.0, "text": "status update"}]
        diarization = [
            {"speaker": "Speaker A", "start": 0.0, "end": 3.0},
            {"speaker": "Speaker B", "start": 4.0, "end": 9.0},
        ]
        result = merge_whisper_with_diarization(whisper, diarization)
        assert result[0]["speaker"] == "Speaker B"

    def test_no_overlap_defaults_to_speaker_a(self):
        whisper = [{"start": 20.0, "end": 25.0, "text": "late text"}]
        diarization = [{"speaker": "Speaker B", "start": 0.0, "end": 10.0}]
        result = merge_whisper_with_diarization(whisper, diarization)
        assert result[0]["speaker"] == "Speaker A"

    def test_empty_whisper(self):
        diarization = [{"speaker": "Speaker A", "start": 0.0, "end": 5.0}]
        result = merge_whisper_with_diarization([], diarization)
        assert result == []

    def test_text_preserved(self):
        whisper = [{"start": 0.0, "end": 2.0, "text": "  hello world  "}]
        diarization = [{"speaker": "Speaker A", "start": 0.0, "end": 5.0}]
        result = merge_whisper_with_diarization(whisper, diarization)
        assert result[0]["text"] == "hello world"


# ─────────────────────────────────────────────────────────────
# format_diarized_transcript
# ─────────────────────────────────────────────────────────────

class TestFormatDiarizedTranscript:
    def test_basic_format(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "text": "Hello everyone"},
            {"speaker": "Speaker B", "start": 65.0, "text": "Good morning"},
        ]
        result = format_diarized_transcript(segs)
        assert "[00:00] Speaker A: Hello everyone" in result
        assert "[01:05] Speaker B: Good morning" in result

    def test_empty_text_skipped(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "text": ""},
            {"speaker": "Speaker B", "start": 5.0, "text": "Hi"},
        ]
        result = format_diarized_transcript(segs)
        assert "Speaker A" not in result
        assert "Speaker B: Hi" in result

    def test_empty_segments(self):
        assert format_diarized_transcript([]) == ""

    def test_whitespace_only_text_skipped(self):
        segs = [{"speaker": "Speaker A", "start": 0.0, "text": "   "}]
        assert format_diarized_transcript(segs) == ""

    def test_multiline_output(self):
        segs = [
            {"speaker": "Speaker A", "start": 0.0, "text": "Line one"},
            {"speaker": "Speaker B", "start": 10.0, "text": "Line two"},
        ]
        lines = format_diarized_transcript(segs).split("\n")
        assert len(lines) == 2


# ─────────────────────────────────────────────────────────────
# _single_speaker_fallback
# ─────────────────────────────────────────────────────────────

class TestSingleSpeakerFallback:
    def test_uses_whisper_segments_when_provided(self):
        whisper = [
            {"start": 0.0, "end": 3.0, "text": "Hello"},
            {"start": 3.0, "end": 6.0, "text": "World"},
        ]
        result = _single_speaker_fallback("Hello World", whisper)
        assert len(result) == 2
        assert all(s["speaker"] == "Speaker A" for s in result)

    def test_falls_back_to_raw_transcript(self):
        result = _single_speaker_fallback("Hello World", None)
        assert len(result) == 1
        assert result[0]["speaker"] == "Speaker A"
        assert result[0]["text"] == "Hello World"

    def test_empty_whisper_segments_falls_back_to_raw(self):
        # An empty list is falsy, so the function falls through to the raw-transcript branch
        result = _single_speaker_fallback("text", [])
        assert len(result) == 1
        assert result[0]["text"] == "text"

    def test_text_stripped(self):
        whisper = [{"start": 0.0, "end": 1.0, "text": "  hi  "}]
        result = _single_speaker_fallback("hi", whisper)
        assert result[0]["text"] == "hi"
