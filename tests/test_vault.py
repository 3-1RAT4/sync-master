from pathlib import Path

from sync_master.playlist_naming import derive_folder_segments
from sync_master.sources.youtube import PlaylistInfo, VideoItem
from sync_master.vault import (
    BLOCK_BEGIN,
    BLOCK_END,
    VaultIndex,
    VideoFolder,
    entry_name,
    new_note,
    place_video,
    read_frontmatter,
    read_transcript_text,
    record_spotify_sync,
    refresh_note,
    sanitize_name,
    split_note,
    store_summary,
    store_transcript,
    store_video,
    summary_to_markdown,
    transcript_to_markdown,
)

PLAYLIST = PlaylistInfo(playlist_id="PL1", title="HUMAN-PODCASTS[!#]")


def _item(video_id="abc", title="Ep: one", position=0, **kw):
    return VideoItem(
        video_id=video_id, title=title, published_at="2025-08-31T10:00:00Z", playlist_id="PL1",
        description="about things", thumbnail_url="https://i/thumb.jpg", position=position, **kw,
    )


# ------------------------------------------------------------------ names


def test_derive_folder_segments_strips_flags_and_splits_on_dashes():
    assert derive_folder_segments("HUMAN-PODCASTS[!#]") == ["HUMAN", "PODCASTS"]
    assert derive_folder_segments("BioHacking") == ["BioHacking"]
    assert derive_folder_segments("A--B-") == ["A", "B"]


def test_sanitize_name_makes_a_title_safe_for_filesystems_and_obsidian_links():
    name = sanitize_name('Andrew Tate | Jack: Neel? "Podcast" #1 [live] <cut> ^ /a\\b*')
    for bad in '/\\:*?"<>|#^[]':
        assert bad not in name
    assert len(sanitize_name("x" * 300)) == 100
    assert sanitize_name("happens...") == "happens"
    assert sanitize_name("   ") == "untitled"


def test_entry_name_is_one_based_position_dot_title():
    assert entry_name(0, "First") == "1.First"
    assert entry_name(9, "Tenth: the sequel") == "10.Tenth- the sequel"


# --------------------------------------------------------------- markdown


def test_transcript_markdown_round_trips_to_the_conversation_format(tmp_path):
    text = (
        "[00:00:00] SPEAKER_02: [Music] I recruited this guy.\n\n"
        "[00:00:13] SPEAKER_00: the wires inside a bomb.\n\n"
        "[01:02:03] UNKNOWN: mumbling"
    )
    md = transcript_to_markdown(text, "vid", "captions", "Mossad")
    assert "**[00:00:00] Speaker 02:** [Music] I recruited this guy." in md
    assert "**[01:02:03] Unattributed:** mumbling" in md
    assert "source: captions" in md

    path = tmp_path / "x.transcript.md"
    path.write_text(md)
    assert read_transcript_text(path) == text


def test_transcript_markdown_keeps_undiarized_text():
    assert "just words" in transcript_to_markdown("just words", "v", "captions", "T")


def test_summary_markdown_keeps_content_verbatim():
    md = summary_to_markdown("**Main**\n\n*   bullet", "v", "deepseek", "deepseek-chat", "T")
    assert "llm_model: deepseek-chat" in md and md.endswith("**Main**\n\n*   bullet\n")


def test_new_note_carries_frontmatter_and_a_managed_block(tmp_path):
    vf = VideoFolder(tmp_path / "1.Ep- one", "1.Ep- one")
    vf.folder.mkdir()
    text = new_note(_item(), PLAYLIST, vf)
    fields, body = split_note(text)
    assert fields["youtube_id"] == "abc" and fields["position"] == 1 and fields["type"] == "video"
    assert fields["published"] == "2025-08-31"
    assert BLOCK_BEGIN in body and BLOCK_END in body
    assert ".mp4" not in body  # nothing downloaded yet, so no embed
    assert "## Description\n\nabout things" in body


# ------------------------------------------------------ note refreshing


def _write_note(vf, item=None):
    vf.folder.mkdir(parents=True, exist_ok=True)
    vf.note.write_text(new_note(item or _item(), PLAYLIST, vf))


def test_refresh_keeps_user_text_and_added_frontmatter_but_updates_the_block(tmp_path):
    vf = VideoFolder(tmp_path / "1.Ep- one", "1.Ep- one")
    _write_note(vf)
    # The user annotates the note and adds their own frontmatter key.
    fields, body = split_note(vf.note.read_text())
    fields["rating"] = 5
    body = body.replace("## Description", "My notes: great episode.\n\n## Description")
    vf.note.write_text("---\n" + __import__("yaml").safe_dump(fields, sort_keys=False) + "---\n" + body)
    # Meanwhile the video gets downloaded and the title changes on YouTube.
    vf.video.write_bytes(b"x")

    refresh_note(vf, _item(title="Ep: one (remastered)"), PLAYLIST)

    fields, body = split_note(vf.note.read_text())
    assert fields["rating"] == 5
    assert fields["title"] == "Ep: one (remastered)"
    assert "My notes: great episode." in body
    assert body.count(BLOCK_BEGIN) == 1
    assert "![[1.Ep- one.mp4]]" in body


