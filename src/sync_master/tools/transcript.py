from dataclasses import dataclass
from pathlib import Path


class NoCaptionsAvailable(Exception):
    pass


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    source: str


def _default_fetch_captions(video_id: str) -> str:
    from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id)
    except (NoTranscriptFound, TranscriptsDisabled) as exc:
        raise NoCaptionsAvailable(video_id) from exc
    return " ".join(segment["text"] for segment in segments)


def _default_transcribe_audio(video_id: str, output_dir: Path) -> str:
    from sync_master.tools.download import download_video

    audio_path = download_video(video_id, output_dir)

    import whisper

    model = whisper.load_model("base")
    result = model.transcribe(str(audio_path))
    return result["text"]


def get_transcript(
    video_id: str,
    output_dir: Path,
    fetch_captions=None,
    transcribe_audio=None,
) -> TranscriptResult:
    fetch_captions = fetch_captions or _default_fetch_captions
    transcribe_audio = transcribe_audio or _default_transcribe_audio

    try:
        text = fetch_captions(video_id)
        source = "captions"
    except NoCaptionsAvailable:
        text = transcribe_audio(video_id, output_dir)
        source = "whisper"

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "transcript.md").write_text(text)

    return TranscriptResult(text=text, source=source)
