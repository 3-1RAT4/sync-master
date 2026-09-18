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
- An [Obsidian](https://obsidian.md) vault — that's where everything
  sync-master produces ends up

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

## Bootstrap

```bash
.venv/bin/sync-master bootstrap
```

This scaffolds `~/.config/sync-master/` (creating `logs/`,
`spotify_overrides.json`, `credentials.env`, `llm.yaml`, and `settings.yaml`
templates — it never overwrites files that already exist), checks whether
`yt-dlp` and `ffmpeg` are on your `PATH`, checks that `vault_dir` points at
an Obsidian vault, and reports which required credentials are still missing.

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

## GPU

Transcription (Whisper) and speaker diarization (pyannote) run on the GPU
when torch can see one, and on the CPU otherwise — `sync-master bootstrap`
prints which. Two things decide whether it can:

- **The torch build must match the card.** `pip install torch` gives you the
  NVIDIA (CUDA) build; on an AMD card it runs everything on the CPU without
  a word of complaint. For AMD, install the ROCm build instead:
  ```bash
  .venv/bin/pip install --index-url https://download.pytorch.org/whl/rocm7.1 "torch==2.13.0+rocm7.1" "torchaudio==2.11.0+rocm7.1"
  ```
  (It needs `libatomic` from your distro.)
- **RX 6600/6700-class AMD cards (gfx103x)** aren't in ROCm's official list;
  they work with `HSA_OVERRIDE_GFX_VERSION=10.3.0` in `credentials.env` and
  **segfault on the first kernel without it** — torch will still claim the
  GPU is available, so don't trust that alone.

Measured on an RX 6700 XT: diarization 7x faster than the four-core CPU.

## Point it at your vault

Edit `~/.config/sync-master/settings.yaml`:

```yaml
vault_dir: /home/you/Documents/Obsidian Vault
output_base_dir: /home/you/sync-master-scratch
```

`vault_dir` is the root of your Obsidian vault; sync-master writes under
`SYNC_MASTER/VIDEOS/YOUTUBE/` inside it and never touches anything else.
`output_base_dir` is scratch space for yt-dlp and Whisper — safe to delete
whenever. See [Configuration](configuration.md#vault_dir-and-output_base_dir-settingsyaml).

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

## Backups

Everything durable is in the vault, as plain files — back it up the way you
back up the rest of the vault (Obsidian Sync, git, a copy of the folder).
`~/.config/sync-master/state.json` is the only other thing worth keeping: it
records which actions have already run, so a lost copy means the next run
re-does work (and, for `spotify_sync`, re-adds tracks) rather than losing any
content.
