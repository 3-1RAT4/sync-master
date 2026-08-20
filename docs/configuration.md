# Configuration

Everything lives under `~/.config/sync-master/`, scaffolded by
`sync-master bootstrap` (see [Setup](setup.md)).

## Playlist naming scheme

There's no per-playlist config file — sync-master auto-discovers every
playlist on your YouTube account each run and reads its configuration
straight from the playlist's own name (`src/sync_master/playlist_naming.py`).
This is what lets it handle an account with dozens or hundreds of playlists:
most of them simply won't match the pattern below, so they're skipped
entirely.

**Format:** `<folder>-<folder>-...-<leaf-name>[<flags>]`

- `-` is a folder separator. `HUMAN-HEARTH-ART-MUSIC-PLAYLISTS-PARTY[!@]`
  becomes the folder path `HUMAN/HEARTH/ART/MUSIC/PLAYLISTS/PARTY`.
- The last segment (`PARTY` above) is the **leaf name** — also used as the
  Spotify playlist name for `spotify_sync` (see below).
- `[...]` at the very end holds action flags, one character each:

  | Flag | Action(s) |
  |---|---|
  | `!` | `download` — save the video via yt-dlp |
  | `@` | `spotify_sync` — find-or-create a matching Spotify playlist and add the track |
  | `#` | `transcript` + `summarize` together |

  Flags can be combined in any order (`[!@#]`, `[@!]`, etc.) — the actions
  always run in a fixed order regardless: `download`, `transcript`,
  `summarize`, `spotify_sync`.

- **No `[...]` suffix, or one with no recognized characters** (`Favoritos`,
  `NAME[]`, `NAME[xyz]`) → the playlist is **not tracked at all**. This is
  the whole mechanism for controlling volume: opt in per playlist by naming
  it, nothing else needed.
- Unrecognized characters inside otherwise-valid brackets are silently
  ignored (`NAME[!x]` → just `download`), so a typo doesn't crash a run.

Since actions are parsed fresh from the live title every run, editing a
playlist's flags on YouTube takes effect on the next `sync-master run` — no
local file to update.

## `output_base_dir` (`settings.yaml`)

Durable output (downloaded video, transcript, summary, Spotify sync record)
lives in Postgres now — see [Database](#database-databaseurl) below.
`output_base_dir` is just **scratch space**: a directory external tools
(yt-dlp, ffmpeg, Whisper, pyannote) can write temporary files into while an
action runs. Nothing under it is authoritative; it's safe to delete at any
time (sync-master will just re-download/re-process on the next run if
needed).

```yaml
output_base_dir: /home/you/sync-master-scratch
```

Each video's scratch files land at
`<output_base_dir>/<folder_path>/<video_id>/` — e.g. `HUMAN-MUSIC-PARTY[!@]`
uses `<output_base_dir>/HUMAN/MUSIC/PARTY/abc123/` for video `abc123` while
processing it.

## Database (`DATABASE_URL`)

sync-master stores everything durable — playlists, videos, per-action
status, the downloaded video bytes, transcript text and per-speaker
segments, summaries, and Spotify sync records — in a Postgres database
named `mydb` by convention (any name works, it's just what `DATABASE_URL`
points at).

Set the connection string in `credentials.env`:

```bash
DATABASE_URL=postgresql+psycopg2://sync_master:changeme@localhost:5432/mydb
```

A local dev instance is provided via `docker-compose.yml` at the repo root:

```bash
docker compose up -d postgres
```

Then apply the schema:

```bash
.venv/bin/alembic upgrade head
```

`sync-master bootstrap` checks that `DATABASE_URL` is reachable as part of
its normal checks. See [Architecture](architecture.md#state-model) for the
full table schema, and
[Development](development.md#database) for running tests against Postgres.

If you're moving an existing pre-Postgres install (one that still has a
`state.json` and populated `output_base_dir`) onto this version, run
`sync-master migrate-legacy` once to import it — see
[Setup](setup.md#migrating-an-existing-install).

## `llm.yaml`

Provider config used by the `summarize` action's LLM call:

```yaml
provider: deepseek
model: deepseek-chat
base_url: https://api.deepseek.com
```

`base_url` makes this work with any OpenAI-compatible endpoint. The API key
itself comes from `credentials.env` (`LLM_API_KEY`), not this file.

## `spotify_overrides.json`

`spotify_sync` resolves two different things, and this file only affects
one of them:

1. **Destination playlist** (which Spotify playlist to add to) — always
   resolved automatically by find-or-create on the leaf name. Not
   overridable here.
2. **Track match** (which Spotify track corresponds to *this video*) — this
   is what `spotify_overrides.json` controls. When the automatic search
   can't find a match, the action is marked `no_match` (see
   [Architecture](architecture.md#state-model)) and left alone on future
   runs — no repeated wasted searches. To fix a specific video by hand, add
   an entry here, keyed by YouTube video ID:

```json
{
  "<video_id>": "spotify:track:abc123",
  "<other_video_id>": "corrected search text"
}
```

- A value starting with `spotify:` is used directly as the URI to add —
  no search performed.
- Anything else is used as the search query instead of the video title.

This file is re-read every run, so adding an entry is what "retries" a
`no_match` video.

## `credentials.env`

Not committed, not templated with real values — see [Setup](setup.md) for
what goes in it, including the YouTube OAuth Client setup this design
requires (listing your own — including private — playlists needs OAuth, not
just an API key).
