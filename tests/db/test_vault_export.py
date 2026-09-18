from pathlib import Path

from sync_master.db import repository
from sync_master.sources.youtube import PlaylistInfo, VideoItem
from sync_master.vault_export import VAULT_SUBDIR, export_vault


def _seed(session):
    """One processed video (file + transcript + summary) and one catalogued-only video."""
    playlist_pk = repository.upsert_playlist(session, source="youtube", external_id="PL1", title="HUMAN-PODCASTS[!#]")
    repository.upsert_video(session, source="youtube", external_id="done", playlist_id=playlist_pk, title="Ep: one")
    repository.upsert_video(session, source="youtube", external_id="bare", playlist_id=playlist_pk, title="Ep two")
    repository.save_video_file(session, "done", filename="a.mp4", content_type="video/mp4", content=b"\x00\x01mp4bytes" * 1000)
    repository.save_transcript(session, "done", "captions", "[00:00:00] SPEAKER_00: hello there", [])
    repository.save_summary(session, "done", "**Summary**", "instr", "deepseek", "deepseek-chat")


def _fake_youtube():
    playlists = [PlaylistInfo(playlist_id="PL1", title="HUMAN-PODCASTS[!#]")]
    # Reversed on purpose: position must come from YouTube, not from the DB.
    items = [
        VideoItem(video_id="bare", title="Ep two", published_at="", playlist_id="PL1", position=0),
        VideoItem(video_id="done", title="Ep: one", published_at="2025-08-31T00:00:00Z", playlist_id="PL1", position=1),
        # In the playlist on YouTube but not in the catalog yet - still gets a note.
        VideoItem(video_id="new", title="Ep three", published_at="", playlist_id="PL1", position=2),
    ]
    return (lambda client: playlists), (lambda pid, youtube_client=None: items)


def test_export_writes_the_agreed_tree_and_round_trips_the_video(db_session, tmp_path):
    _seed(db_session)
    fetch_playlists, fetch_items = _fake_youtube()

    stats = export_vault(
        tmp_path, db_session, youtube_client=None, fetch_playlists_fn=fetch_playlists, fetch_items_fn=fetch_items, log=lambda *_: None
    )

    playlist_dir = tmp_path / VAULT_SUBDIR / "HUMAN" / "PODCASTS"
    assert sorted(p.name for p in playlist_dir.iterdir()) == ["1.Ep two", "2.Ep- one", "3.Ep three"]

    done = playlist_dir / "2.Ep- one"
    assert sorted(p.name for p in done.iterdir()) == [
        "2.Ep- one.md", "2.Ep- one.mp4", "2.Ep- one.summary.md", "2.Ep- one.transcript.md",
    ]
    assert (done / "2.Ep- one.mp4").read_bytes() == b"\x00\x01mp4bytes" * 1000
    assert not (done / "2.Ep- one.mp4.part").exists()
    assert "![[2.Ep- one.mp4]]" in (done / "2.Ep- one.md").read_text()
    transcript = (done / "2.Ep- one.transcript.md").read_text()
    assert "**[00:00:00] Speaker 00:** hello there" in transcript
    assert "source: captions" in transcript  # the enum's value, not "TranscriptSource.CAPTIONS"

    for folder in ("1.Ep two", "3.Ep three"):
        assert [p.name for p in (playlist_dir / folder).iterdir()] == [f"{folder}.md"]

    assert (stats.playlists, stats.notes, stats.videos, stats.transcripts, stats.summaries) == (1, 3, 1, 1, 1)
    assert stats.video_bytes == len(b"\x00\x01mp4bytes" * 1000)


def test_dry_run_writes_nothing_but_counts_everything(db_session, tmp_path):
    _seed(db_session)
    fetch_playlists, fetch_items = _fake_youtube()

    stats = export_vault(
        tmp_path, db_session, youtube_client=None, dry_run=True, fetch_playlists_fn=fetch_playlists, fetch_items_fn=fetch_items, log=lambda *_: None
    )

    assert not (tmp_path / "SYNC_MASTER").exists()
    assert (stats.notes, stats.videos, stats.transcripts, stats.summaries) == (3, 1, 1, 1)


def test_write_video_file_to_streams_and_returns_none_when_nothing_stored(db_session, tmp_path):
    repository.upsert_video(db_session, source="youtube", external_id="v", title="T")
    assert repository.write_video_file_to(db_session, "v", tmp_path / "x.mp4") is None
    assert not (tmp_path / "x.mp4").exists()

    payload = bytes(range(256)) * 5000  # 1.28 MB - crosses a 1 MB chunk boundary
    repository.save_video_file(db_session, "v", filename="x.mp4", content_type="video/mp4", content=payload)
    assert repository.write_video_file_to(db_session, "v", tmp_path / "x.mp4") == len(payload)
    assert (tmp_path / "x.mp4").read_bytes() == payload
