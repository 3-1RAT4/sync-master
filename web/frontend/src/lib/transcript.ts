// Parses the conversation format written by
// src/sync_master/tools/diarize.py:format_as_conversation -
//
//   [HH:MM:SS] SPEAKER_02: words words words
//   <blank line>
//   [HH:MM:SS] SPEAKER_00: more words
//
// Consecutive segments from one speaker are already merged into a single
// turn on the Python side, so a turn here is a real conversational turn.
// Only the *start* of each turn is recorded; a turn's end is the next turn's
// start, and the final turn's end comes from the diarization segments
// (videos.get returns it as transcript_seconds).

export type Turn = {
  start: number;
  /** Raw diarization label, e.g. SPEAKER_02 or UNKNOWN. */
  speaker: string;
  text: string;
};

const TURN_RE = /^\[(\d{1,2}):(\d{2}):(\d{2})\]\s+([^:\n]+):\s*([\s\S]*)$/;

export function parseTurns(text: string): Turn[] {
  const turns: Turn[] = [];

  for (const block of text.split(/\n{2,}/)) {
    const trimmed = block.trim();
    if (!trimmed) continue;

    const match = trimmed.match(TURN_RE);
    if (!match) {
      // A transcript written before diarization existed, or a stray block.
      // Keep the words with the previous turn rather than dropping them.
      const previous = turns.at(-1);
      if (previous) previous.text += `\n\n${trimmed}`;
      else turns.push({ start: 0, speaker: "", text: trimmed });
      continue;
    }

    turns.push({
      start: Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]),
      speaker: match[4],
      text: match[5],
    });
  }

  return turns;
}

/**
 * Breaks a long turn into paragraphs at sentence ends.
 *
 * Some recordings have one person holding the floor for minutes at a time -
 * a 70-minute interview can come back as 24 turns, so a single turn can run
 * past 3,000 characters. This is a *typographic* break only: no timestamp is
 * implied for the paragraphs, because none exists. The turn's own timings are
 * the only ones the transcript actually records, and inventing finer ones by
 * interpolating would be a guess dressed up as data.
 */
export function paragraphize(text: string, target = 700): string[] {
  if (text.length <= target * 1.4) return [text];

  const sentences = text.split(/(?<=[.!?])\s+(?=["“'([]?[A-Z0-9])/);
  const paragraphs: string[] = [];
  let current = "";

  for (const sentence of sentences) {
    current = current ? `${current} ${sentence}` : sentence;
    if (current.length >= target) {
      paragraphs.push(current);
      current = "";
    }
  }
  if (current) {
    // Don't leave a stub hanging on its own.
    if (paragraphs.length > 0 && current.length < 120) paragraphs[paragraphs.length - 1] += ` ${current}`;
    else paragraphs.push(current);
  }

  return paragraphs.length > 0 ? paragraphs : [text];
}

/** Seconds -> 4:31 under an hour, 1:04:31 over it. */
export function formatClock(seconds: number, forceHours = false): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 || forceHours ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** A spoken length, said the way a person would say it. */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  if (total < 60) return `${total} sec`;
  const minutes = Math.round(total / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} hr` : `${hours} hr ${rest} min`;
}

/**
 * Spacing for the elapsed-time rules threaded through the reader. Picked so a
 * transcript of any length gets roughly 8-20 of them: frequent enough to stay
 * oriented in a four-hour conversation, rare enough not to shred a ten-minute
 * one.
 */
export function chooseInterval(totalSeconds: number): number {
  for (const step of [30, 60, 120, 300, 600, 900, 1800]) {
    if (totalSeconds / step <= 20) return step;
  }
  return 3600;
}

// Speaker colours come from the same pigment family the catalog uses for its
// systems, but inside the reader colour means *who is talking* - which is why
// the legend sits directly above the transcript, declaring the mapping where
// it's read rather than leaving it to be inferred.
const SPEAKER_PIGMENTS = [
  "#7B8EEC", // indigo
  "#E0AC4E", // orpiment
  "#4CB89D", // verdigris
  "#D9635B", // madder
  "#B489E0", // tyrian
  "#C08A60", // umber
  "#98A0B4", // steel
];

export type SpeakerInfo = {
  id: string;
  label: string;
  pigment: string;
  /** Total seconds this speaker holds the floor. */
  seconds: number;
  turns: number;
};

export function speakerLabel(id: string): string {
  const match = id.match(/^SPEAKER_(\d+)$/);
  if (match) return `Speaker ${match[1]}`;
  if (!id || id === "UNKNOWN") return "Unattributed";
  return id;
}

/**
 * Speakers in the order they first talk, with how long each holds the floor.
 * First-appearance order (rather than label order) means the person who opens
 * the conversation is always the first colour, which is what a reader expects.
 */
export function collectSpeakers(turns: Turn[], totalSeconds: number): SpeakerInfo[] {
  const order: string[] = [];
  const seconds = new Map<string, number>();
  const counts = new Map<string, number>();

  turns.forEach((turn, i) => {
    if (!order.includes(turn.speaker)) order.push(turn.speaker);
    const end = i + 1 < turns.length ? turns[i + 1].start : totalSeconds;
    seconds.set(turn.speaker, (seconds.get(turn.speaker) ?? 0) + Math.max(0, end - turn.start));
    counts.set(turn.speaker, (counts.get(turn.speaker) ?? 0) + 1);
  });

  return order.map((id, i) => ({
    id,
    label: speakerLabel(id),
    pigment: SPEAKER_PIGMENTS[i % SPEAKER_PIGMENTS.length],
    seconds: seconds.get(id) ?? 0,
    turns: counts.get(id) ?? 0,
  }));
}

/** Deep link into the source video at an exact second. */
export function youtubeVideoUrlAt(externalId: string, seconds: number): string {
  return `https://www.youtube.com/watch?v=${externalId}&t=${Math.floor(seconds)}s`;
}
