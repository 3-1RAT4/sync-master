# Web UI

A read-only browser for the catalog sync-master builds (`web/`) — playlist folder tree, videos, transcripts, summaries, processing status. Fully separate TypeScript stack, not part of the `sync_master` Python package: sync-master's job is still only to hydrate the database (`sync-master run`, `migrate-legacy`) and run the pipeline. It never serves this UI.

```
web/
├── backend/    # Node.js + TypeScript + Express + tRPC + Prisma
└── frontend/   # React + TypeScript SPA (Vite, client-side routing only)
```

## Schema ownership

**Alembic (`alembic/versions/`, Python) is the only schema/migration authority for `mydb`.** The backend's `prisma/schema.prisma` is *introspected* from the live database (`npm run db:pull`, i.e. `prisma db pull && prisma generate`) — Prisma Migrate is never run against this database. If you change the schema, the order is always: write an Alembic migration → apply it → re-run `npm run db:pull` in `web/backend` to pick up the change. Never the other way around.

## Database access: a dedicated read-only role

The backend connects as `sync_master_web`, a Postgres role with `SELECT`-only access — created once, separately from sync-master's own (read-write) role:

```sql
CREATE ROLE sync_master_web LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE mydb TO sync_master_web;
GRANT USAGE ON SCHEMA public TO sync_master_web;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO sync_master_web;
-- so tables added by future Alembic migrations are readable automatically,
-- without a manual re-grant every time (assumes migrations run as `rodz`):
ALTER DEFAULT PRIVILEGES FOR ROLE rodz IN SCHEMA public GRANT SELECT ON TABLES TO sync_master_web;
```

This is defense in depth: a bug in the web stack can't corrupt data even by accident, since the role the backend authenticates as physically cannot write.

### Large objects need their own grant

Downloaded videos are stored as Postgres **large objects** (`video_files.content_oid`, see `alembic/versions/0002_video_files_large_objects.py`), and large objects carry ACLs of their own that table grants do not cover. Without an explicit grant the backend gets `permission denied for large object N` and the player 404s.

Set `WEB_READONLY_ROLE` in `~/.config/sync-master/credentials.env`, and `repository.save_video_file` grants read on each new object as it's written — every download creates a *new* OID (the `lo_manage` trigger unlinks the superseded one), so this has to happen on every write:

```
WEB_READONLY_ROLE=sync_master_web
```

Leave it unset and the grant is skipped silently; a role that doesn't exist is logged and skipped rather than failing the download.

One-time backfill for objects downloaded before this was in place:

```sql
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT content_oid FROM video_files LOOP
    EXECUTE format('GRANT SELECT ON LARGE OBJECT %s TO sync_master_web', r.content_oid);
  END LOOP;
END $$;
```

This grants **read only** — verify with `SELECT lo_put(<oid>, 0, '\x00');` as `sync_master_web`, which must still fail. Grants are not schema, so they live here rather than in an Alembic migration (the role doesn't exist in CI or the test database). `pg_dump` carries large-object ACLs, so they survive a restore provided the role exists *before* `pg_restore` runs.

## Running it locally

Two dev servers, two terminals:

```bash
cd web/backend && npm install && npm run dev    # http://127.0.0.1:4000
cd web/frontend && npm install && npm run dev    # http://localhost:5173
```

The frontend's Vite dev server proxies `/api/*` to the backend (`web/frontend/vite.config.ts`), so the SPA always calls a relative `/api/trpc/...` URL regardless of which port it's actually served from.

For day-to-day use (not active frontend development), build the SPA and let Express serve the static files itself — one process, one port, matching the localhost-only/no-auth access model:

```bash
cd web/frontend && npm run build   # writes web/frontend/dist
# (Express static-file serving of that dist/ directory is not wired up yet -
# see "Not built yet" below.)
```

`web/backend/.env` (gitignored, copy from `.env.example`) holds `DATABASE_URL` for the `sync_master_web` role and the port to listen on.

## API shape

tRPC, not REST — the frontend imports the backend's router type directly (`web/frontend/src/trpc.ts` does a type-only import of `web/backend/src/router.ts`) for full end-to-end type safety with no schema/codegen step. Procedures so far:

- `playlists.list` — every playlist (tracked and untracked; `folder_path`/`leaf_name`/`actions` are `null` for untracked ones).
- `playlists.videos` — videos in a playlist.
- `videos.get` — a video's catalog metadata, transcript, summary, Spotify sync record, and processing status (read from `sync_state.data`, the same JSONB document `src/sync_master/db/repository.py` uses — a separate concern from the catalog tables, only populated for videos in tracked playlists).

### Video streaming is not tRPC

`GET /api/videos/:externalId/stream` (`web/backend/src/videoStream.ts`) is a plain Express route, because tRPC is JSON-RPC and can't carry binary. It streams the stored large object in 1 MB chunks via `lo_get(oid, offset, length)` using node-postgres directly — Prisma has no large-object API.

It implements byte ranges (`206`, `Content-Range`, `416`, suffix ranges, `HEAD`), which is not optional: `<video>` seeking depends on them and Safari won't play without them. Two things to preserve if you touch this:

- **Never buffer a whole object.** These files run to ~500 MB.
- **Never `await once(res, "drain")`.** A cancelled range request — which browsers fire constantly while seeking — means `drain` never arrives, so the loop parks forever holding a pool client. Four of those and the route stops responding. `waitForDrain` resolves on `close`/`error` too.

The transcript reader is wired to the player: timestamps seek it, the timeline scrubs it, and the current turn is highlighted as it plays. Videos with no stored file render no player at all and keep their YouTube links.

BigInt (every `id` column) and `Date` (every `timestamptz` column) need `superjson` as the tRPC transformer to cross the wire at all — configured on both `web/backend/src/trpc.ts` and `web/frontend/src/main.tsx`; keep them in sync if either changes.

## Not built yet

- Express serving the built SPA (`web/frontend/dist`) for single-process/single-port day-to-day use.
- Annotations and Affine sync — explicit future passes, not designed yet.
- Auth — not needed for the current localhost-only access model; revisit before exposing this beyond your own machine.
