const TOKEN = new URLSearchParams(location.search).get("t") || "";
history.replaceState(null, "", location.pathname);

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ---------- icons ---------- */
const P = {
  usb: '<path d="M10 2h4v5h-4zM8 7h8v9a4 4 0 0 1-4 4 4 4 0 0 1-4-4z"/><path d="M12 20v2"/>',
  ssd: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h6M7 14h3"/><circle cx="17" cy="12" r="1"/>',
  hdd: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="12" cy="11" r="4"/><path d="M12 11l3.5 5"/>',
  drive: '<rect x="2" y="13" width="20" height="7" rx="2"/><path d="M5 13l2.5-8h9L19 13M17 16.5h.01"/>',
  disc: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/>',
  files: '<path d="M15 3H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V7z"/><path d="M15 3v4h4M3 8v11a2 2 0 0 0 2 2h9"/>',
  wrench: '<path d="M14.7 6.3a4 4 0 0 0 5 5L21 13l-8 8-3-3 8-8-1.3-1.3a4 4 0 0 0-5-5L14 5z"/><path d="M3 21l6-6"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  chevron: '<path d="M9 5l7 7-7 7"/>',
  chevdown: '<path d="M6 9l6 6 6-6"/>',
  chevleft: '<path d="M15 5l-7 7 7 7"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M12 8v5M12 16h.01"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z"/>',
  all: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 17l-5-5-9 8"/>',
  video: '<rect x="2" y="5" width="15" height="14" rx="2"/><path d="M17 10l5-3v10l-5-3"/>',
  audio: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  document: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  archive: '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9M10 13h4"/>',
  code: '<path d="M8 8l-5 4 5 4M16 8l5 4-5 4M14 4l-4 16"/>',
  program: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/>',
  other: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13M9 7V4h6v3"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
  shrink: '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  play: '<path d="M7 4l13 8-13 8z"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  star: '<path d="M12 3l2.7 5.6 6.2.9-4.5 4.4 1 6.1L12 17.3 6.6 20l1-6.1L3.1 9.5l6.2-.9z"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  pluscircle: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  plug: '<path d="M9 2v5M15 2v5M7 7h10v4a5 5 0 0 1-10 0zM12 16v6"/>',
  eject: '<path d="M5 17h14v2H5zM12 5l7 9H5z"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
};
const icon = (name, cls = "") =>
  `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${P[name] || P.other}</svg>`;
function paintIcons(root = document) {
  $$("[data-icon]", root).forEach((el) => { el.outerHTML = icon(el.dataset.icon); });
}

