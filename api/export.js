// GET /api/export?token=XXX[&type=signups|downloads]
// Token-protected CSV export of the mailing list or download log.
import { getSql, cors } from "./_db.js";

function csvCell(v) {
  const s = String(v ?? "").replace(/"/g, '""');
  return /[",\n]/.test(s) ? `"${s}"` : s;
}

export default async function handler(req, res) {
  if (cors(req, res)) return;

  const token = req.query.token || "";
  const expected = process.env.STATS_TOKEN || "";
  if (!expected || token !== expected) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }

  const type = req.query.type === "downloads" ? "downloads" : "signups";

  try {
    const sql = getSql();
    let header, rows;

    if (type === "signups") {
      const data = await sql`SELECT email, name, created_at FROM signups ORDER BY created_at DESC`;
      header = ["email", "name", "signed_up_at"];
      rows = data.map((r) => [r.email, r.name || "", r.created_at]);
    } else {
      const data = await sql`SELECT email, detail, created_at FROM events WHERE type='download' ORDER BY created_at DESC`;
      header = ["email", "supply_heads", "grades", "years", "search", "activity", "rows", "downloaded_at"];
      rows = data.map((r) => {
        const d = r.detail || {};
        return [
          r.email || "",
          (d.epu || []).join("; "),
          (d.grades || []).join("; "),
          (d.years || []).join("; "),
          d.search || "",
          d.activity || "",
          d.rows ?? "",
          r.created_at,
        ];
      });
    }

    const csv = ["﻿" + header.join(","), ...rows.map((r) => r.map(csvCell).join(","))].join("\n");
    res.setHeader("Content-Type", "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="gebiz-${type}.csv"`);
    res.setHeader("Cache-Control", "no-store");
    res.status(200).send(csv);
  } catch (e) {
    console.error("export error", e);
    res.status(500).json({ error: "Server error" });
  }
}
