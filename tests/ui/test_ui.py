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

    def _letters(self) -> set[str]:          # never this PC's real drive letters
        return {"C"}


fixdrive.Watch = _QuickWatch

FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        FAILS.append(label)


def nav(page, goto: str) -> None:
    """Click a sidebar/top-bar destination; from a scan's screens, go home first (like Disk Drill)."""
    target = page.locator(f"[data-goto={goto}]:visible")
    if not target.count():
        # home -> the scan's own screens: through "Current scan"; scan screens -> home: the home button
        hop = "scan" if goto in ("review", "gallery") else "devices"
        page.locator(f"[data-goto={hop}]:visible").first.click()
        target = page.locator(f"[data-goto={goto}]:visible")
    target.first.click()


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
        check("no method dropdown (Disk Drill: one Search button)", page.locator("#method-btn").count() == 0)
        props = page.inner_text("#dp-props")
        check("panel: General section", "General" in props and "Capacity:" in props, props[:80])
        check("panel: More info section", "More info" in props)
        page.click("#happened [data-hap=formatted]")
        check("what happened: formatted explains lost partitions", "Find lost partitions" in page.inner_text("#hap-hint"))
        shot("1-devices")
        row.click(button="right")
        page.wait_for_selector("#ctx:not([hidden])")
        menu = page.inner_text("#ctx")
        for want in ("Run all recovery methods", "Quick Scan", "Load last scan", "Eject disk"):
            check(f"drive menu: {want}", want in menu)
        shot("29-drive-menu")
        page.keyboard.press("Escape")
        page.mouse.click(5, 5)
        page.click("#happened [data-hap=missing]")
        check("what happened: drive missing opens Fix a drive", page.locator("#screen-fix").is_visible())
        nav(page, "devices")
        page.locator(".dev-row.part").first.click()

        print("scanning")
        page.click("#search-btn")
        page.wait_for_selector("#screen-scan:not([hidden])")
        try:
            page.wait_for_function("document.querySelector('#sc-title').textContent.startsWith('Found')",
                                   timeout=60000)
        except Exception:
            shot("fail-scan")
            print("  title:", page.inner_text("#sc-title"), "| errors:", errors[:5])
            raise
        page.wait_for_timeout(300)
        tiles = page.locator(".dtile")
        check("six type tiles", tiles.count() == 6)
        check("tiles light up for what was found", page.locator(".dtile.on[data-cat=image]").count() == 1)
        pictures = int(page.locator('.dtile[data-cat=image] small').inner_text().split()[0].replace(",", ""))
        check("pictures counted", pictures >= 8, str(pictures))
        check("dashboard says what was found", page.inner_text("#sc-title").startswith("Found"), page.inner_text("#sc-title"))
        shot("2-scan-done")

        print("review")
        page.click("#sc-review")
        page.wait_for_selector("#screen-review:not([hidden])")
        import re as _re
        page.click("#chip-show")
        group_text = lambda g: page.locator(f"#pop-show label:has([name=show][value={g}])").inner_text()  # noqa: E731
        named = int(_re.search(r"([\d,]+)\s*$", group_text("named")).group(1).replace(",", ""))
        carved = int(_re.search(r"([\d,]+)\s*$", group_text("carved")).group(1).replace(",", ""))
        existing = int(_re.search(r"([\d,]+)\s*$", group_text("existing")).group(1).replace(",", ""))
        check("live files listed as Existing", existing >= 1, str(existing))
        page.click("#rv-title")
        check("group row in the tree", "Deleted or lost (17)" in page.locator(".row.group").first.inner_text())
        check("one tree: Deleted or lost group", named == 17, str(named))
        check("one tree: Reconstructed group", carved >= 5, str(carved))
        check("preview panel waits for a file", "select a file" in page.inner_text("#preview").lower())
        check("folders shown", page.locator(".row.folder").count() >= 4)
        check("deleted folder marked", page.locator(".row.folder.deleted").count() >= 1)
        check("chances column", page.locator(".row.file .ch").count() > 0)
        shot("3-review")

        photos = page.locator(".row.folder", has_text="Photos (9)").first
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
        info = page.inner_text("#pv-info")
        check("preview: type and size", "PNG Image - " in info, info[:120])
        check("preview: Disk Drill-style path", "\\Deleted or lost\\" in page.inner_text("#pv-path"), page.inner_text("#pv-path"))
        check("preview: chances as stars", page.locator("#pv-chance .ch .st").count() == 1)
        page.click("#pv-details summary")
        page.wait_for_selector(".pv-dl")
        check("details: why", "Why" in page.inner_text(".pv-dl"))
        check("type column: Windows' names", page.locator(".row.file .cell-muted", has_text="PNG Image").count() > 0)

        print("right-click menu")
        page.locator(".row.file", has_text="IMG_2041.png").click(button="right")
        page.wait_for_selector("#ctx:not([hidden])")
        menu = page.inner_text("#ctx")
        check("menu offers Unmark on a ticked file", "Unmark" in menu)
        for want in ("Mark all items for recovery", "Check only files that were not recovered yet",
                     "Clear selection", "Recover", "Preview", "Hex view"):
            check(f"menu has {want}", want in menu)
        check("not-recovered-yet greyed before any recovery",
              page.locator("#ctx button", has_text="not recovered yet").is_disabled())
        shot("25-context-menu")
        page.locator("#ctx button", has_text="Hex view").click()
        page.wait_for_selector(".pv-hex")
        check("hex view from the menu", "PNG" in page.inner_text(".pv-hex"))
        page.click("#pv-back")
        page.wait_for_selector("#preview .pv-media img")
        page.locator(".row.file", has_text="IMG_2041.png").click(button="right")
        page.locator("#ctx button", has_text="Clear selection").click()
        page.locator(".row.file", has_text="IMG_2041.png").click(button="right")
        page.locator("#ctx button", has_text="Mark for recovery").click()
        check("menu marks the file", page.inner_text("#sel-info").startswith("1 file"), page.inner_text("#sel-info"))
        page.locator(".row.file", has_text="IMG_2041.png").click(button="right")
        page.locator("#ctx button", has_text="Clear selection").click()
        check("menu clears the selection", "Tick the files" in page.inner_text("#sel-info"))
        photos.locator("[data-fpick]").click()                 # the 9 photos ticked again, as before

        print("grid with folders")
        page.click("#view-seg [data-view=grid]")
        page.wait_for_selector(".tile.folder")
        tops = page.locator(".tile.folder .cap").all_inner_texts()
        check("grid starts with the group folders", any(t.startswith("Deleted or lost") for t in tops), str(tops))
        check("breadcrumb at the bottom", page.locator("#crumbs:not([hidden]) [data-crumb]").count() == 1)
        page.locator(".tile.folder", has_text="Deleted or lost").click()
        page.locator(".tile.folder", has_text="Photos").click()
        page.wait_for_selector(".tile .tstar")
        check("grid tiles show stars", page.locator(".tile .tstar").count() > 0)
        check("breadcrumb follows", "Photos" in page.inner_text("#crumbs"), page.inner_text("#crumbs"))
        shot("26-grid-folders")
        page.locator("#crumbs [data-crumb='0']").click()
        check("breadcrumb goes back up", page.locator("#crumbs [data-crumb]").count() == 1)
        page.click("#layout-seg [data-layout=files]")
        check("files layout: no folder tiles", page.locator(".tile.folder").count() == 0)
        page.click("#layout-seg [data-layout=folders]")
        page.click("#view-seg [data-view=tree]")

        print("gallery")
        nav(page, "gallery")
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
        nav(page, "review")

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

        page.click("#chip-chances")
        page.locator("#pop-chances [data-st=good]").uncheck()
        check("chances popover has stars", page.locator("#pop-chances .ch-opt svg").count() == 3)
        page.click("#st-ok")
        page.wait_for_timeout(200)
        low = page.locator(".row.file").count()
        check("chances filter", low == 1, f"{low} rows without High")
        check("chip shows the filter", "on" in (page.get_attribute("#chip-chances", "class") or ""))
        shot("6-filters")
        page.click("#f-reset")
        page.click("#rv-title")

        print("filters: size and date")
        page.click("#chip-size")
        for want in ("Larger than", "Less than", "Exactly", "Interval"):
            check(f"size popover: {want}", want in page.inner_text("#pop-size"))
        page.locator("#pop-size [name=sz][value=lt]").check()
        page.fill(".sz-in[data-for=lt] .sz-a", "1")
        page.select_option(".sz-in[data-for=lt] .sz-unit", "KB")
        page.click("#sz-ok")
        page.wait_for_timeout(200)
        small = page.locator(".row.file").count()
        check("size filter: less than 1 KB", 1 <= small < 29, str(small))
        sizes = page.locator(".row.file .num").all_inner_texts()
        check("every file shown is under 1 KB", all(t.endswith(" B") for t in sizes), str(sizes))
        check("size chip names it", "Less than 1 KB" in page.inner_text("#chip-size"), page.inner_text("#chip-size"))
        shot("27-size-filter")
        page.locator("#chip-size .x").click()
        check("chip x removes the filter", page.inner_text("#chip-size").strip() == "File size")
        page.click("#chip-date")
        for want in ("Today", "Yesterday", "This week", "This month", "This year"):
            check(f"date preset {want}", want in page.inner_text("#pop-date"))
        shot("28-date-filter")
        page.locator("[data-dt=year]").click()
        check("date filter: nothing from this year in the demo", page.locator(".row.file").count() == 0)
        page.click("#f-reset")
        page.click("#rv-title")

        page.click("#nav-results [data-cat=document]:not([data-ext])")
        docs = page.locator(".row.file").count()
        check("type filter: documents", docs >= 4, str(docs))
        page.click("#nav-results [data-cat='']")

        page.click("#chip-show")
        show = page.inner_text("#pop-show")
        for want in ("All files", "Deleted or lost", "Reconstructed", "Show hidden system files", "Hide duplicates"):
            check(f"show popover: {want}", want in show)
        page.locator("#pop-show [name=show][value=carved]").check()
        page.click("#rv-title")
        check("Show: only reconstructed", page.locator(".row.group", has_text="Deleted or lost").count() == 0)
        check("reconstructed grouped by type", page.locator(".row.folder", has_text="Pictures").count() == 1)
        shot("7-reconstructed")
        page.click("#view-seg [data-view=grid]")
        page.click("#layout-seg [data-layout=files]")
        page.wait_for_timeout(500)
        check("grid tiles", page.locator(".tile").count() >= 5)
        shot("8-grid")
        page.click("#layout-seg [data-layout=folders]")
        page.click("#view-seg [data-view=tree]")
        page.click("#f-reset")

        print("recover")
        page.locator(".row.file").first.click(button="right")             # clear whatever is ticked
        clear = page.locator("#ctx button", has_text="Clear selection")
        clear.click() if clear.is_enabled() else page.keyboard.press("Escape")
        page.locator(".row.folder", has_text="Photos (9)").first.locator("[data-fpick]").click()
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
        want = [it for it in app.job.snapshot() if (it.candidate.original_path or "").startswith("Photos/")
                and not it.to_dict()["existing"]]
        same = 0
        for it in want:
            path = os.path.join(dest, *it.candidate.original_path.split("/"))
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    same += fh.read() == app.job.data(it).read_all()
        check("recovered files byte-identical", same == len(want) == 9, f"{same}/{len(want)}")

        print("saved scan")
        nav(page, "devices")
        page.wait_for_selector(".dev-row.part .chip", timeout=10000)
        check("drive shows saved scan", "Saved scan" in page.inner_text(".dev-row.part"))
        check("resume offered", page.locator("#resume-btn").is_visible()
              and "Load last scan" in page.inner_text("#resume-btn"))
        shot("13-saved-scan")
        page.click("#resume-btn")
        page.wait_for_selector("#confirm-dialog[open]")
        check("asks before clearing the ticked files", "new scan" in page.inner_text("#cf-title").lower())
        page.click("#cf-yes")
        page.wait_for_selector("#screen-scan:not([hidden])")
        page.wait_for_function("document.querySelector('#sc-title').textContent.startsWith('Found')"
                               " && !document.querySelector('#sc-autosave').hidden", timeout=30000)
        check("results reopened", f"{named + carved + existing} files" in page.inner_text("#sc-title"),
              page.inner_text("#sc-title"))
        check("resumed note", "Resumed" in page.inner_text("#sc-autosave"))
        nav(page, "devices")
        page.click("#search-btn")
        page.wait_for_selector("#confirm-dialog[open]")
        check("new scan asks before replacing the save", "Replace" in page.inner_text("#cf-title"))
        page.click("#cf-no")

        nav(page, "saved")
        page.wait_for_selector(".saved-row")
        check("saved scans listed", page.locator(".saved-row", has_text="demo.img").count() == 1)
        check("saved scans say where", "TizoRecover" in page.inner_text("#saved-where"))
        check("drive shown as plugged in", "Drive plugged in" in page.inner_text(".saved-row"))
        shot("18-saved-scans")
        page.click("[data-sv-open='0']")
        page.wait_for_selector("#screen-scan:not([hidden]), #screen-review:not([hidden])", timeout=30000)
        check("saved scan opens from the list", True)

        print("lost partitions")
        nav(page, "devices")
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
        ntfs_row.click(button="right")
        page.locator("#ctx button", has_text="Quick Scan").click()
        page.wait_for_selector("#screen-scan:not([hidden])")
        page.wait_for_function("document.querySelector('#sc-title').textContent.startsWith('Found')", timeout=60000)
        page.click("#sc-review")
        page.wait_for_selector(".row.file")
        check("undo format: old file by name", page.locator(".row.file", has_text="before the format.png").count() == 1)
        shot("15-undo-format")

        print("fix a drive")
        nav(page, "fix")
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
        nav(page, "tools")
        check("tools screen", page.locator("#screen-tools").is_visible())
        nav(page, "review")
        page.click("#menu-btn")
        page.click("#theme")
        page.wait_for_timeout(200)
        shot("11-review-light")
        nav(page, "devices")
        shot("12-devices-light")
        page.click("#menu-btn")
        page.click("#theme")
        print("dark (Windows dark mode)")
        page.click("#menu-btn")
        page.click("#theme")                                      # back to "same as Windows"
        page.keyboard.press("Escape")
        page.emulate_media(color_scheme="dark")
        nav(page, "devices")
        page.wait_for_timeout(200)
        check("follows Windows dark mode", page.evaluate("getComputedStyle(document.body).backgroundColor") != "rgb(255, 255, 255)")
        shot("22-devices-dark")
        nav(page, "scan")
        page.wait_for_timeout(200)
        shot("23-dashboard-dark")
        nav(page, "review")
        page.wait_for_timeout(300)
        shot("24-review-dark")
        browser.close()

    check("no JavaScript errors", not errors, "; ".join(errors[:3]))
    server.shutdown()
    print(f"\nscreenshots: {out}")
    print("UI: all passed" if not FAILS else f"UI: {len(FAILS)} failed: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
