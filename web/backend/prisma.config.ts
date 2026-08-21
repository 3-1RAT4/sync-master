import "dotenv/config";
import { defineConfig, env } from "prisma/config";

// Connection info for `prisma db pull` (introspection) only - the schema is
// owned by sync-master's Alembic migrations (../../alembic/versions/), never
// by Prisma Migrate. See docs/web-ui.md.
export default defineConfig({
  schema: "prisma/schema.prisma",
  datasource: {
    url: env("DATABASE_URL"),
  },
});
