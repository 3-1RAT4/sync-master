from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeakerSegment:
    start: float
    end: float
    speaker: str


def _default_pipeline():
    import os

    from pyannote.audio import Pipeline

    return Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=os.environ.get("HUGGINGFACE_TOKEN"),
    )


def diarize_audio(audio_path: Path, pipeline=None) -> list[SpeakerSegment]:
    active_pipeline = pipeline or _default_pipeline()
    diarization = active_pipeline(str(audio_path))

    return [
        SpeakerSegment(start=segment.start, end=segment.end, speaker=speaker)
        for segment, _, speaker in diarization.exclusive_speaker_diarization.itertracks(yield_label=True)
    ]


def _overlap(w_start: float, w_end: float, sp_start: float, sp_end: float) -> float:
    return max(0.0, min(w_end, sp_end) - max(w_start, sp_start))


def _distance(w_start: float, w_end: float, sp_start: float, sp_end: float) -> float:
    return min(
        abs(w_start - sp_start),
        abs(w_start - sp_end),
        abs(w_end - sp_start),
        abs(w_end - sp_end),
    )


def _best_speaker(w_start: float, w_end: float, speaker_segments: list[SpeakerSegment]) -> str:
    if not speaker_segments:
        return "UNKNOWN"

    best = max(
        speaker_segments,
        key=lambda sp: (
            _overlap(w_start, w_end, sp.start, sp.end),
            -_distance(w_start, w_end, sp.start, sp.end),
        ),
    )
    return best.speaker


def format_as_conversation(whisper_segments: list[dict], speaker_segments: list[SpeakerSegment]) -> str:
    turns: list[list[str]] = []

    for segment in whisper_segments:
        speaker = _best_speaker(segment["start"], segment["end"], speaker_segments)
        text = segment["text"].strip()

        if turns and turns[-1][0] == speaker:
            turns[-1][1] = f"{turns[-1][1]} {text}"
        else:
            turns.append([speaker, text])

    return "\n\n".join(f"{speaker}: {text}" for speaker, text in turns)
