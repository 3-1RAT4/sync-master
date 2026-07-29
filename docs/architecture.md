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
         │  acquire ~/.config/sync-master/state.json.lock
         │  (skip the run entirely if another one is already in progress)
         │
         ├── DISCOVERY — src/sync_master/sources/youtube.py + playlist_naming.py
         │     fetch every playlist on the account (OAuth, includes private ones)
         │     for each playlist:
         │        parse_playlist_name(title) -> folder path, leaf name, actions
         │        no recognized [...] suffix -> skip entirely, untracked
         │        otherwise: fetch its items, diff against state.json,
         │        add any new videos (each starts with an empty "actions" dict)
         │
         ├── DISPATCH — src/sync_master/agent/orchestrator.py
         │     for each video that's new or has a failed action:
         │        run_actions_for_video(parsed.actions, ...)
         │        calls exactly those tools (download, transcript, summarize,
         │        spotify_sync), in canonical order, no decision step
         │        each tool call updates the video's action state directly
         │
         └── write state.json back atomically, release the lock
```

Playlist names are **re-parsed fresh every run** from the live title, not
frozen at first discovery — edit a playlist's flags on YouTube and the next
run picks it up.

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
| State | `src/sync_master/state.py` | Load/save `state.json` (atomic write via temp file + rename), lock file to prevent overlapping runs |
| YouTube source | `src/sync_master/sources/youtube.py` | `fetch_my_playlists` (OAuth, lists every playlist on the account) and `fetch_playlist_items` (fetches a playlist's videos), plus diffing against known state |
| YouTube auth | `src/sync_master/youtube_auth.py` | Builds the OAuth-authenticated client from a stored refresh token; the one-time login flow used by `sync-master youtube-login` |
| Naming | `src/sync_master/playlist_naming.py` | `parse_playlist_name` — the folder-path + action-flag parser |
| Config | `src/sync_master/config.py` | Parse `llm.yaml`, `settings.yaml` (`output_base_dir`), `spotify_overrides.json` |
| Tools | `src/sync_master/tools/*.py` | `download` (yt-dlp), `transcript` (YouTube captions → Whisper fallback), `diarize` (pyannote speaker labeling), `naming` (title → filename), `summarize` (LangChain), `spotify_search`, `spotify_playlist` (including find-or-create) |
| Orchestrator | `src/sync_master/agent/orchestrator.py` | Wraps tools per video (dry-run logging, done/failed/no_match state tracking) and `run_actions_for_video`, the deterministic dispatcher |
| Runner | `src/sync_master/runner.py` | Glues discovery and dispatch together for one full run |
| Bootstrap | `src/sync_master/bootstrap.py` | Scaffolds `~/.config/sync-master/`, checks external tools, reports missing credentials, prints the crontab line |
| CLI | `src/sync_master/cli.py` | `sync-master run`, `bootstrap`, `youtube-login`, `spotify-login` |

## State model

Every tracked video lives in `state.json` with a `status` per action:

```json
{
  "videos": {
    "<video_id>": {
      "playlist_id": "...",
      "title": "...",
      "published_at": "...",
      "actions": {
        "download": {"status": "done", "updated_at": "..."},
        "spotify_sync": {"status": "no_match", "updated_at": "..."}
      }
    }
  }
}
```

A video is reconsidered on the next run if it has **no actions recorded yet**
(brand new) or **any action with `status: failed`** (auto-retry). Actions
already `done` or `no_match` are left alone. `no_match` is a distinct
terminal status from `failed` — it means the Spotify *track* search
genuinely found nothing, not that something errored, so it isn't retried
automatically. See
[spotify_overrides.json](configuration.md#spotify_overridesjson) for how to
resolve a `no_match` by hand.
