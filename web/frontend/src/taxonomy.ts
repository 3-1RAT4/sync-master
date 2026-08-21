// The playlist naming convention *is* the taxonomy: a title like
// HUMAN-HEARTH-ART-DANCE nests as HUMAN / HEARTH / ART / DANCE. Mirrors
// src/sync_master/playlist_naming.py's derivation (strip a trailing [...]
// suffix, split the rest on "-") but without requiring a recognized flag
// inside the brackets - every playlist gets a tree position this way, not
// just the ones the processing pipeline tracks.
const SUFFIX_RE = /^(.*)\[[^\]]*\]$/;

export function derivePathSegments(title: string): string[] {
  const match = title.match(SUFFIX_RE);
  const pathPart = match ? match[1] : title;
  return pathPart.split("-").filter(Boolean);
}

export type System = {
  /** Canonical segment name, as it appears in playlist titles. */
  key: string;
  /** Display label for the legend. */
  label: string;
  pigment: string;
};

// The top-level branches of the library are a model of a person - body,
// mind, soul, heart - plus the non-personal trunks (WORLD, AI, PROJECTS).
// Each gets a pigment, and that pigment marks every descendant, so the
// rails down the left of the tree always say which system you're inside.
//
// HUMAN itself is deliberately absent: it's the organism, not a system, and
// it covers ~90% of the library - colouring it would say nothing.
export const SYSTEMS: System[] = [
  { key: "BODY", label: "Body", pigment: "#D9635B" }, // madder
  { key: "MIND", label: "Mind", pigment: "#7B8EEC" }, // indigo
  { key: "SOUL", label: "Soul", pigment: "#E0AC4E" }, // orpiment
  { key: "HEARTH", label: "Hearth", pigment: "#4CB89D" }, // verdigris
  { key: "WORLD", label: "World", pigment: "#C08A60" }, // umber
  { key: "AI", label: "AI", pigment: "#B489E0" }, // tyrian
  { key: "PROJECTS", label: "Projects", pigment: "#98A0B4" }, // steel
];

export const UNCLASSIFIED_PIGMENT = "#5A5466";

// Real titles in the library carry typos that are unambiguously the same
// faculty (HUMAN-SOULT-MEDITATION-MUSIC, HUMAN-HEART-...). Fold them in for
// classification only - the displayed text always stays exactly as it is on
// YouTube, since that's the name the account actually holds.
const ALIASES: Record<string, string> = {
  SOULT: "SOUL",
  HEART: "HEARTH",
};

const BY_KEY = new Map(SYSTEMS.map((s) => [s.key, s]));

/** The first segment that names a system, walking root-to-leaf. */
export function systemForSegments(segments: string[]): System | null {
  for (const segment of segments) {
    const canonical = ALIASES[segment.toUpperCase()] ?? segment.toUpperCase();
    const system = BY_KEY.get(canonical);
    if (system) return system;
  }
  return null;
}

export function systemForTitle(title: string): System | null {
  return systemForSegments(derivePathSegments(title));
}

export function pigmentForTitle(title: string): string {
  return systemForTitle(title)?.pigment ?? UNCLASSIFIED_PIGMENT;
}

export function youtubePlaylistUrl(externalId: string): string {
  return `https://www.youtube.com/playlist?list=${externalId}`;
}

export function youtubeVideoUrl(externalId: string): string {
  return `https://www.youtube.com/watch?v=${externalId}`;
}
