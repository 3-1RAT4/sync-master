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
         │  take the lock (~/.config/sync-master/state.json.lock)
         │  (skip the run entirely if another one is already in progress)
         │
         ├── CATALOG — src/sync_master/vault.py + sources/youtube.py
         │     index the vault: read every video note's frontmatter under
         │        SYNC_MASTER/VIDEOS/YOUTUBE/ -> where each (playlist, video) is
         │     fetch every playlist on the account (OAuth, includes private ones)
         │     for each playlist, for each video in playlist order:
         │        place_video -> the folder <segments>/<N>.<title>/ exists,
         │        with its note: created, renamed into place if YouTube
         │        reordered or retitled it, or just refreshed
         │
         ├── DISPATCH — src/sync_master/agent/orchestrator.py
         │     for each video in a *flagged* playlist that needs processing:
         │        run_actions_for_video(parsed.actions, ...)
         │        calls exactly those tools (download, transcript, summarize,
         │        spotify_sync), in canonical order, no decision step
         │        each tool writes its product into the video's folder
         │        (the mp4, the transcript note, the summary note, or the
         │        Spotify result in the note's frontmatter) and records its
         │        done/failed/no_match status in state.json
         │
         └── release the lock
```

Playlist names are **re-parsed fresh every run** from the live title, not
frozen at first discovery — edit a playlist's flags on YouTube and the next
run picks it up.

Everything durable lives in the Obsidian vault — see [State model](#state-model)
below. `output_base_dir` in `settings.yaml` is scratch space: yt-dlp downloads
there and Whisper/pyannote read from there; the vault gets a copy of the
video, so scratch is safe to delete at any time.

**Every** playlist is catalogued, flagged or not — that's what gives the vault
the whole YouTube tree. Only flagged playlists get actions run.

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
| Vault | `src/sync_master/vault.py` | The store. Names (`N.Title`), the folder index, `place_video` (create / rename into place / refresh), note rendering with the managed block, and the writers for video, transcript, summary and the Spotify result |
| State | `src/sync_master/state.py` | `state.json` (the action ledger, keyed by YouTube id) and the `state.json.lock` file lock |
| YouTube source | `src/sync_master/sources/youtube.py` | `fetch_my_playlists` (OAuth, lists every playlist on the account) and `fetch_playlist_items` (fetches a playlist's videos), plus diffing against known video IDs |
| YouTube auth | `src/sync_master/youtube_auth.py` | Builds the OAuth-authenticated client from a stored refresh token; the one-time login flow used by `sync-master youtube-login` |
| Spotify auth | `src/sync_master/spotify_auth.py` | Builds the `SpotifyOAuth` manager from `SPOTIFY_CLIENT_ID`/`_SECRET`/`_REDIRECT_URI`, with a stable cache path (`~/.config/sync-master/.spotify_cache`) so the token survives across separate CLI invocations (important for cron) |
| Naming | `src/sync_master/playlist_naming.py` | `derive_folder_segments` (the folder every playlist maps to) and `parse_playlist_name` (the flag parser, for the ones that get actions) |
| Config | `src/sync_master/config.py` | Parse `llm.yaml`, `settings.yaml` (`vault_dir`, `output_base_dir`), `spotify_overrides.json` |
| Tools | `src/sync_master/tools/*.py` | `download` (yt-dlp), `transcript` (YouTube captions → Whisper fallback), `diarize` (pyannote speaker labeling), `naming` (title → filename), `summarize` (LangChain), `spotify_search`, `spotify_playlist` (including find-or-create) |
| Orchestrator | `src/sync_master/agent/orchestrator.py` | Wraps tools per video (dry-run logging, done/failed/no_match state tracking) and `run_actions_for_video`, the deterministic dispatcher |
| Runner | `src/sync_master/runner.py` | Glues catalog and dispatch together for one full run; returns a `RunReport` |
| Bootstrap | `src/sync_master/bootstrap.py` | Scaffolds `~/.config/sync-master/`, checks external tools and the vault, reports missing credentials, prints the crontab line |
| CLI | `src/sync_master/cli.py` | `sync-master run`, `bootstrap`, `youtube-login`, `spotify-login` |

## State model

Two things, with a clear split:

**The vault holds the content.** Under `SYNC_MASTER/VIDEOS/YOUTUBE/` inside
the Obsidian vault, every playlist is the folder its dash-segments spell out
and every video is a folder named `N.Title` (N = position in the playlist):

```
HUMAN/PODCASTS/3.Explosive CIA Face-Off- Loyal Officer VS Dissident Spy/
  3.Explosive CIA Face-Off….md              the note - created once
  3.Explosive CIA Face-Off….mp4             download
  3.Explosive CIA Face-Off….transcript.md   transcript
  3.Explosive CIA Face-Off….summary.md      summarize
```

The note's frontmatter carries the identity (`youtube_id`, `playlist_id`,
`position`, `title`, …) and, after `spotify_sync`, the match
(`spotify_track_uri`, `spotify_playlist_id`, `spotify_matched_via`). The
rules sync-master follows in there:

- **The body is never overwritten.** Later runs merge the frontmatter (keys
  you add survive) and regenerate only the block between
  `<!-- sync-master:begin -->` and `<!-- sync-master:end -->`, which holds the
  video embed and the transcript/summary links. Annotate freely elsewhere.
- **Reorders and renames on YouTube move the folder** — folder, prefixed
  files, links in the managed block. Nothing is ever deleted.
- **Anything moved out of `SYNC_MASTER/VIDEOS/YOUTUBE/` is invisible** to the
  sync and gets recreated in place. Reorganise inside it.

**`~/.config/sync-master/state.json` holds the ledger** — what has been run
for which video, keyed by YouTube id so it survives any reorganising:

```json
{"videos": {"abc123": {"playlist_id": "PL…", "title": "…", "published_at": "…",
                        "actions": {"download": {"status": "done", "updated_at": "…"},
                                    "spotify_sync": {"status": "no_match", "updated_at": "…"}}}},
 "spotify_playlists": {"LOFI": "2XUF1FOl8VZnqA4NKWS2Kv"}}
```

A video is reconsidered on the next run if it has **no entry yet for a
currently-required action** (brand new, or a newly-added flag), **any action
with `status: failed`** (auto-retry), or — the vault wins — an action marked
`done` **whose product is missing from the folder**: delete a summary in
Obsidian and the next run writes it again. `no_match` is terminal: the
Spotify *track* search genuinely found nothing, so it isn't retried; see
[spotify_overrides.json](configuration.md#spotify_overridesjson) to resolve
one by hand.
