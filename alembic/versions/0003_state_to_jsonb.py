"""Collapse playlists+videos+video_actions' tracking data into a single JSONB
document, matching the original pre-Postgres state.json shape exactly:
{"videos": {video_id: {playlist_id, title, published_at, actions: {...}}}}.

video_files/transcripts/transcript_segments/summaries/spotify_syncs (the old
*output directory* replacement, not state.json) are untouched, including
their existing FK to videos.youtube_video_id - videos shrinks down to just
that one PK column, kept purely as an FK anchor. playlists is untouched too;
it was never part of state.json.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-20
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_UPGRADE_SQL = """
CREATE TABLE sync_state (
    id   SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    data JSONB NOT NULL DEFAULT '{"videos": {}}'::jsonb
);
INSERT INTO sync_state (id, data) VALUES (1, '{"videos": {}}'::jsonb);

-- Backfill from the currently-normalized tables (handles the general case,
-- not just an empty video_actions table).
UPDATE sync_state SET data = jsonb_build_object(
  'videos',
  (
    SELECT COALESCE(jsonb_object_agg(
      v.youtube_video_id,
      jsonb_build_object(
        'playlist_id', v.youtube_playlist_id,
        'title', v.title,
        'published_at', to_char(v.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        'actions', COALESCE(a.actions, '{}'::jsonb)
      )
    ), '{}'::jsonb)
    FROM videos v
    LEFT JOIN (
      SELECT youtube_video_id, jsonb_object_agg(
        action_name,
        jsonb_strip_nulls(jsonb_build_object(
          'status', status,
          'updated_at', to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
          'error', error
        ))
      ) AS actions
      FROM video_actions GROUP BY youtube_video_id
    ) a ON a.youtube_video_id = v.youtube_video_id
  )
) WHERE id = 1;

DROP TABLE video_actions;
ALTER TABLE videos DROP CONSTRAINT videos_youtube_playlist_id_fkey;
DROP INDEX IF EXISTS idx_videos_youtube_playlist_id;
ALTER TABLE videos DROP COLUMN youtube_playlist_id;
ALTER TABLE videos DROP COLUMN title;
ALTER TABLE videos DROP COLUMN published_at;
ALTER TABLE videos DROP COLUMN created_at;
ALTER TABLE videos DROP COLUMN updated_at;

DROP TYPE action_status;
"""

_DOWNGRADE_SQL = """
CREATE TYPE action_status AS ENUM ('done', 'no_match', 'failed');

ALTER TABLE videos ADD COLUMN youtube_playlist_id TEXT;
ALTER TABLE videos ADD COLUMN title TEXT;
ALTER TABLE videos ADD COLUMN published_at TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE videos ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

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

-- Restore videos.* and playlists rows from the JSONB document. This can only
-- restore playlist_id/title/published_at/actions - it cannot restore
-- playlists.folder_path/leaf_name (never present in state.json), so a
-- downgrade leaves those to be re-derived by the next `sync-master run`
-- (they're re-parsed from the live playlist title every run anyway).
UPDATE videos v SET
  youtube_playlist_id = s.entry ->> 'playlist_id',
  title = s.entry ->> 'title',
  published_at = (s.entry ->> 'published_at')::timestamptz
FROM (
  SELECT key AS youtube_video_id, value AS entry
  FROM sync_state, jsonb_each(data -> 'videos')
  WHERE id = 1
) s
WHERE v.youtube_video_id = s.youtube_video_id;

ALTER TABLE videos ALTER COLUMN youtube_playlist_id SET NOT NULL;
ALTER TABLE videos ALTER COLUMN title SET NOT NULL;
ALTER TABLE videos ALTER COLUMN published_at SET NOT NULL;
ALTER TABLE videos ADD CONSTRAINT videos_youtube_playlist_id_fkey
    FOREIGN KEY (youtube_playlist_id) REFERENCES playlists(youtube_playlist_id);
CREATE INDEX idx_videos_youtube_playlist_id ON videos(youtube_playlist_id);

INSERT INTO video_actions (youtube_video_id, action_name, status, error, updated_at)
SELECT
  s.youtube_video_id,
  action_key::action_name,
  (action_value ->> 'status')::action_status,
  action_value ->> 'error',
  COALESCE((action_value ->> 'updated_at')::timestamptz, now())
FROM (
  SELECT key AS youtube_video_id, value AS entry
  FROM sync_state, jsonb_each(data -> 'videos')
  WHERE id = 1
) s, jsonb_each(s.entry -> 'actions') AS actions(action_key, action_value);

DROP TABLE sync_state;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
