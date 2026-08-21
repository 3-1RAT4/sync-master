import { useState } from "react";
import { Link } from "react-router-dom";
import { trpc } from "../trpc";

type Playlist = {
  id: bigint;
  title: string;
  actions: string[];
  item_count: number | null;
};

type TreeNode = {
  name: string;
  path: string;
  children: Map<string, TreeNode>;
  playlists: Playlist[];
};

// Mirrors src/sync_master/playlist_naming.py's folder-path derivation
// (strip a trailing [...] suffix if present, split the rest on "-"), but
// without requiring a *recognized* flag inside it - every playlist gets a
// tree position this way, not just the ones the processing pipeline tracks.
// A playlist with no dashes (and no brackets) just becomes a single
// top-level leaf, which is the correct degenerate case.
const SUFFIX_RE = /^(.*)\[[^\]]*\]$/;

function derivePathSegments(title: string): string[] {
  const match = title.match(SUFFIX_RE);
  const pathPart = match ? match[1] : title;
  return pathPart.split("-").filter(Boolean);
}

function buildTree(playlists: Playlist[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map(), playlists: [] };

  for (const playlist of playlists) {
    const segments = derivePathSegments(playlist.title);

    let node = root;
    let pathSoFar = "";
    for (const segment of segments) {
      pathSoFar = pathSoFar ? `${pathSoFar}/${segment}` : segment;
      let child = node.children.get(segment);
      if (!child) {
        child = { name: segment, path: pathSoFar, children: new Map(), playlists: [] };
        node.children.set(segment, child);
      }
      node = child;
    }
    node.playlists.push(playlist);
  }

  return root;
}

const INDENT_PX = 18;

function PlaylistRow({ playlist, label, depth }: { playlist: Playlist; label: string; depth: number }) {
  return (
    <Link
      to={`/playlists/${playlist.id}`}
      className="tree-row tree-row-file"
      style={{ paddingLeft: `${depth * INDENT_PX}px` }}
      title={playlist.title}
    >
      <span className="tree-gutter" aria-hidden>
        ▶
      </span>
      <span className="tree-label">{label}</span>
      <span className="tree-meta">
        {playlist.actions.map((a) => (
          <span key={a} className="badge">
            {a}
          </span>
        ))}
        {playlist.item_count !== null && <span className="item-count">{playlist.item_count} videos</span>}
      </span>
    </Link>
  );
}

function FolderRow({ node, depth }: { node: TreeNode; depth: number }) {
  const [expanded, setExpanded] = useState(true);
  const children = [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name));

  if (children.length === 0) {
    // Nothing to expand/collapse - this path is just its playlist(s).
    return (
      <>
        {node.playlists.map((p) => (
          <PlaylistRow key={p.id.toString()} playlist={p} label={node.name} depth={depth} />
        ))}
      </>
    );
  }

  return (
    <>
      <button
        type="button"
        className="tree-row tree-row-folder"
        style={{ paddingLeft: `${depth * INDENT_PX}px` }}
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <span className={`tree-gutter tree-chevron ${expanded ? "expanded" : ""}`} aria-hidden>
          ▸
        </span>
        <span className="tree-label tree-label-folder">{node.name}</span>
      </button>
      {expanded && (
        <>
          {node.playlists.map((p) => (
            <PlaylistRow key={p.id.toString()} playlist={p} label={node.name} depth={depth + 1} />
          ))}
          {children.map((child) => (
            <FolderRow key={child.path} node={child} depth={depth + 1} />
          ))}
        </>
      )}
    </>
  );
}

export default function PlaylistList() {
  const { data: playlists, isLoading, error } = trpc.playlists.list.useQuery();

  if (isLoading) return <p>Loading playlists…</p>;
  if (error) return <p className="error">Failed to load playlists: {error.message}</p>;
  if (!playlists) return null;

  const tree = buildTree(playlists);
  const topLevel = [...tree.children.values()].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="explorer-page">
      <h1>Playlists ({playlists.length})</h1>
      <p className="hint">
        Folder structure derived from each playlist's name (dash-separated segments, e.g.{" "}
        <code>HUMAN-HEARTH-ART-DANCE</code> becomes <code>HUMAN/HEARTH/ART/DANCE</code>). Click a row to open it;
        badges show which processing actions run for that playlist - no badges means it's cataloged but not
        actively processed.
      </p>
      <div className="tree">
        {topLevel.map((node) => (
          <FolderRow key={node.path} node={node} depth={0} />
        ))}
      </div>
    </div>
  );
}
