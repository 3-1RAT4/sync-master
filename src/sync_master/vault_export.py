"""Lays the catalog out in an Obsidian vault.

Structure comes from YouTube (playlists, their videos, and the order they're
in) and content comes from Postgres (stored video, transcript, summary). Every
catalogued video becomes a folder holding a note; the ones the pipeline has
processed also get their mp4, transcript and summary as separate files.

    SYNC_MASTER/VIDEOS/YOUTUBE/<playlist segments...>/<N>.<title>/
        <N>.<title>.md               the note
        <N>.<title>.mp4              when a file is stored
        <N>.<title>.transcript.md    when a transcript is stored
        <N>.<title>.summary.md       when a summary is stored

N is the video's 1-based position in the playlist. Every file carries the full
prefix, not just the folder, so [[links]] and ![[embeds]] stay unambiguous
across a vault with thousands of these folders.

Re-running overwrites files in place and never deletes: a reordered playlist
changes N and leaves the old folder behind. Reconciling that is a sync
problem, deliberately out of scope here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from sync_master.db import repository
from sync_master.db.models import Playlist, Summary, Transcript, Video, VideoFile
from sync_master.playlist_naming import derive_folder_segments
from sync_master.sources.youtube import PlaylistInfo, VideoItem, fetch_my_playlists, fetch_playlist_items

VAULT_SUBDIR = Path("SYNC_MASTER") / "VIDEOS" / "YOUTUBE"

# Filesystem-illegal on at least one OS, plus the characters Obsidian's
# [[link]] syntax can't carry in a note name.
_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|#^\[\]]')
_WHITESPACE = re.compile(r"\s+")
_MAX_NAME = 100

# The conversation format tools/diarize.py:format_as_conversation writes.
_TURN_RE = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]\s+([^:\n]+):\s*(.*)$", re.DOTALL)


def sanitize_name(title: str, max_len: int = _MAX_NAME) -> str:
    """A title as a filename: unsafe characters become '-', whitespace is
    collapsed, and the result is capped so deep paths stay under OS limits.
    The real title lives in the note's frontmatter, so nothing is lost."""
    name = _UNSAFE_CHARS.sub("-", title)
    name = _WHITESPACE.sub(" ", name).strip()
    name = name.rstrip(". ")  # trailing dots are illegal on Windows, and look like extensions
    if len(name) > max_len:
        name = name[:max_len].rstrip(" -.")
    return name or "untitled"


def entry_name(position: int, title: str) -> str:
    """'1.Title' - the prefix that carries the playlist order."""
    return f"{position + 1}.{sanitize_name(title)}"


def _frontmatter(fields: dict) -> str:
    return "---\n" + yaml.safe_dump(fields, sort_keys=False, allow_unicode=True) + "---\n"


def _speaker_label(raw: str) -> str:
    match = re.fullmatch(r"SPEAKER_(\d+)", raw)
    if match:
        return f"Speaker {match.group(1)}"
    return "Unattributed" if raw in ("", "UNKNOWN") else raw


def transcript_to_markdown(text: str, video_id: str, source: str, title: str) -> str:
    """One paragraph per turn, timestamp and speaker in bold. A block that
    isn't in the [HH:MM:SS] SPEAKER: form (a transcript written before
    diarization existed) is kept as plain text rather than dropped."""
    turns = []
    for block in re.split(r"\n{2,}", text):
        block = block.strip()
        if not block:
            continue
        match = _TURN_RE.match(block)
        if match:
            hh, mm, ss, speaker, words = match.groups()
            turns.append(f"**[{hh}:{mm}:{ss}] {_speaker_label(speaker)}:** {words.strip()}")
        else:
            turns.append(block)

    head = _frontmatter({"title": title, "youtube_id": video_id, "type": "transcript", "source": source})
    return head + f"\n# Transcript — {title}\n\n" + "\n\n".join(turns) + "\n"


def summary_to_markdown(content: str, video_id: str, provider: str, model: str, title: str) -> str:
    head = _frontmatter(
        {"title": title, "youtube_id": video_id, "type": "summary", "llm_provider": provider, "llm_model": model}
    )
    return head + f"\n# Summary — {title}\n\n" + content.strip() + "\n"


def video_note(
    item: VideoItem,
    playlist: PlaylistInfo,
    name: str,
    *,
    has_video: bool,
    has_transcript: bool,
    has_summary: bool,
) -> str:
    head = _frontmatter(
        {
            "title": item.title,
            "youtube_id": item.video_id,
            "url": f"https://www.youtube.com/watch?v={item.video_id}",
            "playlist": playlist.title,
            "playlist_id": playlist.playlist_id,
            "position": (item.position or 0) + 1,
            "published": (item.published_at or "")[:10] or None,
            "type": "video",
        }
    )
    parts = [head, f"\n# {item.title}\n"]
    if item.thumbnail_url:
        parts.append(f"\n![thumbnail]({item.thumbnail_url})\n")
    if has_video:
        parts.append(f"\n![[{name}.mp4]]\n")
    links = []
    if has_transcript:
        links.append(f"[[{name}.transcript|Transcript]]")
    if has_summary:
        links.append(f"[[{name}.summary|Summary]]")
    if links:
        parts.append("\n" + " · ".join(links) + "\n")
    parts.append(f"\n[Watch on YouTube](https://www.youtube.com/watch?v={item.video_id})\n")
    if item.description and item.description.strip():
        parts.append("\n## Description\n\n" + item.description.strip() + "\n")
    return "".join(parts)


