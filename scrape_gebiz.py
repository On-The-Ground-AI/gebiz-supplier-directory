"""
GeBIZ Supplier Directory Scraper
Scrapes EPU/CMP/10, EPU/SER/35, EPU/SER/34, EPU/SER/19, EPU/SER/30

Phase 1: Playwright pagination to collect all supplier codes
Phase 2: requests (parallel) to fetch and parse all profile pages
Phase 3: Build searchable HTML database
"""

import json
import re
import time
import warnings
import threading
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from playwright.sync_api import sync_playwright

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ── Configuration ────────────────────────────────────────────────────────────
BASE_URL = "https://www.gebiz.gov.sg"
SEARCH_URL = f"{BASE_URL}/ptn/supplier/directory/index.xhtml"
PROFILE_BASE = f"{BASE_URL}/ptn/supplier/directory/searchDetail.xhtml"

SUPPLY_HEADS = [
    "EPU/CMP/10",   # Computer Related Hardware, Software, and Services
    "EPU/SER/35",   # Service (Training of Personnel)
    "EPU/SER/34",   # Service (Consultant)
    "EPU/SER/19",   # Service (Data Entry, Supply of Manpower)
    "EPU/SER/30",   # Service (Management)
]

OUTPUT_DIR = Path(__file__).parent
JSON_OUT = OUTPUT_DIR / "suppliers.json"
HTML_OUT = OUTPUT_DIR / "gebiz_suppliers.html"
LISTING_CACHE = OUTPUT_DIR / "listing_cache.json"

PROFILE_WORKERS = 1   # MUST be 1 — server session is stateful, concurrent requests corrupt results
PROFILE_DELAY = 0.15  # seconds between profile requests
PAGE_DELAY = 0.8      # seconds between listing page navigations
SAVE_INTERVAL = 100   # save JSON every N profiles fetched

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Listing phase ─────────────────────────────────────────────────────────────

def extract_listing_page(html: str) -> list[dict]:
    """Extract supplier entries from a listing page HTML."""
    soup = BeautifulSoup(html, "lxml")
    entries = []
    links = soup.find_all("a", href=lambda h: h and "searchDetail" in h)
    for link in links:
        href = link.get("href", "")
        code = href.split("code=")[1] if "code=" in href else ""
        name = link.get_text(strip=True)
        if code and name:
            # Try to get UEN + phone from the page text near this link
            entries.append({"code": code, "name": name})
    return entries


def dismiss_dialogs(page) -> None:
    """Dismiss any session-expiry or confirmation dialogs on the page."""
    try:
        ok_btn = page.query_selector("input[value='OK'][type='submit'], button:has-text('OK')")
        if ok_btn and ok_btn.is_visible():
            ok_btn.click()
            time.sleep(0.5)
    except Exception:
        pass


def wait_for_page_ready(page, timeout: int = 15000) -> None:
    """Wait for loading overlays to disappear and page to be interactive."""
    try:
        # Wait for loading screens to disappear
        page.wait_for_selector(".loadingScreen_BOX-OUTER", state="hidden", timeout=timeout)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    dismiss_dialogs(page)


def click_next_btn(page) -> bool:
    """Click the Next button with retry logic. Returns False if no Next button."""
    for attempt in range(3):
        try:
            wait_for_page_ready(page)
            next_btn = page.query_selector("input[id*='_Next_']")
            if not next_btn:
                return False
            # Scroll into view and click
            next_btn.scroll_into_view_if_needed()
            time.sleep(0.3)
            next_btn.click(timeout=10000)
            return True
        except Exception as e:
            if attempt == 2:
                print(f"\n  Next button click failed (attempt {attempt+1}): {e}")
                return False
            time.sleep(1.0)
            dismiss_dialogs(page)
    return False


def fetch_profile_inline(page, code: str, existing: dict = None) -> dict:
    """Fetch a single profile using page.request.get() (same browser session, codes stay valid)."""
    url = f"{PROFILE_BASE}?code={code}"
    try:
        response = page.request.get(url, headers=HEADERS, timeout=20000)
        html = response.text()
        profile = parse_profile(html, code)
        if not profile.get("name") or profile["name"] in ("Supplier Name", ""):
            time.sleep(0.5)
            response2 = page.request.get(url, headers=HEADERS, timeout=20000)
            profile = parse_profile(response2.text(), code)
        return profile
    except Exception as e:
        return existing or {"code": code, "name": "", "error": str(e)}


