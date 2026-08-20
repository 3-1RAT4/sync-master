"""Full YouTube catalog sync with a source-agnostic schema.

Every playlist and every video on the account now gets cataloged (not just
flagged/tracked ones), and playlists/videos gain a `(source, external_id)`
identity instead of YouTube-specific text primary keys - a `sources` table
makes room for a second source later without another schema rewrite.

playlists/videos both move from a natural TEXT primary key to a surrogate
BIGSERIAL `id`, with `(source, external_id)` as a UNIQUE constraint instead.
video_files/transcripts/summaries/spotify_syncs are repointed from
youtube_video_id (TEXT) to video_id (BIGINT REFERENCES videos.id).

sync_state (the processing-status JSONB document) is untouched - it's the
existing pipeline's concern, still keyed by raw YouTube ID strings, and is
also this migration's data source for backfilling videos.title/published_at/
playlist_id (the old `videos` table dropped those columns in 0003; sync_state
still has them for every video the pipeline has ever seen).

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-20
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_UPGRADE_SQL = """
-- 1. sources
CREATE TABLE sources (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);
INSERT INTO sources (id, display_name) VALUES ('youtube', 'YouTube');

-- 2. playlists: add surrogate id + catalog metadata, nothing FKs to it yet
ALTER TABLE playlists ADD COLUMN id BIGSERIAL;
ALTER TABLE playlists ADD COLUMN source TEXT NOT NULL DEFAULT 'youtube' REFERENCES sources(id);
ALTER TABLE playlists ADD COLUMN description TEXT;
ALTER TABLE playlists ADD COLUMN thumbnail_url TEXT;
ALTER TABLE playlists ADD COLUMN item_count INTEGER;
ALTER TABLE playlists ADD COLUMN published_at TIMESTAMPTZ;
ALTER TABLE playlists ALTER COLUMN folder_path DROP NOT NULL;
ALTER TABLE playlists ALTER COLUMN leaf_name DROP NOT NULL;
ALTER TABLE playlists ALTER COLUMN actions DROP NOT NULL;
ALTER TABLE playlists DROP CONSTRAINT playlists_pkey;
ALTER TABLE playlists ADD PRIMARY KEY (id);
ALTER TABLE playlists RENAME COLUMN youtube_playlist_id TO external_id;
ALTER TABLE playlists ADD CONSTRAINT playlists_source_external_id_key UNIQUE (source, external_id);

-- 3. videos: add surrogate id, source, playlist_id FK, + catalog metadata
ALTER TABLE videos ADD COLUMN id BIGSERIAL;
ALTER TABLE videos ADD COLUMN source TEXT NOT NULL DEFAULT 'youtube' REFERENCES sources(id);
ALTER TABLE videos ADD COLUMN playlist_id BIGINT REFERENCES playlists(id);
ALTER TABLE videos ADD COLUMN title TEXT;
ALTER TABLE videos ADD COLUMN description TEXT;
ALTER TABLE videos ADD COLUMN thumbnail_url TEXT;
ALTER TABLE videos ADD COLUMN published_at TIMESTAMPTZ;
ALTER TABLE videos ADD COLUMN first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE videos ADD COLUMN last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Backfill title/published_at/playlist_id from sync_state.data, the only
-- place that still had them after migration 0003.
UPDATE videos v SET
  title = COALESCE(s.entry ->> 'title', v.youtube_video_id),
  published_at = NULLIF(s.entry ->> 'published_at', '')::timestamptz,
  playlist_id = p.id
FROM (
  SELECT key AS youtube_video_id, value AS entry
  FROM sync_state, jsonb_each(data -> 'videos')
  WHERE id = 1
) s
LEFT JOIN playlists p ON p.source = 'youtube' AND p.external_id = (s.entry ->> 'playlist_id')
WHERE v.youtube_video_id = s.youtube_video_id;

UPDATE videos SET title = youtube_video_id WHERE title IS NULL;
ALTER TABLE videos ALTER COLUMN title SET NOT NULL;

-- The pre-existing video_files/transcripts/summaries/spotify_syncs FKs still
-- point at videos(youtube_video_id) - drop them so that column's PRIMARY KEY
-- can move to id before step 4 creates the new id-based FKs.
ALTER TABLE video_files DROP CONSTRAINT video_files_youtube_video_id_fkey;
ALTER TABLE transcripts DROP CONSTRAINT transcripts_youtube_video_id_fkey;
ALTER TABLE summaries DROP CONSTRAINT summaries_youtube_video_id_fkey;
ALTER TABLE spotify_syncs DROP CONSTRAINT spotify_syncs_youtube_video_id_fkey;

