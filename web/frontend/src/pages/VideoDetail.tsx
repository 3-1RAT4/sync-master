import { Link, useParams } from "react-router-dom";
import { trpc } from "../trpc";

const STATUS_CLASS: Record<string, string> = {
  done: "status-done",
  failed: "status-failed",
  no_match: "status-no-match",
};

export default function VideoDetail() {
  const { videoId } = useParams<{ videoId: string }>();
  const { data: video, isLoading, error } = trpc.videos.get.useQuery(
    { id: videoId! },
    { enabled: !!videoId },
  );

  if (isLoading) return <p>Loading video…</p>;
  if (error) return <p className="error">Failed to load video: {error.message}</p>;
  if (!video) return <p>Not found.</p>;

  const actions = video.actions ?? {};

  return (
    <div>
      <p>
        {video.playlists ? (
          <Link to={`/playlists/${video.playlists.id}`}>&larr; {video.playlists.title}</Link>
        ) : (
          <Link to="/">&larr; All playlists</Link>
        )}
      </p>

      <h1>{video.title}</h1>

      {Object.keys(actions).length > 0 && (
        <div className="badges">
          {Object.entries(actions).map(([name, action]) => (
            <span key={name} className={`badge ${STATUS_CLASS[action.status] ?? ""}`}>
              {name}: {action.status}
            </span>
          ))}
        </div>
      )}

      {video.description && <p className="description">{video.description}</p>}

      {video.summaries && (
        <section>
          <h2>Summary</h2>
          <p className="hint">
            {video.summaries.llm_provider} / {video.summaries.llm_model}
          </p>
          <div className="prose">{video.summaries.content}</div>
        </section>
      )}

      {video.spotify_syncs && (
        <section>
          <h2>Spotify</h2>
          <p>
            Matched via {video.spotify_syncs.matched_via} &middot; track{" "}
            <code>{video.spotify_syncs.spotify_track_id}</code>
          </p>
        </section>
      )}

      {video.transcripts && (
        <section>
          <h2>Transcript</h2>
          <p className="hint">source: {video.transcripts.source}</p>
          <pre className="transcript">{video.transcripts.text}</pre>
        </section>
      )}
    </div>
  );
}
