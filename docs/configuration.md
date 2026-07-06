# Configuration

Everything lives under `~/.config/sync-master/`, scaffolded by
`sync-master bootstrap` (see [Setup](setup.md)).

## Source policy files (`sources/*.md`)

One markdown file per tracked playlist. Frontmatter carries the structured
fields the deterministic layer needs; everything below the frontmatter is
plain-language policy handed to the agent — same frontmatter+prose
convention used by a Claude Code `SKILL.md`.

```markdown
---
name: my-podcast
playlist_id: PLyyyyyyyyyyyy
output_dir: ./output/my-podcast
spotify_playlist_id: spotify:playlist:zzzzzzz
---

This is my podcast feed. For each new episode:
1. Get the transcript.
2. Summarize it in 3 short paragraphs, focused on the main topics discussed.
3. Try to match it on Spotify and add it to my playlist.

Don't download the full video file for this source.
```

Frontmatter fields:

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Identifies this source in logs and output paths |
| `playlist_id` | yes | YouTube playlist ID to poll |
| `output_dir` | yes | Where per-video folders (`<output_dir>/<video_id>/`) are written |
| `spotify_playlist_id` | no | Target Spotify playlist for `spotify_sync`. Kept structured (not left for the agent to guess from prose) so an exact ID is never hallucinated |

The prose body is not parsed — it's passed to the LLM agent as-is, so write
it the way you'd explain the policy to a person. Whether to download,
whether to summarize, what tone/length the summary should be, whether to
sync to Spotify: all of that goes in the prose, not the frontmatter.

## `llm.yaml`

Shared provider config for both the orchestration agent and the `summarize`
action:

```yaml
provider: deepseek
model: deepseek-chat
base_url: https://api.deepseek.com
```

`base_url` makes this work with any OpenAI-compatible endpoint. The API key
itself comes from `credentials.env` (`LLM_API_KEY`), not this file.

## `spotify_overrides.json`

When `spotify_sync` can't find a match automatically, it's marked
`no_match` (see [Architecture](architecture.md#state-model)) and left alone
on future runs — no repeated wasted searches. To fix a specific video by
hand, add an entry here, keyed by YouTube video ID:

```json
{
  "<video_id>": "spotify:track:abc123",
  "<other_video_id>": "corrected search text"
}
```

- A value starting with `spotify:` is used directly as the URI to add —
  no search performed.
- Anything else is used as the search query instead of the video title.

This file is re-read every run, so adding an entry is what "retries" a
`no_match` video.

## `credentials.env`

Not committed, not templated with real values — see
[Setup](setup.md#bootstrap) for what goes in it.