def test_refresh_converts_a_note_from_the_first_export_without_duplicating_links(tmp_path):
    vf = VideoFolder(tmp_path / "1.Ep- one", "1.Ep- one")
    vf.folder.mkdir()
    vf.video.write_bytes(b"x")
    vf.transcript.write_text("t")
    # Exactly what export-vault wrote: embed and links inline, no markers.
    vf.note.write_text(
        "---\ntitle: Ep\nyoutube_id: abc\nplaylist_id: PL1\ntype: video\n---\n\n# Ep\n\n"
        "![thumbnail](https://i/thumb.jpg)\n\n![[1.Ep- one.mp4]]\n\n"
        "[[1.Ep- one.transcript|Transcript]] · [[1.Ep- one.summary|Summary]]\n\n"
        "[Watch on YouTube](https://www.youtube.com/watch?v=abc)\n\n## Description\n\nabout things\n"
    )

    refresh_note(vf, _item(), PLAYLIST)

    _, body = split_note(vf.note.read_text())
    assert body.count("![[1.Ep- one.mp4]]") == 1
    assert body.count("[[1.Ep- one.transcript|Transcript]]") == 1
    assert body.count(BLOCK_BEGIN) == 1
    assert body.index("![thumbnail]") < body.index(BLOCK_BEGIN) < body.index("[Watch on YouTube]")
    assert "## Description\n\nabout things" in body


# ------------------------------------------------------- index + placing


def test_index_finds_video_notes_by_frontmatter_and_ignores_the_rest(tmp_path):
    root = tmp_path / "SYNC_MASTER" / "VIDEOS" / "YOUTUBE"
    vf = VideoFolder(root / "HUMAN" / "PODCASTS" / "1.Ep- one", "1.Ep- one")
    _write_note(vf)
    vf.transcript.write_text("---\ntype: transcript\nyoutube_id: abc\n---\n")
    (root / "stray.md").write_text("no frontmatter at all")

    index = VaultIndex.scan(root)

    assert index.find("PL1", "abc") == vf.folder
    assert index.find("PL1", "zzz") is None
    assert len(index.entries) == 1


def test_place_video_creates_then_recognises_then_renames_on_reorder(tmp_path):
    root = tmp_path / "SYNC_MASTER" / "VIDEOS" / "YOUTUBE"
    index = VaultIndex(root)

    first = place_video(index, PLAYLIST, _item(position=0))
    assert first.created and first.folder.folder == root / "HUMAN" / "PODCASTS" / "1.Ep- one"
    assert first.folder.note.exists()
    first.folder.video.write_bytes(b"movie")
    first.folder.transcript.write_text("t")

    # Same position again: found, nothing moves.
    again = place_video(VaultIndex.scan(root), PLAYLIST, _item(position=0))
    assert not again.created and again.moved_from is None

    # Reordered to position 3 and retitled: folder and every prefixed file move.
    moved = place_video(VaultIndex.scan(root), PLAYLIST, _item(position=2, title="Ep: uno"))
    assert moved.moved_from == first.folder.folder
    new = moved.folder
    assert new.folder == root / "HUMAN" / "PODCASTS" / "3.Ep- uno"
    assert not first.folder.folder.exists()
    assert sorted(p.name for p in new.folder.iterdir()) == ["3.Ep- uno.md", "3.Ep- uno.mp4", "3.Ep- uno.transcript.md"]
    assert new.video.read_bytes() == b"movie"
    body = split_note(new.note.read_text())[1]
    assert "![[3.Ep- uno.mp4]]" in body and "1.Ep- one" not in body
    assert read_frontmatter(new.note)["position"] == 3


def test_a_folder_moved_outside_the_managed_root_is_recreated_in_place(tmp_path):
    root = tmp_path / "SYNC_MASTER" / "VIDEOS" / "YOUTUBE"
    placed = place_video(VaultIndex(root), PLAYLIST, _item())
    elsewhere = tmp_path / "ROOT" / "1.Ep- one"
    elsewhere.parent.mkdir()
    placed.folder.folder.rename(elsewhere)

    again = place_video(VaultIndex.scan(root), PLAYLIST, _item())

    assert again.created and again.folder.note.exists()
    assert (elsewhere / "1.Ep- one.md").exists()  # the user's copy is left alone


def test_a_video_in_two_playlists_gets_a_folder_in_each(tmp_path):
    root = tmp_path / "v"
    other = PlaylistInfo(playlist_id="PL2", title="FAVORITOS")
    index = VaultIndex(root)
    a = place_video(index, PLAYLIST, _item())
    b = place_video(index, other, VideoItem(video_id="abc", title="Ep: one", published_at="", playlist_id="PL2", position=4))
    assert a.folder.folder != b.folder.folder
    assert b.folder.folder == root / "FAVORITOS" / "5.Ep- one"


# ---------------------------------------------------------------- outputs


