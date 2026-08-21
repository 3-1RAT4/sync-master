# sync-master documentation

sync-master watches YouTube playlists, detects new videos, and deterministically
runs a fixed set of actions on them — download the video, transcribe it,
summarize it, sync it to Spotify — based on flag characters encoded directly
in each playlist's name on YouTube. No per-playlist config file to maintain,
no LLM deciding what to do: name a playlist `HUMAN-MUSIC-PARTY[!@]` and it's
tracked; leave the brackets off and it's ignored. All durable state and
output (downloaded video, transcript, summary, Spotify sync record) lives in
a Postgres database.

- [Architecture](architecture.md) — how the pieces fit together and why
- [Setup](setup.md) — installing, bootstrapping, Postgres, YouTube/Spotify OAuth, cron, backup/restore
- [Configuration](configuration.md) — the playlist naming scheme, the database, `llm.yaml`, Spotify overrides
- [Actions](actions.md) — what each of the four actions (`download`, `transcript`, `summarize`, `spotify_sync`) does
- [Development](development.md) — running tests, project layout, dry-run mode, the test database
- [Web UI](web-ui.md) — the read-only browser (`web/`), a separate TypeScript stack (Node/tRPC/Prisma + React SPA) reading the same database
