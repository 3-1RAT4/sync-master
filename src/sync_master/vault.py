"""The Obsidian vault as the store.

Everything sync-master produces lives under SYNC_MASTER/VIDEOS/YOUTUBE/ inside
the vault - one folder per playlist following the playlist name's dash
segments, and inside it one folder per video:

    <segments...>/<N>.<title>/
        <N>.<title>.md               the note (created once, see below)
        <N>.<title>.mp4              download action
        <N>.<title>.transcript.md    transcript action
        <N>.<title>.summary.md       summarize action

N is the video's 1-based position in the playlist. Every file carries the full
prefix so [[links]] and ![[embeds]] stay unambiguous across thousands of
folders.

The contract with whoever edits the vault:

* A note's body is never overwritten. It is created once; later runs only
  merge the frontmatter (keys the user added survive) and regenerate the one
  block between the sync-master markers. Annotations anywhere else are left
  alone.
* A video whose position or title changed on YouTube has its folder renamed
  into place - folder, prefixed files, and the links in the managed block.
  Folders are never deleted.
* Each run finds existing folders by reading every video note's frontmatter
  under the managed root (youtube_id + playlist_id). Anything moved out of
  that root is invisible to the sync and will be recreated in place.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from sync_master.playlist_naming import derive_folder_segments
from sync_master.sources.youtube import PlaylistInfo, VideoItem

VAULT_SUBDIR = Path("SYNC_MASTER") / "VIDEOS" / "YOUTUBE"

BLOCK_BEGIN = "<!-- sync-master:begin -->"
BLOCK_END = "<!-- sync-master:end -->"

# Filesystem-illegal on at least one OS, plus the characters Obsidian's
# [[link]] syntax can't carry in a note name.
_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|#^\[\]]')
_WHITESPACE = re.compile(r"\s+")
_MAX_NAME = 100

# The conversation format tools/diarize.py:format_as_conversation writes...
_TURN_RE = re.compile(r"^\[(\d{1,2}):(\d{2}):(\d{2})\]\s+([^:\n]+):\s*(.*)$", re.DOTALL)
# ...and the markdown line transcript_to_markdown turns it into.
_MD_TURN_RE = re.compile(r"^\*\*\[(\d{1,2}:\d{2}:\d{2})\] ([^*]+?):\*\* (.*)$", re.DOTALL)

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_BLOCK_RE = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.DOTALL)


# --------------------------------------------------------------------- names


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


def playlist_dir(root: Path, playlist_title: str) -> Path:
    return root.joinpath(*[sanitize_name(s) for s in derive_folder_segments(playlist_title)])


@dataclass(frozen=True)
class VideoFolder:
    """One video's place in the vault. `name` is the N.Title prefix every file shares."""

    folder: Path
    name: str

    @property
    def note(self) -> Path:
        return self.folder / f"{self.name}.md"

    @property
    def video(self) -> Path:
        return self.folder / f"{self.name}.mp4"

    @property
    def transcript(self) -> Path:
        return self.folder / f"{self.name}.transcript.md"

    @property
    def summary(self) -> Path:
        return self.folder / f"{self.name}.summary.md"

    def has_output(self, action: str) -> bool:
        """Whether an action's product is actually present. The vault wins
        over the ledger: a missing file means the action runs again."""
        if action == "download":
            return self.video.exists()
        if action == "transcript":
            return self.transcript.exists()
        if action == "summarize":
            return self.summary.exists()
        if action == "spotify_sync":
            return "spotify_track_uri" in read_frontmatter(self.note)
        return True


# ---------------------------------------------------------------- markdown


def _frontmatter(fields: dict) -> str:
    return "---\n" + yaml.safe_dump(fields, sort_keys=False, allow_unicode=True) + "---\n"