/* ---------- helpers ---------- */
async function api(path, body) {
  const opts = { headers: { "X-Tizo-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (data.crash) showError(data.error);
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
// The scan number makes every scan's item URLs distinct, so the browser may cache them.
const scanGen = () => (S.scan && S.scan.job) || 0;
const dataUrl = (id, extra = "") => `/api/item/${id}/data?t=${encodeURIComponent(TOKEN)}&g=${scanGen()}${extra}`;
const thumbUrl = (id) => `/api/item/${id}/thumb?t=${encodeURIComponent(TOKEN)}&g=${scanGen()}`;
const previewUrl = (id) => `/api/item/${id}/preview?t=${encodeURIComponent(TOKEN)}&g=${scanGen()}`;
const THUMB_MAX = 12e6;
function thumbFor(it, cls) {
  if (it.status === "overwritten" || it.size > THUMB_MAX) return "";
  if (SHOWABLE_IMAGE.has(it.ext) || (it.category === "image" && !it.named && !EMBEDDED_PREVIEW.has(it.ext))) {
    return `<img class="${cls}" loading="lazy" decoding="async" src="${dataUrl(it.id)}" alt="">`;
  }
  return "";
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function size(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return i === 0 ? `${n} B` : `${n.toFixed(n < 10 ? 1 : 0)} ${u[i]}`;
}
function duration(s) {
  if (s == null || !isFinite(s)) return "—";
  s = Math.round(s);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}
const nf = (n) => (n || 0).toLocaleString();
const plural = (n, one, many = one + "s") => `${nf(n)} ${n === 1 ? one : many}`;
function ago(t) {
  if (!t) return "";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}
const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const date = (t) => (t ? dateFmt.format(new Date(t * 1000)) : "");
function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3600);
}
/* ---------- errors: never silent ---------- */
let errAt = 0;
function reportError(text) {
  text = String(text || "unknown error").slice(0, 4000);
  fetch("/api/client-error", {
    method: "POST", body: JSON.stringify({ message: text }),
    headers: { "X-Tizo-Token": TOKEN, "Content-Type": "application/json" },
  }).catch(() => {});
  showError(text);
}
function showError(text) {
  const d = $("#error-dialog");
  if (!d || d.open || Date.now() - errAt < 10000) return;   // one panel, not a storm
  errAt = Date.now();
  $("#er-text").textContent = text;
  $("#er-close").onclick = () => d.close();
  $("#er-copy").onclick = async () => {
    const log = await api("/api/log").catch(() => ({ text: "", path: "" }));
    const report = `TizoRecover ${(S.env && S.env.version) || "?"} (${(S.env && S.env.platform) || "?"})\n\n` +
      `${text}\n\nLog (${log.path}):\n${log.text}`;
    try { await navigator.clipboard.writeText(report); toast("Report copied"); }
    catch { toast(`Could not copy. The log is at ${log.path}`); }
  };
  d.showModal();
}
window.addEventListener("error", (e) => {
  if (!e.error && !e.message) return;          // a broken <img>/<video> fires this too: not an app error
  reportError(`${e.message} (${e.filename}:${e.lineno}:${e.colno})\n${(e.error && e.error.stack) || ""}`);
});
window.addEventListener("unhandledrejection", (e) => {
  const r = e.reason;
  if (r && /Failed to fetch|NetworkError/.test(String(r.message || r))) return toast("Lost contact with the engine for a moment.");
  reportError(`Unhandled: ${(r && r.stack) || r}`);
});

function ask(title, text, ok = "OK") {
  const d = $("#confirm-dialog");
  $("#cf-title").textContent = title;
  $("#cf-text").textContent = text;
  $("#cf-yes").textContent = ok;
  d.showModal();
  return new Promise((resolve) => {
    const done = (v) => { d.close(); resolve(v); };
    $("#cf-yes").onclick = () => done(true);
    $("#cf-no").onclick = () => done(false);
    d.oncancel = () => resolve(false);
  });
}

const CHANCE = {
  good: { label: "High", tip: "Its data is intact as far as TizoRecover can check: it should open fine." },
  partial: { label: "Average", tip: "Part of it may have been reused or damaged. It may open with errors, or only partly." },
  overwritten: { label: "Low", tip: "Its space now belongs to other files, or reads as blank. It will most likely not open." },
};
const CHANCE_ORDER = { good: 0, partial: 1, overwritten: 2 };
const chance = (s) => `<span class="ch ${s}" title="${CHANCE[s].tip}"><i></i>${CHANCE[s].label}</span>`;
const CATS = ["image", "video", "audio", "document", "archive", "code", "program", "other"];
const CAT_LABEL = { image: "Pictures", video: "Video", audio: "Audio", document: "Documents", archive: "Archives", code: "Code", program: "Programs", other: "Other" };
const CAT_ONE = { image: "Picture", video: "Video", audio: "Audio", document: "Document", archive: "Archive", code: "Code", program: "Program", other: "File" };
const TILE_CATS = ["image", "video", "audio", "document", "archive", "other"];
const tileCat = (c) => (TILE_CATS.includes(c) ? c : "other");
const STAGE_LABEL = { paused: "Paused", starting: "Starting", opening: "Opening the drive", records: "Reading the file table", deep: "Searching free space", done: "Finished", stopped: "Stopped", failed: "Failed" };
const catStyle = (c) => `style="--cc:var(--c-${c})"`;

/* ---------- theme ---------- */
// "system" follows Windows' light/dark setting (the default); the button cycles system -> light -> dark.
const THEME_NEXT = { system: "light", light: "dark", dark: "system" };
const THEME_ICON = { system: "monitor", light: "sun", dark: "moon" };
const THEME_TITLE = { system: "Theme: same as Windows", light: "Theme: light", dark: "Theme: dark" };
let themeMode = "system";
function setTheme(t) {
  themeMode = THEME_NEXT[t] ? t : "system";
  if (themeMode === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = themeMode;
  $("#theme").innerHTML = `${icon(THEME_ICON[themeMode])}${THEME_TITLE[themeMode]}`;
  try { localStorage.setItem("tizo-theme2", themeMode); } catch {}
}
(() => {
  let t = "system";
  try { t = localStorage.getItem("tizo-theme2") || "system"; } catch {}
  setTheme(t);
})();
$("#theme").onclick = () => { setTheme(THEME_NEXT[themeMode]); $("#app-menu").hidden = true; };

/* ---------- state ---------- */
const S = {
  env: {},
  screen: "devices",
  drives: [],
  saved: [],
  parts: null,
  picked: null,
  mode: "deep",
  scan: null,
  items: [],
  polling: null,
  speed: [],
  tileCounts: {},
  groups: new Set(["named", "existing", "carved"]),
  pvHidden: false,
  cat: null,
  ext: null,
  showHidden: false,
  collapsed: new Set(),
  tips: true,
  filters: { q: "", status: new Set(["good", "partial", "overwritten"]), size: "", date: "" },
  sort: { key: "name", dir: 1 },
  view: "tree",
  toggled: new Map(),
  rows: [],
  shown: [],
  tree: null,
  selected: new Set(),
  current: null,
  pvTab: "preview",
  reviewDirty: true,
};
try { S.mode = localStorage.getItem("tizo-mode") || "deep"; S.tips = localStorage.getItem("tizo-tips") !== "0"; } catch {}

/* ---------- navigation ---------- */
function go(screen) {
  if (screen === "review" && !S.scan) screen = "devices";
  if (screen === "scan" && !S.scan) screen = "devices";
  S.screen = screen;
  if (screen === "gallery" && !S.scan) screen = "devices";
  for (const s of ["devices", "scan", "review", "gallery", "saved", "fix", "tools"]) $(`#screen-${s}`).hidden = s !== screen;
  // Like Disk Drill: the sidebar is the home list, or -- on a scan's screens -- its dashboard and results.
  const scanMode = !!S.scan && ["scan", "review", "gallery"].includes(screen);
  $("#nav-home").hidden = scanMode;
  $("#nav-scanmode").hidden = !scanMode;
  $("#nav-gallery").hidden = !scanMode;
  markNav();
  if (screen === "review") { refilter(); requestAnimationFrame(renderList); }
  if (screen === "scan") renderScan();
  if (screen === "tools") renderTools();
  if (screen === "saved") { renderSaved(); loadSaved(false); }
  if (screen === "fix") enterFix();
  if (screen === "gallery") { galleryFilter(); requestAnimationFrame(renderGallery); }
  if (screen === "devices" && S.drives.length) loadSaved(true);
}
document.addEventListener("click", (ev) => {
  const tw = ev.target.closest("[data-navopen]");
  if (tw) {
    ev.stopPropagation();
    const c = tw.dataset.navopen;
    S.navOpen ||= new Set();
    S.navOpen.has(c) ? S.navOpen.delete(c) : S.navOpen.add(c);
    renderNav();
    return;
  }
  const b = ev.target.closest("[data-goto]");
  if (!b || b.closest(".dev-body")) return;
  if (b.dataset.cat !== undefined) {
    S.cat = b.dataset.cat || null;
    S.ext = b.dataset.ext || null;
    S.reviewDirty = true;
    if (typeof viewport !== "undefined") viewport.scrollTop = 0;
  }
  go(b.dataset.goto);
  if (b.dataset.cat !== undefined && S.screen === "review") refilter();
  renderNav();
});
function markNav() {
  $$(".nav [data-goto]").forEach((b) => {
    let on = b.dataset.goto === S.screen;
    if (on && b.dataset.cat !== undefined) on = (b.dataset.cat || null) === (S.cat || null) && (b.dataset.ext || null) === (S.ext || null);
    b.classList.toggle("active", on);
  });
}

/* ---------- app menu (top-left) ---------- */
$("#menu-btn").onclick = (e) => { e.stopPropagation(); $("#app-menu").hidden = !$("#app-menu").hidden; };
document.addEventListener("click", (e) => { if (!e.target.closest("#app-menu")) $("#app-menu").hidden = true; });
$$("#app-menu [data-menu]").forEach((b) => {
  if (b.dataset.menu === "theme") return;
  b.onclick = async () => {
    $("#app-menu").hidden = true;
    const what = b.dataset.menu;
    if (what === "image") return $("#open-image").click();
    if (what === "tzscan") return pickSavedScan();
    if (what === "update") {
      const u = await api("/api/update").catch(() => null);
      if (u && u.available) return checkUpdate();
      return toast(u ? `TizoRecover ${u.current} is the newest version.` : "Could not check for updates.");
    }
    if (what === "logs") {
      const r = await api("/api/log").catch(() => null);
      return r && r.path ? api("/api/open-folder", { path: r.path }).catch(() => {}) : toast("No log yet.");
    }
    if (what === "help") return api("/api/open-url", { url: "https://github.com/BKHornYT/TizoRecover/issues" }).catch(() => {});
    if (what === "about") {
      return ask("About TizoRecover", `TizoRecover ${S.env.version || ""}: free, open-source file recovery (GPL-3.0). It only ever reads from the drive you recover from.`, "OK");
    }
    if (what === "quit") return api("/api/quit", {}).catch(() => window.close());
  };
});

/* ---------- start-up ---------- */
async function init() {
  paintIcons();
  try {
    S.env = await api("/api/env");
    $("#ver").textContent = `Version ${S.env.version}`;
    // Always elevated in normal use; the chip only shows on a development run that skipped it.
    $("#admin-chip").innerHTML = S.env.admin ? ""
      : `<button class="chip warn" id="admin-chip-btn" title="Restart as administrator">${icon("shield")}Not administrator</button>`;
    $("#admin-chip-btn")?.addEventListener("click", elevate);
  } catch (e) {
    toast(`Could not reach the engine: ${e.message}`);
  }
  go("devices");
  loadDrives(false);
  api("/api/partitions").then((p) => { if (p.state === "running") pollParts(); }).catch(() => {});
  setInterval(() => api("/api/ping").catch(() => {}), 10000);
  setTimeout(checkUpdate, 1500);
}

async function checkUpdate() {
  const u = await api("/api/update").catch(() => null);
  if (!u || !u.available) return;
  try { if (localStorage.getItem("tizo-skip-update") === u.version) return; } catch {}
  $("#update-text").textContent = `TizoRecover ${u.version} is available (you have ${u.current}).`;
  const btn = $("#update-btn");
  btn.textContent = u.can_install ? "Update now" : "Download";
  btn.onclick = async () => {
    if (!u.can_install) { api("/api/open-url", { url: u.page }).catch(() => {}); return; }
    btn.disabled = true;
    await api("/api/update/install", {}).catch((e) => toast(e.message));
    const tick = async () => {
      const s = await api("/api/update/status").catch(() => null);
      if (!s) return;
      if (s.state === "downloading") {
        btn.textContent = s.total ? `Downloading ${Math.round((s.done / s.total) * 100)}%` : "Downloading…";
        setTimeout(tick, 500);
      } else if (s.state === "installing") {
        btn.textContent = "Installing, TizoRecover will restart…";
      } else if (s.state === "failed") {
        btn.disabled = false;
        btn.textContent = "Update now";
        toast(`Update failed: ${s.error}`);
      }
    };
    tick();
  };
  $("#update-close").onclick = () => {
    $("#update-banner").hidden = true;
    try { localStorage.setItem("tizo-skip-update", u.version); } catch {}
  };
  $("#update-banner").hidden = false;
}

async function elevate() {
  try {
    const r = await api("/api/elevate", {});
    if (r.ok) toast("Restarting as administrator…");
    else toast("Windows did not allow it. Right-click TizoRecover and choose Run as administrator.");
  } catch (e) { toast(e.message); }
}

/* ---------- devices ---------- */
async function loadDrives(refresh) {
  $("#nav-status").innerHTML = `<span class="spinner sm"></span>Updating disk list…`;
  const box = $("#dev-body");
  if (refresh || !S.drives.length) box.innerHTML = `<div class="dev-empty"><span class="spinner"></span>Looking for drives…</div>`;
  try {
    const { drives } = await api(`/api/drives${refresh ? "?refresh=1" : ""}`);
    S.drives = drives;
  } catch (e) {
    box.innerHTML = `<div class="dev-empty">Could not list drives: ${esc(e.message)}</div>`;
    $("#nav-status").textContent = "";
    return;
  }
  if (!S.drives.some((d) => d.id === S.picked)) {
    S.picked = (S.drives.find((d) => d.removable) || null)?.id || null;
  }
  await loadSaved(false);
  renderDevices();
  $("#nav-status").textContent = "";
  if (S.screen === "tools") renderTools();
}

async function loadSaved(render = true) {
  try {
    const r = await api("/api/saved");
    S.saved = r.saved || [];
    S.savedDir = r.dir || "";
  } catch { S.saved = []; }
  const pill = $("#nav-saved-pill");
  pill.hidden = !S.saved.length;
  pill.textContent = S.saved.length;
  if (render) renderDevices();
  if (S.screen === "saved") renderSaved();
}

/* ---------- gallery ---------- */
// Every picture and video found, big, in one place: the quickest way to see what can come back.
const GAL = { items: [], kind: "media", sort: "date", low: false, zoom: 190, seen: -1, live: new Map() };
try {
  GAL.zoom = Number(localStorage.getItem("tizo-gal-zoom")) || 190;
  GAL.sort = localStorage.getItem("tizo-gal-sort") || "date";
} catch {}
const galView = $("#gal-viewport");
const galSpacer = $("#gal-spacer");
function galleryFilter() {
  const want = GAL.kind === "media" ? null : GAL.kind;
  const list = S.items.filter((it) => (it.category === "image" || it.category === "video")
    && (!want || it.category === want) && (GAL.low || it.status !== "overwritten"));
  const by = {
    date: (a, b) => (b.modified || 0) - (a.modified || 0) || b.size - a.size,
    size: (a, b) => b.size - a.size,
    name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }),
  }[GAL.sort];
  list.sort(by);
  GAL.items = list;
  GAL.seen = S.items.reduce((n, it) => n + (it.category === "image" || it.category === "video" ? 1 : 0), 0);
  const hidden = S.items.filter((it) => (it.category === "image" || it.category === "video") && it.status === "overwritten").length;
  $("#gal-count").textContent = `${plural(list.length, "picture or video", "pictures and videos")}${!GAL.low && hidden ? ` · ${nf(hidden)} with low chances hidden` : ""}`;
  galView.scrollTop = Math.min(galView.scrollTop, Math.max(0, galSpacer.scrollHeight));
}
function galGeometry() {
  const w = galView.clientWidth - 32;
  const cols = Math.max(1, Math.floor((w + 12) / (GAL.zoom + 12)));
  const tileW = (w - (cols - 1) * 12) / cols;
  return { cols, tileW, rowH: tileW + 12 };
}
function galThumb(it) {
  if (it.category === "video") {
    return PLAYABLE_VIDEO.has(it.ext) && it.status !== "overwritten" && it.size < 4e9
      ? `<video muted preload="metadata" src="${dataUrl(it.id)}#t=1"></video><span class="tile-badge">${icon("video")}</span>`
      : `<span class="gal-ph">${icon("video")}<small>${esc((it.ext || "").toUpperCase())}</small></span>`;
  }
  if (it.status === "overwritten" && !GAL.low) return `<span class="gal-ph">${icon("image")}</span>`;
  return `<img loading="lazy" decoding="async" src="${thumbUrl(it.id)}" alt="">`;
}
let galQueued = false;
function queueGallery() {
  if (galQueued) return;
  galQueued = true;
  requestAnimationFrame(() => { galQueued = false; renderGallery(); });
}
galView.addEventListener("scroll", queueGallery, { passive: true });
new ResizeObserver(queueGallery).observe(galView);
function renderGallery() {
  if (S.screen !== "gallery") return;
  const items = GAL.items;
  const { cols, tileW, rowH } = galGeometry();
  const rows = Math.ceil(items.length / cols);
  galSpacer.style.height = `${rows * rowH + 16}px`;
  if (!items.length) {
    for (const el of GAL.live.values()) el.remove();
    GAL.live.clear();
    galSpacer.innerHTML = `<div class="dev-empty">${icon("image")}<span>${S.items.length ? "No pictures or videos among the files found." : "Nothing found yet."}</span></div>`;
    return;
  }
  galSpacer.querySelector(".dev-empty")?.remove();
  const top = galView.scrollTop;
  const first = Math.max(0, Math.floor(top / rowH) - 2) * cols;
  const last = Math.min(items.length, (Math.ceil((top + galView.clientHeight) / rowH) + 2) * cols);
  const w = Math.round(tileW);
  const want = new Set();
  for (let i = first; i < last; i++) {
    const it = items[i];
    const sel = S.selected.has(it.id) ? 1 : 0;
    const key = `${i}|${it.id}|${sel}|${w}|${cols}|${scanGen()}|${GAL.low ? 1 : 0}`;
    want.add(key);
    if (GAL.live.has(key)) continue;
    const x = 16 + (i % cols) * (tileW + 12);
    const y = 16 + Math.floor(i / cols) * rowH;
    tpl.innerHTML = `<div class="gal-tile ${sel ? "sel" : ""} ${it.status}" data-gi="${i}" style="left:${x}px;top:${y}px;width:${w}px;height:${w}px">
      ${galThumb(it)}
      <input type="checkbox" class="check" data-gpick="${it.id}" ${sel ? "checked" : ""}>
      <div class="gal-cap"><span class="sdot ${it.status}" title="${CHANCE[it.status].label} chances"></span><span class="nm">${esc(it.name)}</span><span class="sz">${size(it.size)}</span></div></div>`;
    const el = tpl.content.firstElementChild;
    galSpacer.appendChild(el);
    GAL.live.set(key, el);
  }
  for (const [key, el] of GAL.live) if (!want.has(key)) { el.remove(); GAL.live.delete(key); }
}
galSpacer.addEventListener("error", (ev) => {
  if (ev.target.tagName === "IMG") ev.target.outerHTML = `<span class="gal-ph">${icon("image")}<small>No preview</small></span>`;
}, true);
galSpacer.addEventListener("click", (ev) => {
  const box = ev.target.closest("[data-gpick]");
  if (box) {
    const id = Number(box.dataset.gpick);
    box.checked ? S.selected.add(id) : S.selected.delete(id);
    afterSelection();
    renderGallery();
    return;
  }
  const tile = ev.target.closest("[data-gi]");
  if (tile) openQuickLook(GAL.items[Number(tile.dataset.gi)], GAL.items);
});
function renderGallerySelection() {
  if (!$("#gal-sel")) return;
  const items = selectedItems();
  const bytes = items.reduce((a, it) => a + it.size, 0);
  $("#gal-sel").innerHTML = items.length ? `<b>${plural(items.length, "file")}</b> selected · ${size(bytes)}`
    : `Tick what you want back <span class="hint">Click a picture to see it big, then use ← →</span>`;
  $("#gal-recover").disabled = !items.length;
  $("#gal-recover").lastChild.textContent = items.length ? `Recover ${plural(items.length, "file")}` : "Recover";
}
$$("#gal-kind button").forEach((b) => {
  b.onclick = () => {
    GAL.kind = b.dataset.k;
    $$("#gal-kind button").forEach((x) => x.classList.toggle("active", x === b));
    galView.scrollTop = 0;
    galleryFilter();
    renderGallery();
  };
});
$("#gal-low").onchange = (e) => { GAL.low = e.target.checked; galleryFilter(); renderGallery(); };
$("#gal-sort").value = GAL.sort;
$("#gal-sort").onchange = (e) => {
  GAL.sort = e.target.value;
  try { localStorage.setItem("tizo-gal-sort", GAL.sort); } catch {}
  galView.scrollTop = 0;
  galleryFilter();
  renderGallery();
};
$("#gal-zoom").value = GAL.zoom;
$("#gal-zoom").oninput = (e) => {
  GAL.zoom = Number(e.target.value);
  try { localStorage.setItem("tizo-gal-zoom", String(GAL.zoom)); } catch {}
  queueGallery();
};
$("#gal-all").onclick = () => { for (const it of GAL.items) S.selected.add(it.id); afterSelection(); renderGallery(); };
$("#gal-none").onclick = () => { S.selected.clear(); afterSelection(); renderGallery(); };
$("#gal-recover").onclick = () => openRecover(selectedItems());

/* ---------- saved scans ---------- */
function savedDriveName(dv) {
  if (!dv) return "Unknown drive";
  if (dv.kind === "image") return dv.label || "Disk image";
  const name = dv.label || dv.disk_name || "Drive";
  return dv.letter ? `${dv.letter}:  ${name}` : name;
}
function renderSaved() {
  const box = $("#saved-list");
  $("#saved-where").textContent = S.savedDir ? `Saved in ${S.savedDir}` : "";
  if (!S.saved.length) {
    box.innerHTML = `<div class="dev-empty">${icon("history")}<span>No saved scans yet. They appear here as soon as you scan a drive.</span></div>`;
    return;
  }
  box.innerHTML = S.saved.map((sv, i) => {
    const dv = sv.drive || {};
    const here = sv.drive_id
      ? `<span class="chip ok">Drive plugged in</span>`
      : `<span class="chip warn" title="Plug the drive in to open this scan">Drive not plugged in</span>`;
    const disk = dv.disk_name && dv.disk_name !== savedDriveName(dv) ? ` · ${esc(dv.disk_name)}` : "";
    return `<div class="saved-row">
      <div class="dev-ico ${dv.removable ? "usb" : ""}">${icon(dv.kind === "image" ? "disc" : dv.removable ? "usb" : "drive")}</div>
      <div class="t"><b title="${esc(sv.path)}">${esc(savedDriveName(dv))}</b>
        <small>${esc(savedText(sv))} · ${size(sv.found_bytes || 0)} · ${esc(fsName(sv.filesystem))} · ${size(dv.size || 0)}${disk} ${here}</small></div>
      <div class="acts">
        <button class="btn primary sm" data-sv-open="${i}">${sv.state === "done" ? "Open" : "Open / resume"}</button>
        <button class="btn ghost sm" data-sv-show="${i}" title="Show the file in its folder">${icon("folder")}</button>
        <button class="btn ghost sm" data-sv-del="${i}" title="Delete this saved scan">${icon("trash")}</button>
      </div></div>`;
  }).join("");
}
async function openSavedScan(path) {
  if (running() && !(await ask("Stop the current scan?", "Opening a saved scan stops the one that is running.", "Stop and open"))) return;
  try {
    const r = await api("/api/scan/open", { path });
    resetForScan(r.drive.id, r.drive);
  } catch (e) { toast(e.message); }
}
$("#saved-list").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  const sv = S.saved[Number(b.dataset.svOpen ?? b.dataset.svShow ?? b.dataset.svDel)];
  if (!sv) return;
  if (b.dataset.svOpen !== undefined) return openSavedScan(sv.path);
  if (b.dataset.svShow !== undefined) return api("/api/open-folder", { path: sv.path }).catch((e) => toast(e.message));
  if (b.dataset.svDel !== undefined) {
    if (!(await ask("Delete this saved scan?", `${savedDriveName(sv.drive)}: ${savedText(sv)}. Only the saved results are deleted; nothing on the drive changes.`, "Delete"))) return;
    await api("/api/saved/delete", { path: sv.path }).catch((e) => toast(e.message));
    loadSaved(true);
  }
});
$("#saved-folder").onclick = () => S.savedDir && api("/api/open-folder", { path: S.savedDir }).catch((e) => toast(e.message));
const savedFor = (id) => S.saved.find((x) => x.drive_id === id);
function savedText(sv) {
  const what = sv.state === "done" ? "Finished scan" : sv.mode === "deep" ? `Stopped at ${Math.floor(sv.deep_pct || 0)}%` : "Quick scan";
  return `${what} from ${ago(sv.saved_at)} · ${plural(sv.found, "file")}`;
}

function driveKind(d) {
  if (d.kind === "image") return "disc";
  if (d.removable) return "usb";
  if (d.media === "HDD") return "hdd";
  return "ssd";
}
function driveTitle(d) {
  if (d.lost) return d.label ? `${d.label} (lost)` : `Lost ${fsName(d.filesystem)} partition`;
  if (d.kind === "image") return d.label;
  if (d.letter) return `${d.letter}:  ${d.label || "Local disk"}`;
  if (d.kind === "disk") return "Whole disk";
  return d.label || `Partition ${d.partition}`;
}
const fsName = (fs) => (!fs || fs === "unknown" ? "Unknown" : fs.toUpperCase());

function disks() {
  const map = new Map();
  const ordered = [...S.drives.filter((d) => !d.lost), ...S.drives.filter((d) => d.lost)];
  for (const d of ordered) {
    const key = d.lost ? (d.parent.startsWith("img:") ? d.parent : `disk${d.parent}`) : d.kind === "image" ? d.id : `disk${d.disk}`;
    if (!map.has(key)) {
      map.set(key, { key, name: d.kind === "image" ? d.label : d.disk_name || `Disk ${d.disk}`, bus: d.bus, media: d.media,
        size: d.disk_size || 0, removable: d.removable, system: d.system, image: d.kind === "image", disk: d.disk, parts: [], kind: driveKind(d),
        target: d.kind === "image" ? d.id : String(d.disk) });
    }
    const g = map.get(key);
    g.parts.push(d);
    if (!d.disk_size) g.size = Math.max(g.size, g.parts.reduce((a, p) => a + p.size, 0));
  }
  return [...map.values()].sort((a, b) => (b.removable - a.removable) || (a.image - b.image) || (a.system - b.system) || (a.disk - b.disk));
}