ALTER TABLE videos DROP CONSTRAINT videos_pkey;
ALTER TABLE videos ADD PRIMARY KEY (id);

-- 4. repoint video_files/transcripts/summaries/spotify_syncs at videos.id
--    (done before renaming videos.youtube_video_id, while it still exists
--    to join against)
ALTER TABLE video_files ADD COLUMN video_id BIGINT;
UPDATE video_files vf SET video_id = v.id FROM videos v WHERE v.youtube_video_id = vf.youtube_video_id;
ALTER TABLE video_files ALTER COLUMN video_id SET NOT NULL;
ALTER TABLE video_files ADD CONSTRAINT video_files_video_id_fkey FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE;
ALTER TABLE video_files ADD CONSTRAINT video_files_video_id_key UNIQUE (video_id);
ALTER TABLE video_files DROP COLUMN youtube_video_id;

ALTER TABLE transcripts ADD COLUMN video_id BIGINT;
UPDATE transcripts t SET video_id = v.id FROM videos v WHERE v.youtube_video_id = t.youtube_video_id;
ALTER TABLE transcripts ALTER COLUMN video_id SET NOT NULL;
ALTER TABLE transcripts ADD CONSTRAINT transcripts_video_id_fkey FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE;
ALTER TABLE transcripts ADD CONSTRAINT transcripts_video_id_key UNIQUE (video_id);
ALTER TABLE transcripts DROP COLUMN youtube_video_id;

ALTER TABLE summaries ADD COLUMN video_id BIGINT;
UPDATE summaries s2 SET video_id = v.id FROM videos v WHERE v.youtube_video_id = s2.youtube_video_id;
ALTER TABLE summaries ALTER COLUMN video_id SET NOT NULL;
ALTER TABLE summaries ADD CONSTRAINT summaries_video_id_fkey FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE;
ALTER TABLE summaries ADD CONSTRAINT summaries_video_id_key UNIQUE (video_id);
ALTER TABLE summaries DROP COLUMN youtube_video_id;

ALTER TABLE spotify_syncs ADD COLUMN video_id BIGINT;
UPDATE spotify_syncs sp SET video_id = v.id FROM videos v WHERE v.youtube_video_id = sp.youtube_video_id;
ALTER TABLE spotify_syncs ALTER COLUMN video_id SET NOT NULL;
ALTER TABLE spotify_syncs ADD CONSTRAINT spotify_syncs_video_id_fkey FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE;
ALTER TABLE spotify_syncs ADD CONSTRAINT spotify_syncs_video_id_key UNIQUE (video_id);
ALTER TABLE spotify_syncs DROP COLUMN youtube_video_id;

-- 5. finish videos' restructure now that nothing references youtube_video_id
ALTER TABLE videos RENAME COLUMN youtube_video_id TO external_id;
ALTER TABLE videos ADD CONSTRAINT videos_source_external_id_key UNIQUE (source, external_id);
"""

_DOWNGRADE_SQL = """
-- reverse of step 5
ALTER TABLE videos RENAME COLUMN external_id TO youtube_video_id;
ALTER TABLE videos DROP CONSTRAINT videos_source_external_id_key;

-- reverse of step 4: drop the id-based FKs/columns first (mirrors the
-- upgrade, where step 4 ran after the PK swap below)
ALTER TABLE video_files ADD COLUMN youtube_video_id TEXT;
UPDATE video_files vf SET youtube_video_id = v.youtube_video_id FROM videos v WHERE v.id = vf.video_id;
ALTER TABLE video_files ALTER COLUMN youtube_video_id SET NOT NULL;
ALTER TABLE video_files DROP CONSTRAINT video_files_video_id_fkey;
ALTER TABLE video_files DROP CONSTRAINT video_files_video_id_key;
ALTER TABLE video_files DROP COLUMN video_id;

ALTER TABLE transcripts ADD COLUMN youtube_video_id TEXT;
UPDATE transcripts t SET youtube_video_id = v.youtube_video_id FROM videos v WHERE v.id = t.video_id;
ALTER TABLE transcripts ALTER COLUMN youtube_video_id SET NOT NULL;
ALTER TABLE transcripts DROP CONSTRAINT transcripts_video_id_fkey;
ALTER TABLE transcripts DROP CONSTRAINT transcripts_video_id_key;
ALTER TABLE transcripts DROP COLUMN video_id;

