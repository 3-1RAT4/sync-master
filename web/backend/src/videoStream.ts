import { Router } from "express";
import type { Request, Response } from "express";
import pg from "pg";

// Streams the video files sync-master stores as Postgres large objects
// (video_files.content_oid, written by src/sync_master/db/repository.py).
//
// Deliberately not a tRPC procedure: tRPC is JSON-RPC and can't carry binary,
// and a <video> element needs raw bytes with byte-range support. Prisma has no
// large-object API either, so this uses node-postgres directly.
//
// Reading a large object needs an explicit grant on that object - table
// privileges don't cover them. repository.save_video_file issues it on every
// write; see docs/web-ui.md for the backfill of pre-existing objects.

const connectionString = process.env.DATABASE_URL;
if (!connectionString) {
  throw new Error("DATABASE_URL is not set (see web/backend/.env.example)");
}

// Small pool: browsers fire and cancel range requests constantly while
// seeking, so connections must be returned promptly rather than hoarded.
const pool = new pg.Pool({ connectionString, max: 4 });

/** How much to pull per round trip. A 4MB read measured ~8ms, so 1MB is cheap
 *  and keeps a cancelled request from wasting a large read. */
const CHUNK = 1024 * 1024;

type StoredFile = {
  content_oid: number;
  size_bytes: number;
  content_type: string | null;
  filename: string;
};

async function findFile(externalId: string): Promise<StoredFile | null> {
  const { rows } = await pool.query(
    `SELECT vf.content_oid, vf.size_bytes, vf.content_type, vf.filename
       FROM video_files vf
       JOIN videos v ON v.id = vf.video_id
      WHERE v.external_id = $1 AND v.source = 'youtube'`,
    [externalId],
  );
  if (rows.length === 0) return null;
  const row = rows[0];
  return { ...row, size_bytes: Number(row.size_bytes) };
}

/** Parses a single-range `bytes=` header. Returns null when absent, or
 *  "invalid" when present but unsatisfiable, which callers answer with 416. */
function parseRange(header: string | undefined, size: number): { start: number; end: number } | null | "invalid" {
  if (!header) return null;

  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match) return "invalid";

  const [, rawStart, rawEnd] = match;
  if (rawStart === "" && rawEnd === "") return "invalid";

  // "bytes=-500" means the *last* 500 bytes, not "from 0 to 500".
  let start: number;
  let end: number;
  if (rawStart === "") {
    const suffix = Number(rawEnd);
    if (suffix <= 0) return "invalid";
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(rawStart);
    end = rawEnd === "" ? size - 1 : Math.min(Number(rawEnd), size - 1);
  }

  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || start >= size) return "invalid";
  return { start, end };
}

/**
 * Waits for the socket to drain, but gives up if the client disappears first.
 *
 * A plain `once(res, "drain")` deadlocks here: when the browser cancels a range
 * request mid-write - which it does constantly while seeking - "drain" never
 * fires, so the loop parks forever still holding a pool client. Four of those
 * and the whole route stops responding.
 */
function waitForDrain(res: Response): Promise<void> {
  if (res.writableEnded || res.destroyed) return Promise.resolve();

  return new Promise<void>((resolve) => {
    const done = () => {
      res.removeListener("drain", done);
      res.removeListener("close", done);
      res.removeListener("error", done);
      resolve();
    };
    res.on("drain", done);
    res.on("close", done);
    res.on("error", done);
  });
}

async function streamRange(res: Response, aborted: () => boolean, oid: number, start: number, end: number) {
  const client = await pool.connect();
  try {
    let offset = start;
    while (offset <= end && !aborted()) {
      const length = Math.min(CHUNK, end - offset + 1);
      const { rows } = await client.query<{ chunk: Buffer }>("SELECT lo_get($1, $2, $3) AS chunk", [
        oid,
        offset,
        length,
      ]);

      const chunk = rows[0]?.chunk;
      if (!chunk || chunk.length === 0) break; // object shorter than size_bytes claims
      offset += chunk.length;

      if (!res.write(chunk)) {
        // Let the socket drain instead of buffering a 491MB file in memory.
        await waitForDrain(res);
        if (aborted()) break;
      }
    }
  } finally {
    // Always, including on abort - otherwise every seek leaks a connection.
    client.release();
  }
}

export const videoStreamRouter: Router = Router();

videoStreamRouter.get("/videos/:externalId/stream", async (req: Request, res: Response) => {
  // Express 5 types params as string | string[] to allow wildcards.
  const externalId = String(req.params.externalId);

  let file: StoredFile | null;
  try {
    file = await findFile(externalId);
  } catch (error) {
    console.error(`[stream] lookup failed for ${externalId}:`, error);
    res.status(500).json({ error: "Could not look up this video." });
    return;
  }

  if (!file) {
    res.status(404).json({ error: "No downloaded file is stored for this video." });
    return;
  }

  const size = file.size_bytes;
  const range = parseRange(req.headers.range, size);

  if (range === "invalid") {
    res.status(416).setHeader("Content-Range", `bytes */${size}`);
    res.end();
    return;
  }

  const start = range ? range.start : 0;
  const end = range ? range.end : size - 1;

  res.status(range ? 206 : 200);
  res.setHeader("Content-Type", file.content_type ?? "video/mp4");
  res.setHeader("Content-Length", String(end - start + 1));
  res.setHeader("Accept-Ranges", "bytes");
  // Same bytes forever unless the video is re-downloaded, and it never leaves
  // this machine - so let the browser keep it while seeking around.
  res.setHeader("Cache-Control", "private, max-age=3600");
  if (range) res.setHeader("Content-Range", `bytes ${start}-${end}/${size}`);

  // Players probe with HEAD before requesting bytes.
  if (req.method === "HEAD") {
    res.end();
    return;
  }

  let clientGone = false;
  req.on("close", () => {
    clientGone = true;
  });

  try {
    await streamRange(res, () => clientGone || res.writableEnded, file.content_oid, start, end);
    res.end();
  } catch (error) {
    console.error(`[stream] failed while sending ${externalId}:`, error);
    // Headers are already out by this point, so there's no status left to set.
    res.destroy();
  }
});
