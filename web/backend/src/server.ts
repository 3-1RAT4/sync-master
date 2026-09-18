import "dotenv/config";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createExpressMiddleware } from "@trpc/server/adapters/express";
import cors from "cors";
import express from "express";
import { appRouter } from "./router.js";
import { videoStreamRouter } from "./videoStream.js";

const app = express();

// No auth. On a laptop this binds to loopback only (the default below); on a
// home server it's bound to the LAN with HOST=0.0.0.0, which means anything on
// that network can browse the catalog, read transcripts and stream the videos.
// See docs/web-ui.md before pointing it anywhere wider than that.
app.use(cors());

app.use("/api/trpc", createExpressMiddleware({ router: appRouter }));

// Binary video streaming can't go through tRPC - separate path, and no body
// parser in front of it.
app.use("/api", videoStreamRouter);

// Serve the built SPA when it exists, so a deployment is one process on one
// port. Mounted after /api so it can never shadow an API route. In local dev
// the Vite server serves the frontend instead and this block is inert.
const here = path.dirname(fileURLToPath(import.meta.url));
const spaDir = path.resolve(here, "../../frontend/dist");
if (existsSync(path.join(spaDir, "index.html"))) {
  app.use(express.static(spaDir));
  // Client-side routes (/playlists/:id, /videos/:id) all resolve to index.html.
  app.get(/^\/(?!api\/).*/, (_req, res) => {
    res.sendFile(path.join(spaDir, "index.html"));
  });
} else {
  console.log(`no built frontend at ${spaDir} - API only (run \`npm run build\` in web/frontend to serve it)`);
}

const host = process.env.HOST ?? "127.0.0.1";
const port = Number(process.env.PORT ?? 4000);
app.listen(port, host, () => {
  console.log(`sync-master web backend listening on http://${host}:${port}`);
});
