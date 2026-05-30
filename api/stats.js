// GET /api/stats?token=XXX
// Private analytics summary. Protected by STATS_TOKEN env var.
import { getSql, cors } from "./_db.js";

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

    const [signupTotal] = await sql`SELECT count(*)::int AS n FROM signups`;
    const [visitTotal] = await sql`SELECT count(*)::int AS n FROM events WHERE type='visit'`;
    const [downloadTotal] = await sql`SELECT count(*)::int AS n FROM events WHERE type='download'`;

    const recentSignups = await sql`
      SELECT email, name, created_at FROM signups
      ORDER BY created_at DESC LIMIT 50
    `;

    const recentDownloads = await sql`
      SELECT email, detail, created_at FROM events
      WHERE type='download'
      ORDER BY created_at DESC LIMIT 50
    `;

    // Most-downloaded supply heads (unnest the epu array from detail)
    const topEpu = await sql`
      SELECT code, count(*)::int AS n FROM (
        SELECT jsonb_array_elements_text(detail->'epu') AS code
        FROM events WHERE type='download' AND detail ? 'epu'
      ) t
      GROUP BY code ORDER BY n DESC LIMIT 25
    `;

    const visitsByDay = await sql`
      SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day, count(*)::int AS n
      FROM events WHERE type='visit'
      GROUP BY day ORDER BY day DESC LIMIT 30
    `;

    res.setHeader("Cache-Control", "no-store");
    res.status(200).json({
      totals: {
        signups: signupTotal.n,
        visits: visitTotal.n,
        downloads: downloadTotal.n,
      },
      recentSignups,
      recentDownloads,
      topEpu,
      visitsByDay,
    });
  } catch (e) {
    console.error("stats error", e);
    res.status(500).json({ error: "Server error" });
  }
}