ALTER TABLE summaries ADD COLUMN youtube_video_id TEXT;
UPDATE summaries s2 SET youtube_video_id = v.youtube_video_id FROM videos v WHERE v.id = s2.video_id;
ALTER TABLE summaries ALTER COLUMN youtube_video_id SET NOT NULL;
ALTER TABLE summaries DROP CONSTRAINT summaries_video_id_fkey;
ALTER TABLE summaries DROP CONSTRAINT summaries_video_id_key;
ALTER TABLE summaries DROP COLUMN video_id;

ALTER TABLE spotify_syncs ADD COLUMN youtube_video_id TEXT;
UPDATE spotify_syncs sp SET youtube_video_id = v.youtube_video_id FROM videos v WHERE v.id = sp.video_id;
ALTER TABLE spotify_syncs ALTER COLUMN youtube_video_id SET NOT NULL;
ALTER TABLE spotify_syncs DROP CONSTRAINT spotify_syncs_video_id_fkey;
ALTER TABLE spotify_syncs DROP CONSTRAINT spotify_syncs_video_id_key;
ALTER TABLE spotify_syncs DROP COLUMN video_id;

-- reverse of the step-3 PK swap: now safe since the id-based FKs are gone
ALTER TABLE videos DROP CONSTRAINT videos_pkey;
ALTER TABLE videos ADD PRIMARY KEY (youtube_video_id);

-- recreate the pre-existing FKs/uniques on youtube_video_id
ALTER TABLE video_files ADD CONSTRAINT video_files_youtube_video_id_fkey FOREIGN KEY (youtube_video_id) REFERENCES videos(youtube_video_id) ON DELETE CASCADE;
ALTER TABLE video_files ADD CONSTRAINT video_files_youtube_video_id_key UNIQUE (youtube_video_id);
ALTER TABLE transcripts ADD CONSTRAINT transcripts_youtube_video_id_fkey FOREIGN KEY (youtube_video_id) REFERENCES videos(youtube_video_id) ON DELETE CASCADE;
ALTER TABLE transcripts ADD CONSTRAINT transcripts_youtube_video_id_key UNIQUE (youtube_video_id);
ALTER TABLE summaries ADD CONSTRAINT summaries_youtube_video_id_fkey FOREIGN KEY (youtube_video_id) REFERENCES videos(youtube_video_id) ON DELETE CASCADE;
ALTER TABLE summaries ADD CONSTRAINT summaries_youtube_video_id_key UNIQUE (youtube_video_id);
ALTER TABLE spotify_syncs ADD CONSTRAINT spotify_syncs_youtube_video_id_fkey FOREIGN KEY (youtube_video_id) REFERENCES videos(youtube_video_id) ON DELETE CASCADE;
ALTER TABLE spotify_syncs ADD CONSTRAINT spotify_syncs_youtube_video_id_key UNIQUE (youtube_video_id);

-- reverse of step 3 (column additions)
ALTER TABLE videos DROP COLUMN id;
ALTER TABLE videos DROP COLUMN source;
ALTER TABLE videos DROP COLUMN playlist_id;
ALTER TABLE videos DROP COLUMN title;
ALTER TABLE videos DROP COLUMN description;
ALTER TABLE videos DROP COLUMN thumbnail_url;
ALTER TABLE videos DROP COLUMN published_at;
ALTER TABLE videos DROP COLUMN first_seen_at;
ALTER TABLE videos DROP COLUMN last_seen_at;

-- reverse of step 2
ALTER TABLE playlists DROP CONSTRAINT playlists_source_external_id_key;
ALTER TABLE playlists RENAME COLUMN external_id TO youtube_playlist_id;
ALTER TABLE playlists DROP CONSTRAINT playlists_pkey;
ALTER TABLE playlists ADD PRIMARY KEY (youtube_playlist_id);
ALTER TABLE playlists DROP COLUMN id;
ALTER TABLE playlists DROP COLUMN source;
ALTER TABLE playlists DROP COLUMN description;
ALTER TABLE playlists DROP COLUMN thumbnail_url;
ALTER TABLE playlists DROP COLUMN item_count;
ALTER TABLE playlists DROP COLUMN published_at;
ALTER TABLE playlists ALTER COLUMN folder_path SET NOT NULL;
ALTER TABLE playlists ALTER COLUMN leaf_name SET NOT NULL;
ALTER TABLE playlists ALTER COLUMN actions SET NOT NULL;

-- reverse of step 1
DROP TABLE sources;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