def split_note(text: str) -> tuple[dict, str]:
    """(frontmatter, body). A note without frontmatter is all body."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fields = yaml.safe_load(match.group(1)) or {}
    return (fields if isinstance(fields, dict) else {}), text[match.end() :]


def read_frontmatter(note: Path) -> dict:
    if not note.exists():
        return {}
    # Only the head is needed; a 100KB transcript note shouldn't be read whole
    # just to learn its type.
    with note.open(encoding="utf-8") as handle:
        head = handle.read(4096)
    return split_note(head)[0]


def _speaker_label(raw: str) -> str:
    match = re.fullmatch(r"SPEAKER_(\d+)", raw)
    if match:
        return f"Speaker {match.group(1)}"
    return "Unattributed" if raw in ("", "UNKNOWN") else raw


def _speaker_id(label: str) -> str:
    match = re.fullmatch(r"Speaker (\d+)", label)
    if match:
        return f"SPEAKER_{match.group(1)}"
    return "UNKNOWN" if label == "Unattributed" else label


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


def read_transcript_text(path: Path) -> str:
    """The inverse of transcript_to_markdown: the conversation text the
    summarize action consumes, recovered from the note in the vault."""
    _, body = split_note(path.read_text(encoding="utf-8"))
    turns = []
    for block in re.split(r"\n{2,}", body):
        block = block.strip()
        if not block or block.startswith("# Transcript"):
            continue
        match = _MD_TURN_RE.match(block)
        if match:
            stamp, label, words = match.groups()
            turns.append(f"[{stamp}] {_speaker_id(label)}: {words.strip()}")
        else:
            turns.append(block)
    return "\n\n".join(turns)


def summary_to_markdown(content: str, video_id: str, provider: str, model: str, title: str) -> str:
    head = _frontmatter(
        {"title": title, "youtube_id": video_id, "type": "summary", "llm_provider": provider, "llm_model": model}
    )
    return head + f"\n# Summary — {title}\n\n" + content.strip() + "\n"


def managed_block(vf: VideoFolder) -> str:
    """The part of a note sync-master keeps regenerating: the embed and the
    links, reflecting what's actually in the folder right now."""
    lines = [BLOCK_BEGIN]
    if vf.video.exists():
        lines.append(f"![[{vf.name}.mp4]]")
    links = []
    if vf.transcript.exists():
        links.append(f"[[{vf.name}.transcript|Transcript]]")
    if vf.summary.exists():
        links.append(f"[[{vf.name}.summary|Summary]]")
    if links:
        lines.append(" · ".join(links))
    lines.append(BLOCK_END)
    return "\n".join(lines) + "\n"


def video_fields(item: VideoItem, playlist: PlaylistInfo) -> dict:
    """The frontmatter keys sync-master owns on a video note."""
    return {
        "title": item.title,
        "youtube_id": item.video_id,
        "url": f"https://www.youtube.com/watch?v={item.video_id}",
        "playlist": playlist.title,
        "playlist_id": playlist.playlist_id,
        "position": (item.position or 0) + 1,
        "published": (item.published_at or "")[:10] or None,
        "type": "video",
    }


def new_note(item: VideoItem, playlist: PlaylistInfo, vf: VideoFolder) -> str:
    parts = [_frontmatter(video_fields(item, playlist)), f"\n# {item.title}\n"]
    if item.thumbnail_url:
        parts.append(f"\n![thumbnail]({item.thumbnail_url})\n")
    parts.append("\n" + managed_block(vf))
    parts.append(f"\n[Watch on YouTube](https://www.youtube.com/watch?v={item.video_id})\n")
    if item.description and item.description.strip():
        parts.append("\n## Description\n\n" + item.description.strip() + "\n")
    return "".join(parts)


def _strip_unmanaged_links(body: str, names: set[str]) -> str:
    """Notes written by the first export carried the embed and links as
    plain lines with no markers. Remove those - for any name this video has
    had - so moving them into the managed block doesn't duplicate them."""
    for name in names:
        body = re.sub(rf"^!\[\[{re.escape(name)}\.mp4\]\]\n?", "", body, flags=re.M)
        body = re.sub(rf"^\[\[{re.escape(name)}\.(transcript|summary)\|[^\]]*\]\](?: · \[\[[^\]]*\]\])*\n?", "", body, flags=re.M)
    return body


