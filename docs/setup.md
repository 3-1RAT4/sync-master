# Setup

## Prerequisites

- Python 3.11+
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) and `ffmpeg` available on your `PATH`
- A YouTube Data API v3 key ([Google Cloud Console](https://console.cloud.google.com/))
- A Spotify app (Client ID + Secret) with the redirect URI configured for OAuth
- An API key for your chosen LLM provider (DeepSeek by default; any
  OpenAI-compatible or LangChain-supported provider works)

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

Skip it if every source you track has YouTube-provided captions.

## Bootstrap

```bash
.venv/bin/sync-master bootstrap
```

This scaffolds `~/.config/sync-master/` (creating `sources/`, `logs/`,
`state.json`, `spotify_overrides.json`, `credentials.env`, and `llm.yaml`
templates — it never overwrites files that already exist), checks whether
`yt-dlp` and `ffmpeg` are on your `PATH`, and reports which required
credentials are still missing.

Fill in `~/.config/sync-master/credentials.env`:

```bash
YOUTUBE_API_KEY=
LLM_API_KEY=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REFRESH_TOKEN=
```

`SPOTIFY_REFRESH_TOKEN` isn't something you type in by hand — run:

```bash
.venv/bin/sync-master spotify-login
```

This opens a browser for the one-time Spotify OAuth approval (scopes:
`playlist-modify-public playlist-modify-private`, needed to add tracks to
*your* playlists — an app-level client ID/secret alone isn't sufficient for
that) and writes the resulting refresh token into `credentials.env`.

## Add a source

Create a markdown file under `~/.config/sync-master/sources/`, e.g.
`my-podcast.md` — see [Configuration](configuration.md) for the full format.

## Try it before trusting it

```bash
.venv/bin/sync-master run --dry-run
```

Dry-run logs the tool calls the agent *would* make for each new/pending
video without executing them or touching your files — the fastest way to
check that a source's policy text produces the behavior you expect. Once
that looks right:

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
