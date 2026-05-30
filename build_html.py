"""
Rebuild gebiz_suppliers.html with:
- Multi-select EPU supply head filter panel (checkbox dropdown)
- Text search (name, UEN, description)
- CSV export of filtered results
- AI summaries on card face, full description in expanded section
"""
import json

JSON_PATH = "/Users/seehaojun/Desktop/OTG/BD/suppliers.json"
HTML_PATH = "/Users/seehaojun/Desktop/OTG/BD/gebiz_suppliers.html"


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build():
    with open(JSON_PATH, encoding="utf-8") as f:
        suppliers = json.load(f)

    suppliers = [s for s in suppliers if s.get("name")]
    total = len(suppliers)

    # Collect all supply head codes + labels
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
            f'<label class="epu-item">'
            f'<input type="checkbox" class="epu-cb" value="{esc(code)}"> '
            f'<code>{esc(code)}</code> {esc(name_part)}'
            f'</label>\n'
        )

    # Compact data for CSV export
    csv_data = []
    for s in suppliers:
        sh_codes = [sh.get("code", "") for sh in s.get("supply_heads", []) if sh.get("code")]
        sh_full  = [sh.get("full", "") for sh in s.get("supply_heads", []) if sh.get("full")]
        addr_parts = [s.get("address_1"), s.get("address_2"), s.get("address_3")]
        address = ", ".join(p for p in addr_parts if p)
        csv_data.append({
            "uen": s.get("uen", ""),
            "name": s.get("name", ""),
            "summary": s.get("description_short", ""),
            "description": (s.get("description") or "").replace("\n", " ").replace("\r", ""),
            "address": address,
            "postal_code": s.get("postal_code", ""),
            "city": s.get("city", ""),
            "phone": s.get("phone", ""),
            "fax": s.get("fax", ""),
            "email": s.get("email", ""),
            "website": s.get("company_url", ""),
            "supply_heads": "; ".join(sh_codes),
            "supply_heads_full": "; ".join(sh_full),
            "sh_codes_arr": sh_codes,
        })
    csv_data_js = json.dumps(csv_data, ensure_ascii=False)

    # Build cards HTML
    cards_html = ""
    for s in suppliers:
        sh_codes = [sh.get("code", "") for sh in s.get("supply_heads", []) if sh.get("code")]
        sh_attr = " ".join(sh_codes)
        sh_tags = ""
        for sh in s.get("supply_heads", []):
            status_cls = "tag-approved" if sh.get("status") == "APPROVED" else "tag-other"
            sh_tags += (
                f'<span class="sh-tag {status_cls}" '
                f'title="{esc(sh.get("financial_grade",""))} | Exp: {esc(sh.get("expiry_date",""))} | {esc(sh.get("status",""))}">'
                f'{esc(sh.get("code","") or sh.get("name",""))}</span>'
            )

        ai_summary = esc(s.get("description_short", ""))
        desc_full  = esc(s.get("description", ""))
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
            for sh in s.get("supply_heads", []):
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

        cards_html += f"""<div class="card" data-sh="{esc(sh_attr)}" data-name="{esc(s.get('name','').lower())}" data-uen="{esc(s.get('uen','').lower())}" data-desc="{esc((s.get('description_short') or s.get('description') or '').lower()[:300])}">
  <div class="card-header">
    <div class="card-title-row">
      <span class="uen">{esc(s.get('uen',''))}</span>
      <h3>{esc(s.get('name',''))}</h3>
    </div>
    <div class="sh-tags">{sh_tags}</div>
  </div>
  <div class="card-body">
    {f'<p class="summary">{ai_summary}</p>' if ai_summary else ''}
    <div class="contacts">{contacts}</div>
  </div>
  <div class="expanded" style="display:none">
    {addr_detail}{desc_detail}{sh_table}
  </div>
  <button class="btn-expand" onclick="toggleCard(this)">▼ Details</button>
</div>
"""

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
.top-bar-inner{{max-width:1400px;margin:0 auto;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.top-bar h1{{font-size:1rem;font-weight:700;white-space:nowrap}}
.top-bar h1 small{{font-weight:400;opacity:.75}}
#search-input{{flex:1;min-width:180px;padding:7px 13px;border-radius:7px;border:2px solid rgba(255,255,255,.3);background:rgba(255,255,255,.15);color:#fff;font-size:.9rem;outline:none}}
#search-input::placeholder{{color:rgba(255,255,255,.6)}}
#search-input:focus{{border-color:#fff;background:rgba(255,255,255,.25)}}
#sort-select{{padding:7px 11px;border-radius:7px;border:2px solid rgba(255,255,255,.3);background:rgba(255,255,255,.15);color:#fff;font-size:.85rem;cursor:pointer}}
.btn-export{{padding:7px 14px;border-radius:7px;border:2px solid rgba(255,255,255,.5);background:rgba(255,255,255,.15);color:#fff;font-size:.85rem;cursor:pointer;white-space:nowrap;font-weight:600;transition:background .15s}}
.btn-export:hover{{background:rgba(255,255,255,.3)}}

/* ── Filter bar ── */
.filter-bar{{background:#fff;border-bottom:1px solid var(--border);padding:10px 24px;position:sticky;top:57px;z-index:100}}
.filter-bar-inner{{max-width:1400px;margin:0 auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.filter-label{{font-size:.8rem;font-weight:600;color:var(--muted);white-space:nowrap}}

/* EPU dropdown */
.epu-wrap{{position:relative}}
.btn-epu{{padding:6px 14px;border-radius:7px;border:1.5px solid var(--border);background:#fff;color:var(--text);font-size:.85rem;cursor:pointer;display:flex;align-items:center;gap:6px;transition:border-color .15s}}
.btn-epu:hover,.btn-epu.open{{border-color:var(--primary);color:var(--primary)}}
.btn-epu .badge{{background:var(--primary);color:#fff;border-radius:10px;padding:1px 7px;font-size:.72rem;font-weight:700}}
.epu-panel{{display:none;position:absolute;top:calc(100% + 6px);left:0;width:380px;max-height:400px;background:#fff;border:1.5px solid var(--border);border-radius:var(--r);box-shadow:0 8px 24px rgba(0,0,0,.12);z-index:300;flex-direction:column}}
.epu-panel.open{{display:flex}}
.epu-panel-top{{padding:10px 12px;border-bottom:1px solid var(--border);display:flex;gap:8px;align-items:center}}
.epu-search{{flex:1;padding:5px 10px;border:1.5px solid var(--border);border-radius:6px;font-size:.83rem;outline:none}}
.epu-search:focus{{border-color:var(--primary)}}
.epu-panel-actions{{padding:6px 12px;border-bottom:1px solid var(--border);display:flex;gap:8px}}
.epu-panel-actions button{{padding:3px 10px;font-size:.78rem;border-radius:5px;border:1px solid var(--border);background:#f8f9fa;cursor:pointer}}
.epu-panel-actions button:hover{{background:var(--border)}}
.epu-list{{overflow-y:auto;flex:1;padding:6px 0}}
.epu-item{{display:flex;align-items:baseline;gap:7px;padding:5px 14px;cursor:pointer;font-size:.82rem;transition:background .1s}}
.epu-item:hover{{background:#f1f5f9}}
.epu-item input{{flex-shrink:0;cursor:pointer;accent-color:var(--primary)}}
.epu-item code{{font-size:.78rem;color:var(--muted);flex-shrink:0}}
.epu-item.hidden{{display:none}}

/* Active filter pills */
.active-filters{{display:flex;flex-wrap:wrap;gap:5px;align-items:center}}
.filter-pill{{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;border-radius:12px;background:var(--primary);color:#fff;font-size:.75rem;font-weight:600}}
.filter-pill button{{background:none;border:none;color:#fff;cursor:pointer;padding:0;font-size:.8rem;line-height:1;opacity:.8}}
.filter-pill button:hover{{opacity:1}}

/* ── Content ── */
.content{{max-width:1400px;margin:0 auto;padding:20px 24px}}
.results-bar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;font-size:.88rem;color:var(--muted)}}
.results-bar strong{{color:var(--text)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(390px,1fr));gap:16px}}

/* ── Cards ── */
.card{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--sh);overflow:hidden;transition:box-shadow .2s,transform .1s}}
.card:hover{{box-shadow:0 4px 14px rgba(0,0,0,.1);transform:translateY(-1px)}}
.card.hidden{{display:none}}
.card-header{{padding:13px 15px 9px;border-bottom:1px solid var(--border)}}
.card-title-row{{display:flex;align-items:flex-start;gap:9px;margin-bottom:7px;flex-wrap:wrap}}
.uen{{background:#f1f5f9;color:var(--muted);font-size:.7rem;font-family:monospace;padding:2px 8px;border-radius:4px;border:1px solid var(--border);white-space:nowrap;margin-top:2px;flex-shrink:0}}
h3{{font-size:.92rem;font-weight:700;color:var(--text);line-height:1.3}}
.sh-tags{{display:flex;flex-wrap:wrap;gap:4px}}
.sh-tag{{font-size:.7rem;padding:2px 7px;border-radius:4px;font-weight:600;cursor:default}}
.tag-approved{{background:var(--green-bg);color:var(--green)}}
.tag-other{{background:#f1f5f9;color:var(--muted)}}
.card-body{{padding:11px 15px}}
.summary{{font-size:.84rem;color:var(--text);line-height:1.5;margin-bottom:9px}}
.contacts{{display:flex;flex-wrap:wrap;gap:6px;font-size:.8rem}}
.ci{{color:var(--muted);white-space:nowrap}}
.ci a{{color:var(--primary);text-decoration:none}}
.ci a:hover{{text-decoration:underline}}
.expanded{{padding:0 15px;border-top:1px solid var(--border);background:#f8fafc}}
.dr{{display:flex;gap:10px;padding:5px 0;font-size:.83rem;border-bottom:1px solid var(--border)}}
.dr:last-child{{border-bottom:none}}
.dl{{font-weight:600;color:var(--muted);min-width:58px;flex-shrink:0}}
.desc-detail .dl{{align-self:flex-start;padding-top:1px}}
.desc-detail span{{white-space:pre-wrap;color:var(--muted);font-size:.82rem;line-height:1.55}}
.sh-table{{width:100%;border-collapse:collapse;font-size:.78rem;margin:8px 0}}
.sh-table th,.sh-table td{{padding:4px 7px;text-align:left;border-bottom:1px solid var(--border)}}
.sh-table th{{font-weight:700;color:var(--muted);background:#f1f5f9}}
.status-ok{{color:var(--green);font-weight:600}}
.status-other{{color:var(--muted)}}
.btn-expand{{width:100%;padding:7px;background:none;border:none;border-top:1px solid var(--border);color:var(--muted);font-size:.78rem;cursor:pointer;transition:background .15s}}
.btn-expand:hover{{background:#f1f5f9}}
.no-results{{text-align:center;padding:60px 20px;color:var(--muted);display:none}}

@media(max-width:600px){{
  .grid{{grid-template-columns:1fr}}
  .top-bar-inner{{flex-direction:column;align-items:stretch}}
  .epu-panel{{width:calc(100vw - 48px)}}
}}
</style>
</head>
<body>

<div class="top-bar">
  <div class="top-bar-inner">
    <h1>GeBIZ Supplier Directory <small>({total} suppliers)</small></h1>
    <input type="text" id="search-input" placeholder="Search name, UEN, description…" oninput="filterCards()" autocomplete="off">
    <select id="sort-select" onchange="sortCards()">
      <option value="name">Sort: Name A–Z</option>
      <option value="uen">Sort: UEN</option>
    </select>
    <button class="btn-export" onclick="exportCSV()">⬇ Export CSV</button>
  </div>
</div>

<div class="filter-bar">
  <div class="filter-bar-inner">
    <span class="filter-label">Filter by Supply Head:</span>
    <div class="epu-wrap">
      <button class="btn-epu" id="btn-epu" onclick="toggleEpuPanel()">
        <span id="epu-btn-label">All supply heads</span>
        <span id="epu-badge" class="badge" style="display:none">0</span>
        ▾
      </button>
      <div class="epu-panel" id="epu-panel">
        <div class="epu-panel-top">
          <input type="text" class="epu-search" id="epu-search" placeholder="Search supply head…" oninput="filterEpuList()">
        </div>
        <div class="epu-panel-actions">
          <button onclick="selectAllEpu()">Select all</button>
          <button onclick="clearEpu()">Clear</button>
        </div>
        <div class="epu-list" id="epu-list">
{epu_items_html}
        </div>
      </div>
    </div>
    <div class="active-filters" id="active-filters"></div>
  </div>
</div>

<div class="content">
  <div class="results-bar">
    <span><strong id="results-count">{total}</strong> suppliers shown</span>
    <span id="filter-summary" style="color:var(--muted);font-size:.82rem"></span>
  </div>
  <div class="grid" id="cards-grid">
{cards_html}
  </div>
  <div class="no-results" id="no-results">No suppliers match your filters.</div>
</div>

<script>
const ALL_DATA = {csv_data_js};
const cards = Array.from(document.querySelectorAll('.card'));
let selectedEpu = new Set();

// ── EPU panel ──────────────────────────────────────────────────
function toggleEpuPanel() {{
  const panel = document.getElementById('epu-panel');
  const btn   = document.getElementById('btn-epu');
  const open  = panel.classList.toggle('open');
  btn.classList.toggle('open', open);
  if (open) document.getElementById('epu-search').focus();
}}

document.addEventListener('click', e => {{
  const wrap = document.querySelector('.epu-wrap');
  if (!wrap.contains(e.target)) {{
    document.getElementById('epu-panel').classList.remove('open');
    document.getElementById('btn-epu').classList.remove('open');
  }}
}});

function filterEpuList() {{
  const q = document.getElementById('epu-search').value.toLowerCase();
  document.querySelectorAll('.epu-item').forEach(item => {{
    item.classList.toggle('hidden', q && !item.textContent.toLowerCase().includes(q));
  }});
}}

document.querySelectorAll('.epu-cb').forEach(cb => {{
  cb.addEventListener('change', () => {{
    if (cb.checked) selectedEpu.add(cb.value);
    else selectedEpu.delete(cb.value);
    updateEpuUI();
    filterCards();
  }});
}});

function selectAllEpu() {{
  document.querySelectorAll('.epu-cb:not(.hidden)').forEach(cb => {{
    cb.checked = true;
    selectedEpu.add(cb.value);
  }});
  // if all visible were selected and there are hidden ones, only select visible
  updateEpuUI(); filterCards();
}}

function clearEpu() {{
  document.querySelectorAll('.epu-cb').forEach(cb => {{ cb.checked = false; }});
  selectedEpu.clear();
  updateEpuUI(); filterCards();
}}

function updateEpuUI() {{
  const n = selectedEpu.size;
  const badge  = document.getElementById('epu-badge');
  const btnLbl = document.getElementById('epu-btn-label');
  const pillsEl = document.getElementById('active-filters');

  badge.style.display = n > 0 ? '' : 'none';
  badge.textContent = n;
  btnLbl.textContent = n === 0 ? 'All supply heads' : n === 1 ? [...selectedEpu][0] : `${{n}} supply heads`;

  // Pills
  pillsEl.innerHTML = '';
  [...selectedEpu].sort().forEach(code => {{
    const pill = document.createElement('span');
    pill.className = 'filter-pill';
    pill.innerHTML = `${{code}} <button onclick="removeEpu('${{code}}')" title="Remove">✕</button>`;
    pillsEl.appendChild(pill);
  }});

  const summary = document.getElementById('filter-summary');
  summary.textContent = n > 0 ? `Filtering by ${{n}} supply head${{n>1?'s':''}}` : '';
}}

function removeEpu(code) {{
  selectedEpu.delete(code);
  const cb = document.querySelector(`.epu-cb[value="${{code}}"]`);
  if (cb) cb.checked = false;
  updateEpuUI(); filterCards();
}}

// ── Main filter ───────────────────────────────────────────────
function filterCards() {{
  const q = document.getElementById('search-input').value.toLowerCase().trim();
  let visible = 0;
  cards.forEach(card => {{
    const matchText = !q ||
      (card.dataset.name || '').includes(q) ||
      (card.dataset.uen  || '').includes(q) ||
      (card.dataset.desc || '').includes(q);

    let matchEpu = true;
    if (selectedEpu.size > 0) {{
      const cardCodes = new Set((card.dataset.sh || '').split(' ').filter(Boolean));
      matchEpu = [...selectedEpu].some(c => cardCodes.has(c));
    }}

    if (matchText && matchEpu) {{ card.classList.remove('hidden'); visible++; }}
    else card.classList.add('hidden');
  }});

  document.getElementById('results-count').textContent = visible;
  document.getElementById('no-results').style.display = visible === 0 ? 'block' : 'none';
}}

function sortCards() {{
  const grid = document.getElementById('cards-grid');
  const val  = document.getElementById('sort-select').value;
  const sorted = [...cards].sort((a,b) => {{
    const ka = val === 'uen' ? (a.dataset.uen||'') : (a.dataset.name||'');
    const kb = val === 'uen' ? (b.dataset.uen||'') : (b.dataset.name||'');
    return ka.localeCompare(kb);
  }});
  sorted.forEach(c => grid.appendChild(c));
  filterCards();
}}

// ── CSV export ────────────────────────────────────────────────
function exportCSV() {{
  const q = document.getElementById('search-input').value.toLowerCase().trim();

  const filtered = ALL_DATA.filter(row => {{
    const matchText = !q ||
      row.name.toLowerCase().includes(q) ||
      row.uen.toLowerCase().includes(q) ||
      row.summary.toLowerCase().includes(q) ||
      row.description.toLowerCase().includes(q);

    let matchEpu = true;
    if (selectedEpu.size > 0) {{
      matchEpu = row.sh_codes_arr.some(c => selectedEpu.has(c));
    }}
    return matchText && matchEpu;
  }});

  const cols = ['uen','name','summary','description','phone','fax','email','website',
                'address','postal_code','city','supply_heads','supply_heads_full'];
  const header = cols.join(',');

  const csvRows = filtered.map(row =>
    cols.map(col => {{
      const val = String(row[col] || '').replace(/"/g, '""');
      return val.includes(',') || val.includes('"') || val.includes('\\n') ? `"${{val}}"` : val;
    }}).join(',')
  );

  const csv = [header, ...csvRows].join('\\n');
  const blob = new Blob(['\\uFEFF' + csv], {{ type: 'text/csv;charset=utf-8' }});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url;
  const suffix = selectedEpu.size > 0 ? '-' + [...selectedEpu].join('-') : '-all';
  a.download = `gebiz-suppliers${{suffix}}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}}

// ── Card expand ───────────────────────────────────────────────
function toggleCard(btn) {{
  const exp = btn.previousElementSibling;
  if (exp.style.display === 'none') {{
    exp.style.display = 'block';
    btn.textContent = '▲ Hide details';
  }} else {{
    exp.style.display = 'none';
    btn.textContent = '▼ Details';
  }}
}}
</script>
</body>
</html>"""

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Built {HTML_PATH} ({len(html)//1024}KB) — {total} suppliers")
    with_summary = sum(1 for s in suppliers if s.get("description_short"))
    print(f"  AI summaries: {with_summary}")
    print(f"  EPU codes: {len(all_sh_codes)}")


if __name__ == "__main__":
    build()
