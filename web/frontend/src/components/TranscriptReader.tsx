import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { memo } from "react";
import type { MouseEvent as ReactMouseEvent, ReactNode, RefObject } from "react";
import {
  chooseInterval,
  collectSpeakers,
  formatClock,
  formatDuration,
  paragraphize,
  parseTurns,
  speakerLabel,
  youtubeVideoUrlAt,
} from "../lib/transcript";
import type { Turn } from "../lib/transcript";

function countOccurrences(haystack: string, needle: string): number {
  if (!needle) return 0;
  let count = 0;
  let at = haystack.indexOf(needle);
  while (at !== -1) {
    count += 1;
    at = haystack.indexOf(needle, at + needle.length);
  }
  return count;
}

/** Index of the turn being spoken at `seconds`. */
function turnIndexAt(turns: Turn[], seconds: number): number {
  let low = 0;
  let high = turns.length - 1;
  let found = 0;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (turns[mid].start <= seconds) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;

  const lower = text.toLowerCase();
  const parts: ReactNode[] = [];
  let cursor = 0;
  let at = lower.indexOf(query);

  while (at !== -1) {
    if (at > cursor) parts.push(text.slice(cursor, at));
    parts.push(<mark key={at}>{text.slice(at, at + query.length)}</mark>);
    cursor = at + query.length;
    at = lower.indexOf(query, cursor);
  }
  parts.push(text.slice(cursor));

  return <>{parts}</>;
}

// Memoised: with a video playing, the active turn changes as the conversation
// moves, and without this every one of the 264 turns would re-render each time.
const TurnRow = memo(function TurnRow({
  turn,
  pigment,
  length,
  useHours,
  hitCount,
  needle,
  isActive,
  externalId,
  onSeek,
}: {
  turn: Turn;
  pigment: string;
  length: number;
  useHours: boolean;
  hitCount: number;
  needle: string;
  isActive: boolean;
  externalId: string;
  onSeek: ((seconds: number) => void) | null;
}) {
  const stamp = formatClock(turn.start, useHours);

  return (
    <article
      className={`turn ${isActive ? "is-active" : ""}`}
      data-start={turn.start}
      style={{ ["--sp" as string]: pigment }}
    >
      {/* With a stored file the timestamp drives the player; without one it
          stays a link out to YouTube at that moment. */}
      {onSeek ? (
        <button type="button" className="turn-time mono" onClick={() => onSeek(turn.start)} title="Play from here">
          {stamp}
        </button>
      ) : (
        <a
          className="turn-time mono"
          href={youtubeVideoUrlAt(externalId, turn.start)}
          target="_blank"
          rel="noreferrer"
          title="Play the video from here"
        >
          {stamp}
        </a>
      )}
      <div className="turn-body">
        <p className="turn-head">
          <span className="turn-speaker">{speakerLabel(turn.speaker)}</span>
          <span className="turn-length mono">{formatDuration(length)}</span>
          {hitCount > 0 && <span className="turn-hits mono">{hitCount}</span>}
        </p>
        {paragraphize(turn.text).map((paragraph, p) => (
          <p className="turn-text" key={p}>
            <Highlight text={paragraph} query={needle} />
          </p>
        ))}
      </div>
    </article>
  );
});