def test_outputs_land_in_the_folder_and_has_output_reflects_the_files(tmp_path):
    vf = VideoFolder(tmp_path / "1.Ep- one", "1.Ep- one")
    _write_note(vf)
    assert not any(vf.has_output(a) for a in ("download", "transcript", "summarize", "spotify_sync"))

    src = tmp_path / "scratch.mp4"
    src.write_bytes(b"\x00\x01" * 10)
    assert store_video(vf, src) == 20
    assert vf.video.read_bytes() == src.read_bytes() and src.exists()  # copied, not moved
    assert not vf.video.with_name(vf.video.name + ".part").exists()

    store_transcript(vf, "[00:00:01] SPEAKER_00: hi", "captions", "Ep: one")
    store_summary(vf, "**S**", "deepseek", "deepseek-chat", "Ep: one")
    record_spotify_sync(vf, "spotify:track:1", "pl9", "search")

    assert all(vf.has_output(a) for a in ("download", "transcript", "summarize", "spotify_sync"))
    assert "youtube_id: abc" in vf.transcript.read_text()
    assert read_frontmatter(vf.note)["spotify_track_uri"] == "spotify:track:1"
    assert read_transcript_text(vf.transcript) == "[00:00:01] SPEAKER_00: hi"


def test_two_videos_with_the_same_title_can_trade_positions(tmp_path):
    """Two "Deleted video" placeholders swapping positions: the second's
    target is occupied by the first until the first has moved."""
    root = tmp_path / "v"
    index = VaultIndex(root)
    a = place_video(index, PLAYLIST, _item(video_id="a", title="Deleted video", position=0))
    b = place_video(index, PLAYLIST, _item(video_id="b", title="Deleted video", position=1))
    a.folder.video.write_bytes(b"A"); b.folder.video.write_bytes(b"B")

    # Swap: processed in the new order, so b (now at 1.) is placed first while
    # a still sits in "1.Deleted video".
    index = VaultIndex.scan(root)
    moved_b = place_video(index, PLAYLIST, _item(video_id="b", title="Deleted video", position=0))
    moved_a = place_video(index, PLAYLIST, _item(video_id="a", title="Deleted video", position=1))

    folders = sorted(p.name for p in (root / "HUMAN" / "PODCASTS").iterdir())
    assert folders == ["1.Deleted video", "2.Deleted video"]  # nothing parked, nothing lost
    assert moved_b.folder.video.read_bytes() == b"B" and moved_a.folder.video.read_bytes() == b"A"
    assert read_frontmatter(moved_a.folder.note)["youtube_id"] == "a"
    assert sorted(p.name for p in moved_a.folder.folder.iterdir()) == ["2.Deleted video.md", "2.Deleted video.mp4"]


def test_a_stale_occupant_is_parked_visibly_not_deleted(tmp_path):
    root = tmp_path / "v"
    index = VaultIndex(root)
    place_video(index, PLAYLIST, _item(video_id="gone", title="Deleted video", position=0))
    place_video(index, PLAYLIST, _item(video_id="stays", title="Deleted video", position=3))

    # "gone" left the playlist; "stays" moves into its old slot and nothing ever places "gone" again.
    place_video(VaultIndex.scan(root), PLAYLIST, _item(video_id="stays", title="Deleted video", position=0))

    folders = sorted(p.name for p in (root / "HUMAN" / "PODCASTS").iterdir())
    assert folders == ["1.Deleted video", "1.Deleted video.moving-gone"]
    assert read_frontmatter(root / "HUMAN" / "PODCASTS" / "1.Deleted video" / "1.Deleted video.md")["youtube_id"] == "stays"
    parked = root / "HUMAN" / "PODCASTS" / "1.Deleted video.moving-gone"
    assert (parked / "1.Deleted video.md").exists()  # its files are intact, prefix untouched


def test_creating_into_an_occupied_name_never_hijacks_the_occupant(tmp_path):
    """A new video whose N.Title matches an existing different video's folder
    (same placeholder title, the old one not yet moved) must not take over
    that note."""
    root = tmp_path / "v"
    index = VaultIndex(root)
    old = place_video(index, PLAYLIST, _item(video_id="old", title="Deleted video", position=0))
    old.folder.video.write_bytes(b"OLD")

    fresh = VaultIndex.scan(root)  # "old" is known; "new" is not
    new = place_video(fresh, PLAYLIST, _item(video_id="new", title="Deleted video", position=0))

    assert new.created
    assert read_frontmatter(new.folder.note)["youtube_id"] == "new"
    parked = root / "HUMAN" / "PODCASTS" / "1.Deleted video.moving-old"
    assert read_frontmatter(parked / "1.Deleted video.md")["youtube_id"] == "old"
    assert (parked / "1.Deleted video.mp4").read_bytes() == b"OLD"
    # and when "old" finally gets its real place, it comes back out of the park
    moved = place_video(fresh, PLAYLIST, _item(video_id="old", title="Deleted video", position=7))
    assert moved.folder.folder == root / "HUMAN" / "PODCASTS" / "8.Deleted video"
    assert moved.folder.video.read_bytes() == b"OLD" and not parked.exists()
