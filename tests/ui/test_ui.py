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
from tizorecover.engine import fixdrive  # noqa: E402
from tizorecover.engine.drives import image_drive  # noqa: E402

# Fix Drive must not ask this PC's Windows anything in a test: a made-up diagnosis instead.
FAKE_DIAG = {
    "disks": [{"n": 7, "name": "WD Elements", "bus": "USB", "size": 2_000_000_000_000, "style": "RAW", "offline": False,
               "readonly": False, "system": False, "parts": []}],
    "usb": [{"id": r"USB\VID_04E8&PID_6300\X", "name": "Type-C", "speed": "usb2", "port": "HS06"}],
    "problems": [], "net": [], "used": ["C"], "suspend": {"ac": 1, "dc": 1},
    "failed": [{"id": r"USB\VID_0000&PID_0002\1", "name": "Unknown USB Device (Device Descriptor Request Failed)",
                "at": "2026-10-04T21:15:18+00:00", "speed": "usb2", "port": "HS06", "present": False}],
}
fixdrive.diagnose = lambda: dict(FAKE_DIAG)
fixdrive.snapshot = lambda: {}


class _QuickWatch(fixdrive.Watch):
    def __init__(self, seconds: int = 45) -> None:
        super().__init__(10)


fixdrive.Watch = _QuickWatch

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
    from tests.test_partitions import build_disk
    disk_path = os.path.join(work, "formatted-disk.img")
    disk_bytes, disk_want = build_disk()
    with open(disk_path, "wb") as fh:
        fh.write(disk_bytes)
    app.images = [image_drive(image), image_drive(disk_path)]
    app.all_drives = lambda refresh=False: list(app.images) + list(app.lost)   # never the real drives
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
        page.click("#happened [data-hap=formatted]")
        check("what happened: formatted explains lost partitions", "Find lost partitions" in page.inner_text("#hap-hint"))
        check("what happened: picks all methods", page.inner_text("#method-label") == "All recovery methods")
        shot("1-devices")
        page.click("#happened [data-hap=missing]")
        check("what happened: drive missing opens Fix a drive", page.locator("#screen-fix").is_visible())
        page.click(".nav-item[data-goto=devices]")
        page.locator(".dev-row.part").first.click()

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
        check("named tab count", named == 17, str(named))
        check("reconstructed tab count", carved >= 5, str(carved))
        check("folders shown", page.locator(".row.folder").count() >= 4)
        check("deleted folder marked", page.locator(".row.folder.deleted").count() >= 1)
        check("chances column", page.locator(".row.file .ch").count() > 0)
        shot("3-review")

        photos = page.locator(".row.folder", has_text="Photos").first
        photos.locator("[data-fpick]").click()
        sel = page.inner_text("#sel-info")
        check("folder tick selects 9 files", sel.startswith("9 files"), sel)
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

        print("gallery")
        page.click(".nav-item[data-goto=gallery]")
        page.wait_for_selector(".gal-tile")
        tiles = page.locator(".gal-tile").count()
        check("gallery shows the pictures and videos", tiles >= 8, str(tiles))
        check("gallery counts what it shows", "pictures and videos" in page.inner_text("#gal-count"),
              page.inner_text("#gal-count"))
        page.wait_for_function("[...document.querySelectorAll('.gal-tile img')].some((i) => i.naturalWidth > 0)",
                               timeout=10000)
        check("gallery thumbnails load", True)
        page.click("#gal-kind [data-k=video]")
        check("videos only", page.locator(".gal-tile").count() == 1, str(page.locator(".gal-tile").count()))
        page.click("#gal-kind [data-k=media]")
        page.locator(".gal-tile").first.click()
        page.wait_for_selector("#ql[open]")
        first_name = page.inner_text("#ql-name")
        page.keyboard.press("ArrowRight")
        page.wait_for_function(f"document.querySelector('#ql-name').textContent !== {first_name!r}")
        check("gallery opens the big viewer, arrows step", True)
        page.keyboard.press("Escape")
        tile = page.locator(".gal-tile:not(.sel)").first
        tile.hover()
        tile.locator("[data-gpick]").click()
        check("ticking in the gallery enables Recover", page.locator("#gal-recover").is_enabled())
        shot("21-gallery")
        picked = page.locator(".gal-tile.sel [data-gpick]").count()
        page.locator(".gal-tile.sel").last.hover()
        page.locator(".gal-tile.sel").last.locator("[data-gpick]").click()     # put the selection back
        check("unticking works", page.locator(".gal-tile.sel").count() == picked - 1)
        page.click(".nav-item[data-goto=review]")

        print("quick look")
        page.locator(".row.file", has_text="IMG_2042.png").locator("[data-eye]").click()
        page.wait_for_selector("#ql[open] .pv-media img")
        page.wait_for_function("document.querySelector('#ql .pv-media img').naturalWidth > 0", timeout=10000)
        count = page.inner_text("#ql-count")
        page.keyboard.press("ArrowRight")
        page.wait_for_function(f"document.querySelector('#ql-count').textContent !== {count!r}")
        check("quick look steps with arrows", page.inner_text("#ql-name") == "IMG_2043.png", page.inner_text("#ql-name"))
        was = page.locator("#ql-pick").is_checked()
        page.keyboard.press("Enter")
        check("enter flips the tick", page.locator("#ql-pick").is_checked() != was)
        page.keyboard.press("Enter")
        check("enter flips it back", page.locator("#ql-pick").is_checked() == was)
        shot("16-quick-look")
        raw = None
        for _ in range(12):
            page.keyboard.press("ArrowLeft")
            page.wait_for_timeout(150)
            if page.inner_text("#ql-name") == "DSC_0420.nef":
                raw = True
                break
        check("RAW reached in quick look", bool(raw))
        page.wait_for_selector("#ql .pv-media img")
        page.wait_for_function("document.querySelector('#ql .pv-media img').naturalWidth > 0", timeout=10000)
        check("RAW shows its embedded preview", "stored inside the file" in page.inner_text("#ql-body"))
        shot("17-quick-look-raw")
        page.keyboard.press(" ")
        check("space closes quick look", not page.locator("#ql").evaluate("d => d.open"))
        check("list thumbnails", page.locator(".row.file img.rthumb").count() >= 3)

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
        check("done screen", title == "9 files recovered", title)
        shot("10-recover-done")
        page.click("#rd-cancel")
        want = [it for it in app.job.snapshot() if (it.candidate.original_path or "").startswith("Photos/")]
        same = 0
        for it in want:
            path = os.path.join(dest, *it.candidate.original_path.split("/"))
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    same += fh.read() == app.job.data(it).read_all()
        check("recovered files byte-identical", same == len(want) == 9, f"{same}/{len(want)}")

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

        page.click(".nav-item[data-goto=saved]")
        page.wait_for_selector(".saved-row")
        check("saved scans listed", page.locator(".saved-row", has_text="demo.img").count() == 1)
        check("saved scans say where", "TizoRecover" in page.inner_text("#saved-where"))
        check("drive shown as plugged in", "Drive plugged in" in page.inner_text(".saved-row"))
        shot("18-saved-scans")
        page.click("[data-sv-open='0']")
        page.wait_for_selector("#screen-scan:not([hidden]), #screen-review:not([hidden])", timeout=30000)
        check("saved scan opens from the list", True)

        print("lost partitions")
        page.click(".nav-item[data-goto=devices]")
        page.wait_for_selector("[data-pfind]")
        disk_btn = page.locator(".dev-disk", has_text="formatted-disk.img").locator("[data-pfind]")
        disk_btn.click()
        page.wait_for_selector(".dev-row.part.lost", timeout=60000)
        lost = page.locator(".dev-row.part.lost")
        check("lost file systems listed", lost.count() == 4, str(lost.count()))
        ntfs_row = page.locator(".dev-row.part.lost", has_text="NTFS")
        check("formatted-over NTFS explained", "backup boot sector" in ntfs_row.inner_text())
        shot("14-lost-partitions")
        ntfs_row.click()
        page.click("#method-btn")
        page.click("#method-menu [data-mode=quick]")
        page.click("#search-btn")
        page.wait_for_selector("#screen-scan:not([hidden])")
        page.wait_for_function("document.querySelector('#sc-title').textContent.includes('complete')", timeout=60000)
        page.click("#sc-review")
        page.wait_for_selector(".row.file")
        check("undo format: old file by name", page.locator(".row.file", has_text="before the format.png").count() == 1)
        shot("15-undo-format")

        print("fix a drive")
        page.click(".nav-item[data-goto=fix]")
        page.wait_for_selector(".fix-item", timeout=30000)
        titles = page.inner_text("#fix-list")
        check("failed connection reported", "failed to connect" in titles)
        check("disk without partitions reported", "has no partitions" in titles)
        check("power saving reported", "USB power saving is on" in titles)
        check("first card is the serious one", "bad" in (page.locator(".fix-item").first.get_attribute("class") or ""))
        check("no-partition card offers a scan, not a fix",
              page.locator(".fix-item", has_text="has no partitions").locator("[data-fscan]").count() == 1
              and page.locator(".fix-item", has_text="has no partitions").locator("[data-fix]").count() == 0)
        shot("19-fix-drive")
        page.click("#fw-start")
        page.wait_for_selector("#fw-live .fix-item", timeout=40000)
        check("watch verdict shown", "saw nothing" in page.inner_text("#fw-live"))
        shot("20-fix-watch")

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