def refresh_note(vf: VideoFolder, item: VideoItem, playlist: PlaylistInfo, previous_names: set[str] = frozenset()) -> None:
    """Bring an existing note up to date without touching the user's text:
    merge the owned frontmatter keys and regenerate the managed block. The
    block is put back where it was; if the user removed it, it goes after
    the heading."""
    fields, body = split_note(vf.note.read_text(encoding="utf-8"))
    fields.update(video_fields(item, playlist))

    block = managed_block(vf)
    body = _strip_unmanaged_links(body, set(previous_names) | {vf.name})
    if _BLOCK_RE.search(body):
        body = _BLOCK_RE.sub(lambda _: block, body, count=1)
    else:
        lines = body.split("\n")
        at = 0
        for i, line in enumerate(lines):
            if line.startswith("# "):
                at = i + 1
                # keep the thumbnail with the heading, above the block
                while at < len(lines) and (not lines[at].strip() or lines[at].startswith("![thumbnail]")):
                    at += 1
                break
        lines[at:at] = ["", block.rstrip("\n"), ""]
        body = "\n".join(lines)
    body = re.sub(r"\n{3,}", "\n\n", body)

    vf.note.write_text(_frontmatter(fields) + body, encoding="utf-8")


def refresh_block(vf: VideoFolder) -> None:
    """Re-render only the managed block from what's in the folder now. Called
    by every writer, so the note's embed and links always match the files -
    the actions run after the note was refreshed for the run."""
    if not vf.note.exists():
        return
    fields, body = split_note(vf.note.read_text(encoding="utf-8"))
    block = managed_block(vf)
    if _BLOCK_RE.search(body):
        body = _BLOCK_RE.sub(lambda _: block, body, count=1)
    else:
        body = block + body
    vf.note.write_text(_frontmatter(fields) + body, encoding="utf-8")


def update_frontmatter(note: Path, **fields) -> None:
    current, body = split_note(note.read_text(encoding="utf-8"))
    current.update(fields)
    note.write_text(_frontmatter(current) + body, encoding="utf-8")


# ------------------------------------------------------------------ index


class VaultIndex:
    """Where each (playlist, video) currently lives under the managed root,
    read from the notes themselves so a reorganised or renamed vault is still
    recognised."""

    def __init__(self, root: Path, entries: dict[tuple[str, str], Path] | None = None):
        self.root = root
        self.entries: dict[tuple[str, str], Path] = entries or {}

    @classmethod
    def scan(cls, root: Path) -> VaultIndex:
        entries: dict[tuple[str, str], Path] = {}
        if root.is_dir():
            for note in root.rglob("*.md"):
                if note.name.endswith((".transcript.md", ".summary.md")):
                    continue
                fields = read_frontmatter(note)
                if fields.get("type") != "video":
                    continue
                key = (str(fields.get("playlist_id", "")), str(fields.get("youtube_id", "")))
                if all(key):
                    entries[key] = note.parent
        return cls(root, entries)

    def find(self, playlist_id: str, video_id: str) -> Path | None:
        return self.entries.get((playlist_id, video_id))

    def record(self, playlist_id: str, video_id: str, folder: Path) -> None:
        self.entries[(playlist_id, video_id)] = folder


def _note_stem(folder: Path) -> str:
    """The N.Title prefix a folder's files carry - read from the video note
    itself, because a parked folder's name no longer says."""
    for note in folder.glob("*.md"):
        if not note.name.endswith((".transcript.md", ".summary.md")):
            return note.stem
    return folder.name


