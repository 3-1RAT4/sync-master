# sync-master documentation

sync-master watches data sources (currently YouTube playlists), detects new
items, and uses an AI agent to decide what to do with them — download the
video, transcribe it, summarize it, sync it to Spotify — based on a
plain-language policy you write per source.

- [Architecture](architecture.md) — how the pieces fit together and why
- [Setup](setup.md) — installing, bootstrapping, credentials, cron
- [Configuration](configuration.md) — source policy files, `llm.yaml`, Spotify overrides
- [Actions](actions.md) — what each action does and how to author policy text for it
- [Development](development.md) — running tests, project layout, dry-run mode
