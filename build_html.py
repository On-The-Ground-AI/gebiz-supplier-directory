"""
Rebuild gebiz_suppliers.html with:
- Main search (name, UEN, activity/description)
- Multi-select EPU filter
- Multi-select Grade filter (S2-S10)
- Expiry year toggle buttons (2026-2029)
- Activity text search (description/AI summary only)
- CSV export of current filtered view
"""
import json, re
from collections import Counter

JSON_PATH = "/Users/seehaojun/Desktop/OTG/BD/suppliers.json"
HTML_PATH = "/Users/seehaojun/Desktop/OTG/BD/gebiz_suppliers.html"

# API base for tracking + signup. Empty string = same origin (relative /api),
# which is correct when served from Vercel. Set to an absolute URL (e.g.
# "https://your-app.vercel.app") if hosting the HTML elsewhere (GitHub Pages).
import os
API_BASE = os.environ.get("GEBIZ_API_BASE", "")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def extract_grade(grade_str):
    """Pull 'S8' from 'S8 $10,000,000 (EPU S8)'"""
    m = re.match(r"(S\d+)", grade_str or "")
    return m.group(1) if m else ""


def extract_year(date_str):
    """Pull '2028' from '04 Mar 2028'"""
    parts = (date_str or "").split()
    return parts[-1] if parts and parts[-1].isdigit() else ""


