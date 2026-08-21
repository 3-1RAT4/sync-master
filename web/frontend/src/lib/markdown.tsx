import type { ReactNode } from "react";

// Summaries come back from the LLM as Markdown (see the `summarize` action).
// They were being printed raw, so headings showed as `##` and emphasis as
// `**like this**`. This renders the subset those summaries actually use -
// headings, bullet and numbered lists, bold, italic, inline code - and
// nothing else. It builds React elements rather than HTML strings, so
// there's no way for model output to inject markup.

const INLINE_RE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\n]+\*|_[^_\n]+_)/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  return text.split(INLINE_RE).map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    if (
      (part.startsWith("*") && part.endsWith("*")) ||
      (part.startsWith("_") && part.endsWith("_"))
    ) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "paragraph"; text: string };

const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const BULLET_RE = /^\s*[*+-]\s+(.*)$/;
const ORDERED_RE = /^\s*\d+[.)]\s+(.*)$/;

function toBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const text = paragraph.join(" ");

    // These summaries never use # headings - the model writes its section
    // titles as a line that is nothing but bold text. Read them as the
    // headings they're meant to be, otherwise a summary arrives as one
    // undifferentiated run of paragraphs and lists.
    const standalone = text.match(/^\*\*(.+)\*\*$/);
    if (standalone && !standalone[1].includes("**")) {
      blocks.push({ kind: "heading", level: 1, text: standalone[1] });
    } else {
      blocks.push({ kind: "paragraph", text });
    }
    paragraph = [];
  };

  for (const line of markdown.split("\n")) {
    if (line.trim() === "") {
      flushParagraph();
      continue;
    }

    const heading = line.match(HEADING_RE);
    if (heading) {
      flushParagraph();
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] });
      continue;
    }

    const bullet = line.match(BULLET_RE);
    const ordered = bullet ? null : line.match(ORDERED_RE);
    if (bullet || ordered) {
      flushParagraph();
      const item = (bullet ?? ordered)![1];
      const isOrdered = ordered !== null;
      const last = blocks.at(-1);
      // Wrapped continuation lines belong to the item above them, but a
      // fresh marker always starts a new item.
      if (last?.kind === "list" && last.ordered === isOrdered) last.items.push(item);
      else blocks.push({ kind: "list", ordered: isOrdered, items: [item] });
      continue;
    }

    const last = blocks.at(-1);
    if (last?.kind === "list" && paragraph.length === 0) {
      // Indented wrap of the previous bullet.
      if (line.startsWith("    ") || line.startsWith("\t")) {
        last.items[last.items.length - 1] += ` ${line.trim()}`;
        continue;
      }
    }

    paragraph.push(line.trim());
  }

  flushParagraph();
  return blocks;
}

export function Markdown({ children }: { children: string }) {
  const blocks = toBlocks(children);

  return (
    <div className="md">
      {blocks.map((block, i) => {
        if (block.kind === "heading") {
          // Summary headings sit inside a page that already has an h1/h2, so
          // they start at h3 no matter what level the model wrote.
          const Tag = (["h3", "h4", "h5", "h6"] as const)[Math.min(block.level, 4) - 1] ?? "h4";
          return (
            <Tag key={i} className="md-heading">
              {renderInline(block.text, `h${i}`)}
            </Tag>
          );
        }

        if (block.kind === "list") {
          const Tag = block.ordered ? "ol" : "ul";
          return (
            <Tag key={i} className="md-list">
              {block.items.map((item, j) => (
                <li key={j}>{renderInline(item, `l${i}-${j}`)}</li>
              ))}
            </Tag>
          );
        }

        return (
          <p key={i} className="md-p">
            {renderInline(block.text, `p${i}`)}
          </p>
        );
      })}
    </div>
  );
}
