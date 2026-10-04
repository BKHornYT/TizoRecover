"""Clicks through the whole window against a demo image, in Edge via Playwright.

Optional: needs ``pip install playwright`` and Microsoft Edge (or
``playwright install chromium``). Not part of ``run_all.py``.

    python tests/ui/test_ui.py [screenshot-dir]

Covers: device list -> All recovery methods -> scanning screen -> review
(tabs, type list, folder tree, tri-state folder ticks, filters, search,
preview, grid) -> recover to a temp folder (files byte-checked) -> done
screen, plus the Disk tools screen and the light theme. Any JavaScript error
fails the run. Screenshots land in the given folder (default tests/ui/out).
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from playwright.sync_api import sync_playwright  # noqa: E402

from tests.ui import demo_image  # noqa: E402
from tizorecover.app.server import App, make_server  # noqa: E402
from tizorecover.engine.drives import image_drive  # noqa: E402

FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        FAILS.append(label)


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "ui", "out")
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="tizo-ui-")
    os.environ["LOCALAPPDATA"] = work            # saved scans go to the temp folder, not the user's
    image = demo_image.write(os.path.join(work, "demo.img"))
    dest = os.path.join(work, "recovered")

    app = App()
    app.images = [image_drive(image)]
    app.all_drives = lambda refresh=False: list(app.images)   # never the real drives
    server = make_server(app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={app.token}"
    errors: list[str] = []

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="msedge")
        except Exception:
            browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1360, "height": 860}, bypass_csp=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        shot = lambda name: page.screenshot(path=os.path.join(out, f"{name}.png"))  # noqa: E731

        print("devices")
        page.goto(url)
        row = page.locator(".dev-row.part").first
        row.wait_for()
        row.click()
        check("drive picked", "sel" in (row.get_attribute("class") or ""))
        check("search enabled", page.locator("#search-btn").is_enabled())
        page.click("#method-btn")
        page.click("#method-menu [data-mode=deep]")
        check("method label", page.inner_text("#method-label") == "All recovery methods")
        shot("1-devices")

        print("scanning")
        page.click("#search-btn")
        page.wait_for_selector("#screen-scan:not([hidden])")
        try:
            page.wait_for_function("document.querySelector('#sc-title').textContent.includes('complete')",
                                   timeout=60000)
        except Exception:
            shot("fail-scan")
            print("  title:", page.inner_text("#sc-title"), "| errors:", errors[:5])
            raise
        page.wait_for_timeout(300)
        tiles = page.locator(".tile-cat")
        check("six type tiles", tiles.count() == 6)
        pictures = int(page.locator('.tile-cat[data-cat=image] .n').inner_text().replace(",", ""))
        check("pictures counted", pictures >= 8, str(pictures))
        check("steps all done", page.locator("#sc-steps li.ok").count() == 2)
        shot("2-scan-done")

        print("review")
        page.click("#sc-review")
        page.wait_for_selector("#screen-review:not([hidden])")
        named = int(page.inner_text("#tab-n-named"))
        carved = int(page.inner_text("#tab-n-carved"))
        check("named tab count", named == 16, str(named))
        check("reconstructed tab count", carved >= 5, str(carved))
        check("folders shown", page.locator(".row.folder").count() >= 4)
        check("deleted folder marked", page.locator(".row.folder.deleted").count() >= 1)
        check("chances column", page.locator(".row.file .ch").count() > 0)
        shot("3-review")

        photos = page.locator(".row.folder", has_text="Photos").first
        photos.locator("[data-fpick]").click()
        sel = page.inner_text("#sel-info")
        check("folder tick selects 8 files", sel.startswith("8 files"), sel)
        trip = page.locator(".row.folder", has_text="Iceland 2026").first
        trip.locator("[data-fpick]").click()
        ind = photos.locator("[data-fpick]").evaluate("el => el.indeterminate")
        check("parent folder half-ticked", ind is True)
        trip.locator("[data-fpick]").click()

        trip.locator(".nm").click()
        check("folder collapses", page.locator(".row.file", has_text="IMG_2040.png").count() == 0)
        trip.locator(".nm").click()
        page.locator(".row.file", has_text="IMG_2041.png").locator(".nm").click()
        page.wait_for_selector("#preview:not([hidden]) .pv-media img")
        page.wait_for_function("document.querySelector('.pv-media img').naturalWidth > 0", timeout=10000)
        check("image preview loads", True)
        shot("4-preview")
        page.click("#pv-wide")
        shot("5-preview-wide")
        page.click("#pv-wide")
        page.click("#pv-tabs [data-tab=info]")
        page.wait_for_selector(".pv-info")
        check("details tab", "Chances" in page.inner_text(".pv-info"))
        page.click("#pv-tabs [data-tab=hex]")
        page.wait_for_selector(".pv-hex")
        check("hex tab", "PNG" in page.inner_text(".pv-hex"))
        page.click("#pv-tabs [data-tab=preview]")

        page.fill("#q", "invoice")
        page.wait_for_timeout(400)
        rows = page.locator(".row.file").count()
        check("search finds one", rows == 1, str(rows))
        page.fill("#q", "")
        page.wait_for_timeout(400)

        page.click("#filter-btn")
        page.locator("#f-chances [data-st=good]").uncheck()
        page.wait_for_timeout(200)
        low = page.locator(".row.file").count()
        check("chances filter", low == 1, f"{low} rows without High")
        check("filter badge", page.inner_text("#filter-n") == "1")
        shot("6-filters")
        page.click("#f-reset")
        page.click("#f-close")

        page.click(".type-item[data-cat=document]")
        docs = page.locator(".row.file").count()
        check("type filter: documents", docs >= 4, str(docs))
        page.click(".type-item[data-cat='']")

        page.click("#rv-tabs [data-tab=carved]")
        check("reconstructed grouped by type", page.locator(".row.folder", has_text="Pictures").count() == 1)
        shot("7-reconstructed")
        page.click("#view-seg [data-view=grid]")
        page.wait_for_timeout(500)
        check("grid tiles", page.locator(".tile").count() >= 5)
        shot("8-grid")
        page.click("#view-seg [data-view=tree]")
        page.click("#rv-tabs [data-tab=named]")

        print("recover")
        page.click("#select-none")
        page.locator(".row.folder", has_text="Photos").first.locator("[data-fpick]").click()
        page.click("#recover-btn")
        page.wait_for_selector("#recover-dialog[open]")
        page.fill("#rd-dest", dest)
        page.wait_for_timeout(600)
        check("free space shown", "free" in page.inner_text("#rd-space"))
        shot("9-recover-dialog")
        page.click("#rd-start")
        page.wait_for_selector("#rd-done:not([hidden])", timeout=30000)
        title = page.inner_text("#rd-done-title")
        check("done screen", title == "8 files recovered", title)
        shot("10-recover-done")
        page.click("#rd-cancel")
        want = [it for it in app.job.snapshot() if (it.candidate.original_path or "").startswith("Photos/")]
        same = 0
        for it in want:
            path = os.path.join(dest, *it.candidate.original_path.split("/"))
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    same += fh.read() == app.job.data(it).read_all()
        check("recovered files byte-identical", same == len(want) == 8, f"{same}/{len(want)}")

        print("saved scan")
        page.click(".nav-item[data-goto=devices]")
        page.wait_for_selector(".dev-row.part .chip", timeout=10000)
        check("drive shows saved scan", "Saved scan" in page.inner_text(".dev-row.part"))
        check("resume offered", page.locator("#resume-btn").is_visible()
              and "Open last results" in page.inner_text("#resume-btn"))
        shot("13-saved-scan")
        page.click("#resume-btn")
        page.wait_for_selector("#confirm-dialog[open]")
        check("asks before clearing the ticked files", "new scan" in page.inner_text("#cf-title").lower())
        page.click("#cf-yes")
        page.wait_for_selector("#screen-scan:not([hidden])")
        page.wait_for_function("document.querySelector('#sc-title').textContent.includes('complete')"
                               " && !document.querySelector('#sc-autosave').hidden", timeout=30000)
        check("results reopened", f"{named + carved} files" in page.inner_text("#sc-found-total"),
              page.inner_text("#sc-found-total"))
        check("resumed note", "Resumed" in page.inner_text("#sc-autosave"))
        page.click(".nav-item[data-goto=devices]")
        page.click("#search-btn")
        page.wait_for_selector("#confirm-dialog[open]")
        check("new scan asks before replacing the save", "Replace" in page.inner_text("#cf-title"))
        page.click("#cf-no")

        print("tools + theme")
        page.click(".nav-item[data-goto=tools]")
        check("tools screen", page.locator("#screen-tools").is_visible())
        page.click(".nav-item[data-goto=review]")
        page.click("#theme")
        page.wait_for_timeout(200)
        shot("11-review-light")
        page.click(".nav-item[data-goto=devices]")
        shot("12-devices-light")
        page.click("#theme")
        browser.close()

    check("no JavaScript errors", not errors, "; ".join(errors[:3]))
    server.shutdown()
    print(f"\nscreenshots: {out}")
    print("UI: all passed" if not FAILS else f"UI: {len(FAILS)} failed: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
