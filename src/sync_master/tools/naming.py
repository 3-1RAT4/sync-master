def sanitize_filename(name: str) -> str:
    return name.replace(" ", "_")


def transcript_filename(title: str | None) -> str:
    if not title:
        return "transcript.md"
    return f"{sanitize_filename(title)}_TRANSCRIPT.md"
