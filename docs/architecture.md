# Architecture

## Why it's built this way

sync-master's first design used an LLM agent to *decide* what to do with
each video, based on prose policy files you'd hand-write per playlist. That
didn't scale: a real YouTube account has far more playlists than anyone
wants to write a paragraph of policy for, and having an LLM decide "what to
do" per video adds cost, latency, and unpredictability for a decision that's
actually simple once you know which actions apply.

The current design moves that decision into the playlist names themselves,
on YouTube, where you already organize things. A playlist named
`HUMAN-MUSIC-PARTY[!@]` encodes both a folder path (`-` = `/`) and a set of
action flags (`[...]`) — no separate config file needed. sync-master
discovers *every* playlist on your account each run, parses the ones with a
recognized flag suffix, and ignores everything else. This is also what
solves the volume problem: most playlists have no flags, so they're never
touched.

Actions now run **deterministically** — parse the name once, get a fixed
action list, run exactly those tools in a fixed order. No LLM call decides
*what* to do. The LLM is still used, but only *inside* the `summarize`
action, to write the actual summary text.

## Flow

```
cron (e.g. */15 * * * *)
   └── sync-master run
         │  acquire a Postgres session-level advisory lock
         │  (skip the run entirely if another one is already in progress)
         │
         ├── DISCOVERY — src/sync_master/sources/youtube.py + playlist_naming.py
         │     fetch every playlist on the account (OAuth, includes private ones)
         │     for each playlist:
         │        parse_playlist_name(title) -> folder path, leaf name, actions
         │        no recognized [...] suffix -> skip entirely, untracked
         │        otherwise: upsert the playlist row, fetch its items, diff
         │        against known video_ids in Postgres, insert any new videos
         │
         ├── DISPATCH — src/sync_master/agent/orchestrator.py
         │     for each video that's new or has a failed action:
         │        run_actions_for_video(parsed.actions, ...)
         │        calls exactly those tools (download, transcript, summarize,
         │        spotify_sync), in canonical order, no decision step
         │        each tool call writes its result straight to Postgres
         │        (video bytes, transcript text+segments, summary, spotify
         │        sync row) and records its done/failed/no_match status
         │
         └── release the advisory lock
```

Playlist names are **re-parsed fresh every run** from the live title, not
frozen at first discovery — edit a playlist's flags on YouTube and the next
run picks it up.

Durable state lives entirely in Postgres now — see [State model](#state-model)
below. The only thing still written to the filesystem is scratch space
(`output_base_dir` in `settings.yaml`): temporary files that external tools
(yt-dlp, ffmpeg, Whisper, pyannote) need a real path to operate on, read back
into memory and persisted to the database, then safe to delete at any time.

## Naming scheme

See [Configuration](configuration.md#playlist-naming-scheme) for the full
rules. Quick reference:

| Flag | Action(s) |
|---|---|
| `!` | `download` |
| `@` | `spotify_sync` |
| `#` | `transcript` + `summarize` |

`HUMAN-HEARTH-ART-MUSIC-PLAYLISTS-PARTY[!@]` → folder path
`HUMAN/HEARTH/ART/MUSIC/PLAYLISTS/PARTY`, leaf name `PARTY` (also used as the
Spotify playlist name), actions `[download, spotify_sync]`.

## Components

| Component | File | Responsibility |
|---|---|---|
| DB models | `src/sync_master/db/models.py` | SQLAlchemy ORM models for every table (`playlists`, `videos`, `video_actions`, `video_files`, `transcripts`, `transcript_segments`, `summaries`, `spotify_syncs`) |
| DB engine | `src/sync_master/db/engine.py` | Builds the SQLAlchemy engine/session from `DATABASE_URL` (in `credentials.env`) |
| Repository | `src/sync_master/db/repository.py` | All reads/writes against Postgres — upserts, status queries, the `acquire_run_lock` advisory lock (replaces the old `state.json.lock` file) |
| Migrations | `alembic/versions/` | Schema migrations, applied with `alembic upgrade head` |
| Legacy migration | `src/sync_master/legacy_migration.py` | One-time importer for a pre-Postgres install's `state.json` + output directory (`sync-master migrate-legacy`) |
| YouTube source | `src/sync_master/sources/youtube.py` | `fetch_my_playlists` (OAuth, lists every playlist on the account) and `fetch_playlist_items` (fetches a playlist's videos), plus diffing against known video IDs |
| YouTube auth | `src/sync_master/youtube_auth.py` | Builds the OAuth-authenticated client from a stored refresh token; the one-time login flow used by `sync-master youtube-login` |
| Spotify auth | `src/sync_master/spotify_auth.py` | Builds the `SpotifyOAuth` manager from `SPOTIFY_CLIENT_ID`/`_SECRET`/`_REDIRECT_URI`, with a stable cache path (`~/.config/sync-master/.spotify_cache`) so the token survives across separate CLI invocations (important for cron) |
| Naming | `src/sync_master/playlist_naming.py` | `parse_playlist_name` — the folder-path + action-flag parser |
| Config | `src/sync_master/config.py` | Parse `llm.yaml`, `settings.yaml` (`output_base_dir`, now scratch space), `spotify_overrides.json` |
| Tools | `src/sync_master/tools/*.py` | `download` (yt-dlp), `transcript` (YouTube captions → Whisper fallback), `diarize` (pyannote speaker labeling), `naming` (title → filename), `summarize` (LangChain), `spotify_search`, `spotify_playlist` (including find-or-create) |
| Orchestrator | `src/sync_master/agent/orchestrator.py` | Wraps tools per video (dry-run logging, done/failed/no_match state tracking) and `run_actions_for_video`, the deterministic dispatcher |
| Runner | `src/sync_master/runner.py` | Glues discovery and dispatch together for one full run |
| Bootstrap | `src/sync_master/bootstrap.py` | Scaffolds `~/.config/sync-master/`, checks external tools and the database connection, reports missing credentials, prints the crontab line |
| CLI | `src/sync_master/cli.py` | `sync-master run`, `bootstrap`, `youtube-login`, `spotify-login`, `migrate-legacy` |

## State model

Every tracked video lives in Postgres, one `video_actions` row per action:

```sql
SELECT action_name, status, updated_at FROM video_actions WHERE youtube_video_id = 'abc123';
```

```
 action_name  | status | updated_at
--------------+--------+------------
 download     | done   | ...
 spotify_sync | no_match | ...
```

A video is reconsidered on the next run if it has **no row yet for a
currently-required action** (brand new, or a newly-added flag) or **any
action with `status: failed`** (auto-retry). Actions already `done` or
`no_match` are left alone. `no_match` is a distinct terminal status from
`failed` — it means the Spotify *track* search genuinely found nothing, not
that something errored, so it isn't retried automatically. See
[spotify_overrides.json](configuration.md#spotify_overridesjson) for how to
resolve a `no_match` by hand.

See [Configuration](configuration.md#database-databaseurl) for the full
schema and connection setup.
