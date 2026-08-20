#!/usr/bin/env bash
# Full backup of the sync-master Postgres database via `pg_dump -Fc` (custom
# format - captures schema, data, and Large Objects like video_files' content
# automatically, unlike a plain-format dump).
#
# Usage: backup_db.sh [--database-url URL] [--output-dir DIR]
#
# DATABASE_URL resolution order: --database-url flag > $DATABASE_URL env var
# > ~/.config/sync-master/credentials.env (parsed with grep/cut, never
# `source`d - that file can contain shell-special characters that break
# `source`).
set -euo pipefail

CREDENTIALS_ENV="${SYNC_MASTER_CONFIG_DIR:-$HOME/.config/sync-master}/credentials.env"
OUTPUT_DIR="$HOME/.config/sync-master/backups"
DATABASE_URL="${DATABASE_URL:-}"

usage() {
    echo "Usage: $0 [--database-url URL] [--output-dir DIR]" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --database-url)
            DATABASE_URL="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage
            ;;
    esac
done

if [[ -z "$DATABASE_URL" ]]; then
    if [[ ! -f "$CREDENTIALS_ENV" ]]; then
        echo "No --database-url given and $CREDENTIALS_ENV not found." >&2
        exit 1
    fi
    DATABASE_URL="$(grep '^DATABASE_URL=' "$CREDENTIALS_ENV" | head -n1 | cut -d= -f2-)"
fi

if [[ -z "$DATABASE_URL" ]]; then
    echo "DATABASE_URL is empty (checked flag, env var, and $CREDENTIALS_ENV)." >&2
    exit 1
fi

for tool in pg_dump pg_restore; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "$tool not found on PATH. Install the Postgres client tools first" \
             "(e.g. \`sudo dnf install postgresql\` on Fedora)." >&2
        exit 1
    fi
done

# pg_dump/pg_restore speak libpq URIs, not SQLAlchemy's driver-qualified
# "postgresql+psycopg2://" scheme - strip the "+psycopg2" part.
PG_URI="${DATABASE_URL/postgresql+psycopg2:\/\//postgresql://}"

# Database name for the filename: the last path segment, query string stripped.
DB_NAME="${PG_URI##*/}"
DB_NAME="${DB_NAME%%\?*}"
DB_NAME="${DB_NAME:-db}"

mkdir -p "$OUTPUT_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="$OUTPUT_DIR/${DB_NAME}_${TIMESTAMP}.dump"

echo "Backing up $DB_NAME to $OUT_FILE ..."
pg_dump -Fc --no-owner --no-privileges --file="$OUT_FILE" "$PG_URI"

if [[ ! -s "$OUT_FILE" ]]; then
    echo "pg_dump produced an empty or missing file - treating as failure." >&2
    rm -f "$OUT_FILE"
    exit 1
fi

ln -sf "$(basename "$OUT_FILE")" "$OUTPUT_DIR/latest.dump"

SIZE="$(du -h "$OUT_FILE" | cut -f1)"
OBJECT_COUNT="$(pg_restore --list "$OUT_FILE" | grep -c '^[0-9]')"

echo "Backup complete: $OUT_FILE ($SIZE, $OBJECT_COUNT objects)"
echo "latest.dump -> $(basename "$OUT_FILE")"
