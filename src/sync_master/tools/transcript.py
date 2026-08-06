from dataclasses import dataclass
from pathlib import Path

from sync_master.tools.naming import transcript_filename


class NoCaptionsAvailable(Exception):
    pass


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    source: str


def _default_fetch_caption_segments(video_id: str) -> list[dict]:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import CouldNotRetrieveTranscript

    try:
        fetched = YouTubeTranscriptApi().fetch(video_id)
    except CouldNotRetrieveTranscript as exc:
        raise NoCaptionsAvailable(video_id) from exc
    return [
        {"start": snippet.start, "end": snippet.start + snippet.duration, "text": snippet.text}
        for snippet in fetched
    ]


def _default_transcribe_segments(video_id: str, output_dir: Path, title: str | None) -> list[dict]:
    from sync_master.tools.download import download_video

    audio_path = download_video(video_id, output_dir, title=title)

    import whisper

    model = whisper.load_model("base")
    result = model.transcribe(str(audio_path))
    return [{"start": seg["start"], "end": seg["end"], "text": seg["text"]} for seg in result["segments"]]


def _default_diarize_speakers(video_id: str, output_dir: Path, title: str | None):
    from sync_master.tools.diarize import diarize_audio
    from sync_master.tools.download import download_video

    audio_path = download_video(video_id, output_dir, title=title)
    return diarize_audio(audio_path)


def get_transcript(
    video_id: str,
    output_dir: Path,
    title: str | None = None,
    fetch_caption_segments=None,
    transcribe_segments=None,
    diarize_speakers=None,
) -> TranscriptResult:
    from sync_master.tools.diarize import format_as_conversation

    fetch_caption_segments = fetch_caption_segments or _default_fetch_caption_segments
    transcribe_segments = transcribe_segments or _default_transcribe_segments
    diarize_speakers = diarize_speakers or _default_diarize_speakers

    try:
        segments = fetch_caption_segments(video_id)
        source = "captions"
    except NoCaptionsAvailable:
        segments = transcribe_segments(video_id, output_dir, title)
        source = "whisper"

    speaker_segments = diarize_speakers(video_id, output_dir, title)
    text = format_as_conversation(segments, speaker_segments)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / transcript_filename(title)).write_text(text)

    return TranscriptResult(text=text, source=source)
