import contextlib
import logging
import os
import re
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from sync_master.db.models import (
    Playlist,
    Source,
    SpotifyPlaylist,
    SpotifySync,
    Summary,
    SyncState,
    Transcript,
    TranscriptSegment,
    Video,
    VideoFile,
)

_STATE_ROW_ID = 1

_ADVISORY_LOCK_KEY = "sync-master-run"

_logger = logging.getLogger(__name__)

# Postgres large objects carry their own ACLs, entirely separate from table
# grants - a role with SELECT on video_files still gets "permission denied for
# large object N". The web UI streams these blobs as a read-only role, so it
# needs an explicit grant on each one. Every save creates a *new* OID (the
# lo_manage trigger unlinks the superseded object), so this runs on every write.
_WEB_ROLE_ENV = "WEB_READONLY_ROLE"
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def _grant_large_object_read(session: Session, oid: int) -> None:
    role = os.environ.get(_WEB_ROLE_ENV, "").strip()
    if not role:
        return
    if not _IDENT_RE.fullmatch(role):
        _logger.warning("%s=%r is not a valid role name; skipping large object grant", _WEB_ROLE_ENV, role)
        return

    # Checked rather than caught: a failed GRANT would abort the surrounding
    # transaction and take the video_files row down with it. A missing web role
    # is a normal state (nobody has provisioned the UI yet), not an error.
    exists = session.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}).scalar()
    if not exists:
        _logger.warning("%s=%s does not exist; skipping large object grant", _WEB_ROLE_ENV, role)
        return

    # oid is an integer we just produced and role is validated above, so this
    # interpolation is safe - GRANT accepts neither as a bind parameter.
    session.execute(text(f'GRANT SELECT ON LARGE OBJECT {int(oid)} TO "{role}"'))


class LockHeldError(Exception):
    pass


@contextlib.contextmanager
def acquire_run_lock(session: Session):
    """Postgres session-level advisory lock, replacing the old state.json.lock file.

    Unlike the file lock, this releases automatically if the process dies
    (the lock is tied to the DB session), so it can't be left held by a crash.
    """
    acquired = session.execute(
        text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _ADVISORY_LOCK_KEY}
    ).scalar()
    if not acquired:
        raise LockHeldError("Another sync-master run is already in progress.")
    try:
        yield
    finally:
        session.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _ADVISORY_LOCK_KEY})


def upsert_source(session: Session, source_id: str, display_name: str) -> None:
    stmt = pg_insert(Source).values(id=source_id, display_name=display_name)
    stmt = stmt.on_conflict_do_update(index_elements=[Source.id], set_={"display_name": stmt.excluded.display_name})
    session.execute(stmt)
    session.commit()


def upsert_playlist(
    session: Session,
    source: str,
    external_id: str,
    title: str,
    description: str | None = None,
    thumbnail_url: str | None = None,
    item_count: int | None = None,
    published_at: str | None = None,
    folder_path: Path | str | None = None,
    leaf_name: str | None = None,
    actions: list[str] | None = None,
) -> int:
    """Upserts the full catalog row for a playlist - every playlist on the
    account, not just flagged/tracked ones (folder_path/leaf_name/actions
    are only ever non-NULL for those). Returns the surrogate playlist id,
    needed as the FK value for upsert_video below.
    """
    stmt = pg_insert(Playlist).values(
        source=source,
        external_id=external_id,
        title=title,
        description=description,
        thumbnail_url=thumbnail_url,
        item_count=item_count,
        published_at=published_at,
        folder_path=str(folder_path) if folder_path is not None else None,
        leaf_name=leaf_name,
        actions=actions,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Playlist.source, Playlist.external_id],
        set_={
            "title": stmt.excluded.title,
            "description": stmt.excluded.description,
            "thumbnail_url": stmt.excluded.thumbnail_url,
            "item_count": stmt.excluded.item_count,
            "published_at": stmt.excluded.published_at,
            "folder_path": stmt.excluded.folder_path,
            "leaf_name": stmt.excluded.leaf_name,
            "actions": stmt.excluded.actions,
            "last_seen_at": func.now(),
        },
    ).returning(Playlist.id)
    playlist_pk = session.execute(stmt).scalar_one()
    session.commit()
    return playlist_pk


