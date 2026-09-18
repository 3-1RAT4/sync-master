# Setup

## Prerequisites

- Python 3.11+
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) and `ffmpeg` available on your `PATH`
- A Google Cloud OAuth Client (Desktop app type) with the YouTube Data API v3
  enabled — needed to list and fetch *your own* playlists, including private
  ones, which a plain API key can't do. See [Google Cloud Console](https://console.cloud.google.com/) →
  APIs & Services → Credentials → Create OAuth client ID → Desktop app.
- A Spotify app (Client ID + Secret, from the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard))
  with a redirect URI registered — `http://127.0.0.1:8080/callback` unless you
  override it
- An API key for your chosen LLM provider (DeepSeek by default; any
  OpenAI-compatible or LangChain-supported provider works) — used only by
  the `summarize` action
- A Postgres database (16+ recommended) — a local dev instance is provided
  via `docker-compose.yml` (`docker compose up -d postgres`), or point at
  any existing server

## Install

```bash
cd sync-master
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Whisper (the transcript fallback used when a video has no YouTube captions)
pulls in `torch` and is a large install, so it's an optional extra:

```bash
.venv/bin/pip install -e ".[whisper]"
```

Skip it if every playlist you track has YouTube-provided captions.

Speaker diarization (labeling *who* said what) needs a second, separate
extra — and unlike Whisper, it's effectively **required** for any playlist
with `transcript` flagged, not optional: diarization now runs on every
transcript, not just the Whisper-fallback ones (see
[Actions](actions.md#speaker-diarization) for why):

```bash
.venv/bin/pip install -e ".[diarization]"
```

This one needs a bit more setup than a normal `pip install`: the pipeline is
gated on Hugging Face, and it pulls in further gated sub-models internally —
accepting only the top-level one isn't enough, you'll hit 403s on the others
the first time it actually runs. Create a Hugging Face account, generate a
**Read-Only** access token (https://hf.co/settings/tokens), and accept the
terms on each of these pages while logged in, in this order:

1. https://huggingface.co/pyannote/speaker-diarization-community-1 (the pipeline itself)
2. https://huggingface.co/pyannote/segmentation-3.0 (internal dependency)
3. https://huggingface.co/pyannote/speaker-diarization-3.1 (internal dependency)

Then add the token to `credentials.env`:

```bash
HUGGINGFACE_TOKEN=
```

If you skip this extra, every `transcript` action will fail (it always
attempts diarization) — only skip it if none of your flagged playlists use
`#`.

## Set up the database

```bash
docker compose up -d postgres    # or point DATABASE_URL at an existing server
.venv/bin/alembic upgrade head
```

The default `docker-compose.yml` creates a `mydb` database with user
`sync_master` / password `changeme` — matching the `DATABASE_URL` bootstrap
scaffolds into `credentials.env` below. Change both together if you use
different credentials.

## Bootstrap

```bash
.venv/bin/sync-master bootstrap
```

This scaffolds `~/.config/sync-master/` (creating `logs/`,
`spotify_overrides.json`, `credentials.env`, `llm.yaml`, and `settings.yaml`
templates — it never overwrites files that already exist), checks whether
`yt-dlp` and `ffmpeg` are on your `PATH`, checks that `DATABASE_URL` is
reachable, and reports which required credentials are still missing.

Fill in `~/.config/sync-master/credentials.env`:

```bash
YOUTUBE_OAUTH_CLIENT_ID=
YOUTUBE_OAUTH_CLIENT_SECRET=
YOUTUBE_OAUTH_REFRESH_TOKEN=
LLM_API_KEY=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8080/callback
# Optional: only needed for speaker diarization (the "diarization" extra)
HUGGINGFACE_TOKEN=
DATABASE_URL=postgresql+psycopg2://sync_master:changeme@localhost:5432/mydb
```

`YOUTUBE_OAUTH_CLIENT_ID`/`_SECRET` come from the Google Cloud OAuth Client
you created above. `YOUTUBE_OAUTH_REFRESH_TOKEN` isn't something you type in
by hand — once the client ID/secret are in place, run:

```bash
.venv/bin/sync-master youtube-login
```

