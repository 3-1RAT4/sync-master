import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "./generated/prisma/client.js";

// Connects as the read-only sync_master_web Postgres role (see docs/web-ui.md
// for how it's provisioned) - this app never writes to the database.
// sync-master's own Alembic migrations (../../alembic/versions/) remain the
// sole schema authority; this schema.prisma is regenerated via `npm run
// db:pull` whenever that schema changes, never the other way around.
const connectionString = process.env.DATABASE_URL;
if (!connectionString) {
  throw new Error("DATABASE_URL is not set (see web/backend/.env.example)");
}

const adapter = new PrismaPg({ connectionString });

export const prisma = new PrismaClient({ adapter });
