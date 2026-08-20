from sync_master.tools.naming import sanitize_filename


def test_sanitize_filename_replaces_spaces_with_underscores():
    assert sanitize_filename("My Video Title") == "My_Video_Title"


def test_sanitize_filename_leaves_string_without_spaces_unchanged():
    assert sanitize_filename("NoSpacesHere") == "NoSpacesHere"
