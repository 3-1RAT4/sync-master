"""Initial schema: playlists, videos, actions, and the video artifacts that
replace the old state.json + output directory tree.

Revision ID: 0001
Revises:
Create Date: 2026-08-20
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_UPGRADE_SQL = """
CREATE TYPE action_name AS ENUM ('download', 'transcript', 'summarize', 'spotify_sync');
CREATE TYPE action_status AS ENUM ('done', 'no_match', 'failed');
-- 'unknown' is only ever written by the legacy_migration.py one-time importer, for
-- pre-Postgres transcripts whose source (captions vs. Whisper) was never recorded.
CREATE TYPE transcript_source AS ENUM ('captions', 'whisper', 'unknown');
CREATE TYPE spotify_match_source AS ENUM ('override', 'search');

CREATE TABLE playlists (
    youtube_playlist_id TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    folder_path   TEXT NOT NULL,
    leaf_name     TEXT NOT NULL,
    actions       action_name[] NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE videos (
    youtube_video_id    TEXT PRIMARY KEY,
    youtube_playlist_id TEXT NOT NULL REFERENCES playlists(youtube_playlist_id),
    title         TEXT NOT NULL,
    published_at  TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_videos_youtube_playlist_id ON videos(youtube_playlist_id);

CREATE TABLE video_actions (
    id               BIGSERIAL PRIMARY KEY,
    youtube_video_id TEXT NOT NULL REFERENCES videos(youtube_video_id) ON DELETE CASCADE,
    action_name      action_name NOT NULL,
    status           action_status NOT NULL,
    error            TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (youtube_video_id, action_name)
);
CREATE INDEX idx_video_actions_youtube_video_id ON video_actions(youtube_video_id);

CREATE TABLE video_files (
    id               BIGSERIAL PRIMARY KEY,
    youtube_video_id TEXT NOT NULL UNIQUE REFERENCES videos(youtube_video_id) ON DELETE CASCADE,
    filename         TEXT NOT NULL,
    content_type     TEXT,
    size_bytes       BIGINT NOT NULL,
    content          BYTEA NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transcripts (
    id               BIGSERIAL PRIMARY KEY,
    youtube_video_id TEXT NOT NULL UNIQUE REFERENCES videos(youtube_video_id) ON DELETE CASCADE,
    source           transcript_source NOT NULL,
    text             TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transcript_segments (
    id            BIGSERIAL PRIMARY KEY,
    transcript_id BIGINT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    start_seconds NUMERIC(10,3) NOT NULL,
    end_seconds   NUMERIC(10,3) NOT NULL,
    speaker       TEXT NOT NULL,
    text          TEXT,
    CHECK (end_seconds >= start_seconds)
);
CREATE INDEX idx_transcript_segments_transcript_id ON transcript_segments(transcript_id);

CREATE TABLE summaries (
    id               BIGSERIAL PRIMARY KEY,
    youtube_video_id TEXT NOT NULL UNIQUE REFERENCES videos(youtube_video_id) ON DELETE CASCADE,
    content          TEXT NOT NULL,
    instructions     TEXT NOT NULL,
    llm_provider     TEXT NOT NULL,
    llm_model        TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE spotify_syncs (
    id                   BIGSERIAL PRIMARY KEY,
    youtube_video_id     TEXT NOT NULL UNIQUE REFERENCES videos(youtube_video_id) ON DELETE CASCADE,
    spotify_track_id     TEXT NOT NULL,
    spotify_track_uri    TEXT NOT NULL,
    spotify_playlist_id  TEXT NOT NULL,
    matched_via          spotify_match_source NOT NULL,
    synced_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_DOWNGRADE_SQL = """
DROP TABLE IF EXISTS spotify_syncs;
DROP TABLE IF EXISTS summaries;
DROP TABLE IF EXISTS transcript_segments;
DROP TABLE IF EXISTS transcripts;
DROP TABLE IF EXISTS video_files;
DROP TABLE IF EXISTS video_actions;
DROP TABLE IF EXISTS videos;
DROP TABLE IF EXISTS playlists;
DROP TYPE IF EXISTS spotify_match_source;
DROP TYPE IF EXISTS transcript_source;
DROP TYPE IF EXISTS action_status;
DROP TYPE IF EXISTS action_name;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
