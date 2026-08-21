import { Link, Route, Routes } from "react-router-dom";
import "./App.css";
import PlaylistList from "./pages/PlaylistList";
import PlaylistVideos from "./pages/PlaylistVideos";
import VideoDetail from "./pages/VideoDetail";

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="brand">
          sync-master
        </Link>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<PlaylistList />} />
          <Route path="/playlists/:playlistId" element={<PlaylistVideos />} />
          <Route path="/videos/:videoId" element={<VideoDetail />} />
        </Routes>
      </main>
    </div>
  );
}
