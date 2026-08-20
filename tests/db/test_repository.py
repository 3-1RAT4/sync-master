from pathlib import Path

import pytest

from sync_master.db import repository
from sync_master.tools.diarize import SpeakerSegment


def _make_video(session, video_id="v1"):
    return repository.upsert_video(session, source="youtube", external_id=video_id, title="Ep 1")


def test_upsert_playlist_is_idempotent_and_updates_on_conflict(db_session):
    repository.upsert_playlist(
        db_session,
        source="youtube",
        external_id="PL123",
        title="OLD-NAME[!]",
        folder_path=Path("OLD/NAME"),
        leaf_name="NAME",
        actions=["download"],
    )
    repository.upsert_playlist(
        db_session,
        source="youtube",
        external_id="PL123",
        title="NEW-NAME[!@]",
        folder_path=Path("NEW/NAME"),
        leaf_name="NAME",
        actions=["download", "spotify_sync"],
    )

    row = db_session.execute(
        repository.select(repository.Playlist).where(repository.Playlist.external_id == "PL123")
    ).scalar_one()

    assert row.title == "NEW-NAME[!@]"
    assert row.actions == ["download", "spotify_sync"]


def test_upsert_playlist_allows_untracked_playlists_with_null_flag_fields(db_session):
    repository.upsert_playlist(
        db_session,
        source="youtube",
        external_id="PL999",
        title="Favoritos",
        description="A playlist with no recognized flags",
        item_count=5,
    )

    row = db_session.execute(
        repository.select(repository.Playlist).where(repository.Playlist.external_id == "PL999")
    ).scalar_one()

    assert row.folder_path is None
    assert row.leaf_name is None
    assert row.actions is None
    assert row.item_count == 5


def test_load_state_returns_empty_structure_by_default(db_session):
    state = repository.load_state(db_session)

    assert state == {"videos": {}}


def test_save_then_load_state_round_trips_the_whole_document(db_session):
    data = {
        "videos": {
            "v1": {
                "playlist_id": "PL123",
                "title": "Ep 1",
                "published_at": "2026-01-01T00:00:00Z",
                "actions": {"download": {"status": "done", "updated_at": "2026-01-01T00:00:00Z"}},
            }
        }
    }

    repository.save_state(db_session, data)
    loaded = repository.load_state(db_session)

    assert loaded == data


def test_save_state_overwrites_the_previous_document(db_session):
    repository.save_state(db_session, {"videos": {"v1": {"title": "first"}}})
    repository.save_state(db_session, {"videos": {"v2": {"title": "second"}}})

    assert repository.load_state(db_session) == {"videos": {"v2": {"title": "second"}}}


def test_upsert_video_is_idempotent_and_updates_on_conflict(db_session):
    repository.upsert_video(db_session, source="youtube", external_id="v1", title="Old Title")
    repository.upsert_video(db_session, source="youtube", external_id="v1", title="New Title")

    row = db_session.execute(
        repository.select(repository.Video).where(repository.Video.external_id == "v1")
    ).scalar_one()
    assert row.title == "New Title"


def test_upsert_video_links_to_its_playlist(db_session):
    playlist_pk = repository.upsert_playlist(
        db_session, source="youtube", external_id="PL123", title="Some Playlist[!]"
    )
    video_pk = repository.upsert_video(
        db_session, source="youtube", external_id="v1", title="Ep 1", playlist_id=playlist_pk
    )

    row = db_session.execute(
        repository.select(repository.Video).where(repository.Video.id == video_pk)
    ).scalar_one()
    assert row.playlist_id == playlist_pk


def test_save_video_file_round_trips_bytes(db_session):
    _make_video(db_session)

    repository.save_video_file(
        db_session, "v1", filename="Ep_1.mp4", content_type="video/mp4", content=b"fake video bytes"
    )

    row = db_session.execute(
        repository.select(repository.VideoFile).join(repository.Video).where(repository.Video.external_id == "v1")
    ).scalar_one()

    assert row.filename == "Ep_1.mp4"
    assert row.size_bytes == len(b"fake video bytes")
    assert repository.get_video_file_content(db_session, "v1") == b"fake video bytes"


