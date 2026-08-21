import { createTRPCReact } from "@trpc/react-query";
// Type-only import from the backend - no runtime coupling, just gives this
// SPA full autocomplete/type-checking on every API call. See
// web/backend/src/router.ts.
import type { AppRouter } from "../../backend/src/router";

export const trpc = createTRPCReact<AppRouter>();
