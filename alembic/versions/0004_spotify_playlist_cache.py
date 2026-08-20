"""Cache the resolved Spotify destination playlist ID per playlist name, so
spotify_sync stops calling find_or_create_playlist (a search-then-create
against the Spotify API) on every single video. Keyed by name, not by
YouTube playlist ID: playlist_naming.py's leaf_name is the Spotify playlist
name, and two different YouTube playlists can share the same leaf name
(they're meant to share one Spotify destination) - keying by YouTube
playlist ID would defeat that and let duplicates creep back in.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-20
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_UPGRADE_SQL = """
CREATE TABLE spotify_playlists (
    name                 TEXT PRIMARY KEY,
    spotify_playlist_id  TEXT NOT NULL UNIQUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_DOWNGRADE_SQL = """
DROP TABLE spotify_playlists;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
