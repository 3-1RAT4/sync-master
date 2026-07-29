# Actions

These are the four tools `run_actions_for_video` can dispatch to for a video
(`src/sync_master/agent/orchestrator.py::make_action_tools`). Which ones run
is decided entirely by the playlist's `[...]` name flags (see
[Configuration](configuration.md#playlist-naming-scheme)) — not by an LLM,
not by prose — and they always run in the same fixed canonical order:
`download`, `transcript`, `summarize`, `spotify_sync`.

## `download`

Downloads the best-available-quality video via yt-dlp
(`src/sync_master/tools/download.py`) into the video's folder:
`<output_dir>/<video_id>/<sanitized_title>.<ext>`. The filename is the
video's title with spaces replaced by underscores (`sanitize_filename` in
`src/sync_master/tools/naming.py`) — falls back to the generic name `video`
if no title is available for some reason.

## `transcript`

Tries YouTube's own captions first (`youtube-transcript-api`). If none are
available, falls back to downloading audio and transcribing it with Whisper
(`src/sync_master/tools/transcript.py`). Writes into the **same** per-video
folder as `download` — `<output_dir>/<video_id>/<sanitized_title>_TRANSCRIPT.md`
(falls back to the generic `transcript.md` if no title is available).

`get_transcript` returns which source (`captions` or `whisper`) was used, but
note this isn't currently persisted into `state.json` — the orchestrator's
`transcript` tool discards that part of the result, so `state.json` only
ever records `{"status": "done", ...}` for this action, not which path was
taken.

The Whisper fallback needs the optional `whisper` extra installed — see
[Setup](setup.md#install).

### Speaker diarization (Whisper fallback only)

When the Whisper fallback runs, the transcript isn't just a wall of text —
it's formatted as labeled conversation turns (`SPEAKER_00: ...`,
`SPEAKER_01: ...`) using `pyannote.audio` for diarization
(`src/sync_master/tools/diarize.py`), aligned against Whisper's own segment
timestamps. Consecutive segments from the same speaker are merged into one
turn.

This only applies to the Whisper path — captions from YouTube are plain
text with no speaker labels, since diarizing would mean downloading and
processing audio even when captions already succeeded for free.

Needs the optional `diarization` extra (`pyannote.audio`) installed, **plus**
a Hugging Face account: the pipeline (`pyannote/speaker-diarization-community-1`)
is gated, so you must accept its terms on Hugging Face and set
`HUGGINGFACE_TOKEN` in `credentials.env` — see [Setup](setup.md#install).

Implementation note: `diarize_audio` (`src/sync_master/tools/diarize.py`)
reads `DiarizeOutput.exclusive_speaker_diarization`, not
`.speaker_diarization` — the "exclusive" variant has no overlapping speech
turns, which is what the pipeline's own docs recommend for aligning against
a separate transcription (our Whisper segments). Using the non-exclusive
variant would make some Whisper segments ambiguous between two overlapping
speakers.

## `summarize`

Reads the transcript file written by `transcript` (same title-based naming)
and calls the configured LLM (`src/sync_master/tools/summarize.py`) with a
fixed instruction string (`DEFAULT_SUMMARIZE_INSTRUCTIONS` in
`orchestrator.py` — "summarize concisely, capturing the key points and main
topics discussed"). There's no per-playlist customization of summary style
in this design — the `#` flag means "summarize the same way, everywhere."
Writes `<output_dir>/<video_id>/summary.md`.

Since `#` always expands to `transcript` + `summarize` together (see
[Configuration](configuration.md#playlist-naming-scheme)), and canonical
order runs `transcript` before `summarize`, the dependency is satisfied
without any special-casing.

## `spotify_sync`

Two separate things get resolved here, independently:

1. **Destination playlist** — `find_or_create_playlist` (`src/sync_master/tools/spotify_playlist.py`)
   looks for an existing Spotify playlist whose name matches the YouTube
   playlist's *leaf name* exactly; if none exists, it creates a new private
   one. No manual ID mapping — this is what lets `@` work across as many
   playlists as you flag, with zero per-playlist setup.
2. **Track match** — resolves a Spotify URI for *this specific video*
   (`src/sync_master/tools/spotify_search.py`):
   1. Check `spotify_overrides.json` for this video ID — direct URI or a
      corrected search string, if present.
   2. Otherwise, search using the video's title.
   3. No match found → action status becomes `no_match` (not retried
      automatically; see [Configuration](configuration.md#spotify_overridesjson)).
      This is unrelated to the playlist resolution above — a `no_match`
      here never means "couldn't create the playlist," only "couldn't find
      this track."

## Failure handling

Any action that raises an exception is recorded as `status: failed` with the
error message, and is retried automatically on the next `sync-master run`
(see [Architecture](architecture.md#state-model)). `spotify_sync` finding no
*track* match is *not* a failure — it's the distinct `no_match` status
described above.
