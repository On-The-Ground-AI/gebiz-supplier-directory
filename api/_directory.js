// Server-side view of suppliers.json for the outreach CRM: search the directory
// and turn picked suppliers into CRM rows. Loaded once per warm function.
//
// suppliers.json is bundled into /api/crm via vercel.json `includeFiles`, and
// vercel.json also redirects the public /suppliers.json path so the raw file
// cannot bypass the email-gated download on the public site.
import { readFileSync } from "node:fs";
import { join } from "node:path";

let _rows = null;
let _facets = null;

export function gradeRank(financialGrade) {
  const m = /^S(\d+)/.exec(financialGrade || "");
  return m ? Number(m[1]) : 0;
}

export function normName(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function summarise(r) {
  const heads = [...new Set((r.supply_heads || []).map((h) => h.name))];
  const grade = Math.max(0, ...(r.supply_heads || []).map((h) => gradeRank(h.financial_grade)));
  return {
    uen: r.uen,
    name: r.name,
    phone: r.phone || "",
    email: r.email || "",
    url: r.company_url || "",
    heads,
    grade,
    summary: r.description_short || "",
  };
}

export function loadDirectory() {
  if (!_rows) {
    const raw = JSON.parse(readFileSync(join(process.cwd(), "suppliers.json"), "utf8"));
    _rows = raw.map(summarise);
  }
  return _rows;
}

export function facets(rows = loadDirectory()) {
  if (!_facets) {
    const counts = new Map();
    for (const r of rows) for (const h of r.heads) counts.set(h, (counts.get(h) || 0) + 1);
    _facets = {
      heads: [...counts].sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count })),
      total: rows.length,
    };
  }
  return _facets;
}

/**
 * Filter the directory. `inCrm` is a predicate so the caller decides what
 * "already on the list" means (UEN or normalised company name).
 */
export function searchDirectory(rows, { q = "", head = "", maxGrade = 0, hideInCrm = true, limit = 100, offset = 0 }, inCrm) {
  const needle = String(q).trim().toLowerCase();
  const matches = [];
  for (const r of rows) {
    if (head && !r.heads.includes(head)) continue;
    if (maxGrade && r.grade > maxGrade) continue;
    if (needle && !(r.name.toLowerCase().includes(needle) || r.uen.toLowerCase().includes(needle) || r.summary.toLowerCase().includes(needle))) continue;
    const onList = inCrm(r);
    if (hideInCrm && onList) continue;
    matches.push({ ...r, in_crm: onList });
  }
  if (limit === Infinity) return { total: matches.length, results: matches };
  const lim = Math.min(Math.max(Number(limit) || 100, 1), 200);
  const off = Math.max(Number(offset) || 0, 0);
  return { total: matches.length, results: matches.slice(off, off + lim) };
}

/** What the CRM's "what they do" column gets: the supply heads, trimmed. */
export function whatTheyDo(r) {
  const s = r.heads.join("; ");
  return s.length > 300 ? s.slice(0, 297) + "..." : s;
}
