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

BigInt (every `id` column) and `Date` (every `timestamptz` column) need `superjson` as the tRPC transformer to cross the wire at all — configured on both `web/backend/src/trpc.ts` and `web/frontend/src/main.tsx`; keep them in sync if either changes.

## Not built yet

- Express serving the built SPA (`web/frontend/dist`) for single-process/single-port day-to-day use.
- Annotations and Affine sync — explicit future passes, not designed yet.
- Auth — not needed for the current localhost-only access model; revisit before exposing this beyond your own machine.
