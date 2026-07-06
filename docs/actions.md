# Actions

These are the four tools the orchestration agent can call for a video
(`src/sync_master/agent/orchestrator.py::make_action_tools`). Which ones run,
and in what order, is decided by the agent from the source's policy prose —
not hardcoded — but each tool's own behavior is fixed:

## `download`

Downloads the best-available-quality video via yt-dlp
(`src/sync_master/tools/download.py`) into
`<output_dir>/<video_id>/video.<ext>`.

## `transcript`

Tries YouTube's own captions first (`youtube-transcript-api`). If none are
available, falls back to downloading audio and transcribing it with Whisper
(`src/sync_master/tools/transcript.py`). Writes
`<output_dir>/<video_id>/transcript.md` and records which source
(`captions` or `whisper`) it came from.

The Whisper fallback needs the optional `whisper` extra installed — see
[Setup](setup.md#install).

## `summarize`

Reads `transcript.md` and calls the configured LLM
(`src/sync_master/tools/summarize.py`) with the source's policy prose as
instructions — this is where "summarize in 3 paragraphs" vs. "bullet points
of action items" actually takes effect. Writes
`<output_dir>/<video_id>/summary.md`.

Depends on `transcript` having already run; the agent is expected to run
`transcript` first based on the policy text, not enforced by code.

## `spotify_sync`

Resolves a Spotify URI for the video, then adds it to the source's
`spotify_playlist_id` (`src/sync_master/tools/spotify_search.py` +
`spotify_playlist.py`). Resolution order:

1. Check `spotify_overrides.json` for this video ID — direct URI or a
   corrected search string, if present.
2. Otherwise, search using the video's title.
3. No match found → action status becomes `no_match` (not retried
   automatically; see [Configuration](configuration.md#spotify_overridesjson)).

## Failure handling

Any action that raises an exception is recorded as `status: failed` with the
error message, and is retried automatically on the next `sync-master run`
(see [Architecture](architecture.md#state-model)). `spotify_sync` finding no
match is *not* a failure — it's the distinct `no_match` status described
above.
