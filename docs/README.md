# sync-master documentation

sync-master watches YouTube playlists, detects new videos, and deterministically
runs a fixed set of actions on them — download the video, transcribe it,
summarize it, sync it to Spotify — based on flag characters encoded directly
in each playlist's name on YouTube. No per-playlist config file to maintain,
no LLM deciding what to do: name a playlist `HUMAN-MUSIC-PARTY[!@]` and it's
tracked; leave the brackets off and it's ignored. All durable state and
output (downloaded video, transcript, summary, Spotify sync record) lives in
an Obsidian vault.

- [Architecture](architecture.md) — how the pieces fit together and why
- [Setup](setup.md) — installing, bootstrapping, the vault, YouTube/Spotify OAuth, cron, backups
- [Configuration](configuration.md) — the playlist naming scheme, the vault and scratch directories, `llm.yaml`, Spotify overrides
- [Actions](actions.md) — what each of the four actions (`download`, `transcript`, `summarize`, `spotify_sync`) does
- [Development](development.md) — running tests, project layout, dry-run mode