def upsert_video(
    session: Session,
    source: str,
    external_id: str,
    title: str,
    playlist_id: int | None = None,
    description: str | None = None,
    thumbnail_url: str | None = None,
    published_at: str | None = None,
) -> int:
    """Upserts the full catalog row for a video - every video on the
    account, not just ones in flagged playlists. Also serves as the FK
    anchor for video_files/transcripts/summaries/spotify_syncs, so this
    always runs (via the discovery loop) before any action dispatch for a
    video. Returns the surrogate video id.
    """
    stmt = pg_insert(Video).values(
        source=source,
        external_id=external_id,
        playlist_id=playlist_id,
        title=title,
        description=description,
        thumbnail_url=thumbnail_url,
        published_at=published_at,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Video.source, Video.external_id],
        set_={
            "playlist_id": stmt.excluded.playlist_id,
            "title": stmt.excluded.title,
            "description": stmt.excluded.description,
            "thumbnail_url": stmt.excluded.thumbnail_url,
            "published_at": stmt.excluded.published_at,
            "last_seen_at": func.now(),
        },
    ).returning(Video.id)
    video_pk = session.execute(stmt).scalar_one()
    session.commit()
    return video_pk


def _resolve_video_pk(session: Session, external_id: str, source: str = "youtube") -> int:
    """Every artifact table (video_files/transcripts/summaries/spotify_syncs)
    FKs against videos.id, not the raw external ID - this resolves it.
    Callers always run after upsert_video has already created the row (the
    discovery loop upserts every video before any action dispatch), so a
    missing row here means a real ordering bug, not a normal case.
    """
    return session.execute(
        select(Video.id).where(Video.source == source, Video.external_id == external_id)
    ).scalar_one()


def load_state(session: Session) -> dict:
    """Reads the whole sync_state document - state.json's original shape,
    {"videos": {video_id: {playlist_id, title, published_at, actions: {...}}}},
    now backed by one JSONB column instead of a file. Same name/contract as
    the original state.py:load_state.
    """
    data = session.execute(select(SyncState.data).where(SyncState.id == _STATE_ROW_ID)).scalar_one_or_none()
    return data if data is not None else {"videos": {}}


def save_state(session: Session, data: dict) -> None:
    """Writes the whole sync_state document back. Same name/contract as the
    original state.py:save_state - callers load once, mutate the dict in
    memory, and save it back (see runner.py:perform_run)."""
    stmt = pg_insert(SyncState).values(id=_STATE_ROW_ID, data=data)
    stmt = stmt.on_conflict_do_update(index_elements=[SyncState.id], set_={"data": stmt.excluded.data})
    session.execute(stmt)
    session.commit()


def save_video_file(
    session: Session,
    youtube_video_id: str,
    filename: str,
    content_type: str | None,
    content: bytes,
) -> None:
    # Stored as a Postgres Large Object, not a bytea column - plain bytea hit a
    # real ~500MB-ish allocation ceiling on actual video files (see
    # alembic/versions/0002_*). Writing it needs the raw psycopg2 connection;
    # SQLAlchemy has no first-class large object API. The `lo_manage` trigger
    # on video_files (from the same migration) unlinks the old large object
    # automatically when content_oid changes below, so this can't leak.
    raw_connection = session.connection().connection.dbapi_connection
    large_object = raw_connection.lobject(mode="wb")
    large_object.write(content)
    large_object.close()

    video_pk = _resolve_video_pk(session, youtube_video_id)
    stmt = pg_insert(VideoFile).values(
        video_id=video_pk,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        content_oid=large_object.oid,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[VideoFile.video_id],
        set_={
            "filename": stmt.excluded.filename,
            "content_type": stmt.excluded.content_type,
            "size_bytes": stmt.excluded.size_bytes,
            "content_oid": stmt.excluded.content_oid,
        },
    )
    session.execute(stmt)
    _grant_large_object_read(session, large_object.oid)
    session.commit()


def get_video_file_content(session: Session, youtube_video_id: str) -> bytes | None:
    video_pk = _resolve_video_pk(session, youtube_video_id)
    content_oid = session.execute(
        select(VideoFile.content_oid).where(VideoFile.video_id == video_pk)
    ).scalar_one_or_none()
    if content_oid is None:
        return None

    raw_connection = session.connection().connection.dbapi_connection
    large_object = raw_connection.lobject(content_oid, mode="rb")
    try:
        return large_object.read()
    finally:
        large_object.close()