/* ---------- fix a drive ---------- */
const FIX = { checked: false, polling: false, watching: false };
const LEVEL_ICON = { bad: "alert", warn: "alert", info: "info", ok: "check" };
function enterFix() {
  if (!FIX.checked) fixCheck();
  else pollFix();
}
async function fixCheck() {
  FIX.checked = true;
  $("#fix-list").innerHTML = `<div class="fix-busy"><span class="spinner"></span>Asking Windows about every drive and USB port… (about 10 seconds)</div>`;
  await api("/api/fix/check", {}).catch((e) => toast(e.message));
  pollFix();
}
async function pollFix() {
  if (FIX.polling) return;
  FIX.polling = true;
  try {
    for (;;) {
      const r = await api("/api/fix").catch(() => null);
      if (!r || r.state !== "running") { renderFix(r); break; }
      await new Promise((ok) => setTimeout(ok, 700));
    }
  } finally { FIX.polling = false; }
}
function tipsHtml(tips) {
  return tips && tips.length ? `<ul class="fix-tips">${tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : "";
}
function renderFix(r) {
  const box = $("#fix-list");
  if (!r || r.state === "idle") { box.innerHTML = ""; return; }
  if (r.state === "failed") { box.innerHTML = `<div class="msg bad">${icon("alert")}<span>${esc(r.error)}</span></div>`; return; }
  const list = r.findings || [];
  FIX.findings = list;
  if (!list.length) {
    box.innerHTML = `<div class="fix-item ok"><div class="fi-ico">${icon("check")}</div><div class="grow"><b>Everything Windows can see looks fine</b>
      <p>No offline disks, missing letters, failed connections or driver problems. If your drive still doesn't show up, use <b>Watch while I plug it in</b>.</p></div></div>`;
    return;
  }
  box.innerHTML = list.map((f, i) => `<div class="fix-item ${f.level}">
      <div class="fi-ico">${icon(LEVEL_ICON[f.level] || "info")}</div>
      <div class="grow"><b>${esc(f.title)}</b><p>${esc(f.text)}</p>${tipsHtml(f.tips)}</div>
      <div class="fi-acts">
        ${f.fix ? `<button class="btn ${f.level === "info" ? "ghost" : "primary"} sm" data-fix="${i}" title="${esc(f.fix.why || "")}">${esc(f.fix.label)}</button>` : ""}
        ${f.scan ? `<button class="btn ghost sm" data-fscan="${i}">${icon("search")}Scan it</button>` : ""}
      </div></div>`).join("");
}
$("#fix-list").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button");
  if (!b || !FIX.findings) return;
  if (b.dataset.fix !== undefined) {
    const f = FIX.findings[Number(b.dataset.fix)];
    if (!(await ask(f.fix.label, `${f.fix.why || f.text}`, f.fix.label))) return;
    b.disabled = true;
    try {
      const r = await api("/api/fix/apply", { id: f.id });
      toast(r.message);
      loadDrives(true);
    } catch (e) { toast(e.message); b.disabled = false; return; }
    pollFix();
  } else if (b.dataset.fscan !== undefined) {
    const f = FIX.findings[Number(b.dataset.fscan)];
    go("devices");
    await loadDrives(true);
    const want = f.scan.letter ? S.drives.find((d) => d.letter === f.scan.letter)
      : S.drives.find((d) => d.disk === f.scan.disk && (f.scan.part ? d.partition === f.scan.part : true));
    if (want) { S.picked = want.id; renderDevices(); toast("Picked. Press Search for lost data, or Find lost partitions on the disk."); }
    else toast("Pick the drive in the list.");
  }
});
$("#fix-check").onclick = fixCheck;

const EVENT_TEXT = {
  failed: "got power but couldn't identify itself (Device Descriptor Request Failed)",
  problem: "connected with a problem",
  storage: "USB storage connected",
  disk: "disk appeared",
  usb: "USB device connected",
};
async function watchStart() {
  try { await api("/api/fix/watch", { seconds: 45 }); } catch (e) { toast(e.message); return; }
  FIX.watching = true;
  $("#fw-start").hidden = true;
  $("#fw-stop").hidden = false;
  $("#fw-live").hidden = false;
  for (;;) {
    const w = await api("/api/fix/watch").catch(() => null);
    if (!w) break;
    renderWatch(w);
    if (w.state !== "watching") break;
    await new Promise((ok) => setTimeout(ok, 800));
  }
  FIX.watching = false;
  $("#fw-start").hidden = false;
  $("#fw-start").lastChild.textContent = "Watch again";
  $("#fw-stop").hidden = true;
  fixCheck();
  loadDrives(true);
}
function renderWatch(w) {
  const ev = (w.events || []).map((e) => `<li class="ev ${e.kind}"><span class="t">${e.t.toFixed(0)}s</span>${esc(e.name)} <span class="cell-muted">· ${esc(EVENT_TEXT[e.kind] || "")}</span></li>`).join("");
  let html = "";
  if (w.state === "watching") {
    html = `<div class="fix-busy"><span class="spinner"></span><b>Plug the drive in now.</b> Watching for ${w.left}s more…</div>`;
  } else if (w.state === "failed") {
    html = `<div class="msg bad">${icon("alert")}<span>Watching failed: ${esc(w.error)}</span></div>`;
  } else if (w.result) {
    const r = w.result;
    html = `<div class="fix-item ${r.level}"><div class="fi-ico">${icon(LEVEL_ICON[r.level] || "info")}</div>
      <div class="grow"><b>${esc(r.title)}</b><p>${esc(r.text)}</p>${tipsHtml(r.tips)}</div></div>`;
  }
  $("#fw-live").innerHTML = html + (ev ? `<ol class="fix-events">${ev}</ol>` : (w.state === "watching" ? "" : `<p class="cell-muted">Nothing appeared on USB.</p>`));
}
$("#fw-start").onclick = watchStart;
$("#fw-stop").onclick = () => api("/api/fix/watch", { stop: true }).catch(() => {});

/* ---------- what happened? ---------- */
const HAPPENED = {
  deleted: { mode: "deep", text: "Pick the drive the files were on, then <b>Search for lost data</b>. Names and folders come first, then everything else found by content. Don't copy anything new onto that drive meanwhile." },
  formatted: { mode: "deep", text: "Pick the drive (or the whole disk if it has no letter) and press <b>Find lost partitions</b> on it first: the old file system often comes back with its names. Then <b>Search for lost data</b>. Never let Windows format it." },
  card: { mode: "deep", text: "Pick the card or phone storage, then <b>Search for lost data</b>. When it's done, open <b>Gallery</b> to see every picture and video big." },
};
$$("#happened .hap").forEach((b) => {
  b.onclick = () => {
    const key = b.dataset.hap;
    if (key === "missing") { go("fix"); return; }
    const h = HAPPENED[key];
    $$("#happened .hap").forEach((x) => x.classList.toggle("on", x === b));
    S.mode = h.mode;
    try { localStorage.setItem("tizo-mode", S.mode); } catch {}
    renderMethod();
    $("#hap-hint").innerHTML = `${icon("info")}<span>${h.text}</span>`;
    $("#hap-hint").hidden = false;
  };
});

// A stick plugged in while the drive list is open shows up by itself, already picked.
let driveMask = null;
setInterval(async () => {
  if (S.screen !== "devices" || document.hidden) return;
  const r = await api("/api/drive-mask").catch(() => null);
  if (!r) return;
  if (driveMask !== null && r.mask !== driveMask) {
    const before = new Set(S.drives.map((d) => d.id));
    await loadDrives(true);
    const fresh = S.drives.find((d) => !before.has(d.id) && d.removable);
    if (fresh) {
      S.picked = fresh.id;
      renderDevices();
      toast(`Picked ${driveTitle(fresh).trim()}, the drive you just plugged in.`);
    }
  }
  driveMask = r.mask;
}, 2500);

/* ---------- eject ---------- */
async function ejectDisk(disk, name = "") {
  const busy = S.scan && S.scan.drive && S.scan.drive.disk === disk;
  if (busy && running()) {
    if (!(await ask("Stop the scan and eject?", "This drive is being scanned. The scan stops (its progress is saved, you can resume later), then the drive is ejected.", "Stop and eject"))) return;
  } else if (busy && S.items.length) {
    if (!(await ask("Eject this drive?", "Its found files stay listed, but they can't be previewed or recovered until you plug it back in and open the saved scan.", "Eject"))) return;
  }
  toast("Ejecting…");
  try {
    const r = await api("/api/eject", { disk, force_scan: busy });
    toast(r.message || "You can unplug it now.");
  } catch (e) {
    toast(e.message);
  }
  loadDrives(true);
}

function renderDevices() {
  const box = $("#dev-body");
  const all = disks();
  const hidden = (d) => !d.lost && d.kind === "partition" && !d.letter && d.system;
  const list = all.map((g) => ({ ...g, parts: S.showHidden ? g.parts : g.parts.filter((d) => !hidden(d)) }))
    .filter((g) => g.parts.length);
  const shown = list.reduce((n, g) => n + 1 + (g.image && g.parts.length === 1 ? 0 : g.parts.length), 0);
  $("#dev-count").textContent = `${plural(list.length, "item")}`;
  if (!list.length) {
    box.innerHTML = `<div class="dev-empty">No drives found. Plug in a USB stick or memory card; it shows up here by itself.</div>`;
    renderPicked();
    return;
  }
  box.innerHTML = list.map((g) => {
    const solo = g.image && g.parts.length === 1;
    const collapsed = S.collapsed.has(g.key);
    const conn = g.image ? "File" : (g.bus || "").toUpperCase() || "—";
    const head = `<div class="dev-row disk ${collapsed ? "closed" : ""}" data-disk="${esc(g.key)}">
      <div class="dev-name"><span class="twisty">${icon("chevron")}</span><span class="dimg ${g.kind}">${icon(g.kind)}</span><b title="${esc(g.name)}">${esc(g.name)}</b></div>
      <div class="cell-muted">${g.image ? "Disk image" : "Hardware disk"}</div>
      <div class="cell-muted">${esc(conn)}</div>
      <div class="num">${size(g.size)}</div>
      <div class="dev-acts">${searchCell(g.target, true)}${g.removable && !g.image ? `<button class="icon-btn eject" data-eject="${g.disk}" title="Eject (safely remove)">${icon("eject")}</button>` : ""}</div></div>`;
    const parts = collapsed ? "" : g.parts.map((d) => {
      let sub = d.lost ? `<span class="chip warn">${icon("radar")}Lost</span> ${esc(d.found_by)}`
        : d.kind === "disk" ? `<span class="chip warn">No partitions</span>` : "";
      const sv = savedFor(d.id);
      if (sv) sub += ` <span class="chip accent" title="${esc(savedText(sv))}">${icon("history")}Saved scan</span>`;
      const type = d.lost ? "Lost partition" : d.kind === "image" ? "Disk image" : d.kind === "partition" ? "Partition" : d.kind === "disk" ? "Whole disk" : "Logical volume";
      return `<div class="dev-row part ${solo ? "solo" : ""} ${d.lost ? "lost" : ""} ${S.picked === d.id ? "sel" : ""}" data-id="${esc(d.id)}" tabindex="0">
        <div class="dev-name"><span class="dimg vol ${d.removable ? "usb" : ""}">${icon(d.lost ? "radar" : d.kind === "image" ? "disc" : "drive")}</span>
          <div class="t"><b title="${esc(driveTitle(d))}">${esc(driveTitle(d))}</b>${sub ? `<small>${sub}</small>` : ""}</div></div>
        <div class="cell-muted">${type}</div>
        <div class="cell-muted">${esc(fsName(d.filesystem))}</div>
        <div class="num">${size(d.size)}</div>
        <div class="dev-acts">${solo ? searchCell(g.target, true) : ""}</div>
      </div>`;
    }).join("");
    return `<div class="dev-disk">${solo ? "" : head}${parts}</div>`;
  }).join("");
  $$("[data-pfind]", box).forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); findParts(b.dataset.pfind, b.dataset.thorough === "1"); };
  });
  $$("[data-eject]", box).forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); ejectDisk(Number(b.dataset.eject)); };
  });
  $$("[data-pstop]", box).forEach((b) => {
    b.onclick = (e) => { e.stopPropagation(); api("/api/partitions/stop", {}).catch(() => {}); };
  });
  $$(".dev-row.disk", box).forEach((el) => {
    el.onclick = () => { const k = el.dataset.disk; S.collapsed.has(k) ? S.collapsed.delete(k) : S.collapsed.add(k); renderDevices(); };
  });
  $$(".dev-row.part", box).forEach((el) => {
    el.onclick = () => { S.picked = el.dataset.id; $$(".dev-row.part", box).forEach((x) => x.classList.toggle("sel", x === el)); renderPicked(); };
    el.ondblclick = () => startScan(el.dataset.id, S.mode);
    el.onkeydown = (e) => { if (e.key === "Enter") startScan(el.dataset.id, S.mode); };
  });
  renderPicked();
}

function searchCell(target, compact = false) {
  const p = S.parts;
  if (p && p.state === "running" && p.target === target) {
    const pct = p.total ? Math.floor((p.done / p.total) * 100) : 0;
    return compact
      ? `<div class="parts-run" title="Searching for lost partitions"><span class="spinner sm"></span><span>${pct}%</span><button class="icon-btn" data-pstop title="Stop">${icon("x")}</button></div>`
      : `<div class="parts-run"><span class="spinner"></span><span>Searching ${pct}%</span><button class="btn ghost sm" data-pstop>Stop</button></div>`;
  }
  const deeper = p && p.target === target && p.state === "done" && !p.thorough;
  const title = deeper ? "Read every sector of the drive (slow) for file systems a quick search can miss"
    : "Find lost partitions: look for partitions that were deleted, or file systems a format left behind";
  if (compact) return `<button class="icon-btn find-parts" data-pfind="${esc(target)}" data-thorough="${deeper ? 1 : 0}" title="${title}">${icon("radar")}</button>`;
  return `<button class="btn ghost sm find-parts" data-pfind="${esc(target)}" data-thorough="${deeper ? 1 : 0}" title="${title}">${icon("radar")}${deeper ? "Search every sector" : "Find lost partitions"}</button>`;
}

async function findParts(target, thorough) {
  try { await api("/api/partitions/search", { target, thorough }); } catch (e) { toast(e.message); return; }
  pollParts();
}
async function pollParts() {
  const p = await api("/api/partitions").catch(() => null);
  if (!p) return;
  S.parts = p;
  if (p.state === "running") {
    if (S.screen === "devices") renderDevices();
    setTimeout(pollParts, 700);
    return;
  }
  await loadDrives(false);
  if (p.found) {
    const first = S.drives.find((d) => d.lost && d.parent === p.target);
    if (first) { S.picked = first.id; renderDevices(); }
    toast(`Found ${plural(p.found, "lost file system")} on ${p.label}.`);
  } else if (p.error) {
    toast(p.error);
  } else if (p.state === "done") {
    toast(p.thorough ? "No lost partitions found, even sector by sector." : "No lost partitions found. Search every sector to look harder (slower).");
  }
}

