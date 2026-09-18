# Development

## Project layout

```
sync-master/
├── pyproject.toml
├── src/sync_master/
│   ├── cli.py                  # Typer app: run, bootstrap, youtube-login, spotify-login
│   ├── runner.py                # glues catalog + deterministic dispatch for one run
│   ├── vault.py                 # the store: names, folder index, place/rename/refresh, writers
│   ├── state.py                 # state.json (the action ledger) + the file lock
│   ├── config.py                # llm.yaml, settings.yaml, spotify_overrides.json
│   ├── playlist_naming.py       # derive_folder_segments + parse_playlist_name
│   ├── bootstrap.py             # config scaffolding, credential/tool/vault checks
│   ├── youtube_auth.py          # YouTube OAuth client builder + one-time login flow
│   ├── spotify_auth.py          # Spotify OAuth manager builder (stable cache path)
│   ├── sources/youtube.py       # fetch_my_playlists, fetch_playlist_items (with positions)
│   ├── tools/                   # download, transcript, diarize, naming, summarize, spotify_*
│   └── agent/orchestrator.py    # make_action_tools + run_actions_for_video (deterministic dispatch)
└── tests/                       # pytest, mirrors the src/ layout
```

## Running tests

```bash
.venv/bin/pytest
```

Every module is built test-first with dependencies injected (a fake YouTube
client, a fake yt-dlp downloader, a fake LLM, a fake Spotify client, and a
`tmp_path` standing in for the vault), so the full suite runs in well under
a second with no network access, no API keys, and no services of any kind.
The one test that needs `ffmpeg` on `PATH` (it decodes real audio) skips
itself when it isn't.

`tests/test_vault.py` is where the behaviour that matters most for your
notes lives: that a reorder renames a folder rather than duplicating it,
that a refresh never touches the body of a note, that a note moved outside
the managed root is left alone.

## Dry-run mode

```bash
.venv/bin/sync-master run --dry-run
```

Fetches every playlist and video from YouTube and reports what a real run
would do — how many folders it would create or move, and which actions it
would run for which videos — but **writes nothing**: no notes, no state,
no downloads, no LLM call, no Spotify change. This is the way to check that
your playlist naming produces the action list you expect (see
[Configuration](configuration.md#playlist-naming-scheme)), and, after
reorganising the vault, to check the sync still recognises everything
(`created 0 folders` is what you want to see).

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