def scrape_listings_and_profiles(
    supply_head_code: str,
    page,
    existing_profiles: dict,
    results: dict,
    json_out_path,
    save_interval: int = 100,
) -> int:
    """
    Interleaved scraper: for each listing page, immediately fetch profiles for
    those 10 suppliers while their ?code= URLs are still valid in the current session.
    Returns number of new profiles fetched.
    """
    print(f"\n  Loading search page for {supply_head_code}...")
    page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
    time.sleep(1.5)
    dismiss_dialogs(page)

    dropdown_btn = page.query_selector("#contentForm\\:j_idt156_BUTTON")
    if not dropdown_btn:
        print("  ERROR: dropdown button not found")
        return 0
    dropdown_btn.click()
    time.sleep(0.8)

    btn = page.query_selector(f'button[label*="{supply_head_code}"]')
    if not btn:
        print(f"  ERROR: no button for {supply_head_code}")
        return 0
    btn.click()
    time.sleep(1.2)

    search_btn = page.query_selector("input[name='contentForm:search']")
    if not search_btn:
        print("  ERROR: search button not found")
        return 0
    search_btn.click()
    wait_for_page_ready(page, timeout=30000)
    time.sleep(0.5)

    body = page.inner_text("body")
    m = re.search(r"(\d[\d,]*)\s+results?\s+found", body)
    total = int(m.group(1).replace(",", "")) if m else 0
    print(f"  Found {total} suppliers for {supply_head_code}", flush=True)
    if total == 0:
        return 0

    new_fetched = 0
    page_num = 1
    max_pages = (total // 10) + 2

    while page_num <= max_pages:
        # Guard against race: page might still be navigating when content() is called
        for _attempt in range(3):
            try:
                wait_for_page_ready(page, timeout=15000)
                html = page.content()
                break
            except Exception as _e:
                if _attempt == 2:
                    raise
                time.sleep(1.5)
        entries = extract_listing_page(html)

        if not entries:
            if not click_next_btn(page):
                break
            wait_for_page_ready(page, timeout=30000)
            time.sleep(PAGE_DELAY)
            page_num += 1
            continue

        # Fetch profiles for this page's 10 suppliers IMMEDIATELY (while codes are valid)
        for entry in entries:
            code = entry["code"]
            if code in results and results[code].get("name") and results[code]["name"] not in ("Supplier Name", ""):
                continue  # already have good data for this code
            time.sleep(PROFILE_DELAY)
            profile = fetch_profile_inline(page, code, existing_profiles.get(code))
            results[code] = profile
            if profile.get("name") and profile["name"] not in ("Supplier Name", ""):
                new_fetched += 1

        pct = page_num / max_pages * 100
        good_total = sum(1 for p in results.values() if p.get("name") and p["name"] not in ("Supplier Name", ""))
        print(f"  {supply_head_code} pg {page_num}/{max_pages} ({pct:.0f}%) | profiles: {good_total} total", end="\r", flush=True)

        # Periodic save
        if good_total % save_interval < 10:  # save roughly every save_interval good profiles
            _partial = sorted(results.values(), key=lambda s: s.get("name", "").lower())
            with open(json_out_path, "w", encoding="utf-8") as f:
                json.dump(_partial, f, ensure_ascii=False, indent=2)

        if not click_next_btn(page):
            print(f"\n  {supply_head_code}: Done at page {page_num}. New profiles this run: {new_fetched}", flush=True)
            break
        wait_for_page_ready(page, timeout=30000)
        time.sleep(PAGE_DELAY)
        page_num += 1

    return new_fetched


def scrape_listings(supply_head_code: str, page, ctx) -> list[dict]:
    """Use an existing Playwright page to search a supply head and collect all entries."""
    print(f"\n  Loading search page for {supply_head_code}...")
    page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
    time.sleep(1.5)
    dismiss_dialogs(page)

    # Open the Supply Head dropdown
    dropdown_btn = page.query_selector("#contentForm\\:j_idt156_BUTTON")
    if not dropdown_btn:
        print("  ERROR: dropdown button not found")
        return []
    dropdown_btn.click()
    time.sleep(0.8)

    # Click the matching supply head
    btn = page.query_selector(f'button[label*="{supply_head_code}"]')
    if not btn:
        print(f"  ERROR: no button found for {supply_head_code}")
        return []
    btn.click()
    time.sleep(1.2)

    # Click Search
    search_btn = page.query_selector("input[name='contentForm:search']")
    if not search_btn:
        print("  ERROR: search button not found")
        return []
    search_btn.click()
    wait_for_page_ready(page, timeout=30000)
    time.sleep(0.5)

    # Check result count
    body = page.inner_text("body")
    m = re.search(r"(\d[\d,]*)\s+results?\s+found", body)
    total = int(m.group(1).replace(",", "")) if m else 0
    print(f"  Found {total} suppliers for {supply_head_code}")
    if total == 0:
        return []

    all_entries = []
    page_num = 1
    empty_pages = 0
    max_pages = (total // 10) + 2  # slightly over to handle edge cases

    while page_num <= max_pages:
        html = page.content()
        entries = extract_listing_page(html)

        if not entries:
            empty_pages += 1
            if empty_pages >= 3:
                print(f"\n  3 consecutive empty pages — stopping.")
                break
        else:
            empty_pages = 0

        all_entries.extend(entries)
        print(f"  Page {page_num}/{max_pages}: +{len(entries)} entries ({len(all_entries)} total)", end="\r", flush=True)

        # Click Next (will return False when no button or click fails)
        if not click_next_btn(page):
            print(f"\n  No more pages. Done at page {page_num}.")
            break

        wait_for_page_ready(page, timeout=30000)
        time.sleep(PAGE_DELAY)
        page_num += 1

    print(f"  Collected {len(all_entries)} entries for {supply_head_code}")
    return all_entries


# ── Profile parsing ───────────────────────────────────────────────────────────

def parse_profile(html: str, code: str) -> dict:
    """Parse a supplier profile page into a structured dict."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n", strip=True)
    lines = [l for l in text.split("\n") if l.strip()]

    # Find start of actual profile (after nav/dropdown)
    # Look for "Trading Partner Ref" pattern
    start = 0
    for i, line in enumerate(lines):
        if "Trading Partner Ref" in line or "Trading Partner Ref. No." in line:
            start = max(0, i - 1)
            break

    lines = lines[start:]

    result = {
        "code": code,
        "uen": "",
        "name": "",
        "description": "",
        "company_url": "",
        "country": "",
        "city": "",
        "address_1": "",
        "address_2": "",
        "address_3": "",
        "postal_code": "",
        "phone": "",
        "fax": "",
        "email": "",
        "supply_heads": [],
    }

    # Extract UEN from "Trading Partner Ref. No. XXXXXXXXX"
    for line in lines[:5]:
        m = re.search(r"(?:Trading Partner Ref\.?\s*No\.?\s*)([A-Z0-9]+)", line)
        if m:
            result["uen"] = m.group(1)
            break

    # Extract name (appears before COMPANY PROFILE)
    for i, line in enumerate(lines):
        if line == "COMPANY PROFILE":
            if i > 0:
                result["name"] = lines[i - 1]
            break

    # State machine to parse sections
    SECTION_COMPANY = "company"
    SECTION_ADDRESS = "address"
    SECTION_SUPPLY = "supply"
    SECTION_OTHER = "other"

    section = SECTION_OTHER
    field_pointer = None
    desc_lines = []
    supply_rows = []

    i = 0
    while i < len(lines):
        line = lines[i]

        if line == "COMPANY PROFILE":
            section = SECTION_COMPANY
            field_pointer = None
            i += 1
            continue
        elif line == "REGISTERED ADDRESS":
            # Finalize description
            if desc_lines:
                result["description"] = "\n".join(desc_lines).strip()
            section = SECTION_ADDRESS
            field_pointer = None
            i += 1
            continue
        elif line == "AREAS OF BUSINESS":
            section = SECTION_OTHER
            i += 1
            continue
        elif line == "SUPPLY HEADS":
            section = SECTION_SUPPLY
            i += 1
            continue

        if section == SECTION_COMPANY:
            if line == "Description":
                field_pointer = "description"
            elif line == "Company Url":
                if desc_lines:
                    result["description"] = "\n".join(desc_lines).strip()
                    desc_lines = []
                field_pointer = "company_url"
            elif field_pointer == "description":
                desc_lines.append(line)
            elif field_pointer == "company_url":
                result["company_url"] = line
                field_pointer = None

        elif section == SECTION_ADDRESS:
            if line == "Country":
                field_pointer = "country"
            elif line in ("State", "Province"):
                field_pointer = line.lower()  # skip these fields
            elif line == "City":
                field_pointer = "city"
            elif line == "Address Line 1":
                field_pointer = "address_1"
            elif line == "Address Line 2":
                field_pointer = "address_2"
            elif line == "Address Line 3":
                field_pointer = "address_3"
            elif line == "Postal/Zip Code":
                field_pointer = "postal_code"
            elif line == "Area Code":
                field_pointer = "area_code"  # discard
            elif line == "Contact No.":
                field_pointer = "phone"
            elif line == "Fax No.":
                field_pointer = "fax"
            elif line == "Email":
                field_pointer = "email"
            elif field_pointer and field_pointer in result:
                # Avoid double-setting with the field label itself
                if line not in ("Country", "State", "City", "Province",
                                "Address Line 1", "Address Line 2", "Address Line 3",
                                "Postal/Zip Code", "Area Code", "Contact No.", "Fax No.", "Email"):
                    if not result[field_pointer]:  # don't overwrite
                        result[field_pointer] = line
                    field_pointer = None
            # For area_code, just move on
            elif field_pointer == "area_code":
                field_pointer = None  # skip the value

        elif section == SECTION_SUPPLY:
            # Parse supply head table rows
            # Pattern: "N." line followed by supply_head, financial_grade, expiry_date, status
            if line in ("S/N", "Supply Head", "Financial Grade", "Expiry Date", "Status"):
                i += 1
                continue
            if line.startswith("Showing "):
                break  # End of supply heads table
            # Rows come as: "1." | "EPU/..." | "S8..." | "01 Jan 2028" | "APPROVED"
            if re.match(r"^\d+\.$", line):
                supply_rows.append({"sn": line.rstrip(".")})
                i += 1
                continue
            if supply_rows and "supply_head" not in supply_rows[-1]:
                supply_rows[-1]["supply_head"] = line
                i += 1
                continue
            if supply_rows and "financial_grade" not in supply_rows[-1]:
                supply_rows[-1]["financial_grade"] = line
                i += 1
                continue
            if supply_rows and "expiry_date" not in supply_rows[-1]:
                supply_rows[-1]["expiry_date"] = line
                i += 1
                continue
            if supply_rows and "status" not in supply_rows[-1]:
                supply_rows[-1]["status"] = line
                i += 1
                continue

        i += 1

    # Convert supply rows to final format
    for row in supply_rows:
        sh_text = row.get("supply_head", "")
        m = re.match(r"^([A-Z]+/[A-Z]+/\d+)\s*-?\s*(.*)", sh_text)
        if m:
            code_part = m.group(1)
            name_part = m.group(2)
        else:
            code_part = ""
            name_part = sh_text
        result["supply_heads"].append({
            "code": code_part,
            "name": name_part or sh_text,
            "full": sh_text,
            "financial_grade": row.get("financial_grade", ""),
            "expiry_date": row.get("expiry_date", ""),
            "status": row.get("status", ""),
        })

    # If name not found, try from the first non-empty line
    if not result["name"] and lines:
        result["name"] = lines[0]

    return result


def fetch_profile(code: str, session: requests.Session, existing: dict = None) -> dict:
    """Fetch and parse a single supplier profile."""
    url = f"{PROFILE_BASE}?code={code}"
    try:
        r = session.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  WARNING: HTTP {r.status_code} for code={code}")
            return existing or {"code": code, "name": "", "error": f"HTTP {r.status_code}"}

        # Check if we got actual profile content
        if "COMPANY PROFILE" not in r.text and "Trading Partner" not in r.text:
            return existing or {"code": code, "name": "", "error": "no_content"}

        return parse_profile(r.text, code)
    except Exception as e:
        return existing or {"code": code, "name": "", "error": str(e)}


# ── HTML builder ──────────────────────────────────────────────────────────────

def build_html(suppliers: list[dict]) -> str:
    """Build a single-file searchable HTML database."""

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    # Collect unique supply head codes
    all_sh_codes = sorted(set(
        sh["code"]
        for s in suppliers
        for sh in s.get("supply_heads", [])
        if sh.get("code")
    ))

    # Determine label for each supply head code
    sh_labels = {}
    for s in suppliers:
        for sh in s.get("supply_heads", []):
            if sh.get("code") and sh["code"] not in sh_labels:
                sh_labels[sh["code"]] = sh.get("full") or sh.get("name") or sh["code"]

    # Build EPU filter checkbox list HTML (for multi-select dropdown panel)
    epu_checkboxes_html = ""
    for code in all_sh_codes:
        label = sh_labels.get(code, code)
        epu_checkboxes_html += (
            f'<label class="epu-item" title="{esc(label)}">'
            f'<input type="checkbox" class="epu-cb" value="{esc(code)}"> '
            f'<span class="epu-code">{esc(code)}</span>'
            f'<span class="epu-label">{esc(label.split(" - ", 1)[-1] if " - " in label else label)}</span>'
            f'</label>\n'
        )

    # Build supplier cards
    cards_html = ""
    for s in suppliers:
        sh_codes = [sh["code"] for sh in s.get("supply_heads", []) if sh.get("code")]
        sh_attr = " ".join(sh_codes)
        sh_tags = ""
        for sh in s.get("supply_heads", []):
            status_cls = "tag-approved" if sh.get("status") == "APPROVED" else "tag-other"
            sh_tags += (
                f'<span class="sh-tag {status_cls}" title="{esc(sh.get("financial_grade",""))} | '
                f'Exp: {esc(sh.get("expiry_date",""))} | {esc(sh.get("status",""))}">'
                f'{esc(sh.get("code","") or sh.get("name",""))}</span>'
            )

        desc_full = esc(s.get("description", ""))
        ai_summary = s.get("description_short", "")
        # Card face: show AI summary if available, otherwise nothing (no raw truncation)
        has_ai_summary = bool(ai_summary)
        desc_short = esc(ai_summary)

        addr_parts = [s.get("address_1"), s.get("address_2"), s.get("address_3")]
        addr_parts = [a for a in addr_parts if a]
        address_str = ", ".join(addr_parts)
        if s.get("postal_code"):
            address_str += f" {s.get('postal_code')}"
        if s.get("city"):
            address_str = address_str or s.get("city")

        contact_items = ""
        if s.get("phone"):
            contact_items += f'<span class="contact-item">📞 {esc(s.get("phone",""))}</span>'
        if s.get("fax"):
            contact_items += f'<span class="contact-item">🖷 {esc(s.get("fax",""))}</span>'
        if s.get("email"):
            contact_items += f'<span class="contact-item"><a href="mailto:{esc(s.get("email",""))}">{esc(s.get("email",""))}</a></span>'
        if s.get("company_url"):
            url_display = s.get("company_url", "")
            url_href = url_display if url_display.startswith("http") else "https://" + url_display
            contact_items += f'<span class="contact-item"><a href="{esc(url_href)}" target="_blank" rel="noopener">{esc(url_display)}</a></span>'

        # Build supply heads detail table
        sh_table = ""
        if s.get("supply_heads"):
            sh_table = '<table class="sh-table"><thead><tr><th>Supply Head</th><th>Grade</th><th>Expiry</th><th>Status</th></tr></thead><tbody>'
            for sh in s.get("supply_heads", []):
                status_cls = "status-approved" if sh.get("status") == "APPROVED" else "status-other"
                sh_table += (
                    f'<tr><td>{esc(sh.get("full") or sh.get("name",""))}</td>'
                    f'<td>{esc(sh.get("financial_grade",""))}</td>'
                    f'<td>{esc(sh.get("expiry_date",""))}</td>'
                    f'<td class="{status_cls}">{esc(sh.get("status",""))}</td></tr>'
                )
            sh_table += "</tbody></table>"

        # Expanded address block
        addr_detail = ""
        if address_str:
            addr_detail += f'<div class="detail-row"><span class="detail-label">Address</span><span>{esc(address_str)}</span></div>'
        if s.get("city"):
            addr_detail += f'<div class="detail-row"><span class="detail-label">City</span><span>{esc(s.get("city",""))}</span></div>'

        cards_html += f"""
<div class="card" data-sh="{esc(sh_attr)}"
     data-name="{esc(s.get('name','').lower())}"
     data-uen="{esc(s.get('uen','').lower())}"
     data-desc="{esc((s.get('description') or '').lower())}">
  <div class="card-header">
    <div class="card-title-row">
      <span class="uen-badge">{esc(s.get("uen",""))}</span>
      <h3 class="company-name">{esc(s.get("name",""))}</h3>
    </div>
    <div class="sh-tags">{sh_tags}</div>
  </div>
  <div class="card-body">
    {"" if not has_ai_summary else f'<p class="ai-summary">{desc_short}</p>'}
    <div class="contact-bar">{contact_items}</div>
  </div>
  <div class="card-expanded" style="display:none">
    {addr_detail}
    {"" if not desc_full else f'<div class="detail-row detail-desc"><span class="detail-label">About</span><span>{desc_full}</span></div>'}
    {sh_table}
  </div>
  <button class="btn-expand" onclick="toggleCard(this)">▼ Details</button>
</div>
"""

    # Compact supplier data for CSV export (only fields needed)
    csv_data_js = json.dumps([
        {
            "uen": s.get("uen", ""),
            "name": s.get("name", ""),
            "summary": s.get("description_short", ""),
            "description": (s.get("description") or "").replace("\n", " "),
            "address": ", ".join(filter(None, [s.get("address_1"), s.get("address_2"), s.get("address_3")])),
            "postal_code": s.get("postal_code", ""),
            "city": s.get("city", ""),
            "phone": s.get("phone", ""),
            "fax": s.get("fax", ""),
            "email": s.get("email", ""),
            "website": s.get("company_url", ""),
            "supply_heads": "; ".join(sh.get("code", "") for sh in s.get("supply_heads", []) if sh.get("code")),
            "sh_full": "; ".join(sh.get("full", "") for sh in s.get("supply_heads", []) if sh.get("full")),
            "sh_codes_arr": [sh.get("code", "") for sh in s.get("supply_heads", []) if sh.get("code")],
        }
        for s in suppliers
    ], ensure_ascii=False)

    # Count
    total = len(suppliers)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GeBIZ Supplier Directory — {total} suppliers</title>
<style>
:root {{
  --bg: #f8f9fa;
  --card-bg: #ffffff;
  --border: #e2e8f0;
  --primary: #2563eb;
  --primary-light: #dbeafe;
  --text: #1e293b;
  --text-muted: #64748b;
  --approved: #16a34a;
  --approved-bg: #dcfce7;
  --radius: 10px;
  --shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
}}

.top-bar {{
  background: var(--primary);
  color: white;
  padding: 16px 24px;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}}

.top-bar-inner {{
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}}

.top-bar h1 {{ font-size: 1.1rem; font-weight: 700; white-space: nowrap; }}
.top-bar h1 small {{ font-weight: 400; opacity: 0.8; }}

#search-input {{
  flex: 1;
  min-width: 200px;
  padding: 8px 14px;
  border-radius: 8px;
  border: 2px solid rgba(255,255,255,0.3);
  background: rgba(255,255,255,0.15);
  color: white;
  font-size: 0.95rem;
  outline: none;
  transition: border-color 0.2s;
}}
#search-input::placeholder {{ color: rgba(255,255,255,0.6); }}
#search-input:focus {{ border-color: white; background: rgba(255,255,255,0.25); }}

#sort-select {{
  padding: 8px 12px;
  border-radius: 8px;
  border: 2px solid rgba(255,255,255,0.3);
  background: rgba(255,255,255,0.15);
  color: white;
  font-size: 0.9rem;
  cursor: pointer;
}}

.filter-bar {{
  background: white;
  border-bottom: 1px solid var(--border);
  padding: 10px 24px;
  position: sticky;
  top: 57px;
  z-index: 99;
  overflow-x: auto;
  white-space: nowrap;
}}

.filter-bar-inner {{
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  gap: 8px;
  align-items: center;
}}

.filter-bar-inner label {{
  font-size: 0.8rem;
  color: var(--text-muted);
  font-weight: 600;
  white-space: nowrap;
  margin-right: 4px;
}}

.chip {{
  padding: 5px 12px;
  border-radius: 20px;
  border: 1.5px solid var(--border);
  background: white;
  color: var(--text-muted);
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}}
.chip:hover {{ border-color: var(--primary); color: var(--primary); }}
.chip.active {{ background: var(--primary); border-color: var(--primary); color: white; }}

.content {{
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px 24px;
}}

.results-bar {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  font-size: 0.9rem;
  color: var(--text-muted);
}}

.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 16px;
}}

.card {{
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
  transition: box-shadow 0.2s, transform 0.1s;
}}
.card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.1); transform: translateY(-1px); }}
.card.hidden {{ display: none; }}

.card-header {{
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--border);
}}

.card-title-row {{
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}}

.uen-badge {{
  background: #f1f5f9;
  color: var(--text-muted);
  font-size: 0.72rem;
  font-family: monospace;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--border);
  white-space: nowrap;
  margin-top: 2px;
  flex-shrink: 0;
}}

.company-name {{
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.3;
}}

.sh-tags {{
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}}

.sh-tag {{
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
  cursor: default;
}}

.tag-approved {{ background: var(--approved-bg); color: var(--approved); }}
.tag-other {{ background: #f1f5f9; color: var(--text-muted); }}

.card-body {{ padding: 12px 16px; }}

.ai-summary {{
  font-size: 0.84rem;
  color: var(--text);
  line-height: 1.5;
  margin: 0 0 10px 0;
}}

.detail-desc span {{
  font-size: 0.83rem;
  color: var(--text-muted);
  line-height: 1.6;
  white-space: pre-wrap;
}}

.description {{
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-bottom: 10px;
  line-height: 1.5;
}}

.btn-more {{
  background: none;
  border: none;
  color: var(--primary);
  font-size: 0.8rem;
  cursor: pointer;
  padding: 0;
  margin-left: 4px;
}}

.contact-bar {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 0.82rem;
}}

.contact-item {{
  color: var(--text-muted);
  white-space: nowrap;
}}

.contact-item a {{ color: var(--primary); text-decoration: none; }}
.contact-item a:hover {{ text-decoration: underline; }}

.card-expanded {{
  padding: 0 16px 0;
  border-top: 1px solid var(--border);
  background: #f8fafc;
}}

.card-expanded .detail-row {{
  display: flex;
  gap: 10px;
  padding: 6px 0;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--border);
}}
.card-expanded .detail-row:last-of-type {{ border-bottom: none; }}
.detail-label {{
  font-weight: 600;
  color: var(--text-muted);
  min-width: 60px;
  flex-shrink: 0;
}}

.sh-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  margin: 8px 0;
}}
.sh-table th, .sh-table td {{
  padding: 5px 8px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}}
.sh-table th {{ font-weight: 700; color: var(--text-muted); background: #f1f5f9; }}
.status-approved {{ color: var(--approved); font-weight: 600; }}
.status-other {{ color: var(--text-muted); }}

.btn-expand {{
  width: 100%;
  padding: 8px;
  background: none;
  border: none;
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 0.8rem;
  cursor: pointer;
  transition: background 0.15s;
}}
.btn-expand:hover {{ background: #f1f5f9; }}

.no-results {{
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
  font-size: 1rem;
  display: none;
}}

@media (max-width: 600px) {{
  .grid {{ grid-template-columns: 1fr; }}
  .top-bar-inner {{ flex-direction: column; align-items: stretch; }}
}}
</style>
</head>
<body>

<div class="top-bar">
  <div class="top-bar-inner">
    <h1>GeBIZ Supplier Database <small>({total} suppliers)</small></h1>
    <input type="text" id="search-input" placeholder="Search by name, UEN, or description…" oninput="filterCards()" autocomplete="off">
    <select id="sort-select" onchange="sortCards()">
      <option value="name">Sort: Name A–Z</option>
      <option value="uen">Sort: UEN</option>
    </select>
  </div>
</div>

<div class="filter-bar">
  <div class="filter-bar-inner">
    <label>Supply Head:</label>
    {chips_html}
  </div>
</div>

<div class="content">
  <div class="results-bar">
    <span id="results-count">{total} suppliers</span>
    <span id="active-filter">Showing all</span>
  </div>
  <div class="grid" id="cards-grid">
{cards_html}
  </div>
  <div class="no-results" id="no-results">No suppliers match your search.</div>
</div>

<script>
const cards = Array.from(document.querySelectorAll('.card'));
let activeShFilter = 'ALL';

function filterCards() {{
  const q = document.getElementById('search-input').value.toLowerCase().trim();
  let visible = 0;
  cards.forEach(card => {{
    const name = card.dataset.name || '';
    const uen = card.dataset.uen || '';
    const desc = card.dataset.desc || '';
    const shData = card.dataset.sh || '';

    const matchText = !q || name.includes(q) || uen.includes(q) || desc.includes(q);
    const matchSh = activeShFilter === 'ALL' || shData.split(' ').includes(activeShFilter);

    if (matchText && matchSh) {{
      card.classList.remove('hidden');
      visible++;
    }} else {{
      card.classList.add('hidden');
    }}
  }});
  document.getElementById('results-count').textContent = visible + ' supplier' + (visible !== 1 ? 's' : '');
  document.getElementById('no-results').style.display = visible === 0 ? 'block' : 'none';
}}

function sortCards() {{
  const grid = document.getElementById('cards-grid');
  const val = document.getElementById('sort-select').value;
  const sorted = [...cards].sort((a, b) => {{
    if (val === 'name') return (a.dataset.name || '').localeCompare(b.dataset.name || '');
    if (val === 'uen') return (a.dataset.uen || '').localeCompare(b.dataset.uen || '');
    return 0;
  }});
  sorted.forEach(c => grid.appendChild(c));
  filterCards();
}}

document.querySelectorAll('.chip').forEach(chip => {{
  chip.addEventListener('click', () => {{
    document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    activeShFilter = chip.dataset.sh;
    const label = activeShFilter === 'ALL' ? 'all' : activeShFilter;
    document.getElementById('active-filter').textContent = 'Filter: ' + label;
    filterCards();
  }});
}});

function toggleDesc(btn) {{
  const short = btn.previousElementSibling.previousElementSibling;
  const full = btn.previousElementSibling;
  if (full.style.display === 'none') {{
    full.style.display = 'inline';
    short.style.display = 'none';
    btn.textContent = 'Show less';
  }} else {{
    full.style.display = 'none';
    short.style.display = 'inline';
    btn.textContent = 'Show more';
  }}
}}

function toggleCard(btn) {{
  const expanded = btn.previousElementSibling;
  if (expanded.style.display === 'none') {{
    expanded.style.display = 'block';
    btn.textContent = '▲ Hide details';
  }} else {{
    expanded.style.display = 'none';
    btn.textContent = '▼ Details';
  }}
}}
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("GeBIZ Supplier Directory Scraper (Interleaved Mode)")
    print("=" * 60)

    # Load existing profiles from JSON (for resuming interrupted runs)
    existing_profiles = {}
    if JSON_OUT.exists():
        try:
            with open(JSON_OUT) as f:
                existing_list = json.load(f)
            existing_profiles = {s["code"]: s for s in existing_list if "code" in s}
            # Also build UEN index for deduplication
            seen_uens_loaded = {s.get("uen"): s["code"] for s in existing_list if s.get("uen")}
            print(f"Loaded {len(existing_profiles)} existing profiles from {JSON_OUT.name}")
        except Exception as e:
            print(f"Could not load existing profiles: {e}")
            existing_profiles = {}
            seen_uens_loaded = {}
    else:
        seen_uens_loaded = {}

    results = dict(existing_profiles)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = ctx.new_page()

        # ── Phase 1+2 Combined: For each supply head, interleave listing + profile fetch ──
        for sh_code in SUPPLY_HEADS:
            print(f"\n[{sh_code}] Starting interleaved scrape...")
            new_profiles = scrape_listings_and_profiles(
                supply_head_code=sh_code,
                page=page,
                existing_profiles=existing_profiles,
                results=results,
                json_out_path=JSON_OUT,
                save_interval=SAVE_INTERVAL,
            )
            print(f"  Completed {sh_code}: {new_profiles} new profiles fetched", flush=True)

            # Save after each supply head completes
            _partial = sorted(results.values(), key=lambda s: s.get("name", "").lower())
            with open(JSON_OUT, "w", encoding="utf-8") as f:
                json.dump(_partial, f, ensure_ascii=False, indent=2)
            print(f"  Saved {len(_partial)} total profiles to JSON", flush=True)

        browser.close()

    # Build final supplier list with UEN-based deduplication
    # (same company may appear under multiple supply heads with different codes)
    all_supplier_values = sorted(results.values(), key=lambda s: s.get("name", "").lower())

    # Deduplicate by UEN: keep the entry with the most supply heads
    seen_uens = {}
    final_suppliers = []
    for s in all_supplier_values:
        uen = s.get("uen") or ""
        name = s.get("name") or ""
        if not name or name in ("Supplier Name", "") or s.get("error"):
            continue  # skip bad entries
        if uen and uen in seen_uens:
            # Merge supply_heads from duplicate into existing
            existing = seen_uens[uen]
            existing_sh_codes = {sh["code"] for sh in existing.get("supply_heads", [])}
            for sh in s.get("supply_heads", []):
                if sh["code"] not in existing_sh_codes:
                    existing.setdefault("supply_heads", []).append(sh)
                    existing_sh_codes.add(sh["code"])
        else:
            final_suppliers.append(s)
            if uen:
                seen_uens[uen] = s

    print(f"\n  After UEN dedup: {len(final_suppliers)} unique suppliers")

    # Save JSON
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(final_suppliers, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(final_suppliers)} suppliers to {JSON_OUT}")

    # ── Phase 3: Build HTML ──
    print("\n[HTML] Building searchable database...")
    valid_suppliers = [s for s in final_suppliers if s.get("name")]
    print(f"  Valid suppliers: {len(valid_suppliers)}")
    html = build_html(valid_suppliers)
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved HTML to {HTML_OUT}")

    print("\n✓ Done!")
    print(f"  JSON: {JSON_OUT}")
    print(f"  HTML: {HTML_OUT}")


if __name__ == "__main__":
    main()
