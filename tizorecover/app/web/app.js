const TOKEN = new URLSearchParams(location.search).get("t") || "";
history.replaceState(null, "", location.pathname);

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ---------- icons ---------- */
const P = {
  usb: '<path d="M10 2h4v5h-4zM8 7h8v9a4 4 0 0 1-4 4 4 4 0 0 1-4-4z"/><path d="M12 20v2"/>',
  ssd: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h6M7 14h3"/><circle cx="17" cy="12" r="1"/>',
  hdd: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="12" cy="11" r="4"/><path d="M12 11l3.5 5"/>',
  disc: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  chevron: '<path d="M9 5l7 7-7 7"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M12 8v5M12 16h.01"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z"/>',
  all: '<rect x="3" y="3" width="18" height="18" rx="3"/>',
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
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
const dataUrl = (id, extra = "") => `/api/item/${id}/data?t=${encodeURIComponent(TOKEN)}${extra}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function size(n) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return i === 0 ? `${n} B` : `${n.toFixed(n < 10 ? 1 : 0)} ${u[i]}`;
}
function duration(s) {
  if (s == null) return "";
  s = Math.round(s);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}
const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const date = (t) => (t ? dateFmt.format(new Date(t * 1000)) : "");
function toast(text) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}
const STATUS = {
  good: { label: "Good", tip: "Nothing suggests damage" },
  partial: { label: "Partial", tip: "Some of it may be damaged" },
  overwritten: { label: "Overwritten", tip: "Its space belongs to other files now" },
};
const CATS = ["image", "video", "audio", "document", "archive", "code", "program", "other"];
const CAT_LABEL = { image: "Pictures", video: "Videos", audio: "Music & audio", document: "Documents", archive: "Archives", code: "Code", program: "Programs", other: "Other" };
const STAGE_LABEL = { starting: "Starting", opening: "Opening the drive", records: "Reading the file table", deep: "Searching free space by content", done: "Finished", stopped: "Stopped", failed: "Failed" };

/* ---------- theme ---------- */
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  $("#theme").innerHTML = icon(t === "dark" ? "sun" : "moon");
  try { localStorage.setItem("tizo-theme", t); } catch {}
}
(() => {
  let t = "dark";
  try { t = localStorage.getItem("tizo-theme") || "dark"; } catch {}
  setTheme(t);
})();
$("#theme").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");

/* ---------- state ---------- */
const S = {
  env: {},
  drives: [],
  items: [],
  shown: [],
  selected: new Set(),
  current: null,
  scan: null,
  polling: null,
  filters: { q: "", status: new Set(["good", "partial", "overwritten"]), cat: null, folder: null },
  sort: { key: "status", dir: 1 },
  view: "list",
  tab: "preview",
  treeOpen: new Set([""]),
};

/* ---------- drives screen ---------- */
async function init() {
  paintIcons();
  try {
    S.env = await api("/api/env");
    $("#ver").textContent = `v${S.env.version}`;
    $("#admin-chip").innerHTML = S.env.admin
      ? `<span class="chip ok">${icon("shield")}Administrator</span>`
      : `<span class="chip warn">${icon("shield")}Not administrator</span>`;
    $("#admin-banner").hidden = S.env.admin || S.env.platform !== "win32";
  } catch (e) {
    toast(`Could not reach the engine: ${e.message}`);
  }
  loadDrives(false);
  setInterval(() => api("/api/ping").catch(() => {}), 10000);
}

async function loadDrives(refresh) {
  const box = $("#drive-sections");
  if (refresh) box.innerHTML = '<div class="empty-drives"><span class="spinner"></span> Looking for drives…</div>';
  try {
    const { drives } = await api(`/api/drives${refresh ? "?refresh=1" : ""}`);
    S.drives = drives;
    renderDrives();
  } catch (e) {
    box.innerHTML = `<div class="empty-drives">Could not list drives: ${esc(e.message)}</div>`;
  }
}

function driveIcon(d) {
  if (d.kind === "image") return "disc";
  if (d.removable) return "usb";
  if (d.media === "HDD") return "hdd";
  return "ssd";
}

function driveCard(d, recommended) {
  const title = d.kind === "image" ? d.label : d.letter ? `${d.letter}:  ${d.label || d.disk_name}` : d.label || `${d.disk_name} · partition ${d.partition}`;
  const used = d.size && d.free ? Math.max(0, Math.min(100, ((d.size - d.free) / d.size) * 100)) : 0;
  const chips = [];
  if (d.removable) chips.push('<span class="chip accent">Removable</span>');
  if (d.kind === "partition") chips.push('<span class="chip info">No drive letter</span>');
  if (!d.removable && d.media === "SSD") chips.push('<span class="chip warn" title="SSDs erase deleted data on their own (TRIM), usually within seconds">SSD: deleted files are often wiped</span>');
  if (d.system) chips.push('<span class="chip">Windows drive</span>');
  const sub = [size(d.size), d.filesystem !== "unknown" ? d.filesystem : "unknown filesystem", d.free ? `${size(d.free)} free` : ""].filter(Boolean).join(" · ");
  return `<div class="drive ${d.removable ? "removable" : ""} ${recommended ? "recommended" : ""}" data-id="${esc(d.id)}">
    <div class="drive-head">
      <div class="drive-icon">${icon(driveIcon(d))}</div>
      <div style="min-width:0">
        <div class="drive-title" title="${esc(title)}">${esc(title)}</div>
        <div class="drive-sub">${esc(d.kind === "image" ? d.path : `${d.disk_name} · ${d.bus || ""}`)}</div>
      </div>
    </div>
    ${used ? `<div class="drive-bar" title="${used.toFixed(0)}% in use"><div style="width:${used}%"></div></div>` : ""}
    <div class="drive-sub">${esc(sub)}</div>
    ${chips.length ? `<div class="drive-meta">${chips.join("")}</div>` : ""}
    <div class="drive-actions">
      <button class="btn primary" data-scan="quick">${icon("bolt")}Quick scan</button>
      <button class="btn secondary" data-scan="deep">${icon("layers")}Deep scan</button>
    </div>
    ${d.removable && d.kind !== "image" ? `<div class="drive-foot"><button class="link-danger" data-erase="${d.disk}" title="Wipe the whole drive so nothing can be recovered">${icon("trash")}Erase this drive…</button></div>` : ""}
  </div>`;
}

function renderDrives() {
  const groups = [
    ["Removable drives", S.drives.filter((d) => d.removable && d.kind !== "image")],
    ["Disk images", S.drives.filter((d) => d.kind === "image")],
    ["Other drives", S.drives.filter((d) => !d.removable && d.kind !== "image")],
  ].filter(([, list]) => list.length);
  const box = $("#drive-sections");
  if (!groups.length) {
    box.innerHTML = '<div class="empty-drives">No drives found. Plug in a USB stick or memory card and press Refresh.</div>';
    return;
  }
  let first = true;
  box.innerHTML = groups.map(([label, list]) => {
    const html = `<div class="section-label">${label}</div><div class="drive-grid">${list.map((d) => {
      const rec = first && d.removable;
      if (rec) first = false;
      return driveCard(d, rec);
    }).join("")}</div>`;
    return html;
  }).join("");
  $$(".drive [data-scan]", box).forEach((b) => {
    b.onclick = () => startScan(b.closest(".drive").dataset.id, b.dataset.scan);
  });
  $$(".drive [data-erase]", box).forEach((b) => {
    b.onclick = () => openErase(Number(b.dataset.erase));
  });
}

$("#refresh").onclick = () => loadDrives(true);
$("#open-image").onclick = async () => {
  try {
    const { path } = await api("/api/pick", { kind: "image" });
    if (!path) return;
    const { drive } = await api("/api/image", { path });
    S.drives = S.drives.filter((d) => d.id !== drive.id).concat(drive);
    renderDrives();
  } catch (e) { toast(e.message); }
};
$("#elevate").onclick = async () => {
  try {
    const r = await api("/api/elevate", {});
    if (r.ok) toast("Restarting as administrator…");
    else toast("Windows did not allow it. Right-click TizoRecover and choose Run as administrator.");
  } catch (e) { toast(e.message); }
};

/* ---------- scanning ---------- */
async function startScan(driveId, mode) {
  try {
    await api("/api/scan", { drive: driveId, mode });
  } catch (e) { toast(e.message); return; }
  S.items = [];
  S.selected.clear();
  S.current = null;
  S.filters.folder = null;
  S.filters.cat = null;
  S.treeOpen = new Set([""]);
  $("#screen-drives").hidden = true;
  $("#screen-results").hidden = false;
  showPreview(null);
  refilter();
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

async function poll() {
  clearTimeout(S.polling);
  let s;
  try { s = await api("/api/scan"); } catch (e) { S.polling = setTimeout(poll, 1500); return; }
  S.scan = s;
  const before = S.items.length;
  if (s.found > before) await fetchItems();
  renderScanbar();
  if (S.items.length !== before || s.state !== "running") refilter(true);
  if (s.state === "running" || s.state === "starting") S.polling = setTimeout(poll, 700);
}

function renderScanbar() {
  const s = S.scan;
  if (!s) return;
  const d = s.drive;
  $("#scan-drive").textContent = d.kind === "image" ? d.label : d.letter ? `${d.letter}:  ${d.label || d.disk_name}` : d.label || d.disk_name;
  $("#scan-mode").textContent = `${s.mode === "deep" ? "Deep scan" : "Quick scan"} · ${s.filesystem !== "unknown" ? s.filesystem.toUpperCase() : "filesystem not recognised"}`;
  const p = s.progress;
  const bar = $("#scan-progress");
  const running = s.state === "running" || s.state === "starting";
  bar.classList.toggle("done", s.state === "done");
  const pct = p.total ? Math.min(100, (p.done / p.total) * 100) : 0;
  bar.classList.toggle("indeterminate", running && !p.total);
  bar.firstElementChild.style.width = running ? (p.total ? `${pct}%` : "") : "100%";
  const parts = [STAGE_LABEL[p.stage] || p.stage];
  if (running && p.total) parts.push(`${size(p.done)} of ${size(p.total)} (${pct.toFixed(0)}%)`);
  parts.push(`${duration(p.elapsed)} elapsed`);
  if (running && p.eta != null) parts.push(`about ${duration(p.eta)} left`);
  if (!running) parts.push(`${s.found.toLocaleString()} found`);
  if (s.problems.length) parts.push(`<span style="color:var(--warn)">${esc(s.problems[0])}</span>`);
  $("#scan-stage").innerHTML = parts.map((x) => (x.startsWith("<span") ? x : esc(x))).join(" · ");
  const c = s.counts;
  $("#scan-counts").innerHTML = ["good", "partial", "overwritten"].map((k) =>
    `<span class="chip" title="${STATUS[k].tip}"><span class="dot ${k}"></span>${(c[k] || 0).toLocaleString()}</span>`).join("");
  $("#stop").hidden = !running;
  $("#go-deep").hidden = running || s.mode === "deep" || s.state === "failed";
}

$("#stop").onclick = () => api("/api/scan/stop", {}).catch(() => {});
$("#go-deep").onclick = () => S.scan && startScan(S.scan.drive.id, "deep");
$("#back").onclick = async () => {
  if (S.scan && (S.scan.state === "running" || S.scan.state === "starting")) {
    if (!confirm("Stop the scan and go back to the drives?")) return;
    await api("/api/scan/stop", {}).catch(() => {});
  }
  clearTimeout(S.polling);
  $("#screen-results").hidden = true;
  $("#screen-drives").hidden = false;
};

/* ---------- filtering ---------- */
const UNNAMED = "<content>";
const ALL_KEY = "<all>";
function folderKey(it) { return it.named ? it.folder : `${UNNAMED}/${it.category}`; }

let refilterTimer = null;
function refilter(soon) {
  clearTimeout(refilterTimer);
  if (soon) refilterTimer = setTimeout(doRefilter, 120);
  else doRefilter();
}

function doRefilter() {
  const f = S.filters;
  const q = f.q.trim().toLowerCase();
  const base = S.items.filter((it) => {
    if (q && !(`${it.folder}/${it.name}`.toLowerCase().includes(q))) return false;
    if (f.folder !== null) {
      const k = folderKey(it);
      if (!(k === f.folder || k.startsWith(f.folder + "/"))) return false;
    }
    return true;
  });
  const statusCount = { good: 0, partial: 0, overwritten: 0 };
  const catCount = {};
  for (const it of base) {
    statusCount[it.status]++;
    if (f.status.has(it.status)) catCount[it.category] = (catCount[it.category] || 0) + 1;
  }
  S.shown = base.filter((it) => f.status.has(it.status) && (!f.cat || it.category === f.cat));
  sortShown();
  renderFilters(statusCount, catCount);
  renderTree();
  renderCrumbs();
  renderList();
  renderSelection();
  renderEmpty();
}

const STATUS_ORDER = { good: 0, partial: 1, overwritten: 2 };
function sortShown() {
  const { key, dir } = S.sort;
  const cmp = {
    name: (a, b) => a.name.localeCompare(b.name),
    folder: (a, b) => folderKey(a).localeCompare(folderKey(b)) || a.name.localeCompare(b.name),
    size: (a, b) => a.size - b.size,
    modified: (a, b) => (a.modified || 0) - (b.modified || 0),
    status: (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || (b.named - a.named) || folderKey(a).localeCompare(folderKey(b)) || a.name.localeCompare(b.name),
  }[key];
  S.shown.sort((a, b) => dir * cmp(a, b));
  $$("#thead [data-sort]").forEach((el) => {
    el.classList.toggle("sorted", el.dataset.sort === key);
    el.textContent = el.textContent.replace(/ [▲▼]$/, "") + (el.dataset.sort === key ? (dir > 0 ? " ▲" : " ▼") : "");
  });
}

function renderFilters(statusCount, catCount) {
  const f = S.filters;
  $("#status-filters").innerHTML = ["good", "partial", "overwritten"].map((k) =>
    `<label class="filter" title="${STATUS[k].tip}"><input type="checkbox" class="check" data-status="${k}" ${f.status.has(k) ? "checked" : ""}><span class="dot ${k}"></span>${STATUS[k].label}<span class="n">${statusCount[k].toLocaleString()}</span></label>`).join("");
  $$("#status-filters [data-status]").forEach((el) => {
    el.onchange = () => { el.checked ? f.status.add(el.dataset.status) : f.status.delete(el.dataset.status); refilter(); };
  });
  const total = Object.values(catCount).reduce((a, b) => a + b, 0);
  $("#cat-filters").innerHTML = `<button class="filter ${f.cat ? "" : "active"}" data-cat="">${icon("all")}All types<span class="n">${total.toLocaleString()}</span></button>` +
    CATS.filter((c) => catCount[c]).map((c) =>
      `<button class="filter ${f.cat === c ? "active" : ""}" data-cat="${c}">${icon(c, `cat-${c}`)}${CAT_LABEL[c]}<span class="n">${catCount[c].toLocaleString()}</span></button>`).join("");
  $$("#cat-filters [data-cat]").forEach((el) => {
    el.onclick = () => { f.cat = el.dataset.cat || null; refilter(); };
  });
}

function buildTree() {
  const root = { name: "", key: "", count: 0, children: new Map(), deleted: false };
  for (const it of S.items) {
    if (!S.filters.status.has(it.status)) continue;
    const key = folderKey(it);
    root.count++;
    let node = root;
    let acc = "";
    for (const part of key ? key.split("/") : []) {
      acc = acc ? `${acc}/${part}` : part;
      if (!node.children.has(part)) node.children.set(part, { name: part, key: acc, count: 0, children: new Map(), deleted: false });
      node = node.children.get(part);
      node.count++;
      if (it.folder_deleted) node.deleted = true;
    }
  }
  return root;
}

function renderTree() {
  const root = buildTree();
  const f = S.filters;
  const rows = [];
  const walk = (node, depth) => {
    const kids = [...node.children.values()].sort((a, b) => {
      const ac = a.key.startsWith(UNNAMED), bc = b.key.startsWith(UNNAMED);
      return ac - bc || a.name.localeCompare(b.name);
    });
    for (const k of kids) {
      const open = S.treeOpen.has(k.key);
      const isContent = k.key === UNNAMED;
      const label = isContent ? "Found by content" : k.key.startsWith(UNNAMED + "/") ? CAT_LABEL[k.name] || k.name : k.name;
      rows.push(`<div class="node ${open ? "open" : ""} ${f.folder === k.key ? "active" : ""}" data-key="${esc(k.key)}" style="padding-left:${6 + depth * 14}px">
        <span class="twisty">${k.children.size ? icon("chevron") : ""}</span>
        ${icon(isContent ? "sparkle" : "folder", "fi")}
        <span class="label ${k.deleted ? "deleted" : ""}" title="${esc(label)}${k.deleted ? " (deleted folder)" : ""}">${esc(label)}</span>
        <span class="n">${k.count.toLocaleString()}</span></div>`);
      if (open) walk(k, depth + 1);
    }
  };
  rows.push(`<div class="node ${f.folder === null ? "active" : ""}" data-key="${ALL_KEY}"><span class="twisty"></span>${icon("disc", "fi")}<span class="label">Whole drive</span><span class="n">${root.count.toLocaleString()}</span></div>`);
  walk(root, 0);
  const tree = $("#tree");
  tree.innerHTML = rows.join("");
  $$(".node", tree).forEach((el) => {
    el.onclick = (ev) => {
      const key = el.dataset.key;
      if (key === ALL_KEY) { f.folder = null; refilter(); return; }
      if (ev.target.closest(".twisty") || f.folder === key) {
        S.treeOpen.has(key) ? S.treeOpen.delete(key) : S.treeOpen.add(key);
      } else {
        S.treeOpen.add(key);
      }
      f.folder = key;
      refilter();
    };
  });
}

function renderCrumbs() {
  const f = S.filters;
  let where = "Whole drive";
  if (f.folder !== null) {
    where = f.folder === UNNAMED ? "Found by content" : f.folder.startsWith(UNNAMED + "/") ? `Found by content › ${CAT_LABEL[f.folder.split("/")[1]]}` : f.folder.split("/").join(" › ") || "Top folder";
  }
  $("#crumbs").innerHTML = `<b>${S.shown.length.toLocaleString()}</b> files · ${esc(where)}${f.cat ? ` · ${CAT_LABEL[f.cat]}` : ""}`;
}

$("#q").oninput = (e) => { S.filters.q = e.target.value; refilter(true); };
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
    $("#thead").style.visibility = S.view === "list" ? "" : "hidden";
    $("#viewport").scrollTop = 0;
    renderList();
  };
});

/* ---------- virtual list / grid ---------- */
const ROW = 36;
const viewport = $("#viewport");
const spacer = $("#spacer");
viewport.addEventListener("scroll", () => requestAnimationFrame(renderList));
new ResizeObserver(() => renderList()).observe(viewport);

function gridGeometry() {
  const w = viewport.clientWidth - 24;
  const cols = Math.max(1, Math.floor((w + 10) / 170));
  const tileW = (w - (cols - 1) * 10) / cols;
  const tileH = tileW * 0.75 + 32;
  return { cols, rowH: tileH + 10 };
}

function renderList() {
  const items = S.shown;
  if (S.view === "grid") return renderGrid();
  spacer.style.height = `${items.length * ROW}px`;
  const top = viewport.scrollTop;
  const first = Math.max(0, Math.floor(top / ROW) - 6);
  const last = Math.min(items.length, Math.ceil((top + viewport.clientHeight) / ROW) + 6);
  let html = "";
  for (let i = first; i < last; i++) {
    const it = items[i];
    const folder = it.named ? (it.folder || "(top folder)") : "Found by content";
    html += `<div class="row ${it.status} ${S.current === it.id ? "current" : ""}" data-i="${i}" style="top:${i * ROW}px">
      <div><input type="checkbox" class="check" data-pick="${it.id}" ${S.selected.has(it.id) ? "checked" : ""}></div>
      <div class="name-cell">${icon(it.category, `cat-${it.category}`)}<span class="nm" title="${esc(it.name)}">${esc(it.name)}</span></div>
      <div class="folder" title="${esc(folder)}">${esc(folder)}</div>
      <div class="num">${size(it.size)}</div>
      <div class="num" style="text-align:left">${date(it.modified)}</div>
      <div><span class="badge ${it.status}" title="${STATUS[it.status].tip}">${STATUS[it.status].label}</span></div>
    </div>`;
  }
  spacer.innerHTML = html;
}

function renderGrid() {
  const items = S.shown;
  const { cols, rowH } = gridGeometry();
  const rows = Math.ceil(items.length / cols);
  spacer.style.height = `${rows * rowH + 12}px`;
  const top = viewport.scrollTop;
  const firstRow = Math.max(0, Math.floor(top / rowH) - 2);
  const lastRow = Math.min(rows, Math.ceil((top + viewport.clientHeight) / rowH) + 2);
  let html = `<div class="grid-tiles" style="top:${firstRow * rowH + 12}px;grid-template-columns:repeat(${cols},1fr)">`;
  for (let i = firstRow * cols; i < Math.min(items.length, lastRow * cols); i++) {
    const it = items[i];
    const thumb = it.category === "image" && it.status !== "overwritten" && it.size < 40e6
      ? `<img loading="lazy" src="${dataUrl(it.id)}" alt="">`
      : icon(it.category, `cat-${it.category}`);
    html += `<div class="tile ${S.current === it.id ? "current" : ""}" data-i="${i}">
      <input type="checkbox" class="check" data-pick="${it.id}" ${S.selected.has(it.id) ? "checked" : ""}>
      <div class="thumb">${thumb}</div>
      <div class="cap"><span class="dot ${it.status}"></span><span class="nm" title="${esc(it.name)}">${esc(it.name)}</span></div>
    </div>`;
  }
  spacer.innerHTML = html + "</div>";
}

spacer.addEventListener("error", (ev) => {
  if (ev.target.tagName === "IMG") ev.target.outerHTML = icon("image");
}, true);

let lastPick = null;
spacer.addEventListener("click", (ev) => {
  const box = ev.target.closest("[data-pick]");
  const rowEl = ev.target.closest("[data-i]");
  if (!rowEl) return;
  const i = Number(rowEl.dataset.i);
  const it = S.shown[i];
  if (box) {
    const on = box.checked;
    if (ev.shiftKey && lastPick !== null) {
      const [a, b] = [Math.min(lastPick, i), Math.max(lastPick, i)];
      for (let k = a; k <= b; k++) on ? S.selected.add(S.shown[k].id) : S.selected.delete(S.shown[k].id);
      renderList();
    } else {
      on ? S.selected.add(it.id) : S.selected.delete(it.id);
    }
    lastPick = i;
    renderSelection();
    return;
  }
  select(it);
});
spacer.addEventListener("dblclick", (ev) => {
  const rowEl = ev.target.closest("[data-i]");
  if (!rowEl || ev.target.closest("[data-pick]")) return;
  const it = S.shown[Number(rowEl.dataset.i)];
  S.selected.has(it.id) ? S.selected.delete(it.id) : S.selected.add(it.id);
  renderList();
  renderSelection();
});

document.addEventListener("keydown", (ev) => {
  if ($("#screen-results").hidden || ev.target.matches("input, textarea") || $("#recover-dialog").open) return;
  const idx = S.shown.findIndex((x) => x.id === S.current);
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault();
    const step = S.view === "grid" ? gridGeometry().cols : 1;
    const next = Math.max(0, Math.min(S.shown.length - 1, (idx < 0 ? 0 : idx + (ev.key === "ArrowDown" ? step : -step))));
    if (S.shown[next]) { select(S.shown[next]); scrollToIndex(next); }
  } else if (ev.key === " " && idx >= 0) {
    ev.preventDefault();
    const id = S.current;
    S.selected.has(id) ? S.selected.delete(id) : S.selected.add(id);
    renderList();
    renderSelection();
  }
});
function scrollToIndex(i) {
  const h = S.view === "grid" ? gridGeometry().rowH : ROW;
  const y = S.view === "grid" ? Math.floor(i / gridGeometry().cols) * h : i * h;
  if (y < viewport.scrollTop) viewport.scrollTop = y;
  else if (y + h > viewport.scrollTop + viewport.clientHeight) viewport.scrollTop = y + h - viewport.clientHeight;
}

$("#check-all").onchange = (e) => {
  for (const it of S.shown) e.target.checked ? S.selected.add(it.id) : S.selected.delete(it.id);
  renderList();
  renderSelection();
};
$("#select-good").onclick = () => {
  for (const it of S.shown) if (it.status === "good") S.selected.add(it.id);
  renderList();
  renderSelection();
};
$("#select-none").onclick = () => { S.selected.clear(); renderList(); renderSelection(); };

function selectedItems() {
  const byId = new Map(S.items.map((it) => [it.id, it]));
  return [...S.selected].map((id) => byId.get(id)).filter(Boolean);
}
function renderSelection() {
  const items = selectedItems();
  const bytes = items.reduce((a, it) => a + it.size, 0);
  $("#sel-info").innerHTML = items.length ? `<b>${items.length.toLocaleString()}</b> selected · ${size(bytes)}` : "Tick the files you want back, or select all good ones";
  $("#recover-btn").disabled = !items.length;
  const shownSel = S.shown.length && S.shown.every((it) => S.selected.has(it.id));
  $("#check-all").checked = !!shownSel;
}

function renderEmpty() {
  const el = $("#empty");
  const s = S.scan;
  if (S.shown.length || !s) { el.hidden = true; return; }
  const running = s.state === "running" || s.state === "starting";
  el.hidden = false;
  if (running) {
    el.innerHTML = `<div class="box"><span class="spinner"></span><h3 style="margin-top:12px">Scanning…</h3>Files show up here as they are found.</div>`;
    return;
  }
  if (s.state === "failed") {
    el.innerHTML = `<div class="box"><h3>The scan could not run</h3>${s.problems.map((p) => `<p>${esc(p)}</p>`).join("")}</div>`;
    return;
  }
  if (S.items.length) {
    el.innerHTML = `<div class="box"><h3>No files match</h3>Try another folder, file type or search, or tick more statuses on the left.</div>`;
    return;
  }
  const ssd = s.drive.media === "SSD" && !s.drive.removable;
  el.innerHTML = `<div class="box"><h3>No deleted files found</h3>
    <div>That does not always mean they are gone. Common reasons:</div>
    <ul>
      ${s.mode !== "deep" ? "<li><b>Try a deep scan.</b> A quick scan only finds files the file table still remembers.</li>" : ""}
      ${ssd ? "<li><b>This is an SSD.</b> SSDs erase deleted data on their own (TRIM), usually within seconds, so there is often nothing left to find.</li>" : ""}
      <li>New files may have been saved over the deleted ones.</li>
      <li>The files may have been on a different drive, or in the cloud (OneDrive, Google Photos, iCloud).</li>
      <li>Check the Recycle Bin and Windows' File History or previous versions.</li>
    </ul></div>`;
}

/* ---------- preview ---------- */
let previewToken = 0;
function select(it) {
  S.current = it.id;
  renderList();
  showPreview(it);
}

function showPreview(it) {
  $("#pv-empty").hidden = !!it;
  $("#pv").hidden = !it;
  if (!it) return;
  $("#pv-name").textContent = it.name;
  $("#pv-path").textContent = it.named ? `${it.path}` : "Found by content (original name unknown)";
  renderTab();
}

$$("#pv-tabs button").forEach((b) => {
  b.onclick = () => {
    S.tab = b.dataset.tab;
    $$("#pv-tabs button").forEach((x) => x.classList.toggle("active", x === b));
    renderTab();
  };
});

const TEXTY = new Set(["txt", "md", "csv", "log", "ini", "cfg", "json", "xml", "html", "htm", "yaml", "yml", "py", "js", "ts", "c", "h", "cpp", "cs", "java", "go", "rs", "php", "rb", "sh", "ps1", "bat", "css", "sql", "lua", "srt", "vtt", "toml", "rtf", "docx", "pptx", "xlsx", "odt", "ods", "odp"]);
const PLAYABLE_VIDEO = new Set(["mp4", "m4v", "mov", "webm", "3gp"]);
const PLAYABLE_AUDIO = new Set(["mp3", "wav", "ogg", "opus", "flac", "m4a", "aac"]);
const SHOWABLE_IMAGE = new Set(["jpg", "jpeg", "png", "gif", "bmp", "webp", "ico", "svg", "avif"]);

async function renderTab() {
  const it = S.items.find((x) => x.id === S.current);
  if (!it) return;
  const body = $("#pv-body");
  const my = ++previewToken;
  body.innerHTML = '<div class="pv-note"><span class="spinner"></span></div>';
  if (S.tab === "info") {
    const d = await api(`/api/item/${it.id}`).catch((e) => ({ error: e.message }));
    if (my !== previewToken) return;
    if (d.error) { body.innerHTML = `<div class="pv-note">${esc(d.error)}</div>`; return; }
    const method = { ntfs: "NTFS file table", fat: "FAT directory", carve: "Recognised by content", ext4: "ext4 inode" }[d.method] || d.method;
    body.innerHTML = `<dl class="pv-info">
      <dt>Status</dt><dd><span class="badge ${d.status}">${STATUS[d.status].label}</span></dd>
      <dt>Why</dt><dd>${d.notes.length ? `<ul>${d.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : "No problems found"}</dd>
      <dt>Size</dt><dd>${size(d.size)} (${d.size.toLocaleString()} bytes)</dd>
      <dt>Modified</dt><dd>${date(d.modified) || "unknown"}</dd>
      <dt>Found by</dt><dd>${esc(method)}</dd>
      <dt>Pieces</dt><dd>${d.fragments === 1 ? "1 (in one piece)" : `${d.fragments} (fragmented)`}</dd>
      ${d.folder_deleted ? "<dt>Folder</dt><dd>Its folder was deleted too</dd>" : ""}
      <dt>Location</dt><dd>${d.offset >= 0 ? `byte ${d.offset.toLocaleString()} on the drive` : "inside the file table record"}</dd>
      <dt>Evidence</dt><dd><ul>${d.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></dd>
    </dl>`;
    return;
  }
  if (S.tab === "hex") return renderHex(it, 0, my);
  const ext = it.ext;
  if (it.status === "overwritten") {
    body.innerHTML = `<div class="pv-note">This file's space has been reused or wiped, so a preview would only show other data. The Hex tab shows what is there now.</div>`;
    return;
  }
  if (SHOWABLE_IMAGE.has(ext) || (it.category === "image" && !it.named)) {
    body.innerHTML = `<div class="pv-media"><img alt=""></div>`;
    const img = $("img", body);
    img.onerror = () => { if (my === previewToken) body.innerHTML = `<div class="pv-note">This picture does not open: its data is damaged or in a format the preview cannot show. Recovering it may still work.</div>`; };
    img.src = dataUrl(it.id);
    return;
  }
  if (PLAYABLE_VIDEO.has(ext)) {
    body.innerHTML = `<div class="pv-media"><video controls preload="metadata"></video></div>`;
    const v = $("video", body);
    v.onerror = () => { if (my === previewToken) body.innerHTML = `<div class="pv-note">This video does not play here. It may be damaged, or use a codec the preview lacks (HEVC, for example). Recovering it may still work.</div>`; };
    v.src = dataUrl(it.id);
    return;
  }
  if (PLAYABLE_AUDIO.has(ext)) {
    body.innerHTML = `<div class="pv-media"><audio controls preload="metadata"></audio></div>`;
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
    if (my !== previewToken) return;
    if (!r.text) { body.innerHTML = `<div class="pv-note">${esc(r.note || "No readable text in this file.")}</div>`; return; }
    body.innerHTML = `<pre class="pv-text"></pre>${r.truncated ? '<div class="pv-note">Only the start is shown.</div>' : ""}`;
    $("pre", body).textContent = r.text;
    return;
  }
  body.innerHTML = `<div class="pv-note">No preview for .${esc(ext || "?")} files. The Hex tab shows the raw bytes.</div>`;
}