export default function TranscriptReader({
  text,
  externalId,
  totalSeconds,
  videoRef,
}: {
  text: string;
  externalId: string;
  totalSeconds: number | null;
  /** Null when no file is stored for this video - the reader then falls back
   *  to scroll-driven position and YouTube links. */
  videoRef: RefObject<HTMLVideoElement | null> | null;
}) {
  const [query, setQuery] = useState("");
  const [onlyMatches, setOnlyMatches] = useState(false);
  const [follow, setFollow] = useState(false);
  const [activeStart, setActiveStart] = useState<number | null>(null);

  const turnsRef = useRef<HTMLDivElement>(null);
  const markerRef = useRef<HTMLSpanElement>(null);
  const markerTimeRef = useRef<HTMLSpanElement>(null);
  // Mirrored into a ref so the timeupdate listener can read the current value
  // without being torn down and re-attached every time the toggle flips.
  const followRef = useRef(follow);
  useEffect(() => {
    followRef.current = follow;
  }, [follow]);

  const turns = useMemo(() => parseTurns(text), [text]);
  const total = totalSeconds ?? turns.at(-1)?.start ?? 0;
  const speakers = useMemo(() => collectSpeakers(turns, total), [turns, total]);

  const needle = query.trim().toLowerCase();
  const hits = useMemo(
    () => (needle ? turns.map((t) => countOccurrences(t.text.toLowerCase(), needle)) : []),
    [turns, needle],
  );
  const hitTotal = hits.reduce((sum, n) => sum + n, 0);
  const hitTurns = hits.filter((n) => n > 0).length;

  const scale = total > 0 ? 100 / total : 0;
  const useHours = total >= 3600;

  /**
   * Moves the timeline marker without going through React.
   *
   * `timeupdate` fires about four times a second. Routing that through state
   * would re-render the whole transcript at the same rate, so the marker is
   * written straight to the DOM and only the *active turn* - which changes at
   * most once per turn - is allowed to cause a render.
   */
  const paintMarker = useCallback(
    (seconds: number) => {
      if (markerRef.current) {
        markerRef.current.style.left = `${Math.min(100, seconds * scale)}%`;
      }
      if (markerTimeRef.current) {
        markerTimeRef.current.style.left = `clamp(32px, ${Math.min(100, seconds * scale)}%, calc(100% - 32px))`;
        markerTimeRef.current.textContent = formatClock(seconds, useHours);
      }
    },
    [scale, useHours],
  );

  const seekTo = useCallback(
    (seconds: number) => {
      const video = videoRef?.current;
      if (!video) return;
      // Not a prop mutation: this is the DOM API for moving a video's playhead.
      // oxlint-disable-next-line react/immutability
      video.currentTime = seconds;
      paintMarker(seconds);
      void video.play().catch(() => {
        /* A blocked autoplay still leaves the playhead in the right place. */
      });
    },
    [videoRef, paintMarker],
  );

  // Follow playback: repaint the marker, and promote the spoken turn to active.
  useEffect(() => {
    const video = videoRef?.current;
    if (!video || turns.length === 0) return;

    let lastIndex = -1;
    const onTime = () => {
      const at = video.currentTime;
      paintMarker(at);

      const index = turnIndexAt(turns, at);
      if (index === lastIndex) return;
      lastIndex = index;
      setActiveStart(turns[index].start);

      if (followRef.current) {
        const node = turnsRef.current?.querySelector<HTMLElement>(`[data-start="${turns[index].start}"]`);
        node?.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    };

    video.addEventListener("timeupdate", onTime);
    video.addEventListener("seeked", onTime);
    return () => {
      video.removeEventListener("timeupdate", onTime);
      video.removeEventListener("seeked", onTime);
    };
  }, [videoRef, turns, paintMarker]);

  // With no video, the marker still shows where you're reading. Watching the
  // turns themselves keeps it honest: text length and elapsed time don't run at
  // the same rate, so scroll position can't simply be scaled into a timestamp.
  useEffect(() => {
    if (videoRef?.current) return;
    const root = turnsRef.current;
    if (!root) return;

    const onscreen = new Set<number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const start = Number((entry.target as HTMLElement).dataset.start);
          if (entry.isIntersecting) onscreen.add(start);
          else onscreen.delete(start);
        }
        if (onscreen.size > 0) paintMarker(Math.min(...onscreen));
      },
      // A band just below the sticky bar, so "current" means the turn you're
      // actually reading rather than anything merely on screen.
      { rootMargin: "-150px 0px -65% 0px" },
    );

    root.querySelectorAll<HTMLElement>("[data-start]").forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [videoRef, turns, onlyMatches, needle, paintMarker]);

  // A transcript written before diarization has no [timestamp] SPEAKER heads
  // to work with - show it as plain prose rather than pretending otherwise.
  const structured = turns.length > 1 || (turns[0]?.speaker ?? "") !== "";
  if (!structured) {
    return <div className="prose">{text}</div>;
  }

  const hasVideo = videoRef != null;
  const pigments = new Map(speakers.map((s) => [s.id, s.pigment]));
  const interval = chooseInterval(total);
  const endOf = (i: number) => (i + 1 < turns.length ? turns[i + 1].start : total);

  // When one voice really carries a recording - an interview where the guest
  // holds 84% of the floor - drawing every turn at equal strength flattens the
  // timeline into a barcode. Running that speaker as a baseline band instead
  // lets the interjections read. Only applied when it's actually true: a
  // roughly even two-hander gets equal footing, because calling either of them
  // dominant would invent a difference the recording doesn't have.
  const busiest = speakers.reduce(
    (top, s) => (s.seconds > (top?.seconds ?? 0) ? s : top),
    speakers[0] as (typeof speakers)[number] | undefined,
  );
  const baselineSpeaker = busiest && total > 0 && busiest.seconds / total >= 0.6 ? busiest.id : null;

  function scrollToTurn(start: number) {
    const node = turnsRef.current?.querySelector<HTMLElement>(`[data-start="${start}"]`);
    if (!node) return;
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({
      top: window.scrollY + node.getBoundingClientRect().top - 150,
      behavior: smooth ? "smooth" : "auto",
    });
  }

  /**
   * Click the timeline: seek the player *and* bring the transcript with it.
   *
   * Scrubbing is an explicit "take me there", so it always scrolls - unlike
   * "Follow along", which governs whether the page keeps chasing the audio on
   * its own. Seeking without scrolling leaves you reading minute 38 while the
   * audio plays hour three.
   */
  function scrubTo(event: ReactMouseEvent<HTMLElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const at = ((event.clientX - box.left) / box.width) * total;

    if (hasVideo) seekTo(at);
    scrollToTurn(turns[turnIndexAt(turns, at)].start);
  }

  const rows: ReactNode[] = [];
  let lastMark = 0;

  turns.forEach((turn, i) => {
    if (onlyMatches && (hits[i] ?? 0) === 0) return;

    // An elapsed-time rule every interval, so a four-hour conversation stays
    // navigable without turning a ten-minute one into a ladder. Suppressed
    // while filtering, where consecutive turns aren't consecutive in time.
    if (!onlyMatches) {
      const boundary = Math.floor(turn.start / interval) * interval;
      if (boundary > lastMark) {
        rows.push(
          <div className="time-rule" key={`rule-${boundary}`}>
            <span className="time-rule-label mono">{formatClock(boundary, useHours)}</span>
            <span className="time-rule-line" />
          </div>,
        );
        lastMark = boundary;
      }
    }

    rows.push(
      <TurnRow
        key={`turn-${i}`}
        turn={turn}
        pigment={pigments.get(turn.speaker) ?? "var(--ash-dim)"}
        length={Math.max(0, endOf(i) - turn.start)}
        useHours={useHours}
        hitCount={hits[i] ?? 0}
        needle={needle}
        isActive={activeStart === turn.start}
        externalId={externalId}
        onSeek={hasVideo ? seekTo : null}
      />,
    );
  });

  return (
    <div className="reader">
      <ul className="speakers">
        {speakers.map((s) => (
          <li key={s.id} className="speaker" style={{ ["--sp" as string]: s.pigment }}>
            <span className="speaker-swatch" aria-hidden />
            <span className="speaker-name">{s.label}</span>
            <span className="speaker-stat mono">
              {formatDuration(s.seconds)} · {s.turns} turns
            </span>
          </li>
        ))}
      </ul>

      <div className="reader-bar">
        {/* The whole conversation in one bar: every turn a slice sized by how
            long it ran and coloured by who was talking, with a marker for the
            current moment. Click anywhere to jump there. */}
        <button
          type="button"
          className="ribbon"
          onClick={scrubTo}
          aria-label={`Timeline: ${turns.length} turns across ${formatDuration(total)}. Click to jump to a moment.`}
          title={hasVideo ? "Click to play from here" : "Click to jump to a moment"}
        >
          {turns.map((turn, i) => (
            <span
              key={i}
              className={`ribbon-slice ${turn.speaker === baselineSpeaker ? "is-baseline" : ""}`}
              style={{
                left: `${turn.start * scale}%`,
                width: `${Math.max(0, endOf(i) - turn.start) * scale}%`,
                background: pigments.get(turn.speaker) ?? "var(--ash-dim)",
              }}
            />
          ))}
          {needle !== "" &&
            turns.map((turn, i) =>
              (hits[i] ?? 0) > 0 ? (
                <span key={`hit-${i}`} className="ribbon-hit" style={{ left: `${turn.start * scale}%` }} />
              ) : null,
            )}
          <span ref={markerRef} className="ribbon-now" style={{ left: 0 }} />
          {/* Clamped away from both ends so the label never hangs off the bar. */}
          <span ref={markerTimeRef} className="ribbon-now-time mono" style={{ left: "32px" }}>
            {formatClock(0, useHours)}
          </span>
        </button>

        <div className="reader-controls">
          <input
            type="search"
            className="field-input"
            placeholder="Search this transcript"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <label className="toggle">
            <input
              type="checkbox"
              checked={onlyMatches}
              onChange={(e) => setOnlyMatches(e.target.checked)}
              disabled={needle === ""}
            />
            <span>Only matching turns</span>
          </label>
          {hasVideo && (
            <label className="toggle">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
              <span>Follow along</span>
            </label>
          )}
          {needle !== "" && (
            <span className="toolbar-count mono">
              {hitTotal === 0
                ? "No matches"
                : `${hitTotal} ${hitTotal === 1 ? "match" : "matches"} in ${hitTurns} ${
                    hitTurns === 1 ? "turn" : "turns"
                  }`}
            </span>
          )}
          <div className="toolbar-gap" />
          <span className="toolbar-count mono">
            {turns.length} turns · {formatDuration(total)}
          </span>
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="state">
          Nothing in this transcript matches “{query.trim()}”. Try a shorter phrase.
        </p>
      ) : (
        <div className="turns" ref={turnsRef}>
          {rows}
        </div>
      )}
    </div>
  );
}
