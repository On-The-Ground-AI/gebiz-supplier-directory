// Shared Neon client + CORS helpers for the GeBIZ directory API.
import { neon } from "@neondatabase/serverless";

let _sql = null;
export function getSql() {
  if (!_sql) {
    const url = process.env.DATABASE_URL;
    if (!url) throw new Error("DATABASE_URL not set");
    _sql = neon(url);
  }
  return _sql;
}

// Permissive CORS so the page works from the Vercel domain, GitHub Pages,
// or a local file during testing. Returns true if it handled an OPTIONS preflight.
export function cors(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Access-Control-Max-Age", "86400");
  if (req.method === "OPTIONS") {
    res.status(204).end();
    return true;
  }
  return false;
}

// Fire-and-forget push notification. Supports:
//   - ntfy.sh  (env NOTIFY_NTFY_TOPIC) — zero-setup push, subscribe at ntfy.sh/<topic>
//   - Slack/Discord incoming webhook (env NOTIFY_WEBHOOK)
// Never throws; failures are swallowed so they can't break the main request.
export async function notify(title, message, tag = "bell") {
  const tasks = [];
  const topic = process.env.NOTIFY_NTFY_TOPIC;
  if (topic) {
    tasks.push(
      fetch(`https://ntfy.sh/${topic}`, {
        method: "POST",
        headers: { Title: title, Tags: tag },
        body: message,
      }).catch(() => {})
    );
  }
  const hook = process.env.NOTIFY_WEBHOOK;
  if (hook) {
    // Slack & Discord both accept a JSON body with a "text"/"content" field.
    const payload = hook.includes("discord")
      ? { content: `**${title}**\n${message}` }
      : { text: `*${title}*\n${message}` };
    tasks.push(
      fetch(hook, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {})
    );
  }
  try {
    await Promise.all(tasks);
  } catch {}
}

export function readBody(req) {
  // Vercel parses JSON bodies automatically when Content-Type is application/json,
  // but guard for string bodies just in case.
  if (req.body && typeof req.body === "object") return req.body;
  try {
    return JSON.parse(req.body || "{}");
  } catch {
    return {};
  }
}