async function renderHex(it, offset, my) {
  const body = $("#pv-body");
  const r = await api(`/api/item/${it.id}/hex?offset=${offset}&length=4096`).catch((e) => ({ error: e.message }));
  if (my !== previewToken) return;
  if (r.error) { body.innerHTML = `<div class="pv-note">${esc(r.error)}</div>`; return; }
  const lines = r.rows.map(([off, hex, asc]) =>
    `<span class="off">${off.toString(16).padStart(8, "0")}</span>  ${hex.padEnd(47, " ")}  <span class="asc">${esc(asc)}</span>`).join("\n");
  const more = offset + 4096 < r.size;
  const html = `<pre class="pv-hex">${lines}</pre>${more ? `<div class="pv-more"><button class="btn ghost" id="hex-more">Show more</button></div>` : ""}`;
  if (offset === 0) body.innerHTML = html;
  else { $("#hex-more")?.parentElement.remove(); body.insertAdjacentHTML("beforeend", html); }
  $("#hex-more")?.addEventListener("click", () => renderHex(it, offset + 4096, my));
}

$("#pv-save").onclick = () => {
  const it = S.items.find((x) => x.id === S.current);
  if (it) openRecover([it]);
};

/* ---------- recover dialog ---------- */
const dlg = $("#recover-dialog");
let recoverItems = [];
let recoverPoll = null;

