import { useMemo, useState } from "react";
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

function collectFolderPaths(node: TreeNode, out: string[]): void {
  if (node.children.size === 0) return;
  if (node.path) out.push(node.path);
  for (const child of node.children.values()) collectFolderPaths(child, out);
}

type Filter = { text: string; onlyTracked: boolean };

function playlistMatches(p: Playlist, filter: Filter): boolean {
  if (filter.onlyTracked && p.actions.length === 0) return false;
  if (filter.text && !p.title.toLowerCase().includes(filter.text)) return false;
  return true;
}

// Does any playlist in this node's subtree pass the filter? Used both to
// hide whole empty branches and to force-expand branches that do match.
function subtreeHasMatch(node: TreeNode, filter: Filter): boolean {
  if (node.playlists.some((p) => playlistMatches(p, filter))) return true;
  for (const child of node.children.values()) {
    if (subtreeHasMatch(child, filter)) return true;
  }
  return false;
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

function FolderRow({
  node,
  depth,
  filter,
  filterActive,
  collapsedPaths,
  onToggle,
}: {
  node: TreeNode;
  depth: number;
  filter: Filter;
  filterActive: boolean;
  collapsedPaths: Set<string>;
  onToggle: (path: string) => void;
}) {
  const children = [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name));

  if (children.length === 0) {
    // Nothing to expand/collapse - this path is just its playlist(s).
    return (
      <>
        {node.playlists
          .filter((p) => playlistMatches(p, filter))
          .map((p) => (
            <PlaylistRow key={p.id.toString()} playlist={p} label={node.name} depth={depth} />
          ))}
      </>
    );
  }

  // A filter prunes whole branches with no matches anywhere inside them,
  // and force-expands whatever's left so a match is never hidden behind a
  // collapsed folder. With no filter active, expansion follows the
  // explicit collapsed-paths state (toolbar buttons or individual clicks).
  if (filterActive && !subtreeHasMatch(node, filter)) return null;
  const expanded = filterActive || !collapsedPaths.has(node.path);

  const visiblePlaylists = node.playlists.filter((p) => playlistMatches(p, filter));
  const visibleChildren = filterActive ? children.filter((c) => subtreeHasMatch(c, filter)) : children;

  return (
    <>
      <button
        type="button"
        className="tree-row tree-row-folder"
        style={{ paddingLeft: `${depth * INDENT_PX}px` }}
        onClick={() => onToggle(node.path)}
        aria-expanded={expanded}
      >
        <span className={`tree-gutter tree-chevron ${expanded ? "expanded" : ""}`} aria-hidden>
          ▸
        </span>
        <span className="tree-label tree-label-folder">{node.name}</span>
      </button>
      {expanded && (
        <>
          {visiblePlaylists.map((p) => (
            <PlaylistRow key={p.id.toString()} playlist={p} label={node.name} depth={depth + 1} />
          ))}
          {visibleChildren.map((child) => (
            <FolderRow
              key={child.path}
              node={child}
              depth={depth + 1}
              filter={filter}
              filterActive={filterActive}
              collapsedPaths={collapsedPaths}
              onToggle={onToggle}
            />
          ))}
        </>
      )}
    </>
  );
}

export default function PlaylistList() {
  const { data: playlists, isLoading, error } = trpc.playlists.list.useQuery();
  const [filterText, setFilterText] = useState("");
  const [onlyTracked, setOnlyTracked] = useState(false);
  const [collapsedPaths, setCollapsedPaths] = useState<Set<string>>(new Set());

  const tree = useMemo(() => (playlists ? buildTree(playlists) : null), [playlists]);

  if (isLoading) return <p>Loading playlists…</p>;
  if (error) return <p className="error">Failed to load playlists: {error.message}</p>;
  if (!playlists || !tree) return null;
  // TS doesn't carry the null-narrowing above into the closures below -
  // rebind to a variable whose type reflects that narrowing.
  const knownTree: TreeNode = tree;

  const filter: Filter = { text: filterText.trim().toLowerCase(), onlyTracked };
  const filterActive = filter.text !== "" || filter.onlyTracked;

  const topLevel = [...tree.children.values()].sort((a, b) => a.name.localeCompare(b.name));
  const visibleTopLevel = filterActive ? topLevel.filter((n) => subtreeHasMatch(n, filter)) : topLevel;
  const matchCount = filterActive ? playlists.filter((p) => playlistMatches(p, filter)).length : playlists.length;

  function toggleFolder(path: string) {
    setCollapsedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  function expandAll() {
    setCollapsedPaths(new Set());
  }

  function collapseAll() {
    const allFolderPaths: string[] = [];
    collectFolderPaths(knownTree, allFolderPaths);
    setCollapsedPaths(new Set(allFolderPaths));
  }

  return (
    <div className="explorer-page">
      <h1>Playlists ({playlists.length})</h1>
      <p className="hint">
        Folder structure derived from each playlist's name (dash-separated segments, e.g.{" "}
        <code>HUMAN-HEARTH-ART-DANCE</code> becomes <code>HUMAN/HEARTH/ART/DANCE</code>). Click a row to open it;
        badges show which processing actions run for that playlist - no badges means it's cataloged but not
        actively processed.
      </p>
      <div className="explorer-toolbar">
        <input
          type="search"
          className="filter-input"
          placeholder="Filter by name…"
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
        />
        <label className="toolbar-toggle">
          <input type="checkbox" checked={onlyTracked} onChange={(e) => setOnlyTracked(e.target.checked)} />
          Tracked only
        </label>
        {filterActive && (
          <span className="toolbar-count">
            {matchCount} match{matchCount === 1 ? "" : "es"}
          </span>
        )}
        <div className="toolbar-spacer" />
        <button type="button" className="toolbar-btn" onClick={expandAll}>
          Expand all
        </button>
        <button type="button" className="toolbar-btn" onClick={collapseAll}>
          Collapse all
        </button>
      </div>
      <div className="tree">
        {visibleTopLevel.length === 0 ? (
          <p className="tree-empty">No playlists match this filter.</p>
        ) : (
          visibleTopLevel.map((node) => (
            <FolderRow
              key={node.path}
              node={node}
              depth={0}
              filter={filter}
              filterActive={filterActive}
              collapsedPaths={collapsedPaths}
              onToggle={toggleFolder}
            />
          ))
        )}
      </div>
    </div>
  );
}
