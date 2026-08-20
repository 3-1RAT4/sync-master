import contextlib
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from sync_master.db.models import (
    Playlist,
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


def upsert_playlist(
    session: Session,
    youtube_playlist_id: str,
    title: str,
    folder_path: Path | str,
    leaf_name: str,
    actions: list[str],
) -> None:
    stmt = pg_insert(Playlist).values(
        youtube_playlist_id=youtube_playlist_id,
        title=title,
        folder_path=str(folder_path),
        leaf_name=leaf_name,
        actions=actions,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Playlist.youtube_playlist_id],
        set_={
            "title": stmt.excluded.title,
            "folder_path": stmt.excluded.folder_path,
            "leaf_name": stmt.excluded.leaf_name,
            "actions": stmt.excluded.actions,
            "last_seen_at": func.now(),
        },
    )
    session.execute(stmt)
    session.commit()


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


def ensure_video_row(session: Session, youtube_video_id: str) -> None:
    """Upserts a bare row into the videos anchor table (see db/models.py:Video)
    so video_files/transcripts/summaries/spotify_syncs always have something
    to foreign-key against, regardless of which actions ultimately run for
    this video. Call once when a video is first discovered."""
    stmt = pg_insert(Video).values(youtube_video_id=youtube_video_id)
    stmt = stmt.on_conflict_do_nothing(index_elements=[Video.youtube_video_id])
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

    stmt = pg_insert(VideoFile).values(
        youtube_video_id=youtube_video_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        content_oid=large_object.oid,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[VideoFile.youtube_video_id],
        set_={
            "filename": stmt.excluded.filename,
            "content_type": stmt.excluded.content_type,
            "size_bytes": stmt.excluded.size_bytes,
            "content_oid": stmt.excluded.content_oid,
        },
    )
    session.execute(stmt)
    session.commit()


def get_video_file_content(session: Session, youtube_video_id: str) -> bytes | None:
    content_oid = session.execute(
        select(VideoFile.content_oid).where(VideoFile.youtube_video_id == youtube_video_id)
    ).scalar_one_or_none()
    if content_oid is None:
        return None

    raw_connection = session.connection().connection.dbapi_connection
    large_object = raw_connection.lobject(content_oid, mode="rb")
    try:
        return large_object.read()
    finally:
        large_object.close()


def get_transcript_text(session: Session, youtube_video_id: str) -> str | None:
    return session.execute(
        select(Transcript.text).where(Transcript.youtube_video_id == youtube_video_id)
    ).scalar_one_or_none()


def save_transcript(
    session: Session,
    youtube_video_id: str,
    source: str,
    text_: str,
    segments: list,
) -> None:
    stmt = pg_insert(Transcript).values(
        youtube_video_id=youtube_video_id,
        source=source,
        text=text_,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Transcript.youtube_video_id],
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
    stmt = pg_insert(Summary).values(
        youtube_video_id=youtube_video_id,
        content=content,
        instructions=instructions,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Summary.youtube_video_id],
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
    stmt = pg_insert(SpotifySync).values(
        youtube_video_id=youtube_video_id,
        spotify_track_id=spotify_track_id,
        spotify_track_uri=spotify_track_uri,
        spotify_playlist_id=spotify_playlist_id,
        matched_via=matched_via,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SpotifySync.youtube_video_id],
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