$("#recover-btn").onclick = () => openRecover(selectedItems());

function openRecover(items) {
  recoverItems = items;
  const bytes = items.reduce((a, it) => a + it.size, 0);
  const over = items.filter((it) => it.status === "overwritten").length;
  $("#rd-title").textContent = items.length === 1 ? `Recover ${items[0].name}` : `Recover ${items.length.toLocaleString()} files`;
  $("#rd-sub").textContent = `${size(bytes)} in total. Files are copied out; the drive itself is never changed.`;
  $("#rd-form").hidden = false;
  $("#rd-progress").hidden = true;
  $("#rd-start").hidden = false;
  $("#rd-open").hidden = true;
  $("#rd-cancel").textContent = "Cancel";
  $("#rd-msg").innerHTML = over ? `<div class="msg warn">${over} of these ${over === 1 ? "is" : "are"} marked overwritten and will most likely not open.</div>` : "";
  checkDest();
  dlg.showModal();
}

let destTimer = null;
async function checkDest() {
  const dest = $("#rd-dest").value.trim();
  const over = $("#rd-msg").querySelector(".warn")?.outerHTML || "";
  if (!dest) { $("#rd-start").disabled = true; return; }
  try {
    const r = await api("/api/check-dest", { dest });
    $("#rd-msg").innerHTML = over + (r.error ? `<div class="msg bad">${esc(r.error)}</div>` : "");
    $("#rd-start").disabled = !!r.error;
  } catch (e) {
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
  if (!$("#rd-progress").hidden && $("#rd-cancel").textContent === "Stop") {
    await api("/api/recover/stop", {}).catch(() => {});
    return;
  }
  clearTimeout(recoverPoll);
  dlg.close();
};
$("#rd-start").onclick = async () => {
  const dest = $("#rd-dest").value.trim();
  try {
    await api("/api/recover", { ids: recoverItems.map((it) => it.id), dest, keep_folders: $("#rd-keep").checked });
  } catch (e) {
    $("#rd-msg").innerHTML = `<div class="msg bad">${esc(e.message)}</div>`;
    return;
  }
  $("#rd-form").hidden = true;
  $("#rd-progress").hidden = false;
  $("#rd-start").hidden = true;
  $("#rd-cancel").textContent = "Stop";
  $("#rd-result").innerHTML = "";
  pollRecover();
};
async function pollRecover() {
  const r = await api("/api/recover").catch(() => null);
  if (!r) { recoverPoll = setTimeout(pollRecover, 800); return; }
  const pct = r.bytes ? (r.done_bytes / r.bytes) * 100 : 0;
  $("#rd-bar").style.width = `${r.state === "done" ? 100 : pct}%`;
  $("#rd-status").textContent = `${r.done_files.toLocaleString()} of ${r.files.toLocaleString()} files · ${size(r.done_bytes)} of ${size(r.bytes)}`;
  if (r.state === "running") { recoverPoll = setTimeout(pollRecover, 500); return; }
  const failed = r.failed || [];
  $("#rd-result").innerHTML = (r.state === "done"
    ? `<div class="msg ok">Done. ${(r.done_files - failed.length).toLocaleString()} file(s) saved to ${esc(r.dest)}</div>`
    : `<div class="msg warn">Stopped. ${(r.done_files - failed.length).toLocaleString()} file(s) were saved before stopping.</div>`) +
    (failed.length ? `<div class="msg bad">${failed.length} could not be written: ${esc(failed.slice(0, 3).map((f) => `${f.name} (${f.error})`).join("; "))}</div>` : "");
  $("#rd-cancel").textContent = "Close";
  $("#rd-open").hidden = false;
  $("#rd-open").onclick = () => api("/api/open-folder", { path: r.dest }).catch(() => {});
}

/* ---------- erase ---------- */
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
  $("#ed-phrase").textContent = plan.phrase;
  $("#ed-typed").value = "";
  $("#ed-understood").checked = false;
  $("#ed-msg").innerHTML = "";
  $("#ed-admin").innerHTML = plan.admin ? "" :
    `<div class="msg warn">Erasing needs administrator rights. <button class="btn" id="ed-elevate" style="margin-left:8px">Restart as administrator</button></div>`;
  $("#ed-elevate")?.addEventListener("click", () => $("#elevate").click());
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

const ERASE_STAGE = { preparing: "Preparing", unmounting: "Unmounting the drive", "random data": "Writing random data", zeros: "Writing zeros", verifying: "Checking it worked", formatting: "Formatting", done: "Done", stopped: "Stopped", failed: "Failed" };
async function pollErase() {
  const r = await api("/api/erase").catch(() => null);
  if (!r) { erasePoll = setTimeout(pollErase, 1000); return; }
  const pct = r.total ? (r.done / r.total) * 100 : 0;
  $("#ed-bar").style.width = `${r.state === "done" ? 100 : pct}%`;
  const parts = [ERASE_STAGE[r.stage] || r.stage];
  if (r.passes > 1 && r.state === "running") parts.push(`pass ${r.pass} of ${r.passes}`);
  if (r.total) parts.push(`${size(r.done)} of ${size(r.total)} (${pct.toFixed(0)}%)`);
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
    if (confirm("Stop erasing? The drive will be left partly erased and unusable until it is erased again or formatted.")) {
      await api("/api/erase/stop", {}).catch(() => {});
    }
    return;
  }
  ed.close();
};
ed.addEventListener("cancel", (e) => { if ($("#ed-cancel").textContent === "Stop") e.preventDefault(); });

init();
