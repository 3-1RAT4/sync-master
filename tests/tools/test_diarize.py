import shutil
import subprocess

import pytest

from sync_master.tools.diarize import SAMPLE_RATE, SpeakerSegment, diarize_audio, format_as_conversation, load_waveform


class FakeSegment:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class FakeAnnotation:
    def __init__(self, tracks):
        self._tracks = tracks

    def itertracks(self, yield_label=False):
        for segment, track, label in self._tracks:
            yield segment, track, label


class FakeDiarizeOutput:
    def __init__(self, exclusive_tracks):
        self.exclusive_speaker_diarization = FakeAnnotation(exclusive_tracks)


def test_diarize_audio_returns_speaker_segments_from_exclusive_diarization(tmp_path):
    audio_path = tmp_path / "audio.mp3"
    tracks = [
        (FakeSegment(0.0, 5.0), "track_0", "SPEAKER_00"),
        (FakeSegment(5.0, 10.0), "track_1", "SPEAKER_01"),
    ]

    decoded = {"waveform": "fake-tensor", "sample_rate": SAMPLE_RATE}
    received = []

    def fake_pipeline(audio):
        received.append(audio)
        return FakeDiarizeOutput(tracks)

    segments = diarize_audio(audio_path, pipeline=fake_pipeline, load_audio=lambda path: decoded)

    assert segments == [
        SpeakerSegment(start=0.0, end=5.0, speaker="SPEAKER_00"),
        SpeakerSegment(start=5.0, end=10.0, speaker="SPEAKER_01"),
    ]
    # The pipeline must get the decoded waveform, never the path - a path makes
    # pyannote decode via torchcodec, which needs FFmpeg shared libraries.
    assert received == [decoded]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_load_waveform_decodes_through_the_ffmpeg_binary(tmp_path):
    # Two seconds of a 440Hz tone, synthesised by ffmpeg itself so the test
    # needs no fixture file - and in AAC/m4a, the container yt-dlp produces.
    audio_path = tmp_path / "tone.m4a"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:a", "aac", str(audio_path)],
        check=True,
    )

    audio = load_waveform(audio_path)

    assert audio["sample_rate"] == SAMPLE_RATE
    waveform = audio["waveform"]
    assert tuple(waveform.shape[:1]) == (1,)  # mono
    assert abs(waveform.shape[1] - 2 * SAMPLE_RATE) < SAMPLE_RATE // 10  # ~2s, AAC priming tolerated
    assert str(waveform.dtype) == "torch.float32"
    assert float(waveform.abs().max()) <= 1.0
    assert float(waveform.abs().max()) > 0.1  # it's not silence


def test_format_as_conversation_groups_consecutive_same_speaker_segments():
    whisper_segments = [
        {"start": 0.0, "end": 2.0, "text": " Hello there."},
        {"start": 2.0, "end": 4.0, "text": " How are you?"},
        {"start": 4.5, "end": 6.0, "text": " I'm doing well."},
    ]
    speaker_segments = [
        SpeakerSegment(start=0.0, end=4.0, speaker="SPEAKER_00"),
        SpeakerSegment(start=4.0, end=6.0, speaker="SPEAKER_01"),
    ]

    text = format_as_conversation(whisper_segments, speaker_segments)

    assert text == (
        "[00:00:00] SPEAKER_00: Hello there. How are you?\n\n"
        "[00:00:04] SPEAKER_01: I'm doing well."
    )


def test_format_as_conversation_assigns_closest_speaker_when_no_overlap():
    whisper_segments = [{"start": 10.0, "end": 11.0, "text": " Later text."}]
    speaker_segments = [
        SpeakerSegment(start=0.0, end=5.0, speaker="SPEAKER_00"),
        SpeakerSegment(start=6.0, end=9.0, speaker="SPEAKER_01"),
    ]

    text = format_as_conversation(whisper_segments, speaker_segments)

    assert text == "[00:00:10] SPEAKER_01: Later text."


def test_format_as_conversation_returns_unknown_speaker_when_no_segments():
    whisper_segments = [{"start": 0.0, "end": 1.0, "text": " Hello."}]

    text = format_as_conversation(whisper_segments, [])

    assert text == "[00:00:00] UNKNOWN: Hello."


def test_format_as_conversation_formats_timestamp_past_one_hour():
    whisper_segments = [{"start": 3725.0, "end": 3726.0, "text": " One hour and change."}]

    text = format_as_conversation(whisper_segments, [])

    assert text == "[01:02:05] UNKNOWN: One hour and change."