def write_video_file_to(session: Session, youtube_video_id: str, destination: Path) -> int | None:
    """Streams a stored video to disk in 1MB chunks and returns the byte count,
    or None when nothing is stored for it. Unlike get_video_file_content this
    never holds the whole object in memory - these files run to ~500MB.
    Written to a temp path and renamed, so a failure can't leave a truncated
    file that looks complete.
    """
    video_pk = _resolve_video_pk(session, youtube_video_id)
    content_oid = session.execute(
        select(VideoFile.content_oid).where(VideoFile.video_id == video_pk)
    ).scalar_one_or_none()
    if content_oid is None:
        return None

    raw_connection = session.connection().connection.dbapi_connection
    large_object = raw_connection.lobject(content_oid, mode="rb")
    partial = destination.with_name(destination.name + ".part")
    written = 0
    try:
        with partial.open("wb") as out:
            while True:
                chunk = large_object.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
    finally:
        large_object.close()
    partial.replace(destination)
    return written


def get_transcript_text(session: Session, youtube_video_id: str) -> str | None:
    video_pk = _resolve_video_pk(session, youtube_video_id)
    return session.execute(
        select(Transcript.text).where(Transcript.video_id == video_pk)
    ).scalar_one_or_none()


def save_transcript(
    session: Session,
    youtube_video_id: str,
    source: str,
    text_: str,
    segments: list,
) -> None:
    video_pk = _resolve_video_pk(session, youtube_video_id)
    stmt = pg_insert(Transcript).values(
        video_id=video_pk,
        source=source,
        text=text_,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Transcript.video_id],
        set_={"source": stmt.excluded.source, "text": stmt.excluded.text, "created_at": func.now()},
    ).returning(Transcript.id)
    transcript_id = session.execute(stmt).scalar_one()

    session.execute(delete(TranscriptSegment).where(TranscriptSegment.transcript_id == transcript_id))
    session.add_all(
        [
            TranscriptSegment(
                transcript_id=transcript_id,
                start_seconds=segment.start,
                end_seconds=segment.end,
                speaker=segment.speaker,
            )
            for segment in segments
        ]
    )
    session.commit()


def save_summary(
    session: Session,
    youtube_video_id: str,
    content: str,
    instructions: str,
    llm_provider: str,
    llm_model: str,
) -> None:
    video_pk = _resolve_video_pk(session, youtube_video_id)
    stmt = pg_insert(Summary).values(
        video_id=video_pk,
        content=content,
        instructions=instructions,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Summary.video_id],
        set_={
            "content": stmt.excluded.content,
            "instructions": stmt.excluded.instructions,
            "llm_provider": stmt.excluded.llm_provider,
            "llm_model": stmt.excluded.llm_model,
            "created_at": func.now(),
        },
    )
    session.execute(stmt)
    session.commit()


def save_spotify_sync(
    session: Session,
    youtube_video_id: str,
    spotify_track_id: str,
    spotify_track_uri: str,
    spotify_playlist_id: str,
    matched_via: str,
) -> None:
    video_pk = _resolve_video_pk(session, youtube_video_id)
    stmt = pg_insert(SpotifySync).values(
        video_id=video_pk,
        spotify_track_id=spotify_track_id,
        spotify_track_uri=spotify_track_uri,
        spotify_playlist_id=spotify_playlist_id,
        matched_via=matched_via,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SpotifySync.video_id],
        set_={
            "spotify_track_id": stmt.excluded.spotify_track_id,
            "spotify_track_uri": stmt.excluded.spotify_track_uri,
            "spotify_playlist_id": stmt.excluded.spotify_playlist_id,
            "matched_via": stmt.excluded.matched_via,
            "synced_at": func.now(),
        },
    )
    session.execute(stmt)
    session.commit()


def get_spotify_playlist_id(session: Session, name: str) -> str | None:
    """Cached Spotify playlist ID for a destination playlist name (see
    SpotifyPlaylist), so spotify_sync can skip find_or_create_playlist's
    Spotify API search once a name has been resolved once."""
    return session.execute(
        select(SpotifyPlaylist.spotify_playlist_id).where(SpotifyPlaylist.name == name)
    ).scalar_one_or_none()


def save_spotify_playlist_id(session: Session, name: str, spotify_playlist_id: str) -> None:
    stmt = pg_insert(SpotifyPlaylist).values(name=name, spotify_playlist_id=spotify_playlist_id)
    stmt = stmt.on_conflict_do_update(
        index_elements=[SpotifyPlaylist.name],
        set_={"spotify_playlist_id": stmt.excluded.spotify_playlist_id},
    )
    session.execute(stmt)
    session.commit()
