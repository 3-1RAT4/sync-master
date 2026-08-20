from sync_master.tools.diarize import SpeakerSegment
from sync_master.tools.transcript import NoCaptionsAvailable, TranscriptResult, get_transcript


def test_get_transcript_uses_captions_when_available(tmp_path):
    def fake_fetch_caption_segments(video_id):
        return [{"start": 0.0, "end": 1.0, "text": "Hello from captions"}]

    def fake_transcribe_segments(video_id, scratch_dir, title):
        raise AssertionError("should not fall back to whisper when captions succeed")

    def fake_diarize_speakers(video_id, scratch_dir, title):
        return []

    result = get_transcript(
        "v1",
        tmp_path,
        fetch_caption_segments=fake_fetch_caption_segments,
        transcribe_segments=fake_transcribe_segments,
        diarize_speakers=fake_diarize_speakers,
    )

    assert result == TranscriptResult(text="[00:00:00] UNKNOWN: Hello from captions", source="captions", segments=[])


def test_get_transcript_falls_back_to_whisper_when_no_captions(tmp_path):
    def fake_fetch_caption_segments(video_id):
        raise NoCaptionsAvailable(video_id)

    def fake_transcribe_segments(video_id, scratch_dir, title):
        return [{"start": 0.0, "end": 1.0, "text": "Hello from whisper"}]

    def fake_diarize_speakers(video_id, scratch_dir, title):
        return []

    result = get_transcript(
        "v1",
        tmp_path,
        fetch_caption_segments=fake_fetch_caption_segments,
        transcribe_segments=fake_transcribe_segments,
        diarize_speakers=fake_diarize_speakers,
    )

    assert result == TranscriptResult(text="[00:00:00] UNKNOWN: Hello from whisper", source="whisper", segments=[])


def test_get_transcript_diarizes_even_when_captions_succeed(tmp_path):
    def fake_fetch_caption_segments(video_id):
        return [{"start": 0.0, "end": 1.0, "text": "Hello from captions"}]

    def fake_transcribe_segments(video_id, scratch_dir, title):
        raise AssertionError("should not fall back to whisper when captions succeed")

    def fake_diarize_speakers(video_id, scratch_dir, title):
        return [SpeakerSegment(start=0.0, end=1.0, speaker="SPEAKER_00")]

    result = get_transcript(
        "v1",
        tmp_path,
        fetch_caption_segments=fake_fetch_caption_segments,
        transcribe_segments=fake_transcribe_segments,
        diarize_speakers=fake_diarize_speakers,
    )

    assert result.text == "[00:00:00] SPEAKER_00: Hello from captions"


def test_get_transcript_returns_diarized_speaker_segments_for_persistence(tmp_path):
    speaker_segments = [SpeakerSegment(start=0.0, end=1.0, speaker="SPEAKER_00")]

    result = get_transcript(
        "v1",
        tmp_path,
        fetch_caption_segments=lambda video_id: [{"start": 0.0, "end": 1.0, "text": "Hi"}],
        transcribe_segments=lambda video_id, scratch_dir, title: (_ for _ in ()).throw(AssertionError()),
        diarize_speakers=lambda video_id, scratch_dir, title: speaker_segments,
    )

    assert result.segments == speaker_segments


def test_get_transcript_does_not_write_any_files(tmp_path):
    get_transcript(
        "v1",
        tmp_path,
        title="My Video Title",
        fetch_caption_segments=lambda video_id: [{"start": 0.0, "end": 1.0, "text": "Hello from captions"}],
        transcribe_segments=lambda video_id, scratch_dir, title: (_ for _ in ()).throw(AssertionError()),
        diarize_speakers=lambda video_id, scratch_dir, title: [],
    )

    assert list(tmp_path.iterdir()) == []


def test_get_transcript_passes_title_through_to_transcribe_segments(tmp_path):
    received = {}

    def fake_transcribe_segments(video_id, scratch_dir, title):
        received["title"] = title
        return [{"start": 0.0, "end": 1.0, "text": "Hello from whisper"}]

    get_transcript(
        "v1",
        tmp_path,
        title="My Video Title",
        fetch_caption_segments=lambda video_id: (_ for _ in ()).throw(NoCaptionsAvailable(video_id)),
        transcribe_segments=fake_transcribe_segments,
        diarize_speakers=lambda video_id, scratch_dir, title: [],
    )

    assert received["title"] == "My Video Title"


def test_get_transcript_passes_title_through_to_diarize_speakers(tmp_path):
    received = {}

    def fake_diarize_speakers(video_id, scratch_dir, title):
        received["title"] = title
        return []

    get_transcript(
        "v1",
        tmp_path,
        title="My Video Title",
        fetch_caption_segments=lambda video_id: [{"start": 0.0, "end": 1.0, "text": "Hello from captions"}],
        transcribe_segments=lambda video_id, scratch_dir, title: (_ for _ in ()).throw(AssertionError()),
        diarize_speakers=fake_diarize_speakers,
    )

    assert received["title"] == "My Video Title"
