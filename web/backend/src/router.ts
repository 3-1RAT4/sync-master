import { z } from "zod";
import { prisma } from "./db.js";
import { publicProcedure, router } from "./trpc.js";

// sync_state.data is the processing-pipeline's JSONB document (owned by
// sync-master's Python side, see ../../src/sync_master/db/repository.py) -
// {"videos": {external_id: {playlist_id, title, published_at, actions: {...}}}}.
// It's a separate concern from the catalog tables below: every video is
// cataloged, but only videos in flagged/tracked playlists ever get an entry
// here.
type SyncStateActions = Record<string, { status: string; updated_at?: string; error?: string }>;
type SyncStateDoc = {
  videos: Record<string, { actions?: SyncStateActions }>;
};

async function getProcessingStatus(externalId: string): Promise<SyncStateActions | null> {
  const row = await prisma.sync_state.findUnique({ where: { id: 1 } });
  const doc = row?.data as SyncStateDoc | undefined;
  return doc?.videos?.[externalId]?.actions ?? null;
}

const playlistsRouter = router({
  list: publicProcedure.query(async () => {
    return prisma.playlists.findMany({
      select: {
        id: true,
        source: true,
        external_id: true,
        title: true,
        description: true,
        thumbnail_url: true,
        item_count: true,
        folder_path: true,
        leaf_name: true,
        actions: true,
      },
      orderBy: { title: "asc" },
    });
  }),

  videos: publicProcedure.input(z.object({ playlistId: z.coerce.bigint() })).query(async ({ input }) => {
    return prisma.videos.findMany({
      where: { playlist_id: input.playlistId },
      select: {
        id: true,
        external_id: true,
        title: true,
        description: true,
        thumbnail_url: true,
        published_at: true,
      },
      orderBy: { published_at: "desc" },
    });
  }),
});

const videosRouter = router({
  get: publicProcedure.input(z.object({ id: z.coerce.bigint() })).query(async ({ input }) => {
    const video = await prisma.videos.findUnique({
      where: { id: input.id },
      include: {
        playlists: { select: { id: true, title: true, folder_path: true, leaf_name: true } },
        transcripts: { select: { id: true, source: true, text: true, created_at: true } },
        summaries: { select: { content: true, llm_provider: true, llm_model: true, created_at: true } },
        spotify_syncs: { select: { spotify_track_id: true, spotify_playlist_id: true, matched_via: true } },
        // Presence is what the UI needs - whether to render a player at all.
        // The bytes come from /api/videos/:externalId/stream (videoStream.ts).
        video_files: { select: { size_bytes: true, content_type: true, filename: true } },
      },
    });
    if (!video) return null;

    const actions = await getProcessingStatus(video.external_id);

    // transcripts.text carries the words but only each turn's *start* time
    // (see src/sync_master/tools/diarize.py:format_as_conversation). The
    // diarization segments carry the end times, so the last turn's length -
    // and therefore the true length of the recording - is only knowable from
    // here. The reader needs it to scale its timeline.
    let transcript_seconds: number | null = null;
    if (video.transcripts) {
      const span = await prisma.transcript_segments.aggregate({
        where: { transcript_id: video.transcripts.id },
        _max: { end_seconds: true },
      });
      // Prisma hands back a Decimal, which superjson can't put on the wire.
      transcript_seconds = span._max.end_seconds === null ? null : Number(span._max.end_seconds);
    }

    return { ...video, actions, transcript_seconds };
  }),
});

export const appRouter = router({
  playlists: playlistsRouter,
  videos: videosRouter,
});

export type AppRouter = typeof appRouter;
