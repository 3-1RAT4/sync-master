import { Link, useParams } from "react-router-dom";
import { trpc } from "../trpc";

export default function PlaylistVideos() {
  const { playlistId } = useParams<{ playlistId: string }>();
  const { data: videos, isLoading, error } = trpc.playlists.videos.useQuery(
    { playlistId: playlistId! },
    { enabled: !!playlistId },
  );

  if (isLoading) return <p>Loading videos…</p>;
  if (error) return <p className="error">Failed to load videos: {error.message}</p>;

  return (
    <div>
      <p>
        <Link to="/">&larr; All playlists</Link>
      </p>
      <h1>Videos ({videos?.length ?? 0})</h1>
      <ul className="video-list">
        {videos?.map((v) => (
          <li key={v.id.toString()}>
            <Link to={`/videos/${v.id}`} className="video-row">
              {v.thumbnail_url && <img src={v.thumbnail_url} alt="" className="thumb" />}
              <div>
                <div className="video-title">{v.title}</div>
                {v.published_at && (
                  <div className="video-meta">{new Date(v.published_at).toLocaleDateString()}</div>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