function renderPicked() {
  const d = S.drives.find((x) => x.id === S.picked);
  $("#dp-empty").hidden = !!d;
  $("#dp-drive").hidden = !d;
  $("#search-btn").disabled = !d;
  if (!d) return;
  $("#dp-ico").className = `dp-ico ${d.removable ? "usb" : ""}`;
  $("#dp-ico").innerHTML = icon(d.lost ? "radar" : driveKind(d));
  $("#dp-name").textContent = driveTitle(d).trim();
  const type = d.lost ? "Lost partition" : d.kind === "image" ? "Disk image" : d.kind === "disk" ? "Whole disk" : d.kind === "partition" ? "Partition" : "Logical volume";
  $("#dp-sub").textContent = `${type} · ${size(d.size)}`;
  const sv = savedFor(d.id);
  const rb = $("#resume-btn");
  rb.hidden = !sv;
  if (sv) {
    rb.innerHTML = `<span class="grow"><b>${sv.state === "done" ? "Open last results" : "Resume scan"}</b><small>${esc(savedText(sv))}</small></span>${icon("chevron")}`;
  }
  let note = "";
  if (d.lost) note = `Lost ${esc(fsName(d.filesystem))} file system, found by its ${esc(d.found_by)}. Scanning it reads the drive as it was before.`;
  else if (d.kind === "disk") note = "No partitions on this disk. Don't let Windows initialize or format it: search it here, or find lost partitions first.";
  else if (!d.removable && d.media === "SSD" && d.kind !== "image") note = "SSD: Windows tells SSDs to wipe deleted data (TRIM), often within seconds. Recently deleted files may already be gone.";
  else if (d.system) note = "This is your Windows drive. Windows keeps writing to it, so recover as soon as possible and save to another drive.";
  $("#dp-note").hidden = !note;
  $("#dp-note").innerHTML = note ? `${icon("alert")}<span>${note}</span>` : "";
  const props = [
    ["Type", type], ["File system", fsName(d.filesystem)], ["Capacity", size(d.size)],
    ["Free", d.free ? size(d.free) : "—"], ["Connection", d.kind === "image" ? "File" : d.bus || "—"],
    ["Disk", d.disk_name || "—"], ["Media", d.media && d.media !== "Unspecified" ? d.media : "—"],
    ["Path", d.kind === "image" ? d.path : d.letter ? `${d.letter}:` : d.path],
  ];
  $("#dp-props").innerHTML = `<h4>General</h4>${props.map(([k, v]) => `<div><span>${k}</span><b title="${esc(v)}">${esc(v)}</b></div>`).join("")}`;
  const target = d.kind === "image" ? d.id : String(d.disk);
  $("#dp-actions").innerHTML = d.lost ? "" : searchCell(target) + (d.removable && d.kind !== "image"
    ? `<button class="btn ghost sm" data-eject="${d.disk}">${icon("eject")}Eject</button>` : "");
  $$("#dp-actions [data-pfind]").forEach((b) => { b.onclick = () => findParts(b.dataset.pfind, b.dataset.thorough === "1"); });
  $$("#dp-actions [data-pstop]").forEach((b) => { b.onclick = () => api("/api/partitions/stop", {}).catch(() => {}); });
  $$("#dp-actions [data-eject]").forEach((b) => { b.onclick = () => ejectDisk(Number(b.dataset.eject)); });
}
$("#show-hidden").onchange = (e) => { S.showHidden = e.target.checked; renderDevices(); };

function renderMethod() {
  $("#method-label").textContent = S.mode === "quick" ? "Quick scan" : "All recovery methods";
  $$("#method-menu button").forEach((b) => b.classList.toggle("sel", b.dataset.mode === S.mode));
}
$("#method-btn").onclick = (e) => { e.stopPropagation(); $("#method-menu").hidden = !$("#method-menu").hidden; };
$$("#method-menu button").forEach((b) => {
  b.onclick = () => {
    S.mode = b.dataset.mode;
    try { localStorage.setItem("tizo-mode", S.mode); } catch {}
    renderMethod();
    $("#method-menu").hidden = true;
  };
});
document.addEventListener("click", (e) => {
  if (!e.target.closest("#method")) $("#method-menu").hidden = true;
  if (!e.target.closest(".pop-wrap")) $$(".chips .popover").forEach((p) => { p.hidden = true; });
});
$("#search-btn").onclick = () => S.picked && startScan(S.picked, S.mode);
$("#resume-btn").onclick = () => S.picked && startScan(S.picked, S.mode, { resume: true });
async function pickSavedScan() {
  try {
    const { path } = await api("/api/pick", { kind: "tzscan" });
    if (path) await openSavedScan(path);
  } catch (e) { toast(e.message); }
}
$("#saved-other").onclick = pickSavedScan;
$("#refresh").onclick = () => loadDrives(true);
$("#open-image").onclick = async () => {
  try {
    const { path } = await api("/api/pick", { kind: "image" });
    if (!path) return;
    const { drive } = await api("/api/image", { path });
    S.drives = S.drives.filter((d) => d.id !== drive.id).concat(drive);
    S.picked = drive.id;
    renderDevices();
  } catch (e) { toast(e.message); }
};

/* ---------- scanning ---------- */
// "paused" counts as running: the scan is alive, waiting for its drive to come back (Stop still works).
const running = () => S.scan && (S.scan.state === "running" || S.scan.state === "starting" || S.scan.state === "paused");
const paused = () => S.scan && S.scan.state === "paused" && !S.scan.user_paused;   // waiting for the drive
const userPaused = () => S.scan && S.scan.state === "paused" && !!S.scan.user_paused;
async function togglePause() {
  if (!running()) return;
  await api("/api/scan/pause", { resume: userPaused() }).catch((e) => toast(e.message));
  poll();
}

async function startScan(driveId, mode, opts = {}) {
  if (running() && !(await ask("Stop the current scan?", "A scan is still running. Starting another one stops it. Its progress stays saved.", "Stop and continue"))) return;
  if (!running() && S.items.length && S.selected.size && !(await ask("Start a new scan?", "The files found by the last scan, and your selection, will be cleared from the list.", "Start new scan"))) return;
  const sv = savedFor(driveId);
  if (sv && !opts.resume && !(await ask("Replace the saved scan?", `${savedText(sv)}. A new scan of this drive replaces it. Choose Cancel, then Resume, to keep it.`, "Start new scan"))) return;
  try {
    await api("/api/scan", { drive: driveId, mode, resume: !!opts.resume });
  } catch (e) { toast(e.message); return; }
  resetForScan(driveId, null, mode);
}

function resetForScan(driveId, driveDict, mode = S.mode) {
  S.scan = null;
  S.items = [];
  S.selected.clear();
  S.current = null;
  S.cat = null;
  S.toggled.clear();
  S.speed = [];
  S.lastStep = 0;
  S.tileCounts = {};
  S.filters.q = "";
  $("#q").value = "";
  S.reviewDirty = true;
  showPreview(null);
  GAL.items = [];
  const d = S.drives.find((x) => x.id === driveId) || driveDict;
  S.scan = { state: "starting", mode, drive: d || {}, filesystem: d?.filesystem || "unknown", found: 0, counts: {}, progress: { stage: "starting", done: 0, total: 0, elapsed: 0 }, problems: [] };
  go("scan");
  poll();
}

let fetching = false;
async function fetchItems() {
  if (fetching) return;
  fetching = true;
  try {
    let more = true;
    while (more) {
      const r = await api(`/api/items?since=${S.items.length}`);
      S.items.push(...r.items);
      more = r.items.length > 0 && S.items.length < r.total;
    }
  } finally { fetching = false; }
}

let lastReviewRefresh = 0;
async function poll() {
  clearTimeout(S.polling);
  let s;
  try { s = await api("/api/scan"); } catch { S.polling = setTimeout(poll, 1500); return; }
  if (s.state === "none") return;
  S.scan = s;
  const before = S.items.length;
  if (s.found > before) await fetchItems();
  trackSpeed(s.progress);
  if (S.items.length !== before) S.reviewDirty = true;
  const live = running();
  renderNav();
  if (S.screen === "scan") renderScan();
  if (S.screen === "review") {
    renderReviewHead();
    if (S.reviewDirty && (!live || Date.now() - lastReviewRefresh > 1200)) { lastReviewRefresh = Date.now(); refilter(); }
  }
  if (live) S.polling = setTimeout(poll, 700);
  else loadSaved(S.screen === "devices");
}

function trackSpeed(p) {
  const now = Date.now();
  const last = S.speed[S.speed.length - 1];
  if (last && last.stage !== p.stage) S.speed = [];
  S.speed.push({ t: now, done: p.done, stage: p.stage });
  while (S.speed.length > 2 && now - S.speed[0].t > 6000) S.speed.shift();
}
function currentSpeed() {
  if (S.speed.length < 2) return null;
  const a = S.speed[0], b = S.speed[S.speed.length - 1];
  const dt = (b.t - a.t) / 1000;
  return dt > 0.5 ? Math.max(0, (b.done - a.done) / dt) : null;
}

function overallPct(s) {
  const p = s.progress;
  if (s.state === "done") return 100;
  const frac = p.total ? Math.min(1, p.done / p.total) : 0;
  if (s.mode === "deep") {
    if (p.stage === "records") return frac * 8;
    if (p.stage === "deep") return 8 + frac * 92;
    return 0;
  }
  return p.stage === "records" ? frac * 100 : 0;
}

function driveIconBox(d, el) {
  el.className = `dev-ico ${el.classList.contains("lg") ? "lg" : ""} ${d.removable ? "usb" : ""}`;
  el.innerHTML = icon(driveKind(d));
}

function renderNav() {
  const s = S.scan;
  if (!s) return;
  const live = running();
  $("#nav-scan-spin").hidden = !live;
  $("#nav-scan-label").textContent = paused() ? "Dashboard (paused)" : "Dashboard";
  $("#nav-current").hidden = false;
  $("#nav-current-label").textContent = `${live ? "Scanning" : "Results of"} ${driveTitle(s.drive || {}).trim()}`;
  const d = s.drive || {};
  const counts = {}, exts = {};
  for (const it of S.items) {
    const c = tileCat(it.category);
    counts[c] = (counts[c] || 0) + 1;
    const e = (it.ext || "?").toLowerCase();
    (exts[c] ||= {})[e] = (exts[c][e] || 0) + 1;
  }
  S.navOpen ||= new Set();
  const row = (attrs, ic, label, n, cls = "", twisty = "") =>
    `<button class="nav-item ${cls} ${n ? "" : "zero"}" data-goto="review" ${attrs}>${twisty}${icon(ic)}<span class="grow">${esc(label)}</span>${n ? `<span class="nav-pill">${nf(n)}</span>` : ""}</button>`;
  let html = row(`data-cat="" id="nav-review"`, driveKind(d), driveTitle(d).trim(), S.items.length, "drive");
  for (const c of TILE_CATS) {
    const key = c === "other" ? "other*" : c;
    const isOpen = S.navOpen.has(c) && !!exts[c];
    const tw = exts[c] ? `<span class="nav-tw ${isOpen ? "open" : ""}" data-navopen="${c}">${icon("chevron")}</span>` : `<span class="nav-tw"></span>`;
    html += row(`data-cat="${key}"`, c, CAT_LABEL[c] === "Video" ? "Videos" : CAT_LABEL[c], counts[c] || 0, "cat", tw);
    if (isOpen) {
      for (const [e, n] of Object.entries(exts[c]).sort((a, b) => b[1] - a[1]).slice(0, 12)) {
        html += row(`data-cat="${key}" data-ext="${esc(e)}"`, "file", e.toUpperCase(), n, "sub");
      }
    }
  }
  const box = $("#nav-results");
  if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
  const media = S.items.reduce((n, it) => n + (it.category === "image" || it.category === "video" ? 1 : 0), 0);
  $("#nav-gallery-pill").textContent = media ? nf(media) : "";
  if (S.screen === "gallery" && media !== GAL.seen) { galleryFilter(); renderGallery(); }
  markNav();
}

