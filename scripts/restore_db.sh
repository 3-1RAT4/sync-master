#!/usr/bin/env bash
# Restores a sync-master Postgres database from a pg_dump -Fc backup (see
# backup_db.sh). DESTRUCTIVE to the target database - existing objects are
# dropped and replaced with the backup's contents (--clean --if-exists).
#
# Usage: restore_db.sh [--database-url URL] [--create-db] [--yes] [backup_file]
#
# backup_file defaults to ~/.config/sync-master/backups/latest.dump.
# DATABASE_URL resolution order: --database-url flag > $DATABASE_URL env var
# > ~/.config/sync-master/credentials.env (parsed with grep/cut, never
# `source`d).
set -euo pipefail

CREDENTIALS_ENV="${SYNC_MASTER_CONFIG_DIR:-$HOME/.config/sync-master}/credentials.env"
DEFAULT_BACKUP="$HOME/.config/sync-master/backups/latest.dump"
DATABASE_URL="${DATABASE_URL:-}"
CREATE_DB=0
ASSUME_YES=0
BACKUP_FILE=""

usage() {
    echo "Usage: $0 [--database-url URL] [--create-db] [--yes] [backup_file]" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --database-url)
            DATABASE_URL="$2"
            shift 2
            ;;
        --create-db)
            CREATE_DB=1
            shift
            ;;
        --yes)
            ASSUME_YES=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        -*)
            echo "Unknown argument: $1" >&2
            usage
            ;;
        *)
            BACKUP_FILE="$1"
            shift
            ;;
    esac
done

BACKUP_FILE="${BACKUP_FILE:-$DEFAULT_BACKUP}"

if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

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

for tool in pg_restore psql; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "$tool not found on PATH. Install the Postgres client tools first" \
             "(e.g. \`sudo dnf install postgresql\` on Fedora)." >&2
        exit 1
    fi
done

PG_URI="${DATABASE_URL/postgresql+psycopg2:\/\//postgresql://}"
DB_NAME="${PG_URI##*/}"
DB_NAME="${DB_NAME%%\?*}"

if [[ "$CREATE_DB" -eq 1 ]]; then
    if ! command -v createdb >/dev/null 2>&1; then
        echo "createdb not found on PATH (part of the same postgresql client package)." >&2
        exit 1
    fi
    echo "Ensuring database '$DB_NAME' exists ..."
    createdb --owner="$(whoami)" "$DB_NAME" 2>/dev/null || true
fi

echo "About to restore into: $PG_URI"
echo "  from backup file:     $BACKUP_FILE"
echo "This DROPS and recreates every object currently in that database."

if [[ "$ASSUME_YES" -ne 1 ]]; then
    read -r -p "Type 'yes' to continue: " CONFIRM
    if [[ "$CONFIRM" != "yes" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

RESTORE_STDERR="$(mktemp)"
trap 'rm -f "$RESTORE_STDERR"' EXIT

set +e
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$PG_URI" "$BACKUP_FILE" 2>"$RESTORE_STDERR"
RESTORE_EXIT=$?
set -e

cat "$RESTORE_STDERR" >&2

if [[ "$RESTORE_EXIT" -ne 0 ]]; then
    # A newer pg_dump/pg_restore than the target server understands can emit a
    # SET for a session parameter the server doesn't have yet (e.g.
    # "transaction_timeout", added in Postgres 17) - pg_restore itself reports
    # this as an ignored error and keeps going, so the actual schema/data
    # restore still completes correctly; only the process exit code reflects
    # it. Anything else is treated as a real failure.
    if [[ "$(grep -c '^pg_restore: error:' "$RESTORE_STDERR")" -eq "$(grep -c 'unrecognized configuration parameter "transaction_timeout"' "$RESTORE_STDERR")" ]] \
        && [[ "$(grep -c '^pg_restore: error:' "$RESTORE_STDERR")" -gt 0 ]]; then
        echo "Note: ignored a harmless client/server version mismatch (server doesn't know" \
             "the 'transaction_timeout' setting a newer pg_dump/pg_restore emits) - the" \
             "actual restore completed. Consider matching pg_dump/pg_restore's major" \
             "version to the server's to avoid this warning entirely."
    else
        echo "pg_restore failed with unexpected errors (see above)." >&2
        exit "$RESTORE_EXIT"
    fi
fi

echo "Restore complete."
echo "If this backup predates migrations added since it was taken, run:"
echo "  alembic upgrade head"
