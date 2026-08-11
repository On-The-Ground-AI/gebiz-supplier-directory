"""
GeBIZ Supplier Directory Scraper
Discovers every Supply Head category from the live search dropdown and
scrapes all of them (previously hardcoded to a fixed subset of 5).

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
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from playwright.sync_api import sync_playwright

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ── Configuration ────────────────────────────────────────────────────────────
BASE_URL = "https://www.gebiz.gov.sg"
SEARCH_URL = f"{BASE_URL}/ptn/supplier/directory/index.xhtml"
PROFILE_BASE = f"{BASE_URL}/ptn/supplier/directory/searchDetail.xhtml"

# SUPPLY_HEADS is discovered at runtime from the live dropdown (see
# discover_supply_heads); this fallback is only used if discovery fails.
FALLBACK_SUPPLY_HEADS = [
    "EPU/CMP/10",   # Computer Related Hardware, Software, and Services
    "EPU/SER/35",   # Service (Training of Personnel)
    "EPU/SER/34",   # Service (Consultant)
    "EPU/SER/19",   # Service (Data Entry, Supply of Manpower)
    "EPU/SER/30",   # Service (Management)
]

OUTPUT_DIR = Path(__file__).parent
JSON_OUT = OUTPUT_DIR / "suppliers.json"
METADATA_OUT = OUTPUT_DIR / "scrape_metadata.json"
LISTING_CACHE = OUTPUT_DIR / "listing_cache.json"
DEBUG_DIR = OUTPUT_DIR / "debug"

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


def dump_debug(page, tag: str) -> None:
    """Save the page's HTML + a screenshot, and print candidate elements that
    look like the Supply Head dropdown, so a failed selector can be fixed
    from the artifacts instead of guessing blind."""
    DEBUG_DIR.mkdir(exist_ok=True)
    html_path = DEBUG_DIR / f"{tag}.html"
    png_path = DEBUG_DIR / f"{tag}.png"
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as e:
        print(f"  (debug dump: could not save HTML: {e})")
    try:
        page.screenshot(path=str(png_path), full_page=True)
    except Exception as e:
        print(f"  (debug dump: could not save screenshot: {e})")
    print(f"  DEBUG: saved {html_path} and {png_path}")

    try:
        candidates = page.eval_on_selector_all(
            "button, [role='button'], .ui-selectonemenu, select, [id*='BUTTON'], [id*='button']",
            """els => els.map(el => ({
                tag: el.tagName,
                id: el.id,
                cls: el.className,
                text: (el.innerText || el.textContent || '').trim().slice(0, 60),
            })).filter(c => c.id || c.text)"""
        )
        print(f"  DEBUG: {len(candidates)} candidate button/select elements found. Top matches:")
        # Surface anything that mentions "supply" first, since that's most likely relevant
        candidates.sort(key=lambda c: 0 if "supply" in (c["text"] or "").lower() else 1)
        for c in candidates[:25]:
            print(f"    <{c['tag']} id={c['id']!r} class={c['cls']!r}> {c['text']!r}")
    except Exception as e:
        print(f"  (debug dump: could not enumerate candidates: {e})")


def dismiss_dialogs(page) -> None:
    """Dismiss any session-expiry or confirmation dialogs on the page."""
    try:
        ok_btn = page.query_selector("input[value='OK'][type='submit'], button:has-text('OK')")
        if ok_btn and ok_btn.is_visible():
            ok_btn.click()
            time.sleep(0.5)
    except Exception:
        pass


def discover_supply_heads(page) -> list[str]:
    """Open the Supply Head dropdown on the search page and read every
    category code straight from the live options, instead of relying on a
    hardcoded list that goes stale as GeBIZ adds/renames categories."""
    print("Discovering available Supply Head categories...")
    page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
    time.sleep(1.5)
    dismiss_dialogs(page)

    dropdown_btn = page.query_selector("input.selectOneMenuSearchable_BUTTON")
    if not dropdown_btn:
        print("  ERROR: dropdown button not found during discovery")
        dump_debug(page, "discovery_dropdown_not_found")
        return []
    dropdown_btn.click()
    try:
        page.wait_for_selector("button.selectOneMenuSearchable_LIST-BUTTON", timeout=8000)
    except Exception:
        pass
    time.sleep(0.5)

    labels = page.eval_on_selector_all(
        "button.selectOneMenuSearchable_LIST-BUTTON",
        "els => els.map(el => (el.getAttribute('label') || el.innerText || el.textContent || '').trim())"
    )
    codes = []
    for label in labels:
        m = re.match(r"^([A-Z]+/[A-Z]+/\d+)", label)
        if m:
            codes.append(m.group(1))

    print(f"  Found {len(codes)} Supply Head categories")
    if not codes:
        dump_debug(page, "discovery_no_labels")
    return codes


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

    dropdown_btn = page.query_selector("input.selectOneMenuSearchable_BUTTON")
    if not dropdown_btn:
        print("  ERROR: dropdown button not found")
        dump_debug(page, f"{supply_head_code.replace('/', '-')}_dropdown_not_found")
        return 0
    dropdown_btn.click()
    time.sleep(0.8)

    btn = page.query_selector(f'button[label*="{supply_head_code}"]')
    if not btn:
        print(f"  ERROR: no button for {supply_head_code}")
        dump_debug(page, f"{supply_head_code.replace('/', '-')}_option_not_found")
        return 0
    btn.click()
    time.sleep(1.2)

    search_btn = page.query_selector("input[name='contentForm:search']")
    if not search_btn:
        print("  ERROR: search button not found")
        dump_debug(page, f"{supply_head_code.replace('/', '-')}_search_btn_not_found")
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

        # Fetch profiles for this page's 10 suppliers IMMEDIATELY (while codes are valid).
        # Always re-fetch, even if we already have data from a previous run: a supplier's
        # supply head status/grade/expiry can change between scrapes, and silently trusting
        # stale data here is exactly what caused a supplier's info to go stale unnoticed.
        for entry in entries:
            code = entry["code"]
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

        supply_heads = discover_supply_heads(page) or FALLBACK_SUPPLY_HEADS
        if supply_heads == FALLBACK_SUPPLY_HEADS:
            print(f"  Using fallback list of {len(supply_heads)} supply heads (discovery failed)")
        print(f"Scraping {len(supply_heads)} supply heads: {', '.join(supply_heads)}")

        # ── Phase 1+2 Combined: For each supply head, interleave listing + profile fetch ──
        for sh_code in supply_heads:
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

    # Stamp when this scrape completed, so the site can show "last updated"
    with open(METADATA_OUT, "w", encoding="utf-8") as f:
        json.dump({"last_scraped": datetime.now(timezone.utc).isoformat()}, f, indent=2)
    print(f"Saved scrape timestamp to {METADATA_OUT}")

    print("\n✓ Done! Run build_html.py separately to regenerate the site's index.html.")
    print(f"  JSON: {JSON_OUT}")


if __name__ == "__main__":
    main()