const TIPS = [
  ["Preview first", "Click a file to see it before you recover it. A picture that shows, or a video that plays, will come back fine."],
  ["Save to another drive", "Never recover onto the drive you are scanning: writing to it can overwrite the very files you want back."],
  ["Look while it scans", "You can open Review found items or the Gallery while the scan is still running."],
  ["High chances first", "Files marked High are intact as far as TizoRecover can check. Start with those."],
  ["Stop any time", "Progress is saved every minute. Stop now, come back later and pick up where it left off."],
];
function renderScan() {
  const s = S.scan;
  if (!s) return;
  const d = s.drive || {};
  const live = running();
  const p = s.progress;
  const pct = overallPct(s);
  const total = S.items.reduce((a, it) => a + it.size, 0);
  const name = `“${driveTitle(d).trim()}”`;
  $("#sc-title").textContent = paused() ? `Paused: waiting for ${name}`
    : live ? `Scanning ${name}`
    : s.state === "done" ? `Found ${plural(S.items.length, "file")} on ${size(total)}`
    : s.state === "failed" ? "The scan could not run" : `Stopped: ${plural(S.items.length, "file")} found on ${size(total)}`;
  $("#sc-sub").textContent = userPaused() ? `${plural(S.items.length, "file")} / ${size(total)} - Paused`
    : live
    ? `${p.total ? `${Math.floor(pct)}% complete` : STAGE_LABEL[p.stage] || "Starting"} – ${plural(S.items.length, "file")} / ${size(total)}`
    : s.state === "done" ? `Scan completed successfully · ${s.mode === "deep" ? "All recovery methods" : "Quick scan"} · ${driveTitle(d).trim()}`
    : s.state === "failed" ? "" : `Scan of ${driveTitle(d).trim()} stopped after ${duration(p.elapsed)}. What was found can still be recovered.`;
  $("#sc-progress").hidden = !live;
  $("#sc-bar").style.width = `${p.total ? pct : 0}%`;
  $("#sc-bar").classList.toggle("indet", live && !p.total);

  const counts = {}, bytes = {};
  for (const it of S.items) {
    const c = tileCat(it.category);
    counts[c] = (counts[c] || 0) + 1;
    bytes[c] = (bytes[c] || 0) + it.size;
  }
  const tiles = $("#sc-tiles");
  if (!tiles.children.length) {
    tiles.innerHTML = TILE_CATS.map((c) => `<button class="dtile" data-cat="${c}" data-tc="${c}"><span class="dt-ico">${icon(c)}</span><b>${CAT_LABEL[c] === "Video" ? "Videos" : CAT_LABEL[c]}</b><small>—</small></button>`).join("");
    $$(".dtile", tiles).forEach((t) => { t.onclick = () => { S.cat = t.dataset.cat === "other" ? "other*" : t.dataset.cat; S.ext = null; go("review"); refilter(); renderNav(); }; });
  }
  for (const c of TILE_CATS) {
    const t = $(`.dtile[data-cat="${c}"]`, tiles);
    const n = counts[c] || 0;
    t.classList.toggle("on", n > 0);
    $("small", t).textContent = n ? `${plural(n, "file")} · ${size(bytes[c])}` : "—";
  }
  const sp = currentSpeed();
  const parts = [`${duration(p.elapsed)} elapsed`];
  if (live && p.eta != null) parts.push(`${duration(p.eta)} remaining`);
  if (p.total) parts.push(`${size(p.done)} of ${size(p.total)}`);
  if (live && sp != null && p.total) parts.push(`${size(sp)}/s`);
  $("#sc-status").textContent = parts.join(", ");
  const note = $("#sc-autosave");
  note.hidden = !s.autosave;
  if (s.autosave) {
    note.textContent = `${s.resumed_from ? `Resumed a scan saved ${ago(s.resumed_from)}. ` : ""}${live ? "Progress is saved every minute." : "Saved: reopen it any time from Recent Sessions."}`;
  }
  const badNow = s.bad_bytes && live ? [`${size(s.bad_bytes)} could not be read so far (bad sectors). They are skipped; the scan carries on.`] : [];
  if (s.state === "paused") badNow.unshift("The drive disconnected. The scan is paused and everything found so far is kept: plug it back in (the same port is best) and it carries on by itself.");
  $("#sc-problems").innerHTML = [...badNow, ...s.problems].map((x) => `<div class="msg ${s.state === "failed" ? "bad" : "warn"}">${icon("alert")}<span>${esc(x)}</span></div>`).join("");
  $("#sc-review").disabled = !S.items.length;
  $("#sc-recover").disabled = !S.items.length;
  $("#sc-stop").hidden = !live;
  $("#sc-pause").hidden = !live || paused();
  $("#sc-pause").innerHTML = icon(userPaused() ? "play" : "pause");
  $("#sc-pause").title = userPaused() ? "Resume" : "Pause";
  $("#sc-deeper").hidden = live || s.mode !== "quick" || s.state === "failed" || !d.id;
  const tip = $("#sc-tip");
  tip.hidden = !(live && S.tips);
  if (!tip.hidden) {
    const [t, x] = TIPS[Math.floor(Date.now() / 12000) % TIPS.length];
    $("#sc-tip-title").textContent = `Tip: ${t}.`;
    $("#sc-tip-text").textContent = x;
  }
}
$("#sc-stop").onclick = async () => {
  if (running() && await ask("Stop scanning?", "Files found so far stay in the list and can still be recovered. Progress is saved, so you can resume later.", "Stop scan")) {
    api("/api/scan/stop", {}).catch(() => {});
  }
};
$("#sc-recover").onclick = () => openRecover(S.items.slice());
$("#sc-pause").onclick = togglePause;
$("#rv-pause").onclick = togglePause;
$("#sc-tip-close").onclick = () => { S.tips = false; try { localStorage.setItem("tizo-tips", "0"); } catch {} $("#sc-tip").hidden = true; };
$("#sc-review").onclick = () => go("review");
$("#sc-deeper").onclick = () => S.scan && startScan(S.scan.drive.id, "deep");

/* ---------- review: filtering & tree ---------- */
function renderReviewHead() {
  const s = S.scan;
  if (!s) return;
  const d = s.drive || {};
  const total = (S.shown || []).reduce((a, it) => a + it.size, 0);
  const cat = S.cat === "other*" ? "other" : S.cat;
  $("#rv-title").textContent = S.ext ? S.ext.toUpperCase() : cat ? (cat === "video" ? "Videos" : CAT_LABEL[cat]) : driveTitle(d).trim();
  $("#rv-sub").textContent = `${plural((S.shown || []).length, "file")} / ${size(total)}`;
  const live = running();
  $("#rv-scanpill").hidden = false;
  $("#rv-pause").hidden = !live || paused();
  $("#rv-pause").innerHTML = icon(userPaused() ? "play" : "pause");
  $("#rv-pause").title = userPaused() ? "Resume" : "Pause";
  const found = S.items.reduce((a, it) => a + it.size, 0);
  const pct = overallPct(s);
  $("#rv-pilltext").textContent = live ? `Scanning “${driveTitle(d).trim()}”` : `“${driveTitle(d).trim()}”`;
  $("#rv-pillsub").textContent = `${plural(S.items.length, "file")} / ${size(found)}${userPaused() ? " - Paused" : paused() ? " - Waiting for the drive"
    : live ? ` - ${s.progress.total ? `${Math.floor(pct)}%` : "scanning"}` : s.state === "done" ? " - Scan complete" : " - Stopped"}`;
  $("#rv-pillbar").style.width = live ? `${pct}%` : "0";
}
$("#rv-scanpill").onclick = () => go("scan");

function passesFilters(it) {
  const f = S.filters;
  if (!f.status.has(it.status)) return false;
  if (f.size) {
    const [lo, hi] = f.size.split("-");
    if (it.size < Number(lo) || (hi && it.size >= Number(hi))) return false;
  }
  if (f.date) {
    if (f.date === "none") { if (it.modified) return false; }
    else {
      const days = Number(f.date);
      if (!it.modified) return false;
      const age = (Date.now() / 1000 - it.modified) / 86400;
      if (days > 0 ? age > days : age < -days) return false;
    }
  }
  return true;
}
// Disk Drill's three groups, as top-level rows of one tree.
const GROUPS = ["named", "existing", "carved"];
const GROUP_LABEL = { named: "Deleted or lost", existing: "Existing", carved: "Reconstructed" };
const groupOf = (it) => (!it.named ? "carved" : it.existing ? "existing" : "named");
const inTab = (it) => S.groups.has(groupOf(it));
const catMatch = (it) => (!S.cat || (S.cat === "other*" ? !TILE_CATS.slice(0, 5).includes(it.category) : it.category === S.cat))
  && (!S.ext || (it.ext || "").toLowerCase() === S.ext);

function refilter() {
  S.reviewDirty = false;
  const q = S.filters.q.trim().toLowerCase();
  const base = [];
  S.groupCounts = { named: 0, existing: 0, carved: 0 };
  for (const it of S.items) {
    S.groupCounts[groupOf(it)]++;
    if (!inTab(it)) continue;
    if (q && !(`${it.folder}/${it.name}`.toLowerCase().includes(q))) continue;
    if (!passesFilters(it)) continue;
    base.push(it);
  }
  renderTypes(base);
  S.shown = base.filter(catMatch);
  sortFiles(S.shown);
  S.tree = buildTree(S.shown);
  recount();
  flatten();
  renderReviewHead();
  renderList();
  renderSelection();
  renderEmpty();
  renderFilterBadge();
}

function renderTypes(base) {
  const counts = {}, bytes = {};
  let total = 0, totalBytes = 0;
  for (const it of base) {
    counts[it.category] = (counts[it.category] || 0) + 1;
    bytes[it.category] = (bytes[it.category] || 0) + it.size;
    total++; totalBytes += it.size;
  }
  const row = (key, label, ic, n, b, cc) =>
    `<button class="type-item ${(S.cat === "other*" ? "other" : S.cat || "") === key ? "active" : ""} ${n ? "" : "zero"}" data-cat="${key}" style="--cc:${cc}"><span class="ti">${icon(ic)}</span><b>${label}</b><span class="n">${nf(n)}</span><small>${n ? size(b) : "none"}</small></button>`;
  let html = row("", "All files", "all", total, totalBytes, "var(--accent)");
  for (const c of CATS) {
    if (!counts[c] && (c === "code" || c === "program")) continue;
    html += row(c, CAT_LABEL[c], c, counts[c] || 0, bytes[c] || 0, `var(--c-${c})`);
  }
  html += `<div class="type-sep"></div><div class="chances-legend"><h4>Recovery chances</h4>
    ${["good", "partial", "overwritten"].map((k) => `<div>${chance(k)}<span>${CHANCE[k].tip}</span></div>`).join("")}</div>`;
  $("#types").innerHTML = html;
  $$("#types .type-item").forEach((b) => { b.onclick = () => { S.cat = b.dataset.cat || null; refilter(); $("#viewport").scrollTop = 0; }; });
}

const SORTERS = {
  name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }),
  status: (a, b) => CHANCE_ORDER[a.status] - CHANCE_ORDER[b.status] || a.name.localeCompare(b.name),
  modified: (a, b) => (a.modified || 0) - (b.modified || 0),
  type: (a, b) => a.ext.localeCompare(b.ext) || a.name.localeCompare(b.name),
  size: (a, b) => a.size - b.size,
};
function sortFiles(list) {
  const cmp = SORTERS[S.sort.key];
  list.sort((a, b) => S.sort.dir * cmp(a, b));
  $$("#thead [data-sort]").forEach((el) => {
    const base = el.textContent.replace(/ [▲▼]$/, "");
    el.classList.toggle("sorted", el.dataset.sort === S.sort.key);
    el.textContent = base + (el.dataset.sort === S.sort.key ? (S.sort.dir > 0 ? " ▲" : " ▼") : "");
  });
}

function folderPath(it) {
  const g = groupOf(it);
  if (g !== "carved") return [GROUP_LABEL[g], ...(it.folder ? it.folder.split("/").filter(Boolean) : [])];
  return [GROUP_LABEL[g], CAT_LABEL[it.category] || "Other", (it.ext || "unknown").toLowerCase()];
}

function buildTree(files) {
  const root = { key: "", name: "", depth: -1, kids: new Map(), files: [], count: 0, bytes: 0, sel: 0, deleted: false, newest: 0, statuses: {} };
  for (const it of files) {
    let node = root;
    node.count++; node.bytes += it.size;
    let acc = "";
    for (const part of folderPath(it)) {
      acc = acc ? `${acc}/${part}` : part;
      let kid = node.kids.get(part);
      if (!kid) {
        kid = { key: acc, name: part, depth: node.depth + 1, kids: new Map(), files: [], count: 0, bytes: 0, sel: 0, deleted: false, newest: 0,
          group: node.depth === -1 ? groupOf(it) : null };
        node.kids.set(part, kid);
      }
      node = kid;
      node.count++; node.bytes += it.size;
      if (it.folder_deleted) node.deleted = true;
      if ((it.modified || 0) > node.newest) node.newest = it.modified || 0;
    }
    node.files.push(it);
  }
  return root;
}

function recount(node = S.tree) {
  if (!node) return 0;
  let n = 0;
  for (const it of node.files) if (S.selected.has(it.id)) n++;
  for (const k of node.kids.values()) n += recount(k);
  node.sel = n;
  return n;
}

function isOpen(node) {
  if (S.toggled.has(node.key)) return S.toggled.get(node.key);
  if (node.group) return true;
  return S.shown.length <= 400 || (node.depth === 1 && node.key.startsWith(GROUP_LABEL.carved));
}

function flatten(all = false) {
  const rows = [];
  const flat = S.view === "grid" || S.filters.q.trim();
  if (flat) {
    for (const it of S.shown) rows.push({ file: it, depth: 0, flat: true });
  } else {
    const folderSort = S.sort.key === "size" ? (a, b) => S.sort.dir * (a.bytes - b.bytes)
      : S.sort.key === "modified" ? (a, b) => S.sort.dir * (a.newest - b.newest)
      : (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true });
    const groupSort = (a, b) => GROUPS.indexOf(a.group) - GROUPS.indexOf(b.group);
    const walk = (node) => {
      for (const k of [...node.kids.values()].sort(node.depth === -1 ? groupSort : folderSort)) {
        const open = all || isOpen(k);
        rows.push({ folder: k, depth: k.depth, open });
        if (open) walk(k);
      }
      for (const it of node.files) rows.push({ file: it, depth: node.depth + 1 });
    };
    walk(S.tree);
  }
  if (all) return rows;
  S.rows = rows;
  return rows;
}

/* ---------- review: list / grid ---------- */
const viewport = $("#viewport");
const spacer = $("#spacer");
const ROW = 38;
// Scrolling must not rebuild rows that stay on screen: rebuilding throws away every thumbnail and
// video poster, and each one is a fresh read from the drive. Rows are keyed by position + what they
// show; only rows that appear (or whose state changed) are built, and at most once per frame.
let renderQueued = false;
function queueRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; renderList(); });
}
viewport.addEventListener("scroll", queueRender, { passive: true });
new ResizeObserver(queueRender).observe(viewport);

const liveRows = new Map();   // key -> element currently in the spacer
const tpl = document.createElement("template");
function patchRows(entries) {
  const want = new Set();
  for (const [key, build] of entries) {
    want.add(key);
    if (liveRows.has(key)) continue;
    tpl.innerHTML = build().trim();
    const el = tpl.content.firstElementChild;
    spacer.appendChild(el);
    liveRows.set(key, el);
    el.querySelectorAll("[data-ind]").forEach((c) => { c.indeterminate = true; });
  }
  for (const [key, el] of liveRows) {
    if (!want.has(key)) { el.remove(); liveRows.delete(key); }
  }
}

function gridGeometry() {
  const w = viewport.clientWidth - 24;
  const cols = Math.max(1, Math.floor((w + 10) / 170));
  const tileW = (w - (cols - 1) * 10) / cols;
  return { cols, tileW, rowH: tileW * 0.75 + 30 + 10 };
}

