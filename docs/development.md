# Development

## Project layout

```
sync-master/
├── pyproject.toml
├── src/sync_master/
│   ├── cli.py                  # Typer app: run, bootstrap, youtube-login, spotify-login
│   ├── runner.py                # glues discovery + deterministic dispatch for one run
│   ├── config.py                # llm.yaml, settings.yaml, spotify_overrides.json
│   ├── playlist_naming.py       # parse_playlist_name: folder path + action flags from a title
│   ├── state.py                 # state.json load/save/atomic-write/lock
│   ├── bootstrap.py             # config scaffolding, credential/tool checks
│   ├── youtube_auth.py          # OAuth client builder + one-time login flow
│   ├── sources/youtube.py       # fetch_my_playlists, fetch_playlist_items, diff
│   ├── tools/                   # download, transcript, diarize, naming, summarize, spotify_*
│   └── agent/orchestrator.py    # make_action_tools + run_actions_for_video (deterministic dispatch)
└── tests/                       # pytest, mirrors the src/ layout
```

## Running tests

```bash
.venv/bin/pytest
```

Every module here is built test-first with dependencies injected (a fake
YouTube client, a fake yt-dlp downloader, a fake LLM, a fake Spotify client,
etc.), so the full suite runs in well under a second with no network access
and no API keys required.

## Dry-run mode

```bash
.venv/bin/sync-master run --dry-run
```

Runs the full pipeline — discover playlists, parse names, fetch, diff — but
every tool call is logged instead of executed: nothing is downloaded, the
LLM inside `summarize` is never called, no Spotify playlist is modified or
created, and `state.json` isn't updated with `done`/`failed` statuses for
dry-run calls. Since dispatch is deterministic (no decision-making LLM call
in this design), dry-run costs nothing and calls no external API at all —
it's pure local parsing and logging. This is the primary way to check that
your playlist naming produces the action list you expect (see
[Configuration](configuration.md#playlist-naming-scheme)) across a large,
messy real account before it touches anything for real.

## Adding a new tool/action

1. Write the tool as a small, dependency-injectable function under
   `src/sync_master/tools/`, following the existing modules — accept the
   real dependency (an API client, a downloader, an LLM) as an optional
   keyword argument defaulting to a real implementation built lazily inside
   the function, so tests can inject a fake without needing the real
   dependency installed.
2. Add a wrapped `SimpleTool` for it in
   `make_action_tools` (`src/sync_master/agent/orchestrator.py`), following
   the `_wrap_action` pattern so it gets dry-run logging and
   done/failed/no_match state tracking for free.
3. Pick an unused bracket character and map it to the new action's name in
   `_FLAG_ACTIONS` (`src/sync_master/playlist_naming.py`), and add it to
   `_CANONICAL_ORDER` at the point representing its real dependencies (e.g.
   after `transcript` if it needs a transcript to exist).
4. Write unit tests first for both the tool (see any file under
   `tests/tools/` for the pattern) and the naming change (see
   `tests/test_playlist_naming.py`) — confirm they fail, then implement.

## Adding a new source type (beyond YouTube)

`src/sync_master/sources/youtube.py` is the only source implementation
today, and `playlist_naming.py` is YouTube-shaped (it parses *playlist*
names). A new source needs its own discovery function (list of trackable
"containers" with a name to parse) and its own fetch/diff for the items
inside each — `youtube.py` is the reference to copy. `runner.py`'s
`perform_run` would need a small change to dispatch by source type instead
of assuming YouTube for all of them; that's not done yet since only YouTube
is in scope for v1.
