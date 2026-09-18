from sync_master.playlist_naming import derive_folder_segments
from sync_master.sources.youtube import PlaylistInfo, VideoItem
from sync_master.vault_export import (
    entry_name,
    sanitize_name,
    summary_to_markdown,
    transcript_to_markdown,
    video_note,
)


def test_derive_folder_segments_strips_flags_and_splits_on_dashes():
    assert derive_folder_segments("HUMAN-PODCASTS[!#]") == ["HUMAN", "PODCASTS"]
    assert derive_folder_segments("HUMAN-HEARTH-ART-DANCE") == ["HUMAN", "HEARTH", "ART", "DANCE"]
    # No dashes, no flags: a single top-level folder, not "unclassified".
    assert derive_folder_segments("BioHacking") == ["BioHacking"]
    # Empty segments from a stray dash don't become empty folders.
    assert derive_folder_segments("A--B-") == ["A", "B"]


def test_sanitize_name_makes_a_title_safe_for_filesystems_and_obsidian_links():
    title = 'Andrew Tate | Jack: Neel? "Podcast" #1 [live] <cut> ^ /a\\b*'
    name = sanitize_name(title)
    for bad in '/\\:*?"<>|#^[]':
        assert bad not in name, f"{bad!r} survived in {name!r}"
    assert name == "Andrew Tate - Jack- Neel- -Podcast- -1 -live- -cut- - -a-b-"


def test_sanitize_name_caps_length_and_trims_trailing_dots():
    long = "x" * 300
    assert len(sanitize_name(long)) == 100
    assert sanitize_name("release this if something happens...") == "release this if something happens"
    assert sanitize_name("   ") == "untitled"


def test_entry_name_is_one_based_position_dot_title():
    assert entry_name(0, "First") == "1.First"
    assert entry_name(9, "Tenth: the sequel") == "10.Tenth- the sequel"


def test_transcript_to_markdown_renders_the_diarized_format_one_turn_per_paragraph():
    text = (
        "[00:00:00] SPEAKER_02: [Music] I recruited this guy from scratch.\n\n"
        "[00:00:13] SPEAKER_00: the wires inside a bomb.\n\n"
        "[01:02:03] UNKNOWN: mumbling"
    )
    md = transcript_to_markdown(text, "t3FxH39oYsA", "captions", "Mossad")
    assert md.startswith("---\n")
    assert "youtube_id: t3FxH39oYsA" in md and "source: captions" in md and "type: transcript" in md
    assert "**[00:00:00] Speaker 02:** [Music] I recruited this guy from scratch." in md
    assert "**[00:00:13] Speaker 00:** the wires inside a bomb." in md
    assert "**[01:02:03] Unattributed:** mumbling" in md


def test_transcript_to_markdown_keeps_undiarized_text_instead_of_dropping_it():
    md = transcript_to_markdown("just words, no timestamps", "v", "captions", "T")
    assert "just words, no timestamps" in md


def test_summary_to_markdown_keeps_content_verbatim_with_model_in_frontmatter():
    md = summary_to_markdown("**Main Topic**\n\n*   bullet", "v", "deepseek", "deepseek-chat", "T")
    assert "llm_provider: deepseek" in md and "llm_model: deepseek-chat" in md
    assert md.endswith("**Main Topic**\n\n*   bullet\n")


def test_video_note_links_only_what_exists():
    playlist = PlaylistInfo(playlist_id="PL1", title="HUMAN-PODCASTS[!#]")
    item = VideoItem(
        video_id="abc", title="Ep: one", published_at="2025-08-31T10:00:00Z", playlist_id="PL1",
        description="about things", thumbnail_url="https://i/thumb.jpg", position=0,
    )
    full = video_note(item, playlist, "1.Ep- one", has_video=True, has_transcript=True, has_summary=True)
    assert "position: 1" in full and "published: '2025-08-31'" in full and "playlist: HUMAN-PODCASTS[!#]" in full
    assert "![[1.Ep- one.mp4]]" in full
    assert "[[1.Ep- one.transcript|Transcript]]" in full and "[[1.Ep- one.summary|Summary]]" in full
    assert "![thumbnail](https://i/thumb.jpg)" in full and "## Description\n\nabout things" in full

    bare = video_note(item, playlist, "1.Ep- one", has_video=False, has_transcript=False, has_summary=False)
    assert ".mp4" not in bare and "transcript" not in bare and "summary" not in bare
    assert "https://www.youtube.com/watch?v=abc" in bare
