import { Link, Route, Routes } from "react-router-dom";
import "./App.css";
import PlaylistList from "./pages/PlaylistList";
import PlaylistVideos from "./pages/PlaylistVideos";
import VideoDetail from "./pages/VideoDetail";
import { SYSTEMS } from "./taxonomy";

/** The rail motif that runs down the tree, shrunk to a mark. */
function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden>
      {SYSTEMS.slice(0, 5).map((s) => (
        <i key={s.key} style={{ background: s.pigment }} />
      ))}
    </span>
  );
}

export default function App() {
  return (
    <div className="app">
      <header className="masthead">
        <Link to="/" className="brand">
          <BrandMark />
          <span className="brand-name">sync-master</span>
        </Link>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<PlaylistList />} />
          <Route path="/playlists/:playlistId" element={<PlaylistVideos />} />
          <Route path="/videos/:videoId" element={<VideoDetail />} />
        </Routes>
      </main>
    </div>
  );
}
