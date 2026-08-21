import { useRef } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import TranscriptReader from "../components/TranscriptReader";
import { Markdown } from "../lib/markdown";
import {
  derivePathSegments,
  systemForSegments,
  UNCLASSIFIED_PIGMENT,
  youtubeVideoUrl,
} from "../taxonomy";
import { trpc } from "../trpc";

const STATUS_CLASS: Record<string, string> = {
  done: "is-done",
  failed: "is-failed",
  no_match: "is-no-match",
};

type TabId = "transcript" | "summary" | "description";

export default function VideoDetail() {
  const { videoId } = useParams<{ videoId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const videoRef = useRef<HTMLVideoElement>(null);
  const { data: video, isLoading, error } = trpc.videos.get.useQuery(
    { id: videoId! },
    { enabled: !!videoId },
  );

  if (isLoading) return <p className="state">Loading video…</p>;
  if (error) return <p className="state state-error">Couldn't load this video. {error.message}</p>;
  if (!video) return <p className="state">That video isn't in the catalog.</p>;

  const actions = video.actions ?? {};
  const segments = video.playlists ? derivePathSegments(video.playlists.title) : [];
  const pigment = systemForSegments(segments)?.pigment ?? UNCLASSIFIED_PIGMENT;

  // The transcript leads: it's the thing you came here to read, and the
  // summary is a shortcut past it rather than the other way round.
  const tabs: { id: TabId; label: string; note: string }[] = [];
  if (video.transcripts) {
    tabs.push({ id: "transcript", label: "Transcript", note: `from ${video.transcripts.source}` });
  }
  if (video.summaries) {
    tabs.push({
      id: "summary",
      label: "Summary",
      note: `${video.summaries.llm_provider} · ${video.summaries.llm_model}`,
    });
  }
  if (video.description) {
    tabs.push({ id: "description", label: "Description", note: "as written on YouTube" });
  }

  const requested = searchParams.get("view");
  const active = tabs.find((t) => t.id === requested)?.id ?? tabs[0]?.id;
  const activeTab = tabs.find((t) => t.id === active);

  return (
    <div className="plate plate-narrow" style={{ ["--pig" as string]: pigment }}>
      <header className="plate-head plate-head-tinted">
        {video.playlists ? (
          <Link to={`/playlists/${video.playlists.id}`} className="back mono">
            ← {segments.at(-1) ?? video.playlists.title}
          </Link>
        ) : (
          <Link to="/" className="back mono">
            ← Catalog
          </Link>
        )}

        <h1 className="plate-title plate-title-video">{video.title}</h1>

        {/* Only the handful of videos in a download-flagged playlist have a
            stored file. The rest show no player at all - the "Watch on
            YouTube" link below already covers them. */}
        {video.video_files && (
          <video
            ref={videoRef}
            className="player"
            controls
            preload="metadata"
            src={`/api/videos/${video.external_id}/stream`}
          />
        )}

        <div className="plate-meta">
          <span className="eyebrow">
            {video.published_at ? new Date(video.published_at).toLocaleDateString() : "no date"}
          </span>
          {/* Never inside .eyebrow: that uppercases, and a YouTube id is
              case-sensitive - T3FXH39OYSA is a different video from t3FxH39oYsA. */}
          <span className="ident mono">{video.external_id}</span>
          <a className="link-out mono" href={youtubeVideoUrl(video.external_id)} target="_blank" rel="noreferrer">
            Watch on YouTube ↗
          </a>
        </div>

        {(Object.keys(actions).length > 0 || video.spotify_syncs) && (
          <ul className="states">
            {Object.entries(actions).map(([name, action]) => (
              <li key={name} className={`state-pill ${STATUS_CLASS[action.status] ?? ""}`}>
                <span className="state-name">{name}</span>
                <span className="state-value mono">{action.status.replace("_", " ")}</span>
              </li>
            ))}
            {video.spotify_syncs && (
              <li className="state-pill">
                <span className="state-name">spotify</span>
                <span className="state-value mono">
                  matched on {video.spotify_syncs.matched_via}
                </span>
              </li>
            )}
          </ul>
        )}
      </header>

      {tabs.length === 0 ? (
        <p className="state">This video is catalogued, but nothing has been processed for it yet.</p>
      ) : (
        <>
          <nav className="tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={`tab ${tab.id === active ? "is-active" : ""}`}
                onClick={() => setSearchParams({ view: tab.id }, { replace: true })}
                aria-current={tab.id === active ? "page" : undefined}
              >
                {tab.label}
              </button>
            ))}
            {activeTab && <span className="tabs-note eyebrow">{activeTab.note}</span>}
          </nav>

          <div className="tab-panel">
            {active === "transcript" && video.transcripts && (
              <TranscriptReader
                text={video.transcripts.text}
                externalId={video.external_id}
                totalSeconds={video.transcript_seconds}
                videoRef={video.video_files ? videoRef : null}
              />
            )}

            {active === "summary" && video.summaries && <Markdown>{video.summaries.content}</Markdown>}

            {active === "description" && video.description && (
              <p className="prose prose-dim">{video.description}</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
