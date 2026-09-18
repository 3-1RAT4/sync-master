from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeakerSegment:
    start: float
    end: float
    speaker: str


def _default_pipeline(device: str | None = None):
    import os

    import torch
    from pyannote.audio import Pipeline

    from sync_master.tools.device import torch_device

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=os.environ.get("HUGGINGFACE_TOKEN"),
    )
    # from_pretrained leaves the pipeline on the CPU whatever the machine has;
    # diarizing a multi-hour recording there takes hours, on a GPU minutes.
    return pipeline.to(torch.device(device or torch_device()))


SAMPLE_RATE = 16_000


def load_waveform(audio_path: Path, sample_rate: int = SAMPLE_RATE) -> dict:
    """Decodes anything ffmpeg understands into the in-memory form pyannote
    accepts: {"waveform": (channels, samples) float32 tensor, "sample_rate"}.

    Handing pyannote a file path makes it decode through torchcodec, which
    dlopens FFmpeg's *shared libraries* at runtime - a system dependency this
    project never declared. It happened to work where those libraries were
    installed for other reasons, and fails anywhere with only an ffmpeg
    binary (a static build, say). The binary is already a required tool
    (bootstrap.REQUIRED_EXTERNAL_TOOLS) and is how Whisper decodes, so the
    same subprocess here removes the hidden dependency entirely.
    """
    import subprocess

    import numpy as np
    import torch

    # fmt: off
    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0",
        "-i", str(audio_path),
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(sample_rate),
        "-",
    ]
    # fmt: on
    try:
        pcm = subprocess.run(cmd, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffmpeg could not decode {audio_path}: {exc.stderr.decode(errors='replace')}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not on PATH (it is a required tool, see docs/setup.md)") from exc

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return {"waveform": torch.from_numpy(samples).unsqueeze(0), "sample_rate": sample_rate}


def diarize_audio(audio_path: Path, pipeline=None, load_audio=load_waveform) -> list[SpeakerSegment]:
    active_pipeline = pipeline or _default_pipeline()
    diarization = active_pipeline(load_audio(audio_path))

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


def _format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_as_conversation(segments: list[dict], speaker_segments: list[SpeakerSegment]) -> str:
    turns: list[list] = []

    for segment in segments:
        speaker = _best_speaker(segment["start"], segment["end"], speaker_segments)
        text = segment["text"].strip()

        if turns and turns[-1][1] == speaker:
            turns[-1][2] = f"{turns[-1][2]} {text}"
        else:
            turns.append([segment["start"], speaker, text])

    return "\n\n".join(
        f"[{_format_timestamp(start)}] {speaker}: {text}" for start, speaker, text in turns
    )