function renderList() {
  if (S.screen !== "review") return;
  if (S.view === "grid") return renderGrid();
  const rows = S.rows;
  spacer.style.height = `${rows.length * ROW}px`;
  const top = viewport.scrollTop;
  const first = Math.max(0, Math.floor(top / ROW) - 8);
  const last = Math.min(rows.length, Math.ceil((top + viewport.clientHeight) / ROW) + 8);
  const entries = [];
  for (let i = first; i < last; i++) {
    const r = rows[i];
    if (r.folder) {
      const f = r.folder;
      const state = f.sel === 0 ? "" : f.sel === f.count ? "checked" : "data-ind";
      entries.push([`r${i}|d${f.key}|${r.open ? 1 : 0}|${state}|${f.count}|${f.bytes}|${r.depth}`, () => {
        const pad = `padding-left:${r.depth * 20}px`;
        if (f.group) {
          return `<div class="row folder group ${r.open ? "open" : ""}" data-i="${i}" style="top:${i * ROW}px">
        <div class="c-check"><input type="checkbox" class="check" data-fpick="${i}" ${state === "checked" ? "checked" : ""} ${state === "data-ind" ? "data-ind" : ""}></div>
        <div class="name-cell"><span class="twisty">${icon("chevron")}</span><span class="nm">${esc(f.name)} (${nf(f.count)}) - ${size(f.bytes)}</span></div>
        <div></div><div></div><div></div><div></div></div>`;
        }
        return `<div class="row folder ${r.open ? "open" : ""} ${f.deleted ? "deleted" : ""}" data-i="${i}" style="top:${i * ROW}px">
        <div class="c-check"><input type="checkbox" class="check" data-fpick="${i}" ${state === "checked" ? "checked" : ""} ${state === "data-ind" ? "data-ind" : ""}></div>
        <div class="name-cell" style="${pad}"><span class="twisty">${icon("chevron")}</span>${icon("folder", "fi")}<span class="nm" title="${esc(f.key)}${f.deleted ? " (deleted folder)" : ""}">${esc(f.name)} (${nf(f.count)})</span></div>
        <div></div><div class="cell-muted">${f.deleted ? "Deleted folder" : ""}</div><div class="cell-muted">Folder</div><div class="num cell-muted">${size(f.bytes)}</div></div>`;
      }]);
    } else {
      const it = r.file;
      const sel = S.selected.has(it.id) ? 1 : 0;
      const cur = S.current === it.id ? 1 : 0;
      entries.push([`r${i}|f${it.id}|${sel}|${cur}|${r.flat ? 1 : 0}|${r.depth}|${it.status}|${scanGen()}`, () => {
        const sub = r.flat ? (it.named ? it.folder || "(top folder)" : CAT_LABEL[it.category]) : "";
        return `<div class="row file ${cur ? "current" : ""}" data-i="${i}" style="top:${i * ROW}px">
        <div class="c-check"><input type="checkbox" class="check" data-pick="${it.id}" ${sel ? "checked" : ""}></div>
        <div class="name-cell" style="${r.flat ? "" : `padding-left:${r.depth * 20 + 24}px`}">${thumbFor(it, "rthumb") || icon(it.category, "fi").replace("<svg", `<svg ${catStyle(it.category)}`)}<span class="nm" title="${esc(it.path || it.name)}">${esc(it.name)}</span>${sub ? `<span class="sub" title="${esc(sub)}">${esc(sub)}</span>` : ""}<button class="icon-btn eye" data-eye="${it.id}" title="Quick Look (Space)">${icon("eye")}</button></div>
        <div>${chance(it.status)}</div>
        <div class="cell-muted">${date(it.modified) || "—"}</div>
        <div class="cell-muted">${esc((it.ext || "?").toUpperCase())} ${CAT_ONE[it.category].toLowerCase()}</div>
        <div class="num">${size(it.size)}</div></div>`;
      }]);
    }
  }
  patchRows(entries);
}

function gridThumb(it) {
  if (it.status === "overwritten") return icon(it.category);
  if (it.category === "image" && it.size < 40e6) {
    return `<img loading="lazy" decoding="async" src="${thumbUrl(it.id)}" alt="">`;
  }
  if (PLAYABLE_VIDEO.has(it.ext) && it.size < 4e9) {
    // The first frames only: the browser asks for a small byte range.
    return `<video muted preload="metadata" src="${dataUrl(it.id)}#t=0.5"></video><span class="tile-badge">${icon("video")}</span>`;
  }
  return icon(it.category);
}

