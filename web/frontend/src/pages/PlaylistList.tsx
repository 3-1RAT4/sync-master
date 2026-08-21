import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  derivePathSegments,
  SYSTEMS,
  systemForSegments,
  UNCLASSIFIED_PIGMENT,
  youtubePlaylistUrl,
} from "../taxonomy";
import { trpc } from "../trpc";

type Playlist = {
  id: bigint;
  external_id: string;
  title: string;
  actions: string[];
  item_count: number | null;
};

type TreeNode = {
  name: string;
  path: string;
  segments: string[];
  children: Map<string, TreeNode>;
  playlists: Playlist[];
};

function buildTree(playlists: Playlist[]): TreeNode {
  const root: TreeNode = { name: "", path: "", segments: [], children: new Map(), playlists: [] };

  for (const playlist of playlists) {
    const segments = derivePathSegments(playlist.title);

    let node = root;
    const soFar: string[] = [];
    for (const segment of segments) {
      soFar.push(segment);
      let child = node.children.get(segment);
      if (!child) {
        child = {
          name: segment,
          path: soFar.join("/"),
          segments: [...soFar],
          children: new Map(),
          playlists: [],
        };
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

type Filter = { text: string; onlyTracked: boolean; system: string | null };

function playlistMatches(p: Playlist, filter: Filter): boolean {
  if (filter.onlyTracked && p.actions.length === 0) return false;
  if (filter.system) {
    const system = systemForSegments(derivePathSegments(p.title));
    if ((system?.key ?? null) !== filter.system) return false;
  }
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

/** One hairline per ancestor, tinted by the row's system. */
function Rails({ depth }: { depth: number }) {
  if (depth === 0) return null;
  return (
    <span className="rails" aria-hidden>
      {Array.from({ length: depth }, (_, i) => (
        <span key={i} className="rail" />
      ))}
    </span>
  );
}

function PlaylistRow({
  playlist,
  label,
  depth,
  pigment,
}: {
  playlist: Playlist;
  label: string;
  depth: number;
  pigment: string;
}) {
  return (
    <div className="row row-leaf" style={{ ["--pig" as string]: pigment }}>
      <Link to={`/playlists/${playlist.id}`} className="row-main" title={playlist.title}>
        <Rails depth={depth} />
        <span className="row-mark row-mark-leaf" aria-hidden />
        <span className="row-label">{label}</span>
        <span className="row-tail">
          {playlist.actions.map((a) => (
            <span key={a} className="flag mono">
              {a}
            </span>
          ))}
          {playlist.item_count !== null && (
            <span className="count mono">{playlist.item_count.toLocaleString()}</span>
          )}
        </span>
      </Link>
      <a
        className="row-out mono"
        href={youtubePlaylistUrl(playlist.external_id)}
        target="_blank"
        rel="noreferrer"
        title="Open on YouTube"
      >
        YT
      </a>
    </div>
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
  const system = systemForSegments(node.segments);
  const pigment = system?.pigment ?? UNCLASSIFIED_PIGMENT;
  // The segment that *names* a system wears its pigment; everything below it
  // inherits the rail colour but keeps bone text, so the classification reads
  // once per branch instead of shouting on every row.
  const isSystemHead = system !== null && node.name.toUpperCase() === system.key;

  if (children.length === 0) {
    // Nothing to expand/collapse - this path is just its playlist(s).
    return (
      <>
        {node.playlists
          .filter((p) => playlistMatches(p, filter))
          .map((p) => (
            <PlaylistRow
              key={p.id.toString()}
              playlist={p}
              label={node.name}
              depth={depth}
              pigment={pigment}
            />
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
      <div className="row row-branch" style={{ ["--pig" as string]: pigment }}>
        <button type="button" className="row-main" onClick={() => onToggle(node.path)} aria-expanded={expanded}>
          <Rails depth={depth} />
          <span className={`row-mark row-chevron ${expanded ? "is-open" : ""}`} aria-hidden>
            <svg viewBox="0 0 12 12" width="9" height="9">
              <path d="M4 2.5 L8 6 L4 9.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
            </svg>
          </span>
          <span className={`row-label row-label-branch ${isSystemHead ? "is-system" : ""}`}>{node.name}</span>
          {!expanded && <span className="row-tail count mono">{visibleChildren.length + visiblePlaylists.length}</span>}
        </button>
      </div>
      {expanded && (
        <>
          {visiblePlaylists.map((p) => (
            <PlaylistRow
              key={p.id.toString()}
              playlist={p}
              label={node.name}
              depth={depth + 1}
              pigment={pigment}
            />
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
  const [system, setSystem] = useState<string | null>(null);
  const [collapsedPaths, setCollapsedPaths] = useState<Set<string>>(new Set());

  const tree = useMemo(() => (playlists ? buildTree(playlists) : null), [playlists]);

  const tallies = useMemo(() => {
    const counts = new Map<string, number>();
    for (const p of playlists ?? []) {
      const key = systemForSegments(derivePathSegments(p.title))?.key ?? "";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return counts;
  }, [playlists]);

  if (isLoading) return <p className="state">Loading the catalog…</p>;
  if (error) return <p className="state state-error">Couldn't load the catalog. {error.message}</p>;
  if (!playlists || !tree) return null;
  // TS doesn't carry the null-narrowing above into the closures below -
  // rebind to a variable whose type reflects that narrowing.
  const knownTree: TreeNode = tree;

  const filter: Filter = { text: filterText.trim().toLowerCase(), onlyTracked, system };
  const filterActive = filter.text !== "" || filter.onlyTracked || filter.system !== null;

  const topLevel = [...tree.children.values()].sort((a, b) => a.name.localeCompare(b.name));
  const visibleTopLevel = filterActive ? topLevel.filter((n) => subtreeHasMatch(n, filter)) : topLevel;
  const matchCount = playlists.filter((p) => playlistMatches(p, filter)).length;
  const trackedCount = playlists.filter((p) => p.actions.length > 0).length;
  const videoCount = playlists.reduce((sum, p) => sum + (p.item_count ?? 0), 0);

  function toggleFolder(path: string) {
    setCollapsedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  function clearFilters() {
    setFilterText("");
    setOnlyTracked(false);
    setSystem(null);
  }

  function collapseAll() {
    const allFolderPaths: string[] = [];
    collectFolderPaths(knownTree, allFolderPaths);
    setCollapsedPaths(new Set(allFolderPaths));
  }

  return (
    <div className="plate">
      <header className="plate-head">
        <p className="eyebrow">
          YouTube · {playlists.length} playlists · {videoCount.toLocaleString()} videos ·{" "}
          {trackedCount} tracked
        </p>

        {/* The legend is the hero: it names the systems the library is
            organised into, teaches the rail colours used below, and doubles
            as the branch filter. */}
        <div className="legend">
          {SYSTEMS.map((s, i) => {
            const count = tallies.get(s.key) ?? 0;
            const active = system === s.key;
            return (
              <button
                key={s.key}
                type="button"
                className={`legend-item ${active ? "is-active" : ""} ${count === 0 ? "is-empty" : ""}`}
                style={{ ["--pig" as string]: s.pigment, ["--i" as string]: i }}
                onClick={() => setSystem(active ? null : s.key)}
                aria-pressed={active}
                disabled={count === 0}
              >
                <span className="legend-name">{s.label}</span>
                <span className="legend-count mono">{count}</span>
              </button>
            );
          })}
        </div>

        <p className="plate-note">
          Names carry the tree: <code>HUMAN-HEARTH-ART-DANCE</code> nests as HUMAN / HEARTH / ART /
          DANCE. Rails down the left mark which system a branch belongs to. A playlist with no flags is
          catalogued but not processed.
        </p>
      </header>

      <div className="toolbar">
        <div className="field">
          <label htmlFor="playlist-filter" className="eyebrow">
            Find
          </label>
          <input
            id="playlist-filter"
            type="search"
            className="field-input"
            placeholder="Filter by name"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
          />
        </div>
        <label className="toggle">
          <input type="checkbox" checked={onlyTracked} onChange={(e) => setOnlyTracked(e.target.checked)} />
          <span>Tracked only</span>
        </label>
        {filterActive && (
          <>
            <span className="toolbar-count mono">
              {matchCount} of {playlists.length}
            </span>
            <button type="button" className="btn btn-quiet" onClick={clearFilters}>
              Clear
            </button>
          </>
        )}
        <div className="toolbar-gap" />
        <button type="button" className="btn" onClick={() => setCollapsedPaths(new Set())}>
          Expand all
        </button>
        <button type="button" className="btn" onClick={collapseAll}>
          Collapse all
        </button>
      </div>

      <div className="tree">
        {visibleTopLevel.length === 0 ? (
          <div className="tree-empty">
            <p>No playlist matches those filters.</p>
            <button type="button" className="btn" onClick={clearFilters}>
              Clear filters
            </button>
          </div>
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
