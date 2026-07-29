from sync_master.tools.transcript import NoCaptionsAvailable, TranscriptResult, get_transcript


def test_get_transcript_uses_captions_when_available(tmp_path):
    def fake_fetch_captions(video_id):
        return "Hello from captions"

    def fake_transcribe_audio(video_id, output_dir, title):
        raise AssertionError("should not fall back to whisper when captions succeed")

    result = get_transcript(
        "v1",
        tmp_path,
        fetch_captions=fake_fetch_captions,
        transcribe_audio=fake_transcribe_audio,
    )

    assert result == TranscriptResult(text="Hello from captions", source="captions")


def test_get_transcript_falls_back_to_whisper_when_no_captions(tmp_path):
    def fake_fetch_captions(video_id):
        raise NoCaptionsAvailable(video_id)

    def fake_transcribe_audio(video_id, output_dir, title):
        return "Hello from whisper"

    result = get_transcript(
        "v1",
        tmp_path,
        fetch_captions=fake_fetch_captions,
        transcribe_audio=fake_transcribe_audio,
    )

    assert result == TranscriptResult(text="Hello from whisper", source="whisper")


def test_get_transcript_writes_transcript_markdown_file_when_no_title_given(tmp_path):
    get_transcript(
        "v1",
        tmp_path,
        fetch_captions=lambda video_id: "Hello from captions",
        transcribe_audio=lambda video_id, output_dir, title: (_ for _ in ()).throw(AssertionError()),
    )

    written = (tmp_path / "transcript.md").read_text()
    assert written == "Hello from captions"


def test_get_transcript_writes_to_sanitized_title_based_filename(tmp_path):
    get_transcript(
        "v1",
        tmp_path,
        title="My Video Title",
        fetch_captions=lambda video_id: "Hello from captions",
        transcribe_audio=lambda video_id, output_dir, title: (_ for _ in ()).throw(AssertionError()),
    )

    written = (tmp_path / "My_Video_Title_TRANSCRIPT.md").read_text()
    assert written == "Hello from captions"


def test_get_transcript_passes_title_through_to_transcribe_audio(tmp_path):
    received = {}

    def fake_transcribe_audio(video_id, output_dir, title):
        received["title"] = title
        return "Hello from whisper"

    get_transcript(
        "v1",
        tmp_path,
        title="My Video Title",
        fetch_captions=lambda video_id: (_ for _ in ()).throw(NoCaptionsAvailable(video_id)),
        transcribe_audio=fake_transcribe_audio,
    )

    assert received["title"] == "My Video Title"
