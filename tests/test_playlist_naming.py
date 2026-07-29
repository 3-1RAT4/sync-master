from pathlib import Path

from sync_master.playlist_naming import ParsedPlaylist, parse_playlist_name


def test_parses_folder_path_leaf_name_and_actions():
    parsed = parse_playlist_name("HUMAN-HEARTH-ART-MUSIC-PLAYLISTS-PARTY[!@]")

    assert parsed == ParsedPlaylist(
        folder_path=Path("HUMAN/HEARTH/ART/MUSIC/PLAYLISTS/PARTY"),
        leaf_name="PARTY",
        actions=["download", "spotify_sync"],
    )


def test_returns_none_when_no_brackets():
    assert parse_playlist_name("Favoritos") is None


def test_returns_none_when_brackets_empty():
    assert parse_playlist_name("NAME[]") is None


def test_returns_none_when_no_recognized_flags():
    assert parse_playlist_name("NAME[XYZ]") is None


def test_ignores_unrecognized_characters_alongside_recognized_ones():
    parsed = parse_playlist_name("NAME[!X]")

    assert parsed.actions == ["download"]


def test_hash_flag_expands_to_transcript_and_summarize():
    parsed = parse_playlist_name("NAME[#]")

    assert parsed.actions == ["transcript", "summarize"]


def test_actions_use_fixed_canonical_order_regardless_of_flag_order():
    parsed = parse_playlist_name("NAME[@!#]")

    assert parsed.actions == ["download", "transcript", "summarize", "spotify_sync"]


def test_single_segment_name_with_no_dashes():
    parsed = parse_playlist_name("SOLO[!]")

    assert parsed.folder_path == Path("SOLO")
    assert parsed.leaf_name == "SOLO"
    assert parsed.actions == ["download"]
