// POST /api/track  { type: 'visit' | 'download', email?, detail? }
// Logs a visit or a download event (with what was downloaded).
import { getSql, cors, readBody, notify } from "./_db.js";

export default async function handler(req, res) {
  if (cors(req, res)) return;
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const body = readBody(req);
  const type = String(body.type || "").trim();
  if (type !== "visit" && type !== "download") {
    res.status(400).json({ error: "Invalid type" });
    return;
  }

  const email = body.email ? String(body.email).trim().toLowerCase().slice(0, 320) : null;
  const detail = body.detail && typeof body.detail === "object" ? body.detail : null;
  const ua = (req.headers["user-agent"] || "").slice(0, 500);
  const ref = (req.headers["referer"] || req.headers["referrer"] || "").slice(0, 500);

  try {
    const sql = getSql();
    await sql`
      INSERT INTO events (type, email, detail, user_agent, referrer)
      VALUES (${type}, ${email}, ${detail ? JSON.stringify(detail) : null}, ${ua}, ${ref})
    `;
    // Notify on downloads (visits are too frequent to push)
    if (type === "download") {
      const epu = detail && Array.isArray(detail.epu) && detail.epu.length ? detail.epu.join(", ") : "all supply heads";
      const rowsN = detail && detail.rows != null ? detail.rows : "?";
      await notify(
        "GeBIZ CSV downloaded",
        `${email || "anonymous"}\n${rowsN} rows · ${epu}`,
        "inbox_tray"
      );
    }
    res.status(200).json({ ok: true });
  } catch (e) {
    console.error("track error", e);
    res.status(500).json({ error: "Server error" });
  }
}
