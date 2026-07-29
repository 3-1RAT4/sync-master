from sync_master.tools.naming import sanitize_filename, transcript_filename


def test_sanitize_filename_replaces_spaces_with_underscores():
    assert sanitize_filename("My Video Title") == "My_Video_Title"


def test_sanitize_filename_leaves_string_without_spaces_unchanged():
    assert sanitize_filename("NoSpacesHere") == "NoSpacesHere"


def test_transcript_filename_uses_sanitized_title_with_transcript_suffix():
    assert transcript_filename("My Video Title") == "My_Video_Title_TRANSCRIPT.md"


def test_transcript_filename_falls_back_to_generic_name_when_no_title():
    assert transcript_filename(None) == "transcript.md"