def test_save_video_file_replacing_content_does_not_leak_the_old_large_object(db_session):
    _make_video(db_session)

    repository.save_video_file(db_session, "v1", filename="a.mp4", content_type="video/mp4", content=b"first")
    old_oid = db_session.execute(
        repository.select(repository.VideoFile.content_oid)
        .join(repository.Video)
        .where(repository.Video.external_id == "v1")
    ).scalar_one()

    repository.save_video_file(db_session, "v1", filename="a.mp4", content_type="video/mp4", content=b"second")

    assert repository.get_video_file_content(db_session, "v1") == b"second"
    orphaned = db_session.execute(
        repository.text("SELECT count(*) FROM pg_largeobject_metadata WHERE oid = :oid"), {"oid": old_oid}
    ).scalar_one()
    assert orphaned == 0


def test_save_transcript_persists_text_source_and_segments(db_session):
    _make_video(db_session)

    repository.save_transcript(
        db_session,
        "v1",
        source="captions",
        text_="[00:00:00] SPEAKER_00: hello",
        segments=[SpeakerSegment(start=0.0, end=1.0, speaker="SPEAKER_00")],
    )

    assert repository.get_transcript_text(db_session, "v1") == "[00:00:00] SPEAKER_00: hello"

    transcript = db_session.execute(
        repository.select(repository.Transcript).join(repository.Video).where(repository.Video.external_id == "v1")
    ).scalar_one()
    assert transcript.source.value == "captions"
    assert [s.speaker for s in transcript.segments] == ["SPEAKER_00"]


def test_save_transcript_replaces_segments_on_resave(db_session):
    _make_video(db_session)

    repository.save_transcript(
        db_session, "v1", source="whisper", text_="first",
        segments=[SpeakerSegment(start=0.0, end=1.0, speaker="SPEAKER_00")],
    )
    repository.save_transcript(
        db_session, "v1", source="whisper", text_="second",
        segments=[SpeakerSegment(start=0.0, end=1.0, speaker="SPEAKER_01")],
    )

    transcript = db_session.execute(
        repository.select(repository.Transcript).join(repository.Video).where(repository.Video.external_id == "v1")
    ).scalar_one()
    assert transcript.text == "second"
    assert [s.speaker for s in transcript.segments] == ["SPEAKER_01"]


def test_save_summary_round_trips(db_session):
    _make_video(db_session)

    repository.save_summary(
        db_session, "v1", content="a summary", instructions="be brief",
        llm_provider="deepseek", llm_model="deepseek-chat",
    )

    row = db_session.execute(
        repository.select(repository.Summary).join(repository.Video).where(repository.Video.external_id == "v1")
    ).scalar_one()
    assert row.content == "a summary"
    assert row.llm_model == "deepseek-chat"


def test_save_spotify_sync_extracts_track_id_and_round_trips(db_session):
    _make_video(db_session)

    repository.save_spotify_sync(
        db_session, "v1",
        spotify_track_id="abc123",
        spotify_track_uri="spotify:track:abc123",
        spotify_playlist_id="spotify:playlist:zzz",
        matched_via="search",
    )

    row = db_session.execute(
        repository.select(repository.SpotifySync).join(repository.Video).where(repository.Video.external_id == "v1")
    ).scalar_one()
    assert row.spotify_track_id == "abc123"
    assert row.matched_via.value == "search"


def test_get_spotify_playlist_id_returns_none_when_not_cached(db_session):
    assert repository.get_spotify_playlist_id(db_session, "PARTY") is None


def test_save_then_get_spotify_playlist_id_round_trips(db_session):
    repository.save_spotify_playlist_id(db_session, "PARTY", "spotify:playlist:abc")

    assert repository.get_spotify_playlist_id(db_session, "PARTY") == "spotify:playlist:abc"


def test_save_spotify_playlist_id_upserts_on_conflict(db_session):
    repository.save_spotify_playlist_id(db_session, "PARTY", "spotify:playlist:old")
    repository.save_spotify_playlist_id(db_session, "PARTY", "spotify:playlist:new")

    assert repository.get_spotify_playlist_id(db_session, "PARTY") == "spotify:playlist:new"


def test_acquire_run_lock_blocks_concurrent_acquisition(db_engine):
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db_engine)
    session_a = Session()
    session_b = Session()

    try:
        with repository.acquire_run_lock(session_a):
            with pytest.raises(repository.LockHeldError):
                with repository.acquire_run_lock(session_b):
                    pass
    finally:
        session_a.close()
        session_b.close()


def test_acquire_run_lock_can_be_reacquired_after_release(db_session):
    with repository.acquire_run_lock(db_session):
        pass

    with repository.acquire_run_lock(db_session):
        pass