function renderGrid() {
  const items = S.shown;
  const { cols, tileW, rowH } = gridGeometry();
  const rows = Math.ceil(items.length / cols);
  spacer.style.height = `${rows * rowH + 12}px`;
  const top = viewport.scrollTop;
  const firstRow = Math.max(0, Math.floor(top / rowH) - 2);
  const lastRow = Math.min(rows, Math.ceil((top + viewport.clientHeight) / rowH) + 2);
  const w = Math.round(tileW * 100) / 100;
  const entries = [];
  for (let i = firstRow * cols; i < Math.min(items.length, lastRow * cols); i++) {
    const it = items[i];
    const sel = S.selected.has(it.id) ? 1 : 0;
    const cur = S.current === it.id ? 1 : 0;
    const x = 12 + (i % cols) * (tileW + 10);
    const y = 12 + Math.floor(i / cols) * rowH;
    entries.push([`g${i}|${it.id}|${sel}|${cur}|${w}|${cols}|${scanGen()}`, () =>
      `<div class="tile abs ${cur ? "current" : ""}" data-g="${i}" ${catStyle(it.category).replace('style="', `style="left:${x}px;top:${y}px;width:${w}px;`)}>
      <input type="checkbox" class="check" data-pick="${it.id}" ${sel ? "checked" : ""}>
      <div class="thumb">${gridThumb(it)}</div>
      <div class="cap"><span class="sdot ${it.status}" title="${CHANCE[it.status].label} chances"></span><span class="nm" title="${esc(it.name)}">${esc(it.name)}</span></div></div>`]);
  }
  patchRows(entries);
}
spacer.addEventListener("error", (ev) => { if (ev.target.tagName === "IMG") ev.target.outerHTML = icon("image"); }, true);

function filesUnder(node, out = []) {
  out.push(...node.files);
  for (const k of node.kids.values()) filesUnder(k, out);
  return out;
}
function setOpen(node, open) {
  S.toggled.set(node.key, open);
  flatten();
  renderList();
}

let lastPick = null;
spacer.addEventListener("click", (ev) => {
  const fbox = ev.target.closest("[data-fpick]");
  if (fbox) {
    const node = S.rows[Number(fbox.dataset.fpick)].folder;
    const on = node.sel !== node.count;
    for (const it of filesUnder(node)) on ? S.selected.add(it.id) : S.selected.delete(it.id);
    afterSelection();
    return;
  }
  const box = ev.target.closest("[data-pick]");
  if (box) {
    const id = Number(box.dataset.pick);
    const on = box.checked;
    const list = S.view === "grid" ? S.shown : S.rows.filter((r) => r.file).map((r) => r.file);
    const idx = list.findIndex((x) => x.id === id);
    if (ev.shiftKey && lastPick !== null && idx >= 0) {
      const [a, b] = [Math.min(lastPick, idx), Math.max(lastPick, idx)];
      for (let k = a; k <= b; k++) on ? S.selected.add(list[k].id) : S.selected.delete(list[k].id);
    } else {
      on ? S.selected.add(id) : S.selected.delete(id);
    }
    lastPick = idx;
    afterSelection();
    return;
  }
  const eye = ev.target.closest("[data-eye]");
  if (eye) { openQuickLook(S.items[Number(eye.dataset.eye)]); return; }
  const tile = ev.target.closest("[data-g]");
  if (tile) { select(S.shown[Number(tile.dataset.g)]); return; }
  const rowEl = ev.target.closest("[data-i]");
  if (!rowEl) return;
  const r = S.rows[Number(rowEl.dataset.i)];
  if (r.folder) setOpen(r.folder, !r.open);
  else select(r.file);
});
spacer.addEventListener("dblclick", (ev) => {
  if (ev.target.closest("input, button")) return;
  const rowEl = ev.target.closest("[data-i], [data-g]");
  if (!rowEl) return;
  const it = rowEl.dataset.g != null ? S.shown[Number(rowEl.dataset.g)] : S.rows[Number(rowEl.dataset.i)].file;
  if (it) openQuickLook(it);
});

function afterSelection() {
  recount();
  renderList();
  renderSelection();
}

document.addEventListener("keydown", (ev) => {
  if (S.screen !== "review" || ev.target.matches("input, textarea, select") || $("dialog[open]")) return;
  const files = S.view === "grid" ? S.shown : S.rows.filter((r) => r.file).map((r) => r.file);
  const idx = files.findIndex((x) => x.id === S.current);
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault();
    const step = S.view === "grid" ? gridGeometry().cols : 1;
    const next = Math.max(0, Math.min(files.length - 1, idx < 0 ? 0 : idx + (ev.key === "ArrowDown" ? step : -step)));
    if (files[next]) { select(files[next]); scrollToFile(files[next]); }
  } else if ((ev.key === "ArrowRight" || ev.key === "ArrowLeft") && S.view === "grid") {
    ev.preventDefault();
    const next = Math.max(0, Math.min(files.length - 1, idx + (ev.key === "ArrowRight" ? 1 : -1)));
    if (files[next]) { select(files[next]); scrollToFile(files[next]); }
  } else if (ev.key === " " && idx >= 0) {
    ev.preventDefault();
    openQuickLook(S.items[S.current]);
  } else if (ev.key === "Enter" && idx >= 0) {
    ev.preventDefault();
    S.selected.has(S.current) ? S.selected.delete(S.current) : S.selected.add(S.current);
    afterSelection();
  } else if (ev.key === "Escape" && !$("#preview").hidden) {
    showPreview(null);
  } else if ((ev.key === "a" || ev.key === "A") && (ev.ctrlKey || ev.metaKey)) {
    ev.preventDefault();
    for (const it of S.shown) S.selected.add(it.id);
    afterSelection();
  }
});
function scrollToFile(it) {
  let y, h;
  if (S.view === "grid") {
    const g = gridGeometry();
    h = g.rowH;
    y = Math.floor(S.shown.indexOf(it) / g.cols) * h;
  } else {
    h = ROW;
    y = S.rows.findIndex((r) => r.file === it) * ROW;
  }
  if (y < viewport.scrollTop) viewport.scrollTop = y;
  else if (y + h > viewport.scrollTop + viewport.clientHeight) viewport.scrollTop = y + h - viewport.clientHeight;
}

$("#check-all").onchange = (e) => {
  for (const it of S.shown) e.target.checked ? S.selected.add(it.id) : S.selected.delete(it.id);
  afterSelection();
};
$("#select-high").onclick = () => {
  for (const it of S.shown) if (it.status === "good") S.selected.add(it.id);
  afterSelection();
};
$("#select-none").onclick = () => { S.selected.clear(); afterSelection(); };

function selectedItems() {
  return [...S.selected].map((id) => S.items[id]).filter(Boolean);
}
function renderSelection() {
  renderGallerySelection();
  const items = selectedItems();
  const bytes = items.reduce((a, it) => a + it.size, 0);
  $("#sel-info").innerHTML = items.length
    ? `<b>${plural(items.length, "file")}</b> selected · ${size(bytes)}`
    : `Tick the files and folders you want back <span class="hint"><kbd>Space</kbd> Quick Look</span>`;
  const btn = $("#recover-btn");
  const all = S.shown || [];
  btn.disabled = !items.length && !all.length;
  btn.textContent = items.length ? "Recover" : "Recover all…";
  $("#sel-sum").textContent = items.length ? `${plural(items.length, "item")} on ${size(bytes)}`
    : all.length ? `${plural(all.length, "item")} on ${size(all.reduce((a, it) => a + it.size, 0))}` : "";
  const shownSel = S.shown.length ? S.shown.filter((it) => S.selected.has(it.id)).length : 0;
  const box = $("#check-all");
  box.checked = !!S.shown.length && shownSel === S.shown.length;
  box.indeterminate = shownSel > 0 && shownSel < S.shown.length;
  $("#select-none").hidden = !items.length;
}

function renderEmpty() {
  const el = $("#empty");
  const s = S.scan;
  if (S.shown.length || !s) { el.hidden = true; return; }
  el.hidden = false;
  const live = running();
  if (live) {
    el.innerHTML = `<div class="box"><span class="spinner"></span><h3>Still searching…</h3>Files appear here as soon as they are found.</div>`;
    return;
  }
  if (s.state === "failed") {
    el.innerHTML = `<div class="box"><div class="big-ico">${icon("alert")}</div><h3>The scan could not run</h3>${s.problems.map((p) => `<p>${esc(p)}</p>`).join("")}</div>`;
    return;
  }
  const inThisTab = S.items.filter(inTab).length;
  if (inThisTab) {
    el.innerHTML = `<div class="box"><div class="big-ico">${icon("filter")}</div><h3>No files match</h3>Try another file type, clear the search, or reset the filters.<p><button class="btn" id="empty-reset">Show everything</button></p></div>`;
    $("#empty-reset").onclick = resetFilters;
    return;
  }
  if (S.items.length) {
    el.innerHTML = `<div class="box"><div class="big-ico">${icon("sliders")}</div><h3>Nothing to show</h3>The groups that are switched off under Show hold all the files found.
      <p><button class="btn" id="empty-other">Show all groups</button></p></div>`;
    $("#empty-other").onclick = () => { S.groups = new Set(GROUPS); refilter(); };
    return;
  }
  const d = s.drive || {};
  const ssd = d.media === "SSD" && !d.removable;
  el.innerHTML = `<div class="box"><div class="big-ico">${icon("search")}</div><h3>No deleted files found</h3>
    <div>That does not always mean they are gone. Common reasons:</div>
    <ul>
      ${s.mode !== "deep" ? `<li><b>Run all recovery methods.</b> A quick scan only finds files the file table still remembers.</li>` : ""}
      ${ssd ? "<li><b>This is an SSD.</b> SSDs wipe deleted data on their own (TRIM), usually within seconds.</li>" : ""}
      <li>New files may have been saved over the deleted ones.</li>
      <li>They may have been on another drive, or in the cloud (OneDrive, Google Photos, iCloud).</li>
      <li>Check the Recycle Bin, and Windows' File History or previous versions.</li>
    </ul>
    ${s.mode !== "deep" ? `<p><button class="btn primary" id="empty-deep">${icon("search")}Run all recovery methods</button></p>` : ""}</div>`;
  $("#empty-deep")?.addEventListener("click", () => startScan(d.id, "deep"));
}

/* tabs, search, sort, view, filters */
let qTimer = null;
$("#q").oninput = (e) => { S.filters.q = e.target.value; clearTimeout(qTimer); qTimer = setTimeout(() => { viewport.scrollTop = 0; refilter(); }, 140); };
$$("#thead [data-sort]").forEach((el) => {
  el.onclick = () => {
    const k = el.dataset.sort;
    S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : (k === "size" || k === "modified" ? -1 : 1) };
    refilter();
  };
});
$$("#view-seg button").forEach((b) => {
  b.onclick = () => {
    S.view = b.dataset.view;
    $$("#view-seg button").forEach((x) => x.classList.toggle("active", x === b));
    $("#thead").style.visibility = S.view === "grid" ? "hidden" : "";
    viewport.scrollTop = 0;
    flatten();
    renderList();
  };
});

function renderChanceFilters() {
  $("#f-chances").innerHTML = ["good", "partial", "overwritten"].map((k) =>
    `<label class="opt"><input type="checkbox" class="check" data-st="${k}" ${S.filters.status.has(k) ? "checked" : ""}>${chance(k)}</label>`).join("");
  $$("#f-chances [data-st]").forEach((el) => {
    el.onchange = () => { el.checked ? S.filters.status.add(el.dataset.st) : S.filters.status.delete(el.dataset.st); refilter(); };
  });
}
function renderFilterBadge() {
  const f = S.filters;
  const setChip = (id, active, label, base) => {
    const c = $(id);
    c.classList.toggle("on", !!active);
    $(".fl", c).textContent = active ? label : base;
  };
  const cat = S.cat === "other*" ? "other" : S.cat;
  setChip("#chip-type", cat || S.ext, S.ext ? S.ext.toUpperCase() : cat ? (cat === "video" ? "Videos" : CAT_LABEL[cat]) : "", "File type");
  const chipX = $("#chip-type .x");
  if (cat || S.ext) { if (!chipX) $("#chip-type").insertAdjacentHTML("beforeend", `<span class="x" title="Show all file types">${icon("x")}</span>`); }
  else if (chipX) chipX.remove();
  setChip("#chip-size", f.size, $("#f-size").selectedOptions[0]?.textContent || "", "File size");
  setChip("#chip-date", f.date, $("#f-date").selectedOptions[0]?.textContent || "", "Date modified");
  const names = ["good", "partial", "overwritten"].filter((k) => f.status.has(k)).map((k) => CHANCE[k].label);
  setChip("#chip-chances", f.status.size < 3, names.join(", ") || "None", "Recovery chances");
  const hiddenGroups = GROUPS.filter((g) => !S.groups.has(g) && (S.groupCounts || {})[g]);
  setChip("#chip-show", hiddenGroups.length, `Show: ${GROUPS.filter((g) => S.groups.has(g)).map((g) => GROUP_LABEL[g]).join(", ") || "nothing"}`, "Show");
  $("#f-reset").hidden = !(cat || S.ext || f.size || f.date || f.status.size < 3 || hiddenGroups.length || f.q);
}
function renderShowPop() {
  $("#pop-show").innerHTML = `<div class="pop-sec"><h4>Show</h4>${GROUPS.map((g) =>
    `<label class="opt"><input type="checkbox" class="check" data-group="${g}" ${S.groups.has(g) ? "checked" : ""}><span>${GROUP_LABEL[g]} <small>(${nf((S.groupCounts || {})[g] || 0)})</small></span></label>`).join("")}</div>`;
  $$("#pop-show [data-group]").forEach((el) => {
    el.onchange = () => { el.checked ? S.groups.add(el.dataset.group) : S.groups.delete(el.dataset.group); refilter(); };
  });
}
function renderTypePop() {
  const counts = {};
  for (const it of S.items) if (inTab(it)) counts[tileCat(it.category)] = (counts[tileCat(it.category)] || 0) + 1;
  $("#pop-type").innerHTML = `<div class="pop-sec"><h4>File type</h4>
    <button class="pop-item ${!S.cat ? "sel" : ""}" data-pcat="">All files</button>
    ${TILE_CATS.map((c) => `<button class="pop-item ${(S.cat === c || (c === "other" && S.cat === "other*")) ? "sel" : ""}" data-pcat="${c === "other" ? "other*" : c}" ${counts[c] ? "" : "disabled"}>${icon(c)}${c === "video" ? "Videos" : CAT_LABEL[c]}<small>${nf(counts[c] || 0)}</small></button>`).join("")}</div>`;
  $$("#pop-type [data-pcat]").forEach((b) => {
    b.onclick = () => { S.cat = b.dataset.pcat || null; S.ext = null; $("#pop-type").hidden = true; viewport.scrollTop = 0; refilter(); renderNav(); };
  });
}
const CHIP_POPS = { "#chip-show": "#pop-show", "#chip-type": "#pop-type", "#chip-size": "#pop-size", "#chip-date": "#pop-date", "#chip-chances": "#pop-chances" };
for (const [chip, pop] of Object.entries(CHIP_POPS)) {
  $(chip).onclick = (e) => {
    e.stopPropagation();
    if (chip === "#chip-type" && e.target.closest(".x")) {
      S.cat = null; S.ext = null; viewport.scrollTop = 0; refilter(); renderNav();
      return;
    }
    const open = $(pop).hidden;
    Object.values(CHIP_POPS).forEach((p) => { $(p).hidden = true; });
    if (pop === "#pop-show") renderShowPop();
    if (pop === "#pop-type") renderTypePop();
    if (pop === "#pop-chances") renderChanceFilters();
    $(pop).hidden = !open;
  };
}
function resetFilters() {
  S.filters.status = new Set(["good", "partial", "overwritten"]);
  S.filters.size = "";
  S.filters.date = "";
  S.filters.q = "";
  S.cat = null;
  S.ext = null;
  S.groups = new Set(GROUPS);
  $("#q").value = "";
  $("#f-size").value = "";
  $("#f-date").value = "";
  renderChanceFilters();
  refilter();
  renderNav();
}
$("#f-size").onchange = (e) => { S.filters.size = e.target.value; refilter(); };
$("#f-date").onchange = (e) => { S.filters.date = e.target.value; refilter(); };
$("#f-reset").onclick = resetFilters;

/* ---------- preview ---------- */
let previewToken = 0;
function select(it) {
  if (!it) return;
  S.current = it.id;
  renderList();
  showPreview(it);
}
function showPreview(it) {
  $("#preview").hidden = S.pvHidden;
  $("#preview").classList.toggle("empty", !it);
  if (!it) { S.current = null; renderList(); return; }
  $("#pv-name").textContent = it.name;
  $("#pv-path").textContent = it.named ? `/${it.path}` : "Reconstructed from content (original name unknown)";
  $("#pv-meta").innerHTML = `${size(it.size)} · ${chance(it.status)}`;
  renderPvTab();
}
$("#pv-close").onclick = () => showPreview(null);
$("#pv-toggle").onclick = () => {
  S.pvHidden = !S.pvHidden;
  $("#preview").hidden = S.pvHidden;
  $("#pv-toggle").classList.toggle("on", !S.pvHidden);
  setTimeout(renderList, 30);
};
$("#pv-wide").onclick = () => {
  const p = $("#preview");
  p.classList.toggle("wide");
  $("#pv-wide").innerHTML = icon(p.classList.contains("wide") ? "shrink" : "expand");
  setTimeout(renderList, 50);
};
$$("#pv-tabs button").forEach((b) => {
  b.onclick = () => {
    S.pvTab = b.dataset.tab;
    $$("#pv-tabs button").forEach((x) => x.classList.toggle("active", x === b));
    renderPvTab();
  };
});

const TEXTY = new Set(["txt", "md", "csv", "log", "ini", "cfg", "json", "xml", "html", "htm", "yaml", "yml", "py", "js", "ts", "c", "h", "cpp", "cs", "java", "go", "rs", "php", "rb", "sh", "ps1", "bat", "css", "sql", "lua", "srt", "vtt", "toml", "rtf", "docx", "pptx", "xlsx", "odt", "ods", "odp"]);
const PLAYABLE_VIDEO = new Set(["mp4", "m4v", "mov", "webm", "3gp"]);
const PLAYABLE_AUDIO = new Set(["mp3", "wav", "ogg", "opus", "flac", "m4a", "aac"]);
const SHOWABLE_IMAGE = new Set(["jpg", "jpeg", "png", "gif", "bmp", "webp", "ico", "svg", "avif"]);

async function renderPvTab() {
  const it = S.items[S.current];
  if (!it) return;
  const body = $("#pv-body");
  const my = ++previewToken;
  body.innerHTML = '<div class="pv-note"><span class="spinner"></span></div>';
  if (S.pvTab === "info") {
    const d = await api(`/api/item/${it.id}`).catch((e) => ({ error: e.message }));
    if (my !== previewToken) return;
    if (d.error) { body.innerHTML = `<div class="pv-note">${esc(d.error)}</div>`; return; }
    const method = { ntfs: "NTFS file table", fat: "FAT directory", exfat: "exFAT directory", carve: "Recognised by its content", ext4: "ext4 inode" }[d.method] || d.method;
    body.innerHTML = `<dl class="pv-info">
      <dt>Chances</dt><dd>${chance(d.status)}</dd>
      <dt>Why</dt><dd>${d.notes.length ? `<ul>${d.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : "No problems found"}</dd>
      <dt>Size</dt><dd>${size(d.size)} (${nf(d.size)} bytes)</dd>
      <dt>Modified</dt><dd>${date(d.modified) || "unknown"}</dd>
      <dt>Found by</dt><dd>${esc(method)}</dd>
      <dt>Pieces</dt><dd>${d.fragments === 1 ? "1 (in one piece)" : `${d.fragments} (fragmented)`}</dd>
      ${d.folder_deleted ? "<dt>Folder</dt><dd>Its folder was deleted too</dd>" : ""}
      <dt>Location</dt><dd>${d.offset >= 0 ? `byte ${nf(d.offset)} on the drive` : "inside the file table record"}</dd>
      <dt>Evidence</dt><dd><ul>${d.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></dd>
    </dl>`;
    return;
  }
  if (S.pvTab === "hex") return renderHex(it, 0, my);
  return renderMedia(body, it, () => my === previewToken);
}

// Formats the window cannot draw itself, but which usually carry a JPEG inside.
const EMBEDDED_PREVIEW = new Set(["cr2", "cr3", "nef", "nrw", "arw", "srf", "sr2", "dng", "raf", "orf", "rw2", "pef", "srw", "x3f",
  "tif", "tiff", "heic", "heif", "psd", "mp3", "m4a", "mov", "mp4", "3gp"]);

/** Draws the best preview of ``it`` into ``body``; ``alive()`` turns false once the user moved on. */
async function renderMedia(body, it, alive, opts = {}) {
  const ext = it.ext;
  const note = (ic, text) => { if (alive()) body.innerHTML = `<div class="pv-note">${icon(ic)}${text}</div>`; };
  if (it.status === "overwritten") {
    note("alert", "This file's space has been reused or wiped, so a preview would only show other data. The Hex tab shows what is there now.");
    return;
  }
  const embedded = () => {
    body.innerHTML = `<div class="pv-media"><img alt=""></div><div class="pv-caption">Preview stored inside the file. The file itself is recovered complete.</div>`;
    const img = $("img", body);
    img.onerror = () => note(it.category, `No preview for .${esc(ext || "?")} files here${it.category === "image" ? " (the window cannot draw this picture format)" : ""}. Recovering it works the same.`);
    img.src = previewUrl(it.id);
  };
  if (SHOWABLE_IMAGE.has(ext) || (it.category === "image" && !it.named && !EMBEDDED_PREVIEW.has(ext))) {
    body.innerHTML = `<div class="pv-media"><img alt=""></div>`;
    const img = $("img", body);
    img.onload = () => { if (img.naturalWidth < 200 && img.naturalHeight < 200) img.classList.add("small"); };
    img.onerror = () => note("image", "This picture does not open here: its data is damaged, or it is a format the preview cannot show. Recovering it may still work.");
    img.src = dataUrl(it.id);
    return;
  }
  if (PLAYABLE_VIDEO.has(ext)) {
    body.innerHTML = `<div class="pv-media"><video controls preload="metadata" ${opts.autoplay ? "autoplay" : ""}></video></div>`;
    const v = $("video", body);
    v.onerror = () => { if (alive()) embedded(); };
    v.src = dataUrl(it.id);
    return;
  }
  if (PLAYABLE_AUDIO.has(ext)) {
    body.innerHTML = `<div class="pv-media audio"><img class="cover" alt="" hidden><div class="cover-ph">${icon("audio")}</div><audio controls preload="metadata" ${opts.autoplay ? "autoplay" : ""}></audio></div>`;
    const cover = $(".cover", body);
    cover.onload = () => { cover.hidden = false; $(".cover-ph", body).hidden = true; };
    if (ext === "mp3" || ext === "m4a" || ext === "flac") cover.src = previewUrl(it.id);
    $("audio", body).src = dataUrl(it.id);
    return;
  }
  if (ext === "pdf") {
    body.innerHTML = `<iframe title="PDF preview"></iframe>`;
    $("iframe", body).src = dataUrl(it.id);
    return;
  }
  if (TEXTY.has(ext)) {
    const r = await api(`/api/item/${it.id}/text`).catch((e) => ({ text: "", note: e.message }));
    if (!alive()) return;
    if (!r.text) { body.innerHTML = `<div class="pv-note">${esc(r.note || "No readable text in this file.")}</div>`; return; }
    body.innerHTML = `<pre class="pv-text"></pre>${r.truncated ? '<div class="pv-note">Only the start is shown.</div>' : ""}`;
    $("pre", body).textContent = r.text;
    return;
  }
  if (EMBEDDED_PREVIEW.has(ext) || it.category === "image" || it.category === "video") { embedded(); return; }
  note(it.category, `No preview for .${esc(ext || "?")} files. The Hex tab shows the raw bytes.`);
}

async function renderHex(it, offset, my) {
  const body = $("#pv-body");
  const r = await api(`/api/item/${it.id}/hex?offset=${offset}&length=4096`).catch((e) => ({ error: e.message }));
  if (my !== previewToken) return;
  if (r.error) { body.innerHTML = `<div class="pv-note">${esc(r.error)}</div>`; return; }
  const lines = r.rows.map(([off, hex, asc]) =>
    `<span class="off">${off.toString(16).padStart(8, "0")}</span>  ${hex.padEnd(47, " ")}  <span class="asc">${esc(asc)}</span>`).join("\n");
  const more = offset + 4096 < r.size;
  const html = `<pre class="pv-hex">${lines}</pre>${more ? `<div class="pv-more"><button class="btn ghost sm" id="hex-more">Show more</button></div>` : ""}`;
  if (offset === 0) body.innerHTML = html;
  else { $("#hex-more")?.parentElement.remove(); body.insertAdjacentHTML("beforeend", html); }
  $("#hex-more")?.addEventListener("click", () => renderHex(it, offset + 4096, my));
}
$("#pv-save").onclick = () => { const it = S.items[S.current]; if (it) openRecover([it]); };

/* ---------- Quick Look ---------- */
const ql = $("#ql");
let qlList = [];
let qlIdx = 0;
let qlToken = 0;

function openQuickLook(it, list = null) {
  if (!it) return;
  qlList = list ? list.slice()
    : S.view === "grid" || S.filters.q.trim() ? S.shown.slice() : flatten(true).filter((r) => r.file).map((r) => r.file);
  qlIdx = Math.max(0, qlList.findIndex((x) => x.id === it.id));
  if (!ql.open) ql.showModal();
  // Keys belong to the viewer, not to whichever of its buttons got focus
  // (Enter would otherwise press "close").
  ql.focus();
  renderQuickLook();
}

function renderQuickLook() {
  const it = qlList[qlIdx];
  if (!it) { ql.close(); return; }
  const my = ++qlToken;
  S.current = it.id;
  renderList();
  scrollToFile(it);
  $("#ql-name").textContent = it.name;
  $("#ql-sub").textContent = it.named ? `/${it.path}` : `Reconstructed · ${CAT_ONE[it.category]}`;
  $("#ql-count").textContent = `${nf(qlIdx + 1)} of ${nf(qlList.length)}`;
  $("#ql-meta").innerHTML = `${chance(it.status)}<span>${size(it.size)}</span>${it.modified ? `<span>${esc(date(it.modified))}</span>` : ""}`;
  $("#ql-pick").checked = S.selected.has(it.id);
  $("#ql-prev").disabled = qlIdx === 0;
  $("#ql-next").disabled = qlIdx >= qlList.length - 1;
  const body = $("#ql-body");
  body.innerHTML = '<div class="pv-note"><span class="spinner"></span></div>';
  renderMedia(body, it, () => my === qlToken && ql.open);
}

function qlStep(delta) {
  const next = qlIdx + delta;
  if (next < 0 || next >= qlList.length) return;
  qlIdx = next;
  renderQuickLook();
}
$("#ql-prev").onclick = () => qlStep(-1);
$("#ql-next").onclick = () => qlStep(1);
$("#ql-close").onclick = () => ql.close();
$("#ql-save").onclick = () => { const it = qlList[qlIdx]; if (it) { ql.close(); openRecover([it]); } };
$("#ql-pick").onchange = (e) => {
  const it = qlList[qlIdx];
  if (!it) return;
  e.target.checked ? S.selected.add(it.id) : S.selected.delete(it.id);
  afterSelection();
};
ql.addEventListener("close", () => { qlToken++; $("#ql-body").innerHTML = ""; });
ql.addEventListener("click", (e) => { if (e.target === ql) ql.close(); });
ql.addEventListener("keydown", (e) => {
  if (e.target.matches("input[type=text], textarea")) return;
  const act = {
    ArrowRight: () => qlStep(1), ArrowDown: () => qlStep(1),
    ArrowLeft: () => qlStep(-1), ArrowUp: () => qlStep(-1),
    " ": () => ql.close(), Enter: () => $("#ql-pick").click(),
  }[e.key];
  if (!act) return;
  // Handled here: the list's own shortcuts must not see it (Space would reopen the viewer).
  e.preventDefault();
  e.stopPropagation();
  act();
});

/* ---------- recover dialog ---------- */
const dlg = $("#recover-dialog");
let recoverItems = [];
let recoverPoll = null;
let recoverState = "form";
$("#recover-btn").onclick = () => openRecover(S.selected.size ? selectedItems() : (S.shown || []).slice());

function setRecoverView(view) {
  recoverState = view;
  $("#rd-form").hidden = view !== "form";
  $("#rd-progress").hidden = view !== "running";
  $("#rd-done").hidden = view !== "done";
  $(".dlg-head", dlg).hidden = view === "done";
  $("#rd-start").hidden = view !== "form";
  $("#rd-open").hidden = view !== "done";
  $("#rd-open").classList.add("primary");
  $("#rd-report").hidden = true;
  $("#rd-eject").hidden = true;
  $("#rd-cancel").textContent = view === "form" ? "Cancel" : view === "running" ? "Stop" : "Close";
}

function openRecover(items) {
  recoverItems = items;
  const bytes = items.reduce((a, it) => a + it.size, 0);
  const low = items.filter((it) => it.status === "overwritten").length;
  $("#rd-title").textContent = items.length === 1 ? `Recover “${items[0].name}”` : `Recover ${plural(items.length, "file")}`;
  $("#rd-sub").textContent = `${size(bytes)} will be copied out. The drive you scanned is never changed.`;
  setRecoverView("form");
  $("#rd-msg").innerHTML = low ? `<div class="msg warn">${icon("alert")}<span>${plural(low, "file")} with low chances: ${low === 1 ? "it" : "they"} will most likely not open.</span></div>` : "";
  if (!$("#rd-dest").value) { try { $("#rd-dest").value = localStorage.getItem("tizo-dest") || ""; } catch {} }
  dlg.showModal();
  if (!$("#rd-dest").value) {
    // First time: a dated folder on the Desktop (or another drive), never on the drive being recovered.
    api("/api/suggest-dest").then((r) => { if (r.dest && !$("#rd-dest").value) $("#rd-dest").value = r.dest; checkDest(); })
      .catch(() => checkDest());
  } else checkDest();
}

let destTimer = null;
async function checkDest() {
  const dest = $("#rd-dest").value.trim();
  const need = recoverItems.reduce((a, it) => a + it.size, 0);
  const warnLow = $("#rd-msg .warn")?.outerHTML || "";
  $("#rd-space").innerHTML = "";
  if (!dest) { $("#rd-start").disabled = true; $("#rd-msg").innerHTML = warnLow; return; }
  try {
    const r = await api("/api/check-dest", { dest, need });
    $("#rd-msg").innerHTML = warnLow + (r.error ? `<div class="msg bad">${icon("alert")}<span>${esc(r.error)}</span></div>` : "");
    $("#rd-start").disabled = !!r.error;
    if (r.total) {
      const used = ((r.total - r.free) / r.total) * 100;
      const needPct = Math.min(100 - used, (need / r.total) * 100);
      $("#rd-space").innerHTML = `<div class="bar"><div class="used" style="width:${used}%"></div><div class="need ${need > r.free ? "over" : ""}" style="width:${Math.max(needPct, 0.6)}%"></div></div>
        <span>${esc(r.root || "")} ${size(r.free)} free · these files need ${size(need)}</span>`;
    }
  } catch {
    $("#rd-start").disabled = true;
  }
}
$("#rd-dest").oninput = () => { clearTimeout(destTimer); destTimer = setTimeout(checkDest, 250); };
$("#rd-browse").onclick = async () => {
  try {
    const { path } = await api("/api/pick", { kind: "folder" });
    if (path) { $("#rd-dest").value = path; checkDest(); }
  } catch (e) { toast(e.message); }
};
$("#rd-cancel").onclick = async () => {
  if (recoverState === "running") { await api("/api/recover/stop", {}).catch(() => {}); return; }
  clearTimeout(recoverPoll);
  dlg.close();
};
dlg.addEventListener("cancel", (e) => { if (recoverState === "running") e.preventDefault(); });
$("#rd-start").onclick = async () => {
  const dest = $("#rd-dest").value.trim();
  try {
    await api("/api/recover", { ids: recoverItems.map((it) => it.id), dest, keep_folders: $("#rd-keep").checked });
  } catch (e) {
    $("#rd-msg").innerHTML = `<div class="msg bad">${icon("alert")}<span>${esc(e.message)}</span></div>`;
    return;
  }
  try { localStorage.setItem("tizo-dest", dest); } catch {}
  setRecoverView("running");
  $("#rd-bar").style.width = "0%";
  pollRecover();
};
async function pollRecover() {
  const r = await api("/api/recover").catch(() => null);
  if (!r) { recoverPoll = setTimeout(pollRecover, 800); return; }
  const pct = r.bytes ? (r.done_bytes / r.bytes) * 100 : 0;
  $("#rd-bar").style.width = `${r.state === "done" ? 100 : pct}%`;
  $("#rd-pct").textContent = `${Math.floor(r.state === "done" ? 100 : pct)}%`;
  $("#rd-status").textContent = `${nf(r.done_files)} of ${plural(r.files, "file")} · ${size(r.done_bytes)} of ${size(r.bytes)}`;
  if (r.state === "running") { recoverPoll = setTimeout(pollRecover, 400); return; }
  const failed = r.failed || [];
  const ok = r.done_files - failed.length;
  setRecoverView("done");
  const clean = r.state === "done" && !failed.length;
  $("#rd-done-ico").className = `done-ico ${clean ? "" : "warn"}`;
  $("#rd-done-ico").innerHTML = icon(clean ? "check" : "alert");
  $("#rd-done-title").textContent = r.state === "done" ? `${plural(ok, "file")} recovered` : `Stopped: ${plural(ok, "file")} recovered`;
  $("#rd-done-sub").textContent = r.dest;
  $("#rd-done-msg").innerHTML = failed.length
    ? `<div class="msg bad">${icon("alert")}<span>${plural(failed.length, "file")} could not be written: ${esc(failed.slice(0, 3).map((f) => `${f.name} (${f.error})`).join("; "))}${failed.length > 3 ? "…" : ""}</span></div>` : "";
  $("#rd-open").onclick = () => api("/api/open-folder", { path: r.dest }).catch(() => {});
  // Your files are safe: offer to eject the drive they came from (a USB stick or card).
  const src = S.scan && S.scan.drive;
  if (r.state === "done" && src && src.removable && src.kind !== "image") {
    $("#rd-eject").hidden = false;
    $("#rd-eject").onclick = async () => { dlg.close(); await ejectDisk(src.disk); };
  }
  if (r.report) {
    $("#rd-report").hidden = false;
    $("#rd-report").onclick = () => api("/api/open-folder", { path: r.report }).catch(() => {});
  }
}

/* ---------- disk tools: erase ---------- */
function renderTools() {
  const list = disks().filter((g) => g.removable && !g.image);
  $("#erase-list").innerHTML = list.length ? list.map((g) =>
    `<div class="tool-row"><div class="dev-ico usb">${icon("usb")}</div><div class="t"><b>${esc(g.name)}</b><small>${size(g.size)} · ${g.parts.map((p) => esc(p.letter ? `${p.letter}: ${p.label || ""}` : p.label || "partition")).join(", ")}</small></div>
      <button class="btn" data-erase="${g.disk}">${icon("trash")}Erase…</button></div>`).join("")
    : `<div class="muted">No removable drives are plugged in.</div>`;
  $$("[data-erase]", $("#erase-list")).forEach((b) => { b.onclick = () => openErase(Number(b.dataset.erase)); });
}

const ed = $("#erase-dialog");
let erasePlan = null;
let eraseTimer = null;
let erasePoll = null;
let eraseReadyAt = 0;

async function openErase(disk) {
  let plan;
  try { plan = await api("/api/erase/prepare", { disk }); }
  catch (e) { toast(e.message); return; }
  erasePlan = plan;
  eraseReadyAt = Date.now() + plan.wait * 1000;
  $("#ed-title").textContent = `Erase ${plan.disk_name}?`;
  $("#ed-sub").textContent = `${size(plan.size)} · disk ${plan.disk} · ${plan.bus}`;
  $("#ed-volumes").innerHTML = plan.volumes.map((v) =>
    `<div>${icon("usb")} <b>${v.letter ? esc(v.letter) + ":" : "(no letter)"}</b> ${esc(v.label || "")} · ${esc(v.filesystem)} · ${size(v.size)}</div>`).join("");
  const span = ([lo, hi]) => (hi < 90 ? "under a minute" : `about ${duration(lo)} to ${duration(hi)}`);
  $$("[data-est]", ed).forEach((el) => { el.textContent = `· ${span(plan.estimates[el.dataset.est])}`; });
  $("input[name=ed-method][value=quick]").checked = true;
  $("#ed-phrase").textContent = plan.phrase;
  $("#ed-typed").value = "";
  $("#ed-understood").checked = false;
  $("#ed-msg").innerHTML = "";
  $("#ed-admin").innerHTML = plan.admin ? "" :
    `<div class="msg warn">Erasing needs administrator rights. <button class="btn sm" id="ed-elevate" style="margin-left:8px">Restart as administrator</button></div>`;
  $("#ed-elevate")?.addEventListener("click", elevate);
  $("#ed-form").hidden = false;
  $("#ed-progress").hidden = true;
  $("#ed-start").hidden = false;
  $("#ed-cancel").textContent = "Cancel";
  ed.showModal();
  $("#ed-cancel").focus();
  clearInterval(eraseTimer);
  eraseTimer = setInterval(updateEraseButton, 250);
  updateEraseButton();
}

function updateEraseButton() {
  if (!erasePlan) return;
  const left = Math.ceil((eraseReadyAt - Date.now()) / 1000);
  const typed = $("#ed-typed").value.trim().toUpperCase() === erasePlan.phrase.toUpperCase();
  const ok = left <= 0 && typed && $("#ed-understood").checked && erasePlan.admin;
  const btn = $("#ed-start");
  btn.disabled = !ok;
  btn.textContent = left > 0 ? `Erase drive (${left})` : "Erase drive";
}
$("#ed-typed").addEventListener("paste", (e) => e.preventDefault());
$("#ed-typed").oninput = updateEraseButton;
$("#ed-understood").onchange = updateEraseButton;
ed.addEventListener("close", () => { clearInterval(eraseTimer); clearTimeout(erasePoll); });

$("#ed-start").onclick = async () => {
  if ($("#ed-start").disabled || !erasePlan) return;
  const method = $("input[name=ed-method]:checked").value;
  const filesystem = $("input[name=ed-fs]:checked").value;
  try {
    await api("/api/erase/start", {
      token: erasePlan.token, typed: $("#ed-typed").value, understood: $("#ed-understood").checked,
      method, filesystem, label: $("#ed-label").value,
    });
  } catch (e) {
    $("#ed-msg").innerHTML = `<div class="msg bad">${esc(e.message)}</div>`;
    if (/expired|changed/.test(e.message)) $("#ed-start").disabled = true;
    return;
  }
  clearInterval(eraseTimer);
  erasePlan = null;
  $("#ed-form").hidden = true;
  $("#ed-progress").hidden = false;
  $("#ed-start").hidden = true;
  $("#ed-cancel").textContent = "Stop";
  $("#ed-result").innerHTML = "";
  pollErase();
};

const ERASE_STAGE = { preparing: "Preparing", "file tables": "Wiping file tables", unmounting: "Unmounting the drive", "random data": "Writing random data", zeros: "Writing zeros", verifying: "Checking it worked", formatting: "Formatting", done: "Done", stopped: "Stopped", failed: "Failed" };
async function pollErase() {
  const r = await api("/api/erase").catch(() => null);
  if (!r) { erasePoll = setTimeout(pollErase, 1000); return; }
  const pct = r.total ? (r.done / r.total) * 100 : 0;
  $("#ed-bar").style.width = `${r.state === "done" ? 100 : pct}%`;
  const parts = [ERASE_STAGE[r.stage] || r.stage];
  if (r.passes > 1 && r.state === "running") parts.push(`pass ${r.pass} of ${r.passes}`);
  if (r.total) parts.push(`${size(r.done)} of ${size(r.total)} (${pct.toFixed(0)}%)`);
  if (r.skipped) parts.push(`${size(r.skipped)} already blank, skipped`);
  parts.push(`${duration(r.elapsed)} elapsed`);
  if (r.eta != null) parts.push(`about ${duration(r.eta)} left`);
  $("#ed-status").textContent = parts.join(" · ");
  if (r.state === "running" || r.state === "starting") { erasePoll = setTimeout(pollErase, 700); return; }
  $("#ed-result").innerHTML = r.state === "done" ? `<div class="msg ok">${esc(r.result)}</div>`
    : r.state === "stopped" ? `<div class="msg warn">${esc(r.result)}</div>`
    : `<div class="msg bad">${esc(r.error)}</div>`;
  $("#ed-cancel").textContent = "Close";
  loadDrives(true);
}
$("#ed-cancel").onclick = async () => {
  if ($("#ed-cancel").textContent === "Stop") {
    if (await ask("Stop erasing?", "The drive will be left partly erased and unusable until it is erased again or formatted.", "Stop erasing")) {
      await api("/api/erase/stop", {}).catch(() => {});
    }
    return;
  }
  ed.close();
};
ed.addEventListener("cancel", (e) => { if ($("#ed-cancel").textContent === "Stop") e.preventDefault(); });

renderMethod();
init();
