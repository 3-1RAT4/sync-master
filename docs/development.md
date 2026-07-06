# Development

## Project layout

```
sync-master/
├── pyproject.toml
├── src/sync_master/
│   ├── cli.py              # Typer app: run, bootstrap, spotify-login
│   ├── runner.py           # glues detection + orchestration for one run
│   ├── config.py           # sources/*.md, llm.yaml, spotify_overrides.json
│   ├── state.py            # state.json load/save/atomic-write/lock
│   ├── bootstrap.py        # config scaffolding, credential/tool checks
│   ├── sources/youtube.py  # YouTube Data API v3 fetch + diff
│   ├── tools/               # download, transcript, summarize, spotify_*
│   └── agent/orchestrator.py  # LangGraph agent + per-video tool wiring
└── tests/                  # pytest, mirrors the src/ layout
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

Runs the full pipeline — fetch, diff, build the agent, invoke it — but every
tool call is logged instead of executed: nothing is downloaded, no LLM
summarization tool actually runs*, no Spotify playlist is modified, and
`state.json` isn't updated with `done`/`failed` statuses for dry-run calls.
This is the primary way to iterate on a source's policy prose (see
[Configuration](configuration.md#source-policy-files-sourcesmd)) without
burning API calls or touching real files.

\* The orchestration agent itself still calls the real LLM to *decide* what
to do — only the four action tools it can invoke are short-circuited. Real
API cost for orchestration reasoning still applies in dry-run.

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
3. Write its unit tests first (see any file under `tests/tools/` for the
   pattern) — confirm they fail, then implement.

## Adding a new source type (beyond YouTube)

`src/sync_master/sources/youtube.py` is the only source implementation today.
A new source needs: a fetch function returning a list of items with a stable
ID, and a diff function excluding IDs already in `state.json` — `youtube.py`
is the reference to copy. `runner.py`'s `perform_run` would need a small
change to dispatch by source type instead of assuming YouTube for all of
them; that's not done yet since only YouTube is in scope for v1.
