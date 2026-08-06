from sync_master.tools.diarize import SpeakerSegment, diarize_audio, format_as_conversation


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

    segments = diarize_audio(audio_path, pipeline=lambda path: FakeDiarizeOutput(tracks))

    assert segments == [
        SpeakerSegment(start=0.0, end=5.0, speaker="SPEAKER_00"),
        SpeakerSegment(start=5.0, end=10.0, speaker="SPEAKER_01"),
    ]


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