def _evict_occupant(index: VaultIndex, target: Path, video_id: str) -> None:
    """If `target` is already a different video's folder, park that folder
    aside. Happens when two videos share a title - two "Deleted video"
    placeholders trading positions, say - and one's new place is the other's
    old one. The occupant is moved to its own new position when its turn
    comes; if it turns out to be stale (gone from the playlist) it stays
    parked under a name no real video can have, visible rather than lost."""
    if not target.is_dir():
        return
    occupant = read_frontmatter(target / f"{_note_stem(target)}.md")
    if occupant.get("youtube_id") in (None, video_id):
        return  # ours already, or an empty shell
    parked = target.with_name(f"{target.name}.moving-{occupant['youtube_id']}")
    target.rename(parked)
    index.record(str(occupant.get("playlist_id", "")), str(occupant["youtube_id"]), parked)


@dataclass(frozen=True)
class Placement:
    folder: VideoFolder
    created: bool
    moved_from: Path | None


def place_video(index: VaultIndex, playlist: PlaylistInfo, item: VideoItem) -> Placement:
    """Make sure the video's folder is where YouTube says it should be:
    create it, rename it into place, or just refresh the note."""
    name = entry_name(item.position or 0, item.title)
    target = playlist_dir(index.root, playlist.title) / name
    vf = VideoFolder(target, name)
    existing = index.find(playlist.playlist_id, item.video_id)

    if existing is None or not existing.is_dir():
        _evict_occupant(index, target, item.video_id)
        target.mkdir(parents=True, exist_ok=True)
        if not vf.note.exists():
            vf.note.write_text(new_note(item, playlist, vf), encoding="utf-8")
        else:
            refresh_note(vf, item, playlist)
        index.record(playlist.playlist_id, item.video_id, target)
        return Placement(vf, created=existing is None, moved_from=None)

    if existing.resolve() != target.resolve():
        # The prefix on the files is whatever the note is called, which is
        # not always the folder's name (see the eviction below).
        old_name = _note_stem(existing)
        target.parent.mkdir(parents=True, exist_ok=True)
        _evict_occupant(index, target, item.video_id)
        existing.rename(target)
        # The prefix is on every file, so they move with the folder's name.
        for path in target.iterdir():
            if path.name.startswith(old_name):
                path.rename(target / (name + path.name[len(old_name) :]))
        index.record(playlist.playlist_id, item.video_id, target)
        refresh_note(vf, item, playlist, previous_names={old_name})
        return Placement(vf, created=False, moved_from=existing)

    refresh_note(vf, item, playlist)
    return Placement(vf, created=False, moved_from=None)


# ----------------------------------------------------------------- outputs


def store_video(vf: VideoFolder, source: Path) -> int:
    """Copy a downloaded file into the folder. Copied, not moved: the scratch
    copy is what transcription reads next (yt-dlp skips re-downloading a
    file that's already there)."""
    partial = vf.video.with_name(vf.video.name + ".part")
    shutil.copyfile(source, partial)
    partial.replace(vf.video)
    refresh_block(vf)
    return vf.video.stat().st_size


def store_transcript(vf: VideoFolder, text: str, source: str, title: str) -> None:
    vf.transcript.write_text(transcript_to_markdown(text, _youtube_id(vf), source, title), encoding="utf-8")
    refresh_block(vf)


def store_summary(vf: VideoFolder, content: str, provider: str, model: str, title: str) -> None:
    vf.summary.write_text(summary_to_markdown(content, _youtube_id(vf), provider, model, title), encoding="utf-8")
    refresh_block(vf)


def record_spotify_sync(vf: VideoFolder, track_uri: str, playlist_id: str, matched_via: str) -> None:
    """The Spotify result goes in the note's frontmatter, where Obsidian can show it."""
    update_frontmatter(
        vf.note, spotify_track_uri=track_uri, spotify_playlist_id=playlist_id, spotify_matched_via=matched_via
    )


def _youtube_id(vf: VideoFolder) -> str:
    return str(read_frontmatter(vf.note).get("youtube_id", ""))