def catalog_playlists(session: Session) -> list[PlaylistInfo]:
    """The catalog's playlists, for exporting without touching YouTube."""
    return [
        PlaylistInfo(
            playlist_id=p.external_id,
            title=p.title,
            description=p.description or "",
            thumbnail_url=p.thumbnail_url,
            item_count=p.item_count,
        )
        for p in session.execute(select(Playlist).order_by(Playlist.title)).scalars()
    ]


def catalog_items(session: Session, playlist_external_id: str) -> list[VideoItem]:
    """A playlist's videos from the catalog. Order is insertion order (videos.id),
    which is the order YouTube returned them when first catalogued - the best
    stand-in for playlist position the database has, since position itself was
    never stored. A later reorder on YouTube isn't reflected here."""
    playlist = session.execute(select(Playlist).where(Playlist.external_id == playlist_external_id)).scalar_one()
    rows = session.execute(select(Video).where(Video.playlist_id == playlist.id).order_by(Video.id)).scalars()
    return [
        VideoItem(
            video_id=v.external_id,
            title=v.title,
            published_at=v.published_at.isoformat() if v.published_at else "",
            playlist_id=playlist_external_id,
            description=v.description or "",
            thumbnail_url=v.thumbnail_url,
            position=index,
        )
        for index, v in enumerate(rows)
    ]


@dataclass
class StoredContent:
    transcript: tuple[str, str] | None = None  # (source, text)
    summary: tuple[str, str, str] | None = None  # (content, provider, model)
    has_video: bool = False


def load_stored_content(session: Session) -> dict[str, StoredContent]:
    """Everything Postgres holds beyond the catalog, keyed by YouTube id -
    fetched once rather than per video, since there are thousands of videos
    and a handful of artifacts."""
    stored: dict[str, StoredContent] = {}

    for external_id, source, text in session.execute(
        select(Video.external_id, Transcript.source, Transcript.text).join(Transcript, Transcript.video_id == Video.id)
    ):
        # transcripts.source is a Postgres enum; the model gives it back as a
        # Python Enum, whose str() is "TranscriptSource.CAPTIONS", not "captions".
        stored.setdefault(external_id, StoredContent()).transcript = (getattr(source, "value", source), text)

    for external_id, content, provider, model in session.execute(
        select(Video.external_id, Summary.content, Summary.llm_provider, Summary.llm_model).join(
            Summary, Summary.video_id == Video.id
        )
    ):
        stored.setdefault(external_id, StoredContent()).summary = (content, provider, model)

    for (external_id,) in session.execute(select(Video.external_id).join(VideoFile, VideoFile.video_id == Video.id)):
        stored.setdefault(external_id, StoredContent()).has_video = True

    return stored


@dataclass
class ExportStats:
    playlists: int = 0
    notes: int = 0
    videos: int = 0
    video_bytes: int = 0
    transcripts: int = 0
    summaries: int = 0
    folders: list[str] = field(default_factory=list)


def export_vault(
    vault_dir: Path,
    session: Session,
    youtube_client,
    *,
    dry_run: bool = False,
    fetch_playlists_fn=fetch_my_playlists,
    fetch_items_fn=fetch_playlist_items,
    write_video_fn=repository.write_video_file_to,
    log=print,
) -> ExportStats:
    root = vault_dir / VAULT_SUBDIR
    stored = load_stored_content(session)
    stats = ExportStats()

    for playlist in fetch_playlists_fn(youtube_client):
        segments = derive_folder_segments(playlist.title)
        playlist_dir = root.joinpath(*[sanitize_name(s) for s in segments])
        items = fetch_items_fn(playlist.playlist_id, youtube_client=youtube_client)
        stats.playlists += 1
        stats.folders.append(str(playlist_dir.relative_to(vault_dir)))
        log(f"{playlist_dir.relative_to(vault_dir)}  ({len(items)} videos)")

        for index, item in enumerate(items):
            if item.position is None:
                item = replace(item, position=index)
            name = entry_name(item.position, item.title)
            folder = playlist_dir / name
            content = stored.get(item.video_id, StoredContent())

            stats.notes += 1
            if content.transcript:
                stats.transcripts += 1
            if content.summary:
                stats.summaries += 1
            if content.has_video:
                stats.videos += 1
            if dry_run:
                continue

            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{name}.md").write_text(
                video_note(
                    item,
                    playlist,
                    name,
                    has_video=content.has_video,
                    has_transcript=content.transcript is not None,
                    has_summary=content.summary is not None,
                ),
                encoding="utf-8",
            )
            if content.transcript:
                source, text = content.transcript
                (folder / f"{name}.transcript.md").write_text(
                    transcript_to_markdown(text, item.video_id, source, item.title), encoding="utf-8"
                )
            if content.summary:
                body, provider, model = content.summary
                (folder / f"{name}.summary.md").write_text(
                    summary_to_markdown(body, item.video_id, provider, model, item.title), encoding="utf-8"
                )
            if content.has_video:
                written = write_video_fn(session, item.video_id, folder / f"{name}.mp4")
                stats.video_bytes += written or 0

    return stats
