"""
Fill gaps left by the per-supply-head scrape.

Some suppliers are not reachable through any single supply-head search (the
unfiltered search reports more results than the 45 heads add up to). This
walks the unfiltered "All" search and fetches a profile for every listed
supplier not already in suppliers.json. Profile codes only work inside the
search session that listed them, so profiles are fetched while paginating.
Run after scrape_gebiz.py, then build_html.py.
"""
import sys, json, time
sys.path.insert(0, "/Users/seehaojun/Desktop/OTG/Apps/gebiz-supplier-directory")
import scrape_gebiz as g
from playwright.sync_api import sync_playwright
path=g.JSON_OUT
have={s['code']:s for s in json.load(open(path))}
uens={s['uen'] for s in have.values()}
added=bad=0; n=1
def save():
    json.dump(sorted(have.values(),key=lambda s:s.get("name","").lower()),open(path,"w"),ensure_ascii=False,indent=2)
with sync_playwright() as p:
    b=p.chromium.launch(headless=True); pg=b.new_context(user_agent=g.HEADERS["User-Agent"]).new_page()
    pg.goto(g.SEARCH_URL,wait_until="networkidle",timeout=60000); time.sleep(1.5); g.dismiss_dialogs(pg)
    pg.query_selector("input[name='contentForm:search']").click(); time.sleep(3)
    while True:
        g.wait_for_page_ready(pg,15000)
        for e in g.extract_listing_page(pg.content()):
            c=e["code"]
            if c in have: continue
            time.sleep(g.PROFILE_DELAY)
            prof,fresh=g.fetch_profile_inline(pg,c,None)
            if fresh and prof.get("uen") and prof.get("name") and prof["name"]!="Supplier Name":
                if prof["uen"] in uens: continue  # same company already held under another code
                have[c]=prof; uens.add(prof["uen"]); added+=1
                if added%50==0: save()
            else: bad+=1
        print(f"pg {n} added={added} bad={bad} total={len(have)}",end="\r",flush=True)
        if not g.click_next_btn(pg): break
        time.sleep(g.PAGE_DELAY); n+=1
    b.close()
save(); print("\nDONE added",added,"bad",bad,"total",len(have))
