"""Store video_files content as a Postgres Large Object instead of bytea.

Plain bytea hit a real ceiling on actual account data: Postgres's ~1GB
per-value allocation limit, combined with its buffer-doubling growth
strategy, made inserts fail ("invalid memory alloc request size
1073741824") for videos as small as ~500MB - well within normal YouTube
video sizes. Large Objects are Postgres's purpose-built mechanism for this
(streamed in chunks, no single-allocation ceiling, up to 4TB), and the `lo`
contrib extension's lo_manage() trigger keeps them from leaking orphaned
data when a video_files row is replaced or its video is deleted.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-20
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_UPGRADE_SQL = """
CREATE EXTENSION IF NOT EXISTS lo;

ALTER TABLE video_files DROP COLUMN content;
ALTER TABLE video_files ADD COLUMN content_oid OID NOT NULL;

CREATE TRIGGER video_files_content_oid_lo_manage
    BEFORE UPDATE OR DELETE ON video_files
    FOR EACH ROW EXECUTE FUNCTION lo_manage(content_oid);
"""

_DOWNGRADE_SQL = """
DROP TRIGGER IF EXISTS video_files_content_oid_lo_manage ON video_files;
ALTER TABLE video_files DROP COLUMN content_oid;
ALTER TABLE video_files ADD COLUMN content BYTEA NOT NULL DEFAULT ''::bytea;
ALTER TABLE video_files ALTER COLUMN content DROP DEFAULT;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
