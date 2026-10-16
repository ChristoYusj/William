"""End-to-end test of the Firefox extension in a headless Firefox (Selenium), against live Apertus.

    LLM_API_KEY=... python tests/e2e_firefox.py [outdir]

The key is written into the throwaway profile's extension storage by script (never typed, printed or saved).
Checks: PDF auto-redirect to the viewer, page rendering + text layer, document summary + topic highlights + news,
selection summary, extraction table with provenance, JSON download; batch page with 3 links (incl. a bad one),
JSON + PDF downloads; settings page; popup; in-page summary panel.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "src" / "extension"
UUID = "0e0c6b8a-1d1b-4a8e-9c1a-7a11a0000001"
BASE = f"moz-extension://{UUID}"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "eval" / "e2e")
OUT.mkdir(parents=True, exist_ok=True)
DL = OUT / "downloads"
DL.mkdir(exist_ok=True)
for f in DL.iterdir():
    f.unlink()

OPD_PDF = "https://files.openparldata.ch/doc/5192/592b1e53ea42d39cd74b6c66309cd362b91b0eb79393ee48b58137b3aaa9f283"
BATCH = ["https://api.openparldata.ch/v1/docs/928926", "https://api.openparldata.ch/v1/docs/448120",
         "https://example.invalid/missing.pdf"]

results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), str(detail)[:1500]))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)


def wait(d, cond, timeout=240, step=1.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = cond(d)
            if v:
                return v
        except Exception:
            pass
        time.sleep(step)
    return None


def go_ext(d, path):
    """Marionette refuses d.get(moz-extension://...). Enter via the web-accessible viewer, then move same-origin."""
    if not d.current_url.startswith(BASE):
        if not d.current_url.startswith("http"):
            d.get("https://example.com/")
        d.execute_script("location.href = arguments[0]", f"{BASE}/viewer/viewer.html")
        wait(d, lambda d: d.current_url.startswith(BASE), 15, 0.3)
    d.execute_script("location.href = arguments[0]", f"{BASE}/{path}")
    wait(d, lambda d: d.current_url.startswith(f"{BASE}/{path.split('?')[0]}") and
         d.execute_script("return document.readyState") == "complete", 15, 0.3)
    time.sleep(0.5)


def main():
    key = os.environ.get("LLM_API_KEY")
    if not key:
        sys.exit("LLM_API_KEY not set")
    o = Options()
    o.add_argument("-headless")
    o.set_preference("extensions.webextensions.uuids", json.dumps({"william@hackapertus.local": UUID}))
    o.set_preference("browser.download.folderList", 2)
    o.set_preference("browser.download.dir", str(DL))
    o.set_preference("browser.download.useDownloadDir", True)
    o.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/pdf,application/json")
    o.set_preference("pdfjs.disabled", True)
    from selenium.webdriver.firefox.service import Service
    # lets Marionette script moz-extension pages (treated as privileged since Firefox ~129)
    d = webdriver.Firefox(options=o, service=Service(service_args=["--allow-system-access"]))
    d.set_window_size(1400, 1000)
    try:
        d.install_addon(str(EXT), temporary=True)
        time.sleep(2)

        # ---- settings page: store key + defaults
        go_ext(d, "options/options.html")
        wait(d, lambda d: d.find_element(By.ID, "save"), 20)
        d.execute_async_script("const cb=arguments[arguments.length-1];"
                               "browser.storage.local.set({apiKey: arguments[0]}).then(()=>cb(true));", key)
        go_ext(d, "batch/batch.html")
        go_ext(d, "options/options.html")
        model = wait(d, lambda d: d.find_element(By.ID, "model").get_attribute("value"), 20)
        stored = d.execute_async_script("const cb=arguments[arguments.length-1];"
                                        "browser.storage.local.get('apiKey').then(s=>cb(!!s.apiKey));")
        check("settings: key stored, default model shown", stored and model == "swiss-ai/Apertus-v1.5-70B", model)

        # ---- PDF auto-redirect + viewer render
        d.get(OPD_PDF)
        ok = wait(d, lambda d: d.current_url.startswith(f"{BASE}/viewer/viewer.html"), 60)
        check("viewer: OPD PDF link auto-opens in William viewer", ok, d.current_url[:120])
        pages = wait(d, lambda d: len(d.find_elements(By.CSS_SELECTOR, ".page canvas")) or None, 60)
        spans = wait(d, lambda d: len(d.find_elements(By.CSS_SELECTOR, ".textLayer span")) or None, 60)
        check("viewer: pages rendered with selectable text layer", pages and spans, f"{pages} pages, {spans} text spans")
        d.save_screenshot(str(OUT / "viewer_render.png"))

        # ---- document summary
        d.find_element(By.ID, "bSum").click()
        summ = wait(d, lambda d: d.find_element(By.CSS_SELECTOR, "#out .w-summary").text, 240)
        topics = d.find_elements(By.CSS_SELECTOR, "#out .w-topic")
        inline = d.find_elements(By.CSS_SELECTOR, "#out .w-summary .w-topic")
        status = d.find_element(By.ID, "status").text
        check("viewer: document summary in document language", summ and "language it" in status, f"{status} | {summ[:120]}")
        check("viewer: topic highlights present (inline in summary)", len(topics) >= 1 and len(inline) >= 1,
              f"{len(inline)} inline / {len(topics)} total")
        if topics:
            topics[0].click()
            news = wait(d, lambda d: d.find_elements(By.CSS_SELECTOR, "#out .w-newsbox li a") or
                        d.find_elements(By.CSS_SELECTOR, "#out .w-news-empty"), 20)
            links = d.find_elements(By.CSS_SELECTOR, "#out .w-newsbox li a")
            hrefs = [a.get_attribute("href") for a in links]
            check("viewer: clicking a highlight lists Swiss news articles", links and all(h.startswith("https://") for h in hrefs),
                  f"{len(links)} articles, e.g. {links[0].text[:70] if links else '-'}")
        d.save_screenshot(str(OUT / "viewer_summary.png"))

        # ---- selection summary
        d.execute_script("""
            const spans=[...document.querySelectorAll('.textLayer span')].filter(s=>s.textContent.trim().length>3);
            const r=document.createRange(); r.setStartBefore(spans[5]); r.setEndAfter(spans[Math.min(spans.length-1,60)]);
            const s=getSelection(); s.removeAllRanges(); s.addRange(r);
            document.dispatchEvent(new Event('selectionchange'));""")
        time.sleep(1)
        enabled = d.find_element(By.ID, "bSel").is_enabled()
        check("viewer: 'Summarise selection' enables after selecting text", enabled)
        if enabled:
            d.find_element(By.ID, "bSel").click()
            st = wait(d, lambda d: "selection" in d.find_element(By.ID, "status").text and
                      d.find_elements(By.CSS_SELECTOR, "#out .w-summary") and d.find_element(By.ID, "status").text, 240)
            check("viewer: selection summary", st, st)

        # ---- extraction
        d.find_element(By.ID, "bExt").click()
        rows = wait(d, lambda d: d.find_elements(By.CSS_SELECTOR, "#out table.fields tr") or
                    d.find_elements(By.CSS_SELECTOR, "#out .err"), 300)
        err = d.find_elements(By.CSS_SELECTOR, "#out .err")
        rec = json.loads(d.find_element(By.CSS_SELECTOR, "#out pre.json").get_attribute("textContent")) if not err else {}
        a = rec.get("affair", {})
        check("viewer: extraction table + JSON record", rows and not err and rec.get("schema_version") == "opd-affair/0.1",
              err[0].text if err else f"{len(rows)} rows, type={(a.get('type') or {}).get('value')}, "
                                      f"verified_share={rec.get('quality', {}).get('verified_share')}")
        pgs = d.find_elements(By.CSS_SELECTOR, "#out .pg")
        if pgs:
            d.execute_script("arguments[0].click()", pgs[0])
            time.sleep(1)
            check("viewer: p.N evidence link jumps to the page", d.find_elements(By.CSS_SELECTOR, ".page.flash"))
        d.save_screenshot(str(OUT / "viewer_extract.png"))
        dl = d.find_elements(By.ID, "dl")
        if dl:
            dl[0].click()
            f = wait(d, lambda d: [p for p in DL.glob("*.json") if not p.name.endswith(".part")], 20)
            ok = f and json.loads(f[0].read_text(encoding="utf-8"))["schema_version"] == "opd-affair/0.1"
            check("viewer: Download JSON", ok, f[0].name if f else "no file")

        # ---- batch page
        go_ext(d, "batch/batch.html")
        ta = wait(d, lambda d: d.find_element(By.ID, "urls"), 20)
        ta.clear()
        ta.send_keys("\n".join(BATCH))
        d.find_element(By.ID, "run").click()
        done = wait(d, lambda d: d.find_element(By.ID, "status").text.startswith(f"{len(BATCH)} / {len(BATCH)}"), 600, 2)
        cards = d.find_elements(By.CSS_SELECTOR, ".card")
        tables = d.find_elements(By.CSS_SELECTOR, ".card table.fields")
        errs = d.find_elements(By.CSS_SELECTOR, ".card .err")
        check("batch: 3 links processed (2 records, 1 clean error)", done and len(tables) == 2 and len(errs) == 1,
              f"status={d.find_element(By.ID, 'status').text}, tables={len(tables)}, errors={[e.text[:60] for e in errs]}")
        hl = d.find_elements(By.CSS_SELECTOR, ".card .w-summary .w-topic")
        check("batch: summaries with inline topic highlights", hl, f"{len(hl)} inline highlights")
        d.save_screenshot(str(OUT / "batch.png"))
        for f in DL.iterdir():
            f.unlink()
        d.find_element(By.ID, "dlJson").click()
        fj = wait(d, lambda d: list(DL.glob("william-affairs*.json")), 20)
        if fj:
            data = json.loads(fj[0].read_text(encoding="utf-8"))
            check("batch: Download JSON (all items)", len(data["items"]) == 3 and sum("record" in i for i in data["items"]) == 2,
                  f"{len(data['items'])} items")
        else:
            check("batch: Download JSON (all items)", False, "no file")
        d.find_element(By.ID, "dlPdf").click()
        fp = wait(d, lambda d: list(DL.glob("william-report*.pdf")), 20)
        if fp:
            from pypdf import PdfReader
            r = PdfReader(str(fp[0]), strict=True)
            txt = r.pages[0].extract_text()
            check("batch: Download PDF report (valid, summary inside)", len(r.pages) >= 3 and "summary report" in txt,
                  f"{len(r.pages)} pages")
        else:
            check("batch: Download PDF report", False, "no file")

        # ---- popup (opened as a tab; summarises the active tab = a real web page)
        d.get("https://www.parlament.ch/de/ratsbetrieb/suche-curia-vista/geschaeft?AffairId=20234448")
        time.sleep(4)
        page_handle = d.current_window_handle
        d.switch_to.new_window("tab")
        go_ext(d, "popup/popup.html")
        time.sleep(1)
        check("popup: loads with buttons, no missing-key warning",
              d.find_element(By.ID, "bBatch").is_displayed() and not d.find_element(By.ID, "key").is_displayed())
        d.close()
        d.switch_to.window(page_handle)

        # ---- in-page panel: run exactly what the context-menu handler in background.js runs, on a live page
        d.get("https://www.parlament.ch/de/services/news/Seiten/default.aspx")
        time.sleep(5)
        page_handle = d.current_window_handle
        d.switch_to.new_window("tab")
        go_ext(d, "options/options.html")
        time.sleep(1)
        res = d.execute_async_script("""
            const cb = arguments[arguments.length-1];
            (async () => {
              const { summarize } = await import('/shared/engine.js');
              const [tab] = (await browser.tabs.query({})).filter(t => t.url.includes('parlament.ch'));
              const show = async (p) => { await browser.tabs.insertCSS(tab.id, {file: '/content/panel.css'});
                await browser.tabs.executeScript(tab.id, {file: '/content/panel.js'});
                await browser.tabs.sendMessage(tab.id, p); };
              await show({type: 'william-loading'});
              const [text] = await browser.tabs.executeScript(tab.id, {code: 'document.body.innerText'});
              const r = await summarize(text);
              await show({type: 'william-summary', res: r, selection: false});
              return {ok: true, lang: r.language, topics: r.topics.length, located: r.topics.filter(t => t.span).length};
            })().then(cb, e => cb({ok: false, err: String(e)}));""")
        d.close()
        d.switch_to.window(page_handle)
        panel = wait(d, lambda d: d.find_element(By.ID, "william-panel").text, 20)
        hl = d.find_elements(By.CSS_SELECTOR, "#william-panel .wp-sum .wp-topic")
        check("panel: page summary injected into a live website", res.get("ok") and panel and "William" in panel,
              f"{res} | {len(hl)} inline highlights")
        if hl:
            hl[0].click()
            n = wait(d, lambda d: d.find_elements(By.CSS_SELECTOR, "#william-panel .wp-news li a") or
                     d.find_elements(By.CSS_SELECTOR, "#william-panel .wp-nh"), 10)
            check("panel: highlight opens Swiss news list", n, f"{len(n or [])} items")
        d.save_screenshot(str(OUT / "panel.png"))
        check("panel: page scripts cannot access the extension API", d.execute_script("return typeof browser") == "undefined")
    except Exception:
        check("harness crashed", False, traceback.format_exc()[-1500:])
        try:
            d.save_screenshot(str(OUT / "crash.png"))
        except Exception:
            pass
    finally:
        d.quit()
    (OUT / "results.json").write_text(json.dumps([{"check": n, "pass": p, "detail": x} for n, p, x in results],
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{sum(p for _, p, _ in results)}/{len(results)} checks passed")
    sys.exit(0 if all(p for _, p, _ in results) else 1)


if __name__ == "__main__":
    main()
