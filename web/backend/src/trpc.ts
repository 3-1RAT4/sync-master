import { initTRPC } from "@trpc/server";
import superjson from "superjson";

// superjson lets BigInt (every id/count column here - Postgres BIGSERIAL) and
// Date (every timestamptz column) cross the wire correctly; plain JSON can't
// serialize BigInt at all. The frontend's tRPC client must use the same
// transformer - see web/frontend/src/trpc.ts.
const t = initTRPC.create({ transformer: superjson });

export const router = t.router;
export const publicProcedure = t.procedure;
