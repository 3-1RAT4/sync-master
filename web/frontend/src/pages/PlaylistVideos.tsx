import { Link, useParams } from "react-router-dom";
import {
  derivePathSegments,
  systemForSegments,
  UNCLASSIFIED_PIGMENT,
  youtubePlaylistUrl,
  youtubeVideoUrl,
} from "../taxonomy";
import { trpc } from "../trpc";

export default function PlaylistVideos() {
  const { playlistId } = useParams<{ playlistId: string }>();
  const { data: videos, isLoading, error } = trpc.playlists.videos.useQuery(
    { playlistId: playlistId! },
    { enabled: !!playlistId },
  );
  // Already cached from the tree on the home page, so this is normally free.
  const { data: playlists } = trpc.playlists.list.useQuery();
  const playlist = playlists?.find((p) => p.id.toString() === playlistId);

  const segments = playlist ? derivePathSegments(playlist.title) : [];
  const system = systemForSegments(segments);
  const pigment = system?.pigment ?? UNCLASSIFIED_PIGMENT;

  if (isLoading) return <p className="state">Loading videos…</p>;
  if (error) return <p className="state state-error">Couldn't load videos. {error.message}</p>;

  return (
    <div className="plate" style={{ ["--pig" as string]: pigment }}>
      <header className="plate-head plate-head-tinted">
        <Link to="/" className="back mono">
          ← Catalog
        </Link>

        {segments.length > 0 && (
          <nav className="crumbs" aria-label="Playlist path">
            {segments.map((segment, i) => (
              <span key={`${segment}-${i}`} className={i === segments.length - 1 ? "crumb is-leaf" : "crumb"}>
                {segment}
              </span>
            ))}
          </nav>
        )}

        <h1 className="plate-title">{segments.at(-1) ?? playlist?.title ?? "Playlist"}</h1>

        <div className="plate-meta">
          <span className="eyebrow">
            {videos?.length ?? 0} videos{system ? ` · ${system.label}` : ""}
            {playlist && playlist.actions.length > 0 ? ` · ${playlist.actions.join(" · ")}` : " · not tracked"}
          </span>
          {playlist && (
            <a className="link-out mono" href={youtubePlaylistUrl(playlist.external_id)} target="_blank" rel="noreferrer">
              Open on YouTube ↗
            </a>
          )}
        </div>
      </header>

      {videos && videos.length === 0 ? (
        <p className="state">This playlist has no videos in the catalog yet. The next sync will fill it.</p>
      ) : (
        <ul className="videos">
          {videos?.map((v) => (
            <li key={v.id.toString()} className="video">
              <Link to={`/videos/${v.id}`} className="video-main">
                {v.thumbnail_url ? (
                  <img src={v.thumbnail_url} alt="" className="thumb" loading="lazy" />
                ) : (
                  <span className="thumb thumb-blank" aria-hidden />
                )}
                <span className="video-text">
                  <span className="video-title">{v.title}</span>
                  <span className="video-meta mono">
                    {v.published_at ? new Date(v.published_at).toLocaleDateString() : "no date"} · {v.external_id}
                  </span>
                </span>
              </Link>
              <a
                className="row-out mono"
                href={youtubeVideoUrl(v.external_id)}
                target="_blank"
                rel="noreferrer"
                title="Open on YouTube"
              >
                YT
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
