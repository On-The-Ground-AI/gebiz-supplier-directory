// GET /api/digest?token=XXX
// Hourly visit digest — pushes a Telegram summary of visits since the last digest.
// Triggered by the GitHub Actions cron (.github/workflows/hourly-digest.yml).
// Counts are exact regardless of when the cron actually fires, because we track
// the last-digest timestamp in the `meta` table.
import { getSql, cors, notify } from "./_db.js";

export default async function handler(req, res) {
  if (cors(req, res)) return;

  const token = req.query.token || "";
  const expected = process.env.STATS_TOKEN || "";
  if (!expected || token !== expected) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }

  try {
    const sql = getSql();

    // Initialise the marker to "now" on first ever run (so we don't dump history).
    await sql`
      INSERT INTO meta (key, value) VALUES ('last_visit_digest_at', now()::text)
      ON CONFLICT (key) DO NOTHING
    `;

    const [{ value: last }] = await sql`SELECT value FROM meta WHERE key='last_visit_digest_at'`;

    const [{ n }] = await sql`
      SELECT count(*)::int AS n FROM events
      WHERE type='visit' AND created_at > ${last}::timestamptz
    `;
    const [{ total }] = await sql`SELECT count(*)::int AS total FROM events WHERE type='visit'`;

    // Advance the marker to now.
    await sql`UPDATE meta SET value = now()::text WHERE key='last_visit_digest_at'`;

    // Only push when there were visits — keeps quiet hours silent.
    if (n > 0) {
      await notify(
        "Hourly visit digest",
        `👁 ${n} visit${n === 1 ? "" : "s"} in the last hour\nTotal visits: ${total}`,
        "eyes"
      );
    }

    res.setHeader("Cache-Control", "no-store");
    res.status(200).json({ ok: true, visits: n, totalVisits: total, since: last, pushed: n > 0 });
  } catch (e) {
    console.error("digest error", e);
    res.status(500).json({ error: "Server error" });
  }
}