This opens a browser for the one-time OAuth approval (scope: `youtube` -
read/write; needed because `youtube.readonly` can't rename playlists) and
writes the resulting refresh token into `credentials.env`. If you're
upgrading an install that authorized under the old `youtube.readonly` scope,
re-run this command to get a token with write access - the existing
refresh token doesn't gain the new scope on its own.

Similarly, once `SPOTIFY_CLIENT_ID`/`_SECRET` are filled in (and
`SPOTIFY_REDIRECT_URI` is registered in your Spotify app's dashboard exactly
as written in `credentials.env`), run:

```bash
.venv/bin/sync-master spotify-login
```

This opens a browser for the one-time Spotify OAuth approval (scopes:
`playlist-modify-public playlist-modify-private playlist-read-private
playlist-read-collaborative` — the `modify` scopes create playlists and add
tracks; the `read` scopes are what let `find_or_create_playlist` see a
private playlist it already created, so it doesn't create a duplicate every
run). Unlike the YouTube flow, the resulting token is **not** written into
`credentials.env` — `spotipy` caches it itself at
`~/.config/sync-master/.spotify_cache`, and `sync-master run` reads from
that cache automatically afterward.

## Set your scratch directory

Durable output lives in Postgres (see [Configuration](configuration.md#database-database_url));
`output_base_dir` is just scratch space for external tools. Edit
`~/.config/sync-master/settings.yaml`:

```yaml
output_base_dir: /home/you/sync-master-scratch
```

## Name your playlists

There's no local source file to add — instead, rename the playlists you
want tracked on YouTube itself, using the `[...]` flag suffix described in
[Configuration](configuration.md#playlist-naming-scheme). Playlists with no
recognized suffix are simply left alone.

## Try it before trusting it

```bash
.venv/bin/sync-master run --dry-run
```

Dry-run logs the tool calls that *would* run for each new/pending video
without executing them or touching your files — the fastest way to check
that your playlist naming produces the action list you expect, especially
across a large, messy real account, before it touches anything for real.
Once that looks right:

```bash
.venv/bin/sync-master run
```

## Schedule it

`bootstrap` prints the recommended crontab line (default: every 15 minutes).
Add it yourself with `crontab -e`:

```
*/15 * * * * /path/to/sync-master/.venv/bin/sync-master run
```

sync-master does not modify your crontab for you.

## Migrating an existing install

If you're upgrading a pre-Postgres install (one with an existing
`~/.config/sync-master/state.json` and a populated `output_base_dir`), run
this once after setting up the database and filling in `DATABASE_URL`:

```bash
.venv/bin/sync-master migrate-legacy
```

This reads the old `state.json` and output directory tree and inserts the
equivalent rows into Postgres (playlists, videos, action statuses, video
files, transcripts, summaries). It's safe to re-run. A few things can't be
recovered from the old format, since it never recorded them: which source
(`captions` or `whisper`) each transcript came from (stored as `unknown`),
per-speaker diarization segments (left empty), and the resolved Spotify
track/playlist for a `spotify_sync` action that already succeeded (only its
`done`/`no_match`/`failed` status carries over into `video_actions`, so it
won't be needlessly redone — the `spotify_syncs` table itself just stays
empty for those). All of this is captured correctly going forward. Once
you've confirmed the import looks right, the old `state.json` and
`output_base_dir` are no longer read by sync-master and can be deleted.

## Exporting to an Obsidian vault

```bash
sync-master export-vault --vault ~/Documents/"Obsidian Vault" --dry-run   # show the tree
sync-master export-vault --vault ~/Documents/"Obsidian Vault"             # write it
```

Lays the catalog out under `SYNC_MASTER/VIDEOS/YOUTUBE/` inside the vault:
one folder per playlist, following the playlist name's dash-segments
(`HUMAN-PODCASTS[!#]` → `HUMAN/PODCASTS/`), and inside it one folder per video
named `N.Title`, where `N` is the video's position in the playlist on YouTube.
Every video gets a note; the ones the pipeline has processed also get their
`.mp4`, `.transcript.md` and `.summary.md` beside it, all carrying the same
`N.Title` prefix so `[[links]]` stay unambiguous.

Structure comes from YouTube (so the token must be valid) and content from
Postgres. Re-running overwrites files in place and never deletes — a
reordered playlist changes `N` and leaves the old folder behind. Set
`vault_dir` in `settings.yaml` to skip `--vault`.

## Backup and restore

Everything durable lives in Postgres now, including video bytes (stored as
Postgres Large Objects). `scripts/backup_db.sh` and `scripts/restore_db.sh`
wrap `pg_dump`/`pg_restore`'s custom format (`-Fc`), which captures schema,
data, and Large Objects together — a plain-format dump would silently drop
the video bytes unless you remembered `-b` yourself.

Needs the Postgres client tools, which aren't a Python dependency:

```bash
sudo dnf install postgresql   # or your distro's equivalent
```

Take a backup:

```bash
scripts/backup_db.sh
```

Writes a timestamped `.dump` file to `~/.config/sync-master/backups/`
(outside the repo, so it can never end up committed) and updates a
`latest.dump` symlink to it. Override the source with `--database-url` or
the destination directory with `--output-dir`.

Restore one:

```bash
scripts/restore_db.sh                                    # restores latest.dump into DATABASE_URL
scripts/restore_db.sh --database-url ... some_backup.dump # restore a specific file elsewhere
```

Dumps keep the large-object grants the web UI relies on, so a restore into a
database where `sync_master_web` already exists needs no follow-up; if the
role doesn't exist yet, create it first (see [web-ui.md](web-ui.md)).

**This is destructive to its target** — existing objects are dropped and
replaced with the backup's contents. It asks for confirmation unless you
pass `--yes` (needed for non-interactive/cron use). Pass `--create-db` if
the target database doesn't exist yet (e.g. restoring onto a fresh server).

If `pg_dump`/`pg_restore` are a newer major version than the Postgres server
itself, you may see a warning about an unrecognized session parameter (e.g.
`transaction_timeout`) — `restore_db.sh` already detects and ignores this
specific known-harmless mismatch; the actual restore still completes
correctly. Matching the client's major version to the server's avoids the
warning entirely.

Avoid running either script while a `sync-master run` involving heavy
transcription/diarization is active — both scripts are safe to run
concurrently with normal usage, but a CPU-saturated `sync-master run` can
starve Postgres badly enough to make `pg_restore` (which writes Large
Objects) noticeably slow.
