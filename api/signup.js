// POST /api/signup  { email, name? }
// Adds an email to the mailing list (idempotent on email).
import { getSql, cors, readBody, notify } from "./_db.js";

export default async function handler(req, res) {
  if (cors(req, res)) return;
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const body = readBody(req);
  const email = String(body.email || "").trim().toLowerCase();
  const name = body.name ? String(body.name).trim().slice(0, 200) : null;

  // Basic email validation
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 320) {
    res.status(400).json({ error: "Invalid email" });
    return;
  }

  const ua = (req.headers["user-agent"] || "").slice(0, 500);
  const ref = (req.headers["referer"] || req.headers["referrer"] || "").slice(0, 500);

  try {
    const sql = getSql();
    const rows = await sql`
      INSERT INTO signups (email, name, user_agent, referrer)
      VALUES (${email}, ${name}, ${ua}, ${ref})
      ON CONFLICT (email) DO NOTHING
      RETURNING id
    `;
    // Only notify for a genuinely new signup (not a repeat)
    if (rows.length > 0) {
      const [{ n }] = await sql`SELECT count(*)::int AS n FROM signups`;
      await notify(
        "New GeBIZ directory signup",
        `${name ? name + " — " : ""}${email}\nTotal subscribers: ${n}`,
        "tada"
      );
    }
    res.status(200).json({ ok: true });
  } catch (e) {
    console.error("signup error", e);
    res.status(500).json({ error: "Server error" });
  }
}
