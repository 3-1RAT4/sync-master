# Architecture

## Why it's split this way

Two layers do very different jobs, so they're built very differently:

- **Detecting new videos** is a simple, reliable list comparison. There's no
  judgment call involved, so it's plain deterministic Python — no LLM, no
  cost, no risk of hallucinating a "new" video that isn't actually new.
- **Deciding what to do with a new video** genuinely benefits from judgment:
  different playlists want different things (download vs. transcript-only,
  3-paragraph summary vs. bullet points, sync to Spotify or not), and that's
  expressed as plain-language policy per source rather than a rigid
  config schema. An LLM agent reads that policy and decides which tools to
  call, in what order.

## Flow

```
cron (e.g. */15 * * * *)
   └── sync-master run
         │  acquire ~/.config/sync-master/state.json.lock
         │  (skip the run entirely if another one is already in progress)
         │
         ├── DETERMINISTIC LAYER — src/sync_master/runner.py + sources/youtube.py
         │     for each source in ~/.config/sync-master/sources/*.md:
         │        fetch current playlist items (YouTube Data API v3)
         │        diff against state.json → add any new videos
         │           (each starts with an empty "actions" dict)
         │
         ├── AI ORCHESTRATION LAYER — src/sync_master/agent/orchestrator.py
         │     for each video that's new or has a failed action:
         │        build a prompt from: the video's source policy text,
         │        the video's metadata, and its current action state
         │        run a LangGraph tool-calling agent against that prompt
         │        the agent decides which tools to call (download,
         │        transcript, summarize, spotify_sync) and in what order
         │        each tool call updates the video's action state directly
         │
         └── write state.json back atomically, release the lock
```

The agent is *guided*, not unconstrained: it only ever acts on one video at a
time, it only has the four tools listed above, and every tool call is
recorded. That keeps behavior debuggable even though the exact sequence of
calls per video isn't hardcoded — see `sync-master run --dry-run` in
[Development](development.md) for how to inspect what it would do before it
does it.

## Components

| Component | File | Responsibility |
|---|---|---|
| State | `src/sync_master/state.py` | Load/save `state.json` (atomic write via temp file + rename), lock file to prevent overlapping runs |
| YouTube source | `src/sync_master/sources/youtube.py` | Paginated fetch of playlist items via YouTube Data API v3, diff against known state |
| Config | `src/sync_master/config.py` | Parse `sources/*.md` (frontmatter + policy prose), `llm.yaml`, `spotify_overrides.json` |
| Tools | `src/sync_master/tools/*.py` | `download` (yt-dlp), `transcript` (YouTube captions → Whisper fallback), `summarize` (LangChain), `spotify_search`, `spotify_playlist` |
| Orchestrator | `src/sync_master/agent/orchestrator.py` | Wraps tools per video (with dry-run / state-tracking behavior), builds the prompt, runs the LangGraph agent |
| Runner | `src/sync_master/runner.py` | Glues the deterministic and AI layers together for one full run |
| Bootstrap | `src/sync_master/bootstrap.py` | Scaffolds `~/.config/sync-master/`, checks external tools, reports missing credentials, prints the crontab line |
| CLI | `src/sync_master/cli.py` | `sync-master run`, `bootstrap`, `spotify-login` |

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
        "transcript": {"status": "done", "updated_at": "..."},
        "summarize": {"status": "pending"},
        "spotify_sync": {"status": "no_match", "updated_at": "..."}
      }
    }
  }
}
```

A video is reconsidered on the next run if it has **no actions recorded yet**
(brand new) or **any action with `status: failed`** (auto-retry). Actions
already `done` or `no_match` are left alone. `no_match` is a distinct
terminal status from `failed` — it means the Spotify search genuinely found
nothing, not that something errored, so it isn't retried automatically. See
[spotify_overrides.json](configuration.md#spotify_overridesjson) for how to
resolve a `no_match` by hand.
