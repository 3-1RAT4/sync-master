import enum
from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, CheckConstraint, DateTime, ForeignKey, Numeric, SmallInteger, Text, UniqueConstraint, func
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


class Source(Base):
    """A dimension table for where a playlist/video came from - just
    'youtube' today, but playlists/videos identify by (source, external_id)
    rather than a YouTube-specific column, so a second source is a new row
    here plus a new fetcher, not a schema rewrite."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)


class Playlist(Base):
    """The full catalog of every playlist on the account - not just
    flagged/tracked ones. folder_path/leaf_name/actions are only populated
    for playlists the naming scheme recognizes (parse_playlist_name); NULL
    for everything else, which is still cataloged for browsing/annotation."""

    __tablename__ = "playlists"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = _bigint_pk()
    source: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)  # YouTube's playlist ID today
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    item_count: Mapped[int | None] = mapped_column()
    published_at: Mapped[datetime | None] = _timestamptz()
    folder_path: Mapped[str | None] = mapped_column(Text)
    leaf_name: Mapped[str | None] = mapped_column(Text)
    actions: Mapped[list[str] | None] = mapped_column(ARRAY(_pg_enum(ActionName, "action_name")))
    first_seen_at: Mapped[datetime] = _timestamptz(server_default=func.now())
    last_seen_at: Mapped[datetime] = _timestamptz(server_default=func.now())

    videos: Mapped[list["Video"]] = relationship(back_populates="playlist")


class Video(Base):
    """The full catalog of every video on the account - not just videos in
    flagged playlists. Processing status (download/transcript/summarize/
    spotify_sync) is a separate concern tracked in sync_state, keyed by
    external_id directly; this table is the metadata catalog and the FK
    anchor for video_files/transcripts/summaries/spotify_syncs.
    """

    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = _bigint_pk()
    source: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)  # YouTube's video ID today
    playlist_id: Mapped[int | None] = mapped_column(ForeignKey("playlists.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = _timestamptz()
    first_seen_at: Mapped[datetime] = _timestamptz(server_default=func.now())
    last_seen_at: Mapped[datetime] = _timestamptz(server_default=func.now())

    playlist: Mapped["Playlist | None"] = relationship(back_populates="videos")
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
    db/repository.py:load_state/save_state. Intentionally decoupled from the
    Video/Playlist catalog above - this is the processing pipeline's status
    tracking, not catalog metadata, and still keyed by raw YouTube ID strings.
    """

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{"videos": {}}')


class VideoFile(Base):
    __tablename__ = "video_files"

    id: Mapped[int] = _bigint_pk()
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), unique=True)
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
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), unique=True)
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
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    llm_provider: Mapped[str] = mapped_column(Text, nullable=False)
    llm_model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _timestamptz(server_default=func.now())

    video: Mapped["Video"] = relationship(back_populates="summary")


class SpotifySync(Base):
    __tablename__ = "spotify_syncs"

    id: Mapped[int] = _bigint_pk()
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), unique=True)
    spotify_track_id: Mapped[str] = mapped_column(Text, nullable=False)
    spotify_track_uri: Mapped[str] = mapped_column(Text, nullable=False)
    spotify_playlist_id: Mapped[str] = mapped_column(Text, nullable=False)
    matched_via: Mapped[SpotifyMatchSource] = mapped_column(_pg_enum(SpotifyMatchSource, "spotify_match_source"))
    synced_at: Mapped[datetime] = _timestamptz(server_default=func.now())

    video: Mapped["Video"] = relationship(back_populates="spotify_sync")


class SpotifyPlaylist(Base):
    """Caches the resolved Spotify playlist ID per destination playlist name
    (playlist_naming.py's leaf_name), so spotify_sync doesn't need to search
    Spotify for it on every video - see repository.py:get_spotify_playlist_id
    /save_spotify_playlist_id.
    """

    __tablename__ = "spotify_playlists"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    spotify_playlist_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = _timestamptz(server_default=func.now())
