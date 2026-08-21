import "dotenv/config";
import { createExpressMiddleware } from "@trpc/server/adapters/express";
import cors from "cors";
import express from "express";
import { appRouter } from "./router.js";
import { videoStreamRouter } from "./videoStream.js";

const app = express();

// Local dev: the Vite dev server (a different port) proxies to this one, but
// CORS is enabled anyway so the frontend can also be pointed here directly.
// Personal/localhost-only tool - no auth. See docs/web-ui.md before exposing
// this beyond localhost.
app.use(cors());

app.use("/api/trpc", createExpressMiddleware({ router: appRouter }));

// Binary video streaming can't go through tRPC - separate path, and no body
// parser in front of it.
app.use("/api", videoStreamRouter);

const port = Number(process.env.PORT ?? 4000);
app.listen(port, "127.0.0.1", () => {
  console.log(`sync-master web backend listening on http://127.0.0.1:${port}`);
});
