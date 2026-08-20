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

This opens a browser for the one-time OAuth approval (scope:
`youtube.readonly`) and writes the resulting refresh token into
`credentials.env`.

Similarly, once `SPOTIFY_CLIENT_ID`/`_SECRET` are filled in (and
`SPOTIFY_REDIRECT_URI` is registered in your Spotify app's dashboard exactly
as written in `credentials.env`), run:

```bash
.venv/bin/sync-master spotify-login
```

This opens a browser for the one-time Spotify OAuth approval (scopes:
`playlist-modify-public playlist-modify-private`, needed to add tracks to
*your* playlists — an app-level client ID/secret alone isn't sufficient for
that). Unlike the YouTube flow, the resulting token is **not** written into
`credentials.env` — `spotipy` caches it itself at
`~/.config/sync-master/.spotify_cache`, and `sync-master run` reads from
that cache automatically afterward.

## Set your scratch directory

Durable output lives in Postgres (see [Configuration](configuration.md#database-databaseurl));
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
