import enum
from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, CheckConstraint, DateTime, ForeignKey, Numeric, SmallInteger, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, OID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Matches the Alembic migration's TIMESTAMPTZ/BIGSERIAL (tests create schema straight
# from these models via Base.metadata.create_all, so these have to stay identical to
# what the migration produces in production).
def _timestamptz(**kwargs):
    return mapped_column(DateTime(timezone=True), **kwargs)


def _bigint_pk():
    return mapped_column(BigInteger, primary_key=True)


def _pg_enum(python_enum, name: str):
    # Without values_callable, SQLAlchemy's Enum binds/reads a (str, enum.Enum)
    # member's .name (e.g. "DOWNLOAD") as the database value, not its .value
    # (e.g. "download"). The Alembic migration's native Postgres enum types use
    # the lowercase .value strings, so every enum column has to be told
    # explicitly to bind/read by .value instead - otherwise every read and
    # write of these columns fails against a real database (caught by
    # actually running sync-master migrate-legacy against real data).
    return SAEnum(python_enum, name=name, values_callable=lambda obj: [e.value for e in obj])


class ActionName(str, enum.Enum):
    DOWNLOAD = "download"
    TRANSCRIPT = "transcript"
    SUMMARIZE = "summarize"
    SPOTIFY_SYNC = "spotify_sync"


class TranscriptSource(str, enum.Enum):
    CAPTIONS = "captions"
    WHISPER = "whisper"
    UNKNOWN = "unknown"  # only ever written by legacy_migration.py for pre-Postgres transcripts,
    # whose source was never recorded and can't be recovered; the live pipeline always writes
    # CAPTIONS or WHISPER.


class SpotifyMatchSource(str, enum.Enum):
    OVERRIDE = "override"
    SEARCH = "search"


class Playlist(Base):
    __tablename__ = "playlists"

    youtube_playlist_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    folder_path: Mapped[str] = mapped_column(Text, nullable=False)
    leaf_name: Mapped[str] = mapped_column(Text, nullable=False)
    actions: Mapped[list[str]] = mapped_column(
        ARRAY(_pg_enum(ActionName, "action_name")), nullable=False
    )
    first_seen_at: Mapped[datetime] = _timestamptz(server_default=func.now())
    last_seen_at: Mapped[datetime] = _timestamptz(server_default=func.now())


class Video(Base):
    """Just an FK anchor now - playlist/title/published_at/actions all moved
    into sync_state.data (see SyncState below). This table exists purely so
    video_files/transcripts/summaries/spotify_syncs still have a real primary
    key to reference; nothing else reads or writes columns on it.
    """

    __tablename__ = "videos"

    youtube_video_id: Mapped[str] = mapped_column(Text, primary_key=True)

    file: Mapped["VideoFile | None"] = relationship(
        back_populates="video", cascade="all, delete-orphan", uselist=False
    )
    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="video", cascade="all, delete-orphan", uselist=False
    )
    summary: Mapped["Summary | None"] = relationship(
        back_populates="video", cascade="all, delete-orphan", uselist=False
    )
    spotify_sync: Mapped["SpotifySync | None"] = relationship(
        back_populates="video", cascade="all, delete-orphan", uselist=False
    )


class SyncState(Base):
    """Singleton row holding the entire state.json-shaped document:
    {"videos": {video_id: {playlist_id, title, published_at, actions: {...}}}}.
    Read once per run, mutated in memory, written back - see
    db/repository.py:load_state/save_state.
    """

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{"videos": {}}')


class VideoFile(Base):
    __tablename__ = "video_files"

    id: Mapped[int] = _bigint_pk()
    youtube_video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.youtube_video_id", ondelete="CASCADE"), unique=True
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    # A Postgres Large Object reference (see alembic/versions/0002_*), not the bytes
    # themselves - plain bytea hit a real ~1GB/500MB-ish allocation ceiling on actual
    # video files. Read/write it via repository.py's psycopg2 lobject calls, never
    # through this column directly.
    content_oid: Mapped[int] = mapped_column(OID, nullable=False)
    created_at: Mapped[datetime] = _timestamptz(server_default=func.now())

    video: Mapped["Video"] = relationship(back_populates="file")


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = _bigint_pk()
    youtube_video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.youtube_video_id", ondelete="CASCADE"), unique=True
    )
    source: Mapped[TranscriptSource] = mapped_column(_pg_enum(TranscriptSource, "transcript_source"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _timestamptz(server_default=func.now())

    video: Mapped["Video"] = relationship(back_populates="transcript")
    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan", order_by="TranscriptSegment.start_seconds"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (CheckConstraint("end_seconds >= start_seconds"),)

    id: Mapped[int] = _bigint_pk()
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"))
    start_seconds: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    end_seconds: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    speaker: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)

    transcript: Mapped["Transcript"] = relationship(back_populates="segments")


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = _bigint_pk()
    youtube_video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.youtube_video_id", ondelete="CASCADE"), unique=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    llm_provider: Mapped[str] = mapped_column(Text, nullable=False)
    llm_model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _timestamptz(server_default=func.now())

    video: Mapped["Video"] = relationship(back_populates="summary")


class SpotifySync(Base):
    __tablename__ = "spotify_syncs"

    id: Mapped[int] = _bigint_pk()
    youtube_video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.youtube_video_id", ondelete="CASCADE"), unique=True
    )
    spotify_track_id: Mapped[str] = mapped_column(Text, nullable=False)
    spotify_track_uri: Mapped[str] = mapped_column(Text, nullable=False)
    spotify_playlist_id: Mapped[str] = mapped_column(Text, nullable=False)
    matched_via: Mapped[SpotifyMatchSource] = mapped_column(_pg_enum(SpotifyMatchSource, "spotify_match_source"))
    synced_at: Mapped[datetime] = _timestamptz(server_default=func.now())

    video: Mapped["Video"] = relationship(back_populates="spotify_sync")
