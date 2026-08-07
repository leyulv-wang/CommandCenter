import { db, type JourneyForgeDB } from '@/storage/db';
import type { RecordingRow } from '@/shared/types';

export async function latestCommandCenterRecording(
  database: JourneyForgeDB = db,
): Promise<RecordingRow | null> {
  const rows = await database.recordings.toArray();
  return (
    rows
      .filter((row) => Boolean(row.command_center))
      .sort(
        (left, right) =>
          right.updated_at - left.updated_at ||
          right.created_at - left.created_at,
      )[0] ?? null
  );
}