def build():
    with open(JSON_PATH, encoding="utf-8") as f:
        suppliers = json.load(f)

    suppliers = [s for s in suppliers if s.get("name")]
    total = len(suppliers)

    # Pre-compute per-supplier grade and year sets
    all_grades = set()
    all_years  = set()
    for s in suppliers:
        grades, years = set(), set()
        for sh in s.get("supply_heads", []):
            g = extract_grade(sh.get("financial_grade", ""))
            y = extract_year(sh.get("expiry_date", ""))
            if g: grades.add(g); all_grades.add(g)
            if y: years.add(y);  all_years.add(y)
        s["_grades"] = sorted(grades)
        s["_years"]  = sorted(years)

    grades_sorted = sorted(all_grades, key=lambda x: int(x[1:]) if x[1:].isdigit() else 99)
    years_sorted  = sorted(all_years)

    # EPU supply head labels
    sh_labels = {}
    for s in suppliers:
        for sh in s.get("supply_heads", []):
            c = sh.get("code")
            if c and c not in sh_labels:
                sh_labels[c] = sh.get("full") or sh.get("name") or c
    all_sh_codes = sorted(sh_labels)

    # Build EPU checkbox list
    epu_items_html = ""
    for code in all_sh_codes:
        full = sh_labels[code]
        name_part = full.split(" - ", 1)[-1] if " - " in full else full
        epu_items_html += (
            f'<label class="cb-item" title="{esc(full)}">'
            f'<input type="checkbox" class="epu-cb" value="{esc(code)}"> '
            f'<code>{esc(code)}</code> <span class="cb-text">{esc(name_part)}</span>'
            f'</label>\n'
        )

    # Grade checkboxes
    grade_items_html = ""
    for g in grades_sorted:
        grade_items_html += (
            f'<label class="cb-item">'
            f'<input type="checkbox" class="grade-cb" value="{esc(g)}"> <span class="cb-text">{esc(g)}</span>'
            f'</label>\n'
        )

    # Year buttons HTML
    year_btns_html = ""
    for y in years_sorted:
        year_btns_html += f'<button class="yr-btn" data-yr="{esc(y)}" onclick="toggleYear(this)">{esc(y)}</button>\n'

    # Compact data for CSV export
    csv_data = []
    for s in suppliers:
        sh_codes = [sh.get("code","") for sh in s.get("supply_heads",[]) if sh.get("code")]
        sh_full  = [sh.get("full","")  for sh in s.get("supply_heads",[]) if sh.get("full")]
        addr_parts = [s.get("address_1"), s.get("address_2"), s.get("address_3")]
        address = ", ".join(p for p in addr_parts if p)
        csv_data.append({
            "uen":               s.get("uen",""),
            "name":              s.get("name",""),
            "summary":           s.get("description_short",""),
            "description":       (s.get("description") or "").replace("\n"," ").replace("\r",""),
            "address":           address,
            "postal_code":       s.get("postal_code",""),
            "city":              s.get("city",""),
            "phone":             s.get("phone",""),
            "fax":               s.get("fax",""),
            "email":             s.get("email",""),
            "website":           s.get("company_url",""),
            "supply_heads":      "; ".join(sh_codes),
            "supply_heads_full": "; ".join(sh_full),
            "grades":            "; ".join(s["_grades"]),
            "expiry_years":      "; ".join(s["_years"]),
            "sh_codes_arr":      sh_codes,
            "grades_arr":        s["_grades"],
            "years_arr":         s["_years"],
        })
    csv_data_js = json.dumps(csv_data, ensure_ascii=False)
    api_base_js = json.dumps(API_BASE)

    # Build cards HTML
    cards_html = ""
    for s in suppliers:
        sh_codes = [sh.get("code","") for sh in s.get("supply_heads",[]) if sh.get("code")]
        sh_attr  = " ".join(sh_codes)
        grade_attr = " ".join(s["_grades"])
        year_attr  = " ".join(s["_years"])

        sh_tags = ""
        for sh in s.get("supply_heads", []):
            status_cls = "tag-approved" if sh.get("status") == "APPROVED" else "tag-other"
            sh_tags += (
                f'<span class="sh-tag {status_cls}" '
                f'title="{esc(sh.get("financial_grade",""))} | Exp: {esc(sh.get("expiry_date",""))} | {esc(sh.get("status",""))}">'
                f'{esc(sh.get("code","") or sh.get("name",""))}</span>'
            )

        ai_summary = esc(s.get("description_short",""))
        desc_full  = esc(s.get("description",""))
        # Combined description text for search (summary + full desc, lower-cased, max 500c)
        desc_search = ((s.get("description_short") or "") + " " + (s.get("description") or "")).lower()[:500]

        addr_parts = [s.get("address_1"), s.get("address_2"), s.get("address_3")]
        address_str = ", ".join(p for p in addr_parts if p)
        if s.get("postal_code"):
            address_str += f" {s['postal_code']}"

        contacts = ""
        if s.get("phone"):
            contacts += f'<span class="ci">📞 {esc(s["phone"])}</span>'
        if s.get("fax"):
            contacts += f'<span class="ci">🖷 {esc(s["fax"])}</span>'
        if s.get("email"):
            contacts += f'<span class="ci"><a href="mailto:{esc(s["email"])}">{esc(s["email"])}</a></span>'
        if s.get("company_url"):
            url_d = s["company_url"]
            url_h = url_d if url_d.startswith("http") else "https://" + url_d
            contacts += f'<span class="ci"><a href="{esc(url_h)}" target="_blank" rel="noopener">{esc(url_d)}</a></span>'

        sh_table = ""
        if s.get("supply_heads"):
            sh_table = '<table class="sh-table"><thead><tr><th>Supply Head</th><th>Grade</th><th>Expiry</th><th>Status</th></tr></thead><tbody>'
            for sh in s.get("supply_heads",[]):
                sc = "status-ok" if sh.get("status") == "APPROVED" else "status-other"
                sh_table += (
                    f'<tr><td>{esc(sh.get("full") or sh.get("name",""))}</td>'
                    f'<td>{esc(sh.get("financial_grade",""))}</td>'
                    f'<td>{esc(sh.get("expiry_date",""))}</td>'
                    f'<td class="{sc}">{esc(sh.get("status",""))}</td></tr>'
                )
            sh_table += "</tbody></table>"

        addr_detail = ""
        if address_str:
            addr_detail += f'<div class="dr"><span class="dl">Address</span><span>{esc(address_str)}</span></div>'
        if s.get("city"):
            addr_detail += f'<div class="dr"><span class="dl">City</span><span>{esc(s["city"])}</span></div>'

        desc_detail = ""
        if desc_full:
            desc_detail = f'<div class="dr desc-detail"><span class="dl">About</span><span>{desc_full}</span></div>'

        summary_p = f'<p class="summary">{ai_summary}</p>' if ai_summary else ""
        cards_html += (
            f'<div class="card"'
            f' data-sh="{esc(sh_attr)}"'
            f' data-grade="{esc(grade_attr)}"'
            f' data-yr="{esc(year_attr)}"'
            f' data-name="{esc(s.get("name","").lower())}"'
            f' data-uen="{esc(s.get("uen","").lower())}"'
            f' data-desc="{esc(desc_search)}">\n'
            f'  <div class="card-header">\n'
            f'    <div class="card-title-row">\n'
            f'      <span class="uen">{esc(s.get("uen",""))}</span>\n'
            f'      <h3>{esc(s.get("name",""))}</h3>\n'
            f'    </div>\n'
            f'    <div class="sh-tags">{sh_tags}</div>\n'
            f'  </div>\n'
            f'  <div class="card-body">\n'
            f'    {summary_p}\n'
            f'    <div class="contacts">{contacts}</div>\n'
            f'  </div>\n'
            f'  <div class="expanded" style="display:none">\n'
            f'    {addr_detail}{desc_detail}{sh_table}\n'
            f'  </div>\n'
            f'  <button class="btn-expand" onclick="toggleCard(this)">▼ Details</button>\n'
            f'</div>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GeBIZ Supplier Directory — {total} suppliers</title>
<style>
:root{{
  --bg:#f8f9fa;--card:#fff;--border:#e2e8f0;--primary:#2563eb;
  --text:#1e293b;--muted:#64748b;--green:#16a34a;--green-bg:#dcfce7;
  --r:10px;--sh:0 1px 3px rgba(0,0,0,.08);
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}}

/* ── Top bar ── */
.top-bar{{background:var(--primary);color:#fff;padding:14px 24px;position:sticky;top:0;z-index:200;box-shadow:0 2px 8px rgba(0,0,0,.18)}}
.top-bar-inner{{max-width:1400px;margin:0 auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.top-bar h1{{font-size:.95rem;font-weight:700;white-space:nowrap}}
.top-bar h1 small{{font-weight:400;opacity:.75}}
.search-wrap{{flex:1;min-width:160px;position:relative}}
.search-wrap input{{width:100%;padding:7px 13px;border-radius:7px;border:2px solid rgba(255,255,255,.3);background:rgba(255,255,255,.15);color:#fff;font-size:.88rem;outline:none}}
.search-wrap input::placeholder{{color:rgba(255,255,255,.6)}}
.search-wrap input:focus{{border-color:#fff;background:rgba(255,255,255,.25)}}
.search-wrap .clear-btn{{position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:none;color:rgba(255,255,255,.7);font-size:1rem;cursor:pointer;display:none}}
#sort-select{{padding:7px 10px;border-radius:7px;border:2px solid rgba(255,255,255,.3);background:rgba(255,255,255,.15);color:#fff;font-size:.82rem;cursor:pointer}}
.btn-export{{padding:7px 13px;border-radius:7px;border:2px solid rgba(255,255,255,.5);background:rgba(255,255,255,.12);color:#fff;font-size:.82rem;cursor:pointer;white-space:nowrap;font-weight:600;transition:background .15s}}
.btn-export:hover{{background:rgba(255,255,255,.28)}}

/* ── Filter bar ── */
.filter-bar{{background:#fff;border-bottom:1px solid var(--border);padding:10px 24px;position:sticky;top:57px;z-index:100}}
.filter-bar-inner{{max-width:1400px;margin:0 auto;display:flex;align-items:flex-start;gap:10px;flex-wrap:wrap}}
.filter-group{{display:flex;align-items:center;gap:7px;flex-wrap:wrap}}
.filter-label{{font-size:.75rem;font-weight:700;color:var(--muted);white-space:nowrap;text-transform:uppercase;letter-spacing:.03em}}
.filter-divider{{width:1px;height:28px;background:var(--border);flex-shrink:0;align-self:center}}

/* Activity search */
#activity-input{{padding:5px 11px;border-radius:7px;border:1.5px solid var(--border);font-size:.83rem;outline:none;width:210px;color:var(--text)}}
#activity-input:focus{{border-color:var(--primary)}}
#activity-input::placeholder{{color:var(--muted)}}

/* Generic dropdown */
.dd-wrap{{position:relative}}
.btn-dd{{padding:5px 12px;border-radius:7px;border:1.5px solid var(--border);background:#fff;color:var(--text);font-size:.82rem;cursor:pointer;display:flex;align-items:center;gap:5px;transition:border-color .15s;white-space:nowrap}}
.btn-dd:hover,.btn-dd.open{{border-color:var(--primary);color:var(--primary)}}
.btn-dd .badge{{background:var(--primary);color:#fff;border-radius:10px;padding:1px 6px;font-size:.68rem;font-weight:700}}
.dd-panel{{display:none;position:absolute;top:calc(100% + 5px);left:0;background:#fff;border:1.5px solid var(--border);border-radius:var(--r);box-shadow:0 8px 24px rgba(0,0,0,.12);z-index:300;min-width:180px}}
.dd-panel.open{{display:block}}
.dd-actions{{padding:6px 10px;border-bottom:1px solid var(--border);display:flex;gap:6px}}
.dd-actions button{{padding:3px 9px;font-size:.75rem;border-radius:5px;border:1px solid var(--border);background:#f8f9fa;cursor:pointer}}
.dd-actions button:hover{{background:var(--border)}}
.dd-list{{padding:5px 0;max-height:260px;overflow-y:auto}}

/* EPU panel extras */
.epu-panel-top{{padding:8px 10px;border-bottom:1px solid var(--border)}}
.epu-search{{width:100%;padding:5px 9px;border:1.5px solid var(--border);border-radius:6px;font-size:.8rem;outline:none}}
.epu-search:focus{{border-color:var(--primary)}}
.epu-dd{{width:400px}}
.grade-dd{{width:130px}}

.cb-item{{display:flex;align-items:center;gap:8px;padding:6px 13px;cursor:pointer;font-size:.82rem;line-height:1.35;transition:background .1s}}
.cb-item:hover{{background:#f1f5f9}}
.cb-item input{{flex-shrink:0;cursor:pointer;accent-color:var(--primary);width:15px;height:15px;margin:0}}
.cb-item code{{font-size:.74rem;color:var(--primary);flex-shrink:0;font-weight:600;min-width:88px}}
.cb-item .cb-text{{color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.cb-item.hidden{{display:none}}

/* Year buttons */
.yr-btn{{padding:4px 11px;border-radius:6px;border:1.5px solid var(--border);background:#fff;color:var(--muted);font-size:.8rem;cursor:pointer;transition:all .15s;font-weight:500}}
.yr-btn:hover{{border-color:var(--primary);color:var(--primary)}}
.yr-btn.active{{background:var(--primary);border-color:var(--primary);color:#fff;font-weight:700}}

/* Active filter pills */
.pills-row{{display:flex;flex-wrap:wrap;gap:5px;align-items:center;padding:4px 24px 6px;max-width:1400px;margin:0 auto}}
.pill{{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;border-radius:12px;font-size:.73rem;font-weight:600}}
.pill-epu{{background:#dbeafe;color:#1d4ed8}}
.pill-grade{{background:#ede9fe;color:#6d28d9}}
.pill-yr{{background:#dcfce7;color:#15803d}}
.pill-activity{{background:#fef3c7;color:#92400e}}
.pill button{{background:none;border:none;cursor:pointer;padding:0;font-size:.8rem;line-height:1;opacity:.7;color:inherit}}
.pill button:hover{{opacity:1}}
.clear-all{{font-size:.73rem;color:var(--muted);cursor:pointer;padding:2px 6px;border-radius:5px;border:1px solid var(--border);background:#fff;margin-left:4px}}
.clear-all:hover{{color:var(--text);border-color:var(--text)}}

/* ── Content ── */
.content{{max-width:1400px;margin:0 auto;padding:16px 24px}}
.results-bar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;font-size:.86rem;color:var(--muted)}}
.results-bar strong{{color:var(--text);font-size:.95rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(390px,1fr));gap:15px}}

/* ── Cards ── */
.card{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--sh);overflow:hidden;transition:box-shadow .2s,transform .1s}}
.card:hover{{box-shadow:0 4px 14px rgba(0,0,0,.1);transform:translateY(-1px)}}
.card.hidden{{display:none}}
.card-header{{padding:12px 14px 8px;border-bottom:1px solid var(--border)}}
.card-title-row{{display:flex;align-items:flex-start;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.uen{{background:#f1f5f9;color:var(--muted);font-size:.68rem;font-family:monospace;padding:2px 7px;border-radius:4px;border:1px solid var(--border);white-space:nowrap;margin-top:2px;flex-shrink:0}}
h3{{font-size:.9rem;font-weight:700;color:var(--text);line-height:1.3}}
.sh-tags{{display:flex;flex-wrap:wrap;gap:3px}}
.sh-tag{{font-size:.68rem;padding:2px 6px;border-radius:3px;font-weight:600;cursor:default}}
.tag-approved{{background:var(--green-bg);color:var(--green)}}
.tag-other{{background:#f1f5f9;color:var(--muted)}}
.card-body{{padding:10px 14px}}
.summary{{font-size:.83rem;color:var(--text);line-height:1.5;margin-bottom:8px}}
.contacts{{display:flex;flex-wrap:wrap;gap:5px;font-size:.78rem}}
.ci{{color:var(--muted);white-space:nowrap}}
.ci a{{color:var(--primary);text-decoration:none}}
.ci a:hover{{text-decoration:underline}}
.expanded{{padding:0 14px;border-top:1px solid var(--border);background:#f8fafc}}
.dr{{display:flex;gap:9px;padding:5px 0;font-size:.81rem;border-bottom:1px solid var(--border)}}
.dr:last-child{{border-bottom:none}}
.dl{{font-weight:600;color:var(--muted);min-width:56px;flex-shrink:0}}
.desc-detail .dl{{align-self:flex-start;padding-top:1px}}
.desc-detail span{{white-space:pre-wrap;color:var(--muted);font-size:.8rem;line-height:1.55}}
.sh-table{{width:100%;border-collapse:collapse;font-size:.76rem;margin:7px 0}}
.sh-table th,.sh-table td{{padding:4px 6px;text-align:left;border-bottom:1px solid var(--border)}}
.sh-table th{{font-weight:700;color:var(--muted);background:#f1f5f9}}
.status-ok{{color:var(--green);font-weight:600}}
.status-other{{color:var(--muted)}}
.btn-expand{{width:100%;padding:6px;background:none;border:none;border-top:1px solid var(--border);color:var(--muted);font-size:.76rem;cursor:pointer;transition:background .15s}}
.btn-expand:hover{{background:#f1f5f9}}
.no-results{{text-align:center;padding:60px 20px;color:var(--muted)}}
.no-results h2{{font-size:1.1rem;margin-bottom:8px;color:var(--text)}}
.site-footer{{margin-top:28px;padding:18px 4px 8px;border-top:1px solid var(--border);font-size:.76rem;color:var(--muted);line-height:1.5;text-align:center}}
.site-footer a{{color:var(--primary);text-decoration:none}}
.site-footer a:hover{{text-decoration:underline}}

/* ── Email gate modal ── */
.modal-overlay{{position:fixed;inset:0;background:rgba(15,23,42,.5);z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(2px)}}
.modal{{background:#fff;border-radius:14px;max-width:420px;width:100%;padding:28px 26px 22px;position:relative;box-shadow:0 20px 60px rgba(0,0,0,.3);animation:modalIn .18s ease-out}}
@keyframes modalIn{{from{{opacity:0;transform:translateY(10px) scale(.98)}}to{{opacity:1;transform:none}}}}
.modal-close{{position:absolute;top:12px;right:14px;background:none;border:none;font-size:1.1rem;color:var(--muted);cursor:pointer;line-height:1}}
.modal-close:hover{{color:var(--text)}}
.modal h2{{font-size:1.25rem;margin-bottom:6px;color:var(--text)}}
.modal-sub{{font-size:.86rem;color:var(--muted);line-height:1.5;margin-bottom:18px}}
.modal form{{display:flex;flex-direction:column;gap:10px}}
.modal input{{padding:10px 13px;border:1.5px solid var(--border);border-radius:8px;font-size:.92rem;outline:none;width:100%}}
.modal input:focus{{border-color:var(--primary)}}
.modal-err{{color:#dc2626;font-size:.8rem;min-height:1em}}
.modal-submit{{background:var(--primary);color:#fff;border:none;border-radius:8px;padding:11px;font-size:.95rem;font-weight:700;cursor:pointer;transition:background .15s}}
.modal-submit:hover{{background:#1d4ed8}}
.modal-submit:disabled{{opacity:.6;cursor:default}}
.modal-fine{{font-size:.74rem;color:var(--muted);text-align:center;margin-top:12px}}

@media(max-width:640px){{
  .grid{{grid-template-columns:1fr}}
  .top-bar-inner{{flex-direction:column;align-items:stretch}}
  .epu-dd{{width:calc(100vw - 48px)}}
  #activity-input{{width:100%}}
}}
</style>
</head>
<body>

<div class="top-bar">
  <div class="top-bar-inner">
    <h1>GeBIZ Supplier Directory <small>({total} suppliers)</small></h1>
    <div class="search-wrap">
      <input type="text" id="search-input" placeholder="Search name, UEN, or description…" oninput="onSearchInput()" autocomplete="off">
      <button class="clear-btn" id="search-clear" onclick="clearSearch()">✕</button>
    </div>
    <select id="sort-select" onchange="sortCards()">
      <option value="name">Sort: Name A–Z</option>
      <option value="uen">Sort: UEN</option>
    </select>
    <button class="btn-export" onclick="exportCSV()">⬇ Export CSV</button>
  </div>
</div>

<div class="filter-bar">
  <div class="filter-bar-inner">

    <!-- Supply Head -->
    <div class="filter-group">
      <span class="filter-label">Supply Head</span>
      <div class="dd-wrap">
        <button class="btn-dd" id="btn-epu" onclick="togglePanel('epu-panel', this)">
          <span id="epu-lbl">All</span>
          <span id="epu-badge" class="badge" style="display:none">0</span> ▾
        </button>
        <div class="dd-panel epu-dd" id="epu-panel">
          <div class="epu-panel-top">
            <input type="text" class="epu-search" id="epu-search" placeholder="Search…" oninput="filterEpuList()">
          </div>
          <div class="dd-actions">
            <button onclick="selectAllEpu()">Select all</button>
            <button onclick="clearEpu()">Clear</button>
          </div>
          <div class="dd-list" id="epu-list">
{epu_items_html}
          </div>
        </div>
      </div>
    </div>

    <div class="filter-divider"></div>

    <!-- Grade -->
    <div class="filter-group">
      <span class="filter-label">Grade</span>
      <div class="dd-wrap">
        <button class="btn-dd" id="btn-grade" onclick="togglePanel('grade-panel', this)">
          <span id="grade-lbl">All</span>
          <span id="grade-badge" class="badge" style="display:none">0</span> ▾
        </button>
        <div class="dd-panel grade-dd" id="grade-panel">
          <div class="dd-actions">
            <button onclick="selectAllGrades()">Select all</button>
            <button onclick="clearGrades()">Clear</button>
          </div>
          <div class="dd-list">
{grade_items_html}
          </div>
        </div>
      </div>
    </div>

    <div class="filter-divider"></div>

    <!-- Expiry year -->
    <div class="filter-group">
      <span class="filter-label">Expiry</span>
      {year_btns_html}
    </div>

    <div class="filter-divider"></div>

    <!-- Activity / description search -->
    <div class="filter-group">
      <span class="filter-label">Activity</span>
      <input type="text" id="activity-input" placeholder="e.g. cybersecurity, training, SAP…" oninput="filterCards()" autocomplete="off">
    </div>

  </div>
</div>

<!-- Active filter pills -->
<div class="pills-row" id="pills-row" style="display:none">
  <span style="font-size:.73rem;font-weight:600;color:var(--muted)">Active filters:</span>
  <span id="pills-container"></span>
  <button class="clear-all" onclick="clearAll()">Clear all</button>
</div>

<div class="content">
  <div class="results-bar">
    <span><strong id="results-count">{total}</strong> suppliers shown</span>
    <span id="filter-note" style="font-size:.8rem;color:var(--muted)"></span>
  </div>
  <div class="grid" id="cards-grid">
{cards_html}
  </div>
  <div class="no-results" id="no-results" style="display:none">
    <h2>No suppliers match your filters</h2>
    <p>Try broadening your search or removing some filters.</p>
  </div>
  <footer class="site-footer">
    Data sourced from the public <a href="https://www.gebiz.gov.sg/ptn/supplier/directory/index.xhtml" target="_blank" rel="noopener">GeBIZ Supplier Directory</a>.
    Downloading a CSV requires an email and records which filters/data sets were exported, to help us improve the directory.
  </footer>
</div>

<!-- Email gate modal -->
<div class="modal-overlay" id="email-modal" style="display:none">
  <div class="modal">
    <button class="modal-close" onclick="closeModal()" aria-label="Close">✕</button>
    <h2>Download supplier data</h2>
    <p class="modal-sub">Enter your email to download the CSV and get occasional updates to the directory. We'll only ask once.</p>
    <form id="email-form" onsubmit="return submitEmail(event)">
      <input type="text" id="modal-name" placeholder="Name (optional)" autocomplete="name">
      <input type="email" id="modal-email" placeholder="you@company.com" required autocomplete="email">
      <div class="modal-err" id="modal-err"></div>
      <button type="submit" class="modal-submit" id="modal-submit">Download CSV →</button>
    </form>
    <p class="modal-fine">Your email is stored privately and never shared. For analytics, we record which filters and data sets are downloaded.</p>
  </div>
</div>

<script>
const API_BASE = {api_base_js};
const ALL_DATA = {csv_data_js};
const cards = Array.from(document.querySelectorAll('.card'));

let selectedEpu    = new Set();
let selectedGrades = new Set();
let selectedYears  = new Set();

// ── Panel toggle ───────────────────────────────────────────────
function togglePanel(panelId, btn) {{
  const panel = document.getElementById(panelId);
  const willOpen = !panel.classList.contains('open');
  // Close all panels
  document.querySelectorAll('.dd-panel').forEach(p => p.classList.remove('open'));
  document.querySelectorAll('.btn-dd').forEach(b => b.classList.remove('open'));
  if (willOpen) {{
    panel.classList.add('open');
    btn.classList.add('open');
    const srch = panel.querySelector('.epu-search');
    if (srch) srch.focus();
  }}
}}
document.addEventListener('click', e => {{
  if (!e.target.closest('.dd-wrap')) {{
    document.querySelectorAll('.dd-panel').forEach(p => p.classList.remove('open'));
    document.querySelectorAll('.btn-dd').forEach(b => b.classList.remove('open'));
  }}
}});

// ── EPU ───────────────────────────────────────────────────────
function filterEpuList() {{
  const q = document.getElementById('epu-search').value.toLowerCase();
  document.querySelectorAll('.epu-cb').forEach(cb => {{
    const item = cb.closest('.cb-item');
    if (item) item.classList.toggle('hidden', !!q && !item.textContent.toLowerCase().includes(q));
  }});
}}
document.querySelectorAll('.epu-cb').forEach(cb => {{
  cb.addEventListener('change', () => {{
    if (cb.checked) selectedEpu.add(cb.value); else selectedEpu.delete(cb.value);
    updatePills(); filterCards();
  }});
}});
function selectAllEpu() {{
  document.querySelectorAll('.epu-cb:not(.hidden)').forEach(cb => {{ cb.checked=true; selectedEpu.add(cb.value); }});
  updatePills(); filterCards();
}}
function clearEpu() {{
  document.querySelectorAll('.epu-cb').forEach(cb => {{ cb.checked=false; }});
  selectedEpu.clear(); updatePills(); filterCards();
}}

// ── Grade ─────────────────────────────────────────────────────
document.querySelectorAll('.grade-cb').forEach(cb => {{
  cb.addEventListener('change', () => {{
    if (cb.checked) selectedGrades.add(cb.value); else selectedGrades.delete(cb.value);
    updatePills(); filterCards();
  }});
}});
function selectAllGrades() {{
  document.querySelectorAll('.grade-cb').forEach(cb => {{ cb.checked=true; selectedGrades.add(cb.value); }});
  updatePills(); filterCards();
}}
function clearGrades() {{
  document.querySelectorAll('.grade-cb').forEach(cb => {{ cb.checked=false; }});
  selectedGrades.clear(); updatePills(); filterCards();
}}

// ── Year ──────────────────────────────────────────────────────
function toggleYear(btn) {{
  const yr = btn.dataset.yr;
  btn.classList.toggle('active');
  if (btn.classList.contains('active')) selectedYears.add(yr); else selectedYears.delete(yr);
  updatePills(); filterCards();
}}

// ── Search ────────────────────────────────────────────────────
function onSearchInput() {{
  const q = document.getElementById('search-input').value;
  document.getElementById('search-clear').style.display = q ? 'block' : 'none';
  filterCards();
}}
function clearSearch() {{
  document.getElementById('search-input').value = '';
  document.getElementById('search-clear').style.display = 'none';
  filterCards();
}}

// ── Main filter ───────────────────────────────────────────────
function filterCards() {{
  const q        = document.getElementById('search-input').value.toLowerCase().trim();
  const activity = document.getElementById('activity-input').value.toLowerCase().trim();
  let visible = 0;

  cards.forEach(card => {{
    // Text search (name + UEN + description)
    const matchText = !q || (card.dataset.name||'').includes(q) ||
                           (card.dataset.uen||'').includes(q)  ||
                           (card.dataset.desc||'').includes(q);

    // Activity search (description only)
    const matchActivity = !activity || (card.dataset.desc||'').includes(activity);

    // EPU
    const cardEpu = new Set((card.dataset.sh||'').split(' ').filter(Boolean));
    const matchEpu = !selectedEpu.size || [...selectedEpu].some(c => cardEpu.has(c));

    // Grade
    const cardGrades = new Set((card.dataset.grade||'').split(' ').filter(Boolean));
    const matchGrade = !selectedGrades.size || [...selectedGrades].some(g => cardGrades.has(g));

    // Year
    const cardYears = new Set((card.dataset.yr||'').split(' ').filter(Boolean));
    const matchYear = !selectedYears.size || [...selectedYears].some(y => cardYears.has(y));

    if (matchText && matchActivity && matchEpu && matchGrade && matchYear) {{
      card.classList.remove('hidden'); visible++;
    }} else {{
      card.classList.add('hidden');
    }}
  }});

  document.getElementById('results-count').textContent = visible;
  document.getElementById('no-results').style.display = visible === 0 ? 'block' : 'none';

  const active = selectedEpu.size + selectedGrades.size + selectedYears.size + (q?1:0) + (activity?1:0);
  document.getElementById('filter-note').textContent = active > 0 ? `${{active}} filter${{active>1?'s':''}} active` : '';
}}

// ── Pills ─────────────────────────────────────────────────────
function updatePills() {{
  // EPU button label
  const ne = selectedEpu.size;
  document.getElementById('epu-lbl').textContent = ne===0 ? 'All' : ne===1 ? [...selectedEpu][0] : `${{ne}} selected`;
  document.getElementById('epu-badge').style.display = ne>0 ? '' : 'none';
  document.getElementById('epu-badge').textContent = ne;

  // Grade button label
  const ng = selectedGrades.size;
  document.getElementById('grade-lbl').textContent = ng===0 ? 'All' : ng===1 ? [...selectedGrades][0] : `${{ng}} selected`;
  document.getElementById('grade-badge').style.display = ng>0 ? '' : 'none';
  document.getElementById('grade-badge').textContent = ng;

  // Pills
  const container = document.getElementById('pills-container');
  container.innerHTML = '';
  const addPill = (label, cls, onRemove) => {{
    const pill = document.createElement('span');
    pill.className = `pill ${{cls}}`;
    pill.innerHTML = `${{label}} <button onclick="${{onRemove}}" title="Remove">✕</button>`;
    container.appendChild(pill);
  }};
  [...selectedEpu].sort().forEach(c => addPill(c, 'pill-epu', `removeEpu('${{c}}')`));
  [...selectedGrades].sort().forEach(g => addPill(g, 'pill-grade', `removeGrade('${{g}}')`));
  [...selectedYears].sort().forEach(y => addPill(y, 'pill-yr', `removeYear('${{y}}')`));

  const totalPills = selectedEpu.size + selectedGrades.size + selectedYears.size;
  document.getElementById('pills-row').style.display = totalPills > 0 ? 'flex' : 'none';
}}

function removeEpu(code) {{
  selectedEpu.delete(code);
  const cb = document.querySelector(`.epu-cb[value="${{code}}"]`);
  if (cb) cb.checked = false;
  updatePills(); filterCards();
}}
function removeGrade(g) {{
  selectedGrades.delete(g);
  const cb = document.querySelector(`.grade-cb[value="${{g}}"]`);
  if (cb) cb.checked = false;
  updatePills(); filterCards();
}}
function removeYear(y) {{
  selectedYears.delete(y);
  const btn = document.querySelector(`.yr-btn[data-yr="${{y}}"]`);
  if (btn) btn.classList.remove('active');
  updatePills(); filterCards();
}}
function clearAll() {{
  clearEpu(); clearGrades();
  selectedYears.clear();
  document.querySelectorAll('.yr-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('search-input').value = '';
  document.getElementById('activity-input').value = '';
  document.getElementById('search-clear').style.display = 'none';
  updatePills(); filterCards();
}}

// ── Sort ──────────────────────────────────────────────────────
function sortCards() {{
  const grid = document.getElementById('cards-grid');
  const val  = document.getElementById('sort-select').value;
  [...cards].sort((a,b) => {{
    const ka = val==='uen' ? (a.dataset.uen||'') : (a.dataset.name||'');
    const kb = val==='uen' ? (b.dataset.uen||'') : (b.dataset.name||'');
    return ka.localeCompare(kb);
  }}).forEach(c => grid.appendChild(c));
  filterCards();
}}

// ── Tracking ──────────────────────────────────────────────────
function apiPost(path, payload) {{
  // Fire-and-forget; never block the UI if the API is unreachable.
  try {{
    fetch(API_BASE + path, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload),
      keepalive: true,
    }}).catch(() => {{}});
  }} catch (e) {{}}
}}

const STORE_KEY = 'gebiz_email';
function savedEmail() {{ try {{ return localStorage.getItem(STORE_KEY) || ''; }} catch {{ return ''; }} }}

// Track the visit once per page load
apiPost('/api/track', {{ type: 'visit' }});

// ── Current filter state (for download logging + CSV) ─────────
function currentFilter() {{
  const q        = document.getElementById('search-input').value.toLowerCase().trim();
  const activity = document.getElementById('activity-input').value.toLowerCase().trim();
  const filtered = ALL_DATA.filter(row => {{
    const txt  = (row.name+' '+row.uen+' '+row.summary+' '+row.description).toLowerCase();
    const desc = (row.summary+' '+row.description).toLowerCase();
    if (q && !txt.includes(q)) return false;
    if (activity && !desc.includes(activity)) return false;
    if (selectedEpu.size    && !row.sh_codes_arr.some(c => selectedEpu.has(c)))  return false;
    if (selectedGrades.size && !row.grades_arr.some(g => selectedGrades.has(g))) return false;
    if (selectedYears.size  && !row.years_arr.some(y => selectedYears.has(y)))   return false;
    return true;
  }});
  return {{ q, activity, filtered }};
}}

// ── CSV export with email gate ────────────────────────────────
let pendingExport = false;

function exportCSV() {{
  const email = savedEmail();
  if (email) {{ doExport(email); }}
  else {{ openModal(); }}
}}

function openModal() {{
  pendingExport = true;
  document.getElementById('modal-err').textContent = '';
  document.getElementById('email-modal').style.display = 'flex';
  setTimeout(() => document.getElementById('modal-email').focus(), 50);
}}
function closeModal() {{
  pendingExport = false;
  document.getElementById('email-modal').style.display = 'none';
}}

function submitEmail(e) {{
  e.preventDefault();
  const email = document.getElementById('modal-email').value.trim().toLowerCase();
  const name  = document.getElementById('modal-name').value.trim();
  const errEl = document.getElementById('modal-err');
  if (!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email)) {{
    errEl.textContent = 'Please enter a valid email address.';
    return false;
  }}
  const btn = document.getElementById('modal-submit');
  btn.disabled = true; btn.textContent = 'Saving…';

  // Save email to mailing list (fire-and-forget) and remember locally
  apiPost('/api/signup', {{ email, name }});
  try {{ localStorage.setItem(STORE_KEY, email); }} catch {{}}

  document.getElementById('email-modal').style.display = 'none';
  btn.disabled = false; btn.textContent = 'Download CSV →';
  if (pendingExport) {{ pendingExport = false; doExport(email); }}
  return false;
}}

function doExport(email) {{
  const {{ q, activity, filtered }} = currentFilter();

  const cols = ['uen','name','summary','description','phone','fax','email','website',
                'address','postal_code','city','supply_heads','supply_heads_full','grades','expiry_years'];
  const header = cols.join(',');
  const csvRows = filtered.map(row =>
    cols.map(col => {{
      const val = String(row[col]||'').replace(/"/g,'""');
      return val.includes(',') || val.includes('"') || val.includes('\\n') ? `"${{val}}"` : val;
    }}).join(',')
  );

  const csv  = ['\\uFEFF', header, ...csvRows].join('\\n');
  const blob = new Blob([csv], {{ type:'text/csv;charset=utf-8' }});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url;
  const parts = [];
  if (selectedEpu.size)    parts.push([...selectedEpu].join('+'));
  if (selectedGrades.size) parts.push('grade-'+[...selectedGrades].join('+'));
  if (selectedYears.size)  parts.push([...selectedYears].join('+'));
  if (q)        parts.push('search-'+q.replace(/\\s+/g,'-').slice(0,20));
  if (activity) parts.push('activity-'+activity.replace(/\\s+/g,'-').slice(0,20));
  a.download = `gebiz-suppliers${{parts.length ? '-'+parts.join('-') : ''}}.csv`;
  a.click();
  URL.revokeObjectURL(url);

  // Log what was downloaded
  apiPost('/api/track', {{
    type: 'download',
    email,
    detail: {{
      epu: [...selectedEpu], grades: [...selectedGrades], years: [...selectedYears],
      search: q || null, activity: activity || null, rows: filtered.length,
    }},
  }});
}}

// Close modal on overlay click
document.getElementById('email-modal').addEventListener('click', e => {{
  if (e.target.id === 'email-modal') closeModal();
}});

// ── Card expand ───────────────────────────────────────────────
function toggleCard(btn) {{
  const exp = btn.previousElementSibling;
  if (exp.style.display==='none') {{ exp.style.display='block'; btn.textContent='▲ Hide details'; }}
  else {{ exp.style.display='none'; btn.textContent='▼ Details'; }}
}}
</script>
</body>
</html>"""

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    with_summary = sum(1 for s in suppliers if s.get("description_short"))
    print(f"Built {HTML_PATH}")
    print(f"  {total} suppliers | {with_summary} AI summaries | {len(all_sh_codes)} EPU codes")
    print(f"  Grades: {grades_sorted}")
    print(f"  Expiry years: {years_sorted}")
    print(f"  File size: {len(html)//1024}KB")


if __name__ == "__main__":
    build()
