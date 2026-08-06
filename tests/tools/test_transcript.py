from sync_master.tools.transcript import NoCaptionsAvailable, TranscriptResult, get_transcript


def test_get_transcript_uses_captions_when_available(tmp_path):
    def fake_fetch_caption_segments(video_id):
        return [{"start": 0.0, "end": 1.0, "text": "Hello from captions"}]

    def fake_transcribe_segments(video_id, output_dir, title):
        raise AssertionError("should not fall back to whisper when captions succeed")

    def fake_diarize_speakers(video_id, output_dir, title):
        return []

    result = get_transcript(
        "v1",
        tmp_path,
        fetch_caption_segments=fake_fetch_caption_segments,
        transcribe_segments=fake_transcribe_segments,
        diarize_speakers=fake_diarize_speakers,
    )

    assert result == TranscriptResult(text="[00:00:00] UNKNOWN: Hello from captions", source="captions")


def test_get_transcript_falls_back_to_whisper_when_no_captions(tmp_path):
    def fake_fetch_caption_segments(video_id):
        raise NoCaptionsAvailable(video_id)

    def fake_transcribe_segments(video_id, output_dir, title):
        return [{"start": 0.0, "end": 1.0, "text": "Hello from whisper"}]

    def fake_diarize_speakers(video_id, output_dir, title):
        return []

    result = get_transcript(
        "v1",
        tmp_path,
        fetch_caption_segments=fake_fetch_caption_segments,
        transcribe_segments=fake_transcribe_segments,
        diarize_speakers=fake_diarize_speakers,
    )

    assert result == TranscriptResult(text="[00:00:00] UNKNOWN: Hello from whisper", source="whisper")


def test_get_transcript_diarizes_even_when_captions_succeed(tmp_path):
    from sync_master.tools.diarize import SpeakerSegment

    def fake_fetch_caption_segments(video_id):
        return [{"start": 0.0, "end": 1.0, "text": "Hello from captions"}]

    def fake_transcribe_segments(video_id, output_dir, title):
        raise AssertionError("should not fall back to whisper when captions succeed")

    def fake_diarize_speakers(video_id, output_dir, title):
        return [SpeakerSegment(start=0.0, end=1.0, speaker="SPEAKER_00")]

    result = get_transcript(
        "v1",
        tmp_path,
        fetch_caption_segments=fake_fetch_caption_segments,
        transcribe_segments=fake_transcribe_segments,
        diarize_speakers=fake_diarize_speakers,
    )

    assert result.text == "[00:00:00] SPEAKER_00: Hello from captions"


def test_get_transcript_writes_transcript_markdown_file_when_no_title_given(tmp_path):
    get_transcript(
        "v1",
        tmp_path,
        fetch_caption_segments=lambda video_id: [{"start": 0.0, "end": 1.0, "text": "Hello from captions"}],
        transcribe_segments=lambda video_id, output_dir, title: (_ for _ in ()).throw(AssertionError()),
        diarize_speakers=lambda video_id, output_dir, title: [],
    )

    written = (tmp_path / "transcript.md").read_text()
    assert written == "[00:00:00] UNKNOWN: Hello from captions"


def test_get_transcript_writes_to_sanitized_title_based_filename(tmp_path):
    get_transcript(
        "v1",
        tmp_path,
        title="My Video Title",
        fetch_caption_segments=lambda video_id: [{"start": 0.0, "end": 1.0, "text": "Hello from captions"}],
        transcribe_segments=lambda video_id, output_dir, title: (_ for _ in ()).throw(AssertionError()),
        diarize_speakers=lambda video_id, output_dir, title: [],
    )

    written = (tmp_path / "My_Video_Title_TRANSCRIPT.md").read_text()
    assert written == "[00:00:00] UNKNOWN: Hello from captions"


def test_get_transcript_passes_title_through_to_transcribe_segments(tmp_path):
    received = {}

    def fake_transcribe_segments(video_id, output_dir, title):
        received["title"] = title
        return [{"start": 0.0, "end": 1.0, "text": "Hello from whisper"}]

    get_transcript(
        "v1",
        tmp_path,
        title="My Video Title",
        fetch_caption_segments=lambda video_id: (_ for _ in ()).throw(NoCaptionsAvailable(video_id)),
        transcribe_segments=fake_transcribe_segments,
        diarize_speakers=lambda video_id, output_dir, title: [],
    )

    assert received["title"] == "My Video Title"


def test_get_transcript_passes_title_through_to_diarize_speakers(tmp_path):
    received = {}

    def fake_diarize_speakers(video_id, output_dir, title):
        received["title"] = title
        return []

    get_transcript(
        "v1",
        tmp_path,
        title="My Video Title",
        fetch_caption_segments=lambda video_id: [{"start": 0.0, "end": 1.0, "text": "Hello from captions"}],
        transcribe_segments=lambda video_id, output_dir, title: (_ for _ in ()).throw(AssertionError()),
        diarize_speakers=fake_diarize_speakers,
    )

    assert received["title"] == "My Video Title"
