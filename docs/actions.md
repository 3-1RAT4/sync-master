# Actions

These are the four tools `run_actions_for_video` can dispatch to for a video
(`src/sync_master/agent/orchestrator.py::make_action_tools`). Which ones run
is decided entirely by the playlist's `[...]` name flags (see
[Configuration](configuration.md#playlist-naming-scheme)) — not by an LLM,
not by prose — and they always run in the same fixed canonical order:
`download`, `transcript`, `summarize`, `spotify_sync`.

## `download`

Downloads the best-available-quality video via yt-dlp
(`src/sync_master/tools/download.py`) into a scratch directory:
`<output_base_dir>/<folder_path>/<video_id>/<sanitized_title>.<ext>`. The
filename is the video's title with spaces replaced by underscores
(`sanitize_filename` in `src/sync_master/tools/naming.py`) — falls back to
the generic name `video` if no title is available for some reason. The
orchestrator then reads those bytes back and stores them in the `video_files`
table (`src/sync_master/db/repository.py::save_video_file`) — the file on
disk is scratch space after that, not the durable copy.

## `transcript`

Two independent things happen here, always, regardless of each other:

1. **Text**: tries YouTube's own captions first (`youtube-transcript-api`,
   fast/free). If none are available, falls back to downloading audio and
   transcribing it with Whisper. `get_transcript`'s returned `source` field
   (`captions` or `whisper`) is persisted as-is into the `transcripts.source`
   column (`src/sync_master/db/repository.py::save_transcript`) — unlike the
   pre-Postgres design, this is no longer thrown away.
2. **Speakers**: downloads audio (if not already downloaded — see below) and
   runs diarization, **every time**, whether or not captions succeeded for
   the text. This means every `transcript` action needs an audio download,
   even on the fast captions path — a deliberate tradeoff (see
   [Speaker diarization](#speaker-diarization) below) to always get speaker
   labels rather than only on the Whisper fallback. The raw per-speaker
   segments are persisted too, into `transcript_segments` (one row per
   speaker turn) — also no longer thrown away.

These two are merged by timestamp into one output:
`[HH:MM:SS] SPEAKER_00: text...` turns, stored as `transcripts.text`. The
scratch audio file used to produce it (in the same directory `download`
uses) is disposable once this action completes.

The audio download used for diarization (and for the Whisper fallback, when
needed) reuses whatever `download` already fetched, if present —
`download_video` skips re-fetching when a matching file already exists in
the video's scratch folder, whether that's because the `download` action ran
first or because `transcript` itself already fetched it earlier. This
matters because every extra request to YouTube is a chance to trip anti-bot
detection (`Sign in to confirm you're not a bot` from yt-dlp) — see
[Development](development.md) for what to do if you hit that.

The Whisper fallback needs the optional `whisper` extra installed — see
[Setup](setup.md#install).

### Speaker diarization

Diarization (`pyannote.audio`, `src/sync_master/tools/diarize.py`) runs
unconditionally for every video with `transcript` flagged — not just as a
Whisper-fallback bonus. The tradeoff: captions alone are fast and don't need
a video download at all, but YouTube's caption data has no speaker
information, so getting speaker labels *always* means downloading and
processing audio regardless of whether captions succeeded for the text
itself. This was a deliberate choice to always have speaker labels, at the
cost of losing the "free" fast path for videos where captions were
available.

Needs the optional `diarization` extra (`pyannote.audio`) installed, **plus**
a Hugging Face account: the pipeline (`pyannote/speaker-diarization-community-1`)
is gated, so you must accept its terms on Hugging Face and set
`HUGGINGFACE_TOKEN` in `credentials.env` — see [Setup](setup.md#install).
Unlike the original design, this extra is now effectively **required** for
`transcript` to work at all, not just for speaker labels — without it,
every `transcript` action fails when it tries to diarize.

Implementation note: `diarize_audio` (`src/sync_master/tools/diarize.py`)
reads `DiarizeOutput.exclusive_speaker_diarization`, not
`.speaker_diarization` — the "exclusive" variant has no overlapping speech
turns, which is what the pipeline's own docs recommend for aligning against
a separate transcription. Using the non-exclusive variant would make some
segments ambiguous between two overlapping speakers.

## `summarize`

Reads the transcript text back from the `transcripts` table (written by
`transcript`) and calls the configured LLM
(`src/sync_master/tools/summarize.py`) with a fixed instruction string
(`DEFAULT_SUMMARIZE_INSTRUCTIONS` in `orchestrator.py` — "summarize concisely,
capturing the key points and main topics discussed"). There's no
per-playlist customization of summary style in this design — the `#` flag
means "summarize the same way, everywhere." The result, along with which LLM
provider/model produced it, is stored in the `summaries` table.

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
