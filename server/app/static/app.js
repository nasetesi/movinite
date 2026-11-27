/* Movinite UI (the media-server app) -- vanilla JS single page app */
(function () {
"use strict";
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const enc = encodeURIComponent;
let ME = null, LIBS = [];

// ---------------------------------------------------------------- helpers
async function api(path, opts) {
  opts = opts || {};
  const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
  if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  const r = await fetch(path, init);
  if (r.status === 401 && !opts.noAuthRedirect) { showLogin(); throw new Error("Not signed in"); }
  let data = null;
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("json")) data = await r.json(); else data = await r.text();
  if (!r.ok) { const msg = (data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : ("HTTP " + r.status);
    const err = new Error(msg); err.status = r.status; if (data && data.code) err.code = data.code; throw err; }
  return data;
}
function toast(msg, bad) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : "");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), bad ? 6000 : 3000);
}
function fmtDur(s) {
  s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`;
}
function fmtLen(s) { if (!s) return ""; if (s < 60) return Math.round(s) + " sec"; const m = Math.round(s / 60); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m} min`; }
function fmtSize(b) { if (!b) return ""; const u = ["B","KB","MB","GB","TB"]; let i = 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return b.toFixed(i > 1 ? 1 : 0) + " " + u[i]; }
function thumbUrl(n) { return n ? "/api/thumb/" + n : ""; }
function ago(ts) { if (!ts) return "never"; const d = Date.now() / 1000 - ts; if (d < 90) return "just now"; if (d < 3600) return Math.round(d / 60) + " min ago"; if (d < 86400) return Math.round(d / 3600) + " h ago"; return new Date(ts * 1000).toLocaleDateString(); }
function epCode(i) { return (i.season != null ? "S" + String(i.season).padStart(2, "0") : "") + (i.episode != null ? "E" + String(i.episode).padStart(2, "0") : ""); }
const nf = (n) => (+n || 0).toLocaleString();
function fmtEta(s) { if (s == null) return ""; if (s < 60) return "< 1 min"; const m = Math.round(s / 60); return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`; }
function scanText(st, withName) {
  const n = withName ? `${esc(st.name)} ` : "";
  if (st.state === "queued") return `${n}scan queued`;
  if (st.state !== "scanning") return "";
  if (st.cancel) return `${n}cancelling...`;
  if (!st.walk_done) return `Scanning ${n}&mdash; discovering files&hellip; ${nf(st.found)} found${st.done ? ` &middot; ${nf(st.done)} processed` : ""}`;
  if (!st.total) return `Scanning ${n}&mdash; ${nf(st.found)} files, all up to date`;
  return `Scanning ${n}&mdash; ${nf(st.done)} / ${nf(st.total)}${st.eta_s ? ` &middot; ETA ${fmtEta(st.eta_s)}` : ""}`;
}
function scanPct(st) { return st && st.walk_done && st.total ? Math.min(100, 100 * st.done / st.total) : null; }
function metaText(m, withName) {
  if (m.state === "queued") return `Posters queued${withName ? " &middot; " + esc(m.name) : ""}`;
  return `${m.phase === "categories" ? "Fetching cast &amp; details" : "Fetching posters"}${withName ? " &middot; " + esc(m.name) : ""} ${m.total ? nf(m.done) + " / " + nf(m.total) : "&hellip;"}${m.eta_s && m.done > 5 ? " &middot; " + fmtEta(m.eta_s) + " left" : ""}`;
}
function artText(a, withName) {
  if (a.state === "queued") return `Saving artwork queued${withName ? " &middot; " + esc(a.name) : ""}`;
  return `Saving artwork${withName ? " &middot; " + esc(a.name) : ""} ${a.total ? nf(a.done) + " / " + nf(a.total) : "&hellip;"}${a.written ? " &middot; " + nf(a.written) + " files" : ""}`;
}
// ---- live activity: one small request every 1.5 s while something runs, every 8 s otherwise
const ACT = { d: null, prev: {}, timer: null, lastLive: 0, wasActive: false };
async function pollActivity() {
  clearTimeout(ACT.timer);
  if (!ME) return;
  let d = null;
  try { d = await api("/api/activity", { noAuthRedirect: true }); } catch (e) { /* offline / signed out */ }
  if (d) handleActivity(d);
  ACT.timer = setTimeout(pollActivity, document.hidden ? 10000 : (d && d.active ? 1500 : 8000));
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && ME) pollActivity(); });
function handleActivity(d) {
  ACT.d = d;
  for (const st of d.scans) {
    const was = ACT.prev[st.library_id];
    if ((was === "scanning" || was === "queued") && ["done", "error", "cancelled"].includes(st.state)) {
      if (st.state === "error") toast(`Scan of ${st.name} failed: ${st.error || st.last_error || "error"}`, true);
      else toast(`${st.name}: scan ${st.state === "cancelled" ? "cancelled" : "finished"} -- ${nf(st.added)} added, ${nf(st.updated)} updated, ${nf(st.removed)} removed${st.errors ? `, ${nf(st.errors)} errors` : ""}`, st.errors > 0);
    }
    ACT.prev[st.library_id] = st.state;
  }
  for (const a of (d.artwork || [])) {
    const k = "art" + a.library_id, was = ACT.prev[k];
    if ((was === "running" || was === "queued") && ["done", "error", "cancelled"].includes(a.state)) {
      if (a.state === "error") toast(`Saving artwork for ${a.name} stopped: ${a.error || "error"}`, true);
      else toast(`${a.name}: artwork ${a.state === "cancelled" ? "cancelled" : "saved"} -- ${nf(a.written)} files written, ${nf(a.skipped)} skipped${a.errors ? `, ${nf(a.errors)} errors` : ""}`, a.errors > 0);
    }
    ACT.prev[k] = a.state;
  }
  renderActivityPill(d);
  // library page progress line
  const line = $("#lib-scan-line");
  if (line) { const st = d.scans.find(x => x.library_id === +line.dataset.lib); renderLibScanLine(line, st, d.metadata.find(x => x.library_id === +line.dataset.lib)); }
  // live page refresh (grid, home strips, scans panel) while anything runs, plus once after it stops
  const live = route._live;
  if (live && (d.active || ACT.wasActive) && Date.now() - ACT.lastLive >= (d.active ? live.every : 0)) {
    ACT.lastLive = Date.now();
    Promise.resolve(live.fn(d)).catch(() => {});
  }
  ACT.wasActive = d.active;
}
function renderActivityPill(d) {
  const el = $("#activity");
  const scans = d.scans.filter(s => s.state === "scanning" || s.state === "queued").sort((a, b) => (a.state === "scanning" ? -1 : 1));
  const metas = d.metadata.filter(m => m.state === "running" || m.state === "queued");
  const arts = (d.artwork || []).filter(a => a.state === "running" || a.state === "queued");
  if (!scans.length && !metas.length && !arts.length) { el.classList.add("hidden"); el.innerHTML = ""; return; }
  let main, pct = null, sub = "";
  if (scans.length) {
    const st = scans[0]; main = scanText(st, true); pct = scanPct(st);
    if (st.current && st.current.length) sub = st.current[0];
  } else if (metas.length) { const m = metas[0]; main = metaText(m, true); pct = m.total ? 100 * m.done / m.total : null; }
  else { const a = arts[0]; main = artText(a, true); pct = a.total ? 100 * a.done / a.total : null; }
  const more = scans.length + metas.length + arts.length - 1;
  el.innerHTML = `<span class="spin"></span><span class="act-main">${main}</span>${sub ? `<span class="act-sub" title="${esc(sub)}">${esc(sub)}</span>` : ""}${more > 0 ? `<span class="act-more">+${more}</span>` : ""}
    <span class="act-bar ${pct == null ? "indet" : ""}" style="${pct == null ? "" : `width:${pct}%`}"></span>`;
  el.title = "Scan activity -- click for details";
  el.classList.remove("hidden");
}
function renderLibScanLine(el, st, m) {
  let html = "";
  if (st && (st.state === "scanning" || st.state === "queued")) {
    const pct = scanPct(st);
    html = `<div class="scanline"><span class="spin"></span><div style="flex:1;min-width:0"><div>${scanText(st, false)}${st.rate_per_min ? ` &middot; ${nf(st.rate_per_min)} files/min` : ""}</div>
      ${st.current && st.current.length ? `<div class="help" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Now: ${esc(st.current.join(" · "))}</div>` : ""}
      <div class="prog wide"><div class="${pct == null ? "indet" : ""}" style="${pct == null ? "" : `width:${pct}%`}"></div></div></div>
      <span class="help">New items appear below as they are found</span></div>`;
  } else if (m && (m.state === "running" || m.state === "queued")) {
    html = `<div class="scanline"><span class="spin"></span><div style="flex:1">${metaText(m, false)}<div class="prog wide"><div style="width:${m.total ? 100 * m.done / m.total : 5}%"></div></div></div></div>`;
  }
  if (el.innerHTML !== html) el.innerHTML = html;
}
const INTERVALS = [[0, "Off (manual only)"], [1, "Hourly"], [6, "Every 6 hours"], [24, "Daily"]];
function intervalOpts(sel) { return INTERVALS.map(([v, n]) => `<option value="${v}"${v === sel ? " selected" : ""}>${n}</option>`).join(""); }
function intervalName(h) { const x = INTERVALS.find(([v]) => v === h); return x ? x[1] : h + " h"; }
function inTime(ts) { if (!ts) return ""; const d = ts - Date.now() / 1000; if (d <= 60) return "due now"; if (d < 3600) return "in " + Math.round(d / 60) + " min"; if (d < 86400) return "in " + Math.round(d / 3600) + " h"; return new Date(ts * 1000).toLocaleString(); }
const TMDB_NOTE = `<div class="tmdb-attr"><a href="https://www.themoviedb.org/" target="_blank" rel="noopener"><img src="/static/tmdb-logo.svg" alt="TMDB"></a>
  <span>This product uses the TMDB API but is not endorsed or certified by TMDB.</span></div>`;
function metaChips(x, libId) {
  const out = [];
  if (libId) (x.genres || []).forEach(g => out.push(`<a class="chip link" href="#/library/${libId}" data-genre="${esc(g)}" data-lib="${libId}" title="All ${esc(g)} movies">${esc(g)}</a>`));
  else (x.genres || []).slice(0, 4).forEach(g => out.push(`<span class="chip">${esc(g)}</span>`));
  if (x.certification) out.push(`<span class="chip cert" title="Age rating">${esc(x.certification)}</span>`);
  if (x.rating) out.push(`<span class="chip rating" title="TMDB user score">&#9733; ${(+x.rating).toFixed(1)}</span>`);
  return out.length ? `<div class="chips">${out.join("")}</div>` : "";
}
function heroStyle(b) { return b ? ` style="--hero:url('${thumbUrl(b)}')"` : ""; }
// "Fix match": search TMDB, pick a result, or go back to file names
function fixMatchDialog(kind, query, year, apply) {
  modal(`<h2>Fix match</h2><div class="form"><label>${kind === "movie" ? "Movie" : "TV show"} title</label>
    <div style="display:flex;gap:8px"><input type="text" id="fm-q" value="${esc(query || "")}"><input type="number" id="fm-y" placeholder="Year" value="${year || ""}" style="width:100px"><button class="btn" id="fm-go">Search</button></div></div>
    <div id="fm-res" class="fm-res"></div><div class="err" id="fm-err"></div>
    <div class="modal-actions" style="justify-content:space-between"><div style="display:flex;gap:8px"><button class="btn ghost" id="fm-auto" title="Clear the match and let the automatic matcher try again">Automatic</button><button class="btn ghost" id="fm-un" title="Do not use TMDB for this title">Use file name</button></div><button class="btn ghost" id="fm-cancel">Cancel</button></div>
    ${TMDB_NOTE}`, () => {
    const go = async () => {
      $("#fm-err").textContent = ""; $("#fm-res").innerHTML = `<div class="muted">Searching...</div>`;
      try {
        const r = await api(`/api/tmdb/search?kind=${kind}&q=${enc($("#fm-q").value)}&year=${+$("#fm-y").value || 0}`);
        $("#fm-res").innerHTML = r.length ? r.map(x => `<div class="fm-row" data-tid="${x.id}"><div class="fm-img" style="${x.poster_url ? `background-image:url('${esc(x.poster_url)}')` : ""}"></div>
          <div><b>${esc(x.title)}</b> ${x.year ? `<span class="muted">(${x.year})</span>` : ""}${x.original_title && x.original_title !== x.title ? `<div class="help">${esc(x.original_title)}</div>` : ""}<div class="help">${esc(x.overview || "")}</div></div></div>`).join("")
          : `<div class="muted">No results. Try a shorter title or remove the year.</div>`;
        $$("#fm-res [data-tid]").forEach(el => el.onclick = async () => {
          el.classList.add("busy");
          try { await apply({ tmdb_id: +el.dataset.tid }); closeModal(); toast("Match updated"); route._keepScroll = true; route(); }
          catch (e) { el.classList.remove("busy"); $("#fm-err").textContent = e.message; }
        });
      } catch (e) { $("#fm-res").innerHTML = ""; $("#fm-err").textContent = e.message; }
    };
    $("#fm-go").onclick = go;
    $("#fm-q").onkeydown = (e) => { if (e.key === "Enter") go(); };
    $("#fm-cancel").onclick = closeModal;
    $("#fm-un").onclick = async () => { try { await apply({ unmatch: true }); closeModal(); toast("Using the file name"); route._keepScroll = true; route(); } catch (e) { $("#fm-err").textContent = e.message; } };
    $("#fm-auto").onclick = async () => { try { const r = await apply({ auto: true }); closeModal(); toast(r && r.queued ? "Matching in the background" : (r && r.matched === false ? "No automatic match found" : "Matched automatically")); setTimeout(() => { route._keepScroll = true; route(); }, r && r.queued ? 2500 : 0); } catch (e) { $("#fm-err").textContent = e.message; } };
    if (query) go();
  });
}
// lazy artwork: big libraries render thousands of cards; load posters only near the viewport
function artBg(el) {
  // In TV mode, prefer the w780 poster-large when present so 4K / high-DPR panels stay sharp.
  const hi = el.dataset.bgHi;
  const lo = el.dataset.bg;
  if (hi && document.documentElement.classList.contains("tv-mode")) {
    return `url('${hi}'),url('${lo}')`;
  }
  return `url('${lo}')`;
}
const lazyIO = ("IntersectionObserver" in window) ? new IntersectionObserver((ents) => ents.forEach(e => {
  if (e.isIntersecting) { e.target.style.backgroundImage = artBg(e.target); lazyIO.unobserve(e.target); }
}), { rootMargin: "800px 200px" }) : null;
new MutationObserver(() => $$("[data-bg]:not([data-lz])").forEach(el => {
  el.dataset.lz = "1";
  if (lazyIO) lazyIO.observe(el); else el.style.backgroundImage = artBg(el);
})).observe(document.body, { childList: true, subtree: true });
const ico = (body) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const KIND_ICON = {   // 1.7.4: outlined theme icons (24px grid, currentColor)
  movies: `<span class="k-ic">${ico(`<path d="M5.25 10.25h12.5A2 2 0 0 1 19.75 12.25v6.75A2 2 0 0 1 17.75 21H5.25A2 2 0 0 1 3.25 19V12.25A2 2 0 0 1 5.25 10.25Z"/><path d="M3.25 10.25 5.5 3.4h16.5L19.75 10.25"/><path d="M9.7 3.4 7.45 10.25"/><path d="M13.7 3.4 11.45 10.25"/><path d="M17.7 3.4 15.45 10.25"/>`)}</span>`,
  tv: `<span class="k-ic">${ico(`<path d="M5 3.75h14A2.25 2.25 0 0 1 21.25 6v8.25A2.25 2.25 0 0 1 19 16.5H5A2.25 2.25 0 0 1 2.75 14.25V6A2.25 2.25 0 0 1 5 3.75Z"/><path d="M6.15 5.85h11.7A1.1 1.1 0 0 1 18.95 6.95v6.35A1.1 1.1 0 0 1 17.85 14.4H6.15A1.1 1.1 0 0 1 5.05 13.3V6.95A1.1 1.1 0 0 1 6.15 5.85Z"/><path d="M12 16.5v3.15"/><path d="M7.75 20.75h8.5"/>`)}</span>`,
  music: `<span class="k-ic">${ico(`<ellipse cx="8.35" cy="17.35" rx="3.85" ry="2.65" transform="rotate(-20 8.35 17.35)"/><path d="M12.05 16.15V4.55"/><path d="M12.05 4.55c4.35.15 7.15 2.55 6.85 6.55-1.7-2.55-4.35-3.35-6.85-3.15"/>`)}</span>`,
  other: `<span class="k-ic">${ico(`<path d="M3.55 8.45h11.15A2 2 0 0 1 16.7 10.45v6.1A2 2 0 0 1 14.7 18.55H3.55A2 2 0 0 1 1.55 16.55v-6.1A2 2 0 0 1 3.55 8.45Z"/><circle cx="19.3" cy="13.5" r="3.35"/><circle cx="19.3" cy="13.5" r="1.5"/><path d="M5.15 5.6h5.7A1.1 1.1 0 0 1 11.95 6.7v1.75H5.15A1.1 1.1 0 0 1 4.05 7.35V6.7A1.1 1.1 0 0 1 5.15 5.6Z"/>`)}</span>`
};

function modal(html, onMount) {
  $("#modal-box").className = "modal-box";
  $("#modal-box").innerHTML = html; $("#modal").classList.remove("hidden");
  if (onMount) onMount($("#modal-box"));
}
function closeModal() { $("#modal").classList.add("hidden"); $("#modal-box").innerHTML = ""; $("#modal-box").className = "modal-box"; }
$("#modal").addEventListener("mousedown", e => { if (e.target.id === "modal" && !$("#modal").dataset.locked) closeModal(); });

// ---------------------------------------------------------------- auth screens
function showAuth(html) {
  $("#shell").classList.add("hidden"); $("#auth").classList.remove("hidden"); $("#auth").innerHTML = html;
  document.documentElement.classList.add("tv-auth");
  if (window.TVPlex && typeof TVPlex.syncAuth === "function") TVPlex.syncAuth();
}
function hideAuth() {
  stopPairPoll();
  $("#auth").classList.add("hidden");
  document.documentElement.classList.remove("tv-auth");
  if (window.TVPlex && typeof TVPlex.syncAuth === "function") TVPlex.syncAuth();
}
function focusAuth() {
  if (!(window.TV && TV.on)) return;
  TV.init();
  const items = $$("#auth button, #auth input, #auth a, #auth [tabindex='0']").filter(el => TV.visible(el));
  const err = $("#lerr");
  const prefer = (err && err.textContent && $("#pair-use-pass"))
    || $("#pair-refresh") || $("#pair-approve") || $("#pair-use-pass") || $("#loginf button") || items[0];
  if (prefer) TV.focus(prefer);
}

// 2.0.2: short-code TV sign-in, recent-server list, stay-signed-in note
const PAIR = { timer: null, token: null, gen: 0, display: null, url: null, expires_at: 0, delay: 3000 };
function stopPairPoll() { PAIR.gen++; clearTimeout(PAIR.timer); PAIR.timer = null; PAIR.delay = 3000; }
function isTvAuth() { return !!(window.TV && TV.on); }
function pairCodeFromLocation() {
  try {
    if ((location.pathname || "").replace(/\/+$/, "") === "/pair") {
      const q = new URLSearchParams(location.search).get("code");
      if (q) return String(q).toUpperCase().replace(/[^A-Z0-9]/g, "");
    }
  } catch (e) {}
  const h = (location.hash || "").match(/^#\/pair\/?([A-Za-z0-9-]{4,16})/i);
  return h ? h[1].toUpperCase().replace(/[^A-Z0-9]/g, "") : "";
}
function recentServers() {
  try { return JSON.parse(localStorage.getItem("msRecentServers") || "[]") || []; } catch (e) { return []; }
}
function rememberServer(url, name) {
  url = String(url || "").replace(/\/+$/, "");
  if (!url || !/^https?:\/\//i.test(url)) return;
  const list = recentServers().filter(s => s.url !== url);
  list.unshift({ url, name: name || "", last: Date.now() });
  try { localStorage.setItem("msRecentServers", JSON.stringify(list.slice(0, 8))); } catch (e) {}
}
async function probeServer(url) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 1600);
  try {
    const r = await fetch(String(url).replace(/\/+$/, "") + "/.well-known/movinite.json", { signal: ctrl.signal, cache: "no-store" });
    clearTimeout(t);
    if (!r.ok) return null;
    const j = await r.json();
    if (!j || (j.service !== "movinite" && !j.version)) return null;
    return j;
  } catch (e) { clearTimeout(t); return null; }
}
async function fillRecentServers(el) {
  if (!el) return;
  const here = location.origin;
  rememberServer(here);
  const others = recentServers().filter(s => s.url && s.url !== here);
  if (!others.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<div class="muted pair-recent-h">Servers you've used</div>` +
    others.map(s => `<button type="button" class="btn ghost pair-srv" data-url="${esc(s.url)}" tabindex="0">${esc(s.name || s.url)}</button>`).join("");
  el.querySelectorAll(".pair-srv").forEach(b => { b.onclick = () => { location.href = b.dataset.url + "/"; }; });
  for (const s of others) {
    const j = await probeServer(s.url);
    if (!j) continue;
    const label = (j.name || "Movinite") + (j.version ? " · v" + j.version : "");
    rememberServer(s.url, label);
    const b = el.querySelector(`.pair-srv[data-url="${CSS.escape(s.url)}"]`);
    if (b) b.textContent = label;
  }
}
function afterLoginOrPair() {
  const code = pairCodeFromLocation();
  if (code) { showPairApprove(code); return; }
  boot();
}
function showLogin() {
  stopAll();
  stopPairPoll();
  if (isTvAuth()) { showTvPairLogin(); return; }
  showPasswordLogin();
}
function showPasswordLogin(opts) {
  opts = opts || {};
  stopPairPoll();
  showAuth(`<form class="auth-box" id="loginf"><h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1>
    <div class="muted">${opts.note || "Sign in to continue"}</div>
    <label>Username</label><input type="text" id="lu" autocomplete="username" autofocus>
    <label>Password</label><input type="password" id="lp" autocomplete="current-password">
    <button class="btn" type="submit">Sign in</button>
    ${opts.tvBack ? `<button type="button" class="btn ghost" id="pair-back-code" tabindex="0">Back to the TV code</button>` : `<button type="button" class="btn ghost" id="pair-enter" tabindex="0">Approve a TV sign-in</button>`}
    <div id="pair-recent" class="pair-recent"></div>
    <div class="err" id="lerr"></div></form>`);
  $("#loginf").onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/login", { method: "POST", body: { username: $("#lu").value, password: $("#lp").value }, noAuthRedirect: true }); afterLoginOrPair(); }
    catch (err) { $("#lerr").textContent = err.message; }
  };
  const back = $("#pair-back-code");
  if (back) back.onclick = () => showTvPairLogin();
  const enter = $("#pair-enter");
  if (enter) enter.onclick = () => showPairCodeEntry();
  fillRecentServers($("#pair-recent"));
  focusAuth();
}
function showTvPairLogin() {
  showAuth(`<div class="auth-box auth-tv-pair" id="pairf">
    <h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1>
    <h2 class="auth-h">Sign in with your phone</h2>
    <p class="muted pair-lead">On a phone that's already signed in, open Movinite and scan this code — or visit the address below and enter the letters.</p>
    <div class="pair-row">
      <div class="pair-qr" id="pair-qr" aria-hidden="true"></div>
      <div class="pair-side">
        <div class="pair-code" id="pair-code">------</div>
        <div class="muted" id="pair-status">Getting a code…</div>
        <div class="muted pair-stay">This TV stays signed in. You can sign out later from the menu.</div>
      </div>
    </div>
    <div class="pair-url muted" id="pair-url"></div>
    <div class="pair-actions">
      <button type="button" class="btn" id="pair-refresh" tabindex="0">Get a new code</button>
      <button type="button" class="btn ghost" id="pair-use-pass" tabindex="0">Sign in with a username and password</button>
    </div>
    <div id="pair-recent" class="pair-recent"></div>
    <div class="err" id="lerr"></div>
  </div>`);
  $("#pair-refresh").onclick = () => startTvPair(true);
  $("#pair-use-pass").onclick = () => showPasswordLogin({ tvBack: true, note: "Sign in with a username and password. This TV will stay signed in." });
  fillRecentServers($("#pair-recent"));
  startTvPair(false);
  focusAuth();
}
async function startTvPair(force) {
  stopPairPoll();
  const gen = ++PAIR.gen;
  const status = $("#pair-status"), codeEl = $("#pair-code"), qr = $("#pair-qr"), err = $("#lerr"), urlEl = $("#pair-url");
  if (!status) return;
  if (force) status.textContent = "Getting a new code…";
  if (err) err.textContent = "";
  const paint = (r) => {
    PAIR.token = r.poll_token;
    PAIR.display = r.display || r.code;
    PAIR.url = r.url || "";
    PAIR.expires_at = r.expires_at || 0;
    if (codeEl) codeEl.textContent = PAIR.display || "------";
    if (qr) qr.innerHTML = (window.MSQR && PAIR.url) ? MSQR.svg(PAIR.url, 220) : "";
    if (urlEl) urlEl.textContent = PAIR.url ? PAIR.url.replace(/^https?:\/\//, "") : "";
    status.textContent = "Waiting for approval on your phone…";
    tickPairPoll(gen);
  };
  const now = Date.now() / 1000;
  if (!force && PAIR.token && PAIR.expires_at > now + 15) {
    paint({ poll_token: PAIR.token, display: PAIR.display, url: PAIR.url, expires_at: PAIR.expires_at });
    return;
  }
  try {
    const r = await api("/api/pair/start", { method: "POST", body: force ? { force: true } : {}, noAuthRedirect: true });
    if (gen !== PAIR.gen) return;
    paint(r);
  } catch (e) {
    if (gen !== PAIR.gen) return;
    status.textContent = "";
    if (err) err.textContent = e.message || "Couldn't start a sign-in code";
    focusAuth();
  }
}
function tickPairPoll(gen) {
  clearTimeout(PAIR.timer);
  const wait = Math.max(3000, PAIR.delay || 3000);
  PAIR.timer = setTimeout(async () => {
    if (gen !== PAIR.gen || !PAIR.token) return;
    try {
      const r = await api("/api/pair/poll", { method: "POST", body: { token: PAIR.token }, noAuthRedirect: true });
      if (gen !== PAIR.gen) return;
      PAIR.delay = 3000;
      if (r.status === "approved") { stopPairPoll(); afterLoginOrPair(); return; }
      if (r.status === "pending") {
        const st = $("#pair-status");
        if (st && r.expires_in != null && r.expires_in < 60) st.textContent = "This code expires in less than a minute. Approve it on your phone, or get a new one.";
        tickPairPoll(gen);
        return;
      }
      if (r.status === "expired" || r.status === "denied" || r.status === "unknown") {
        const st = $("#pair-status");
        if (st) st.textContent = r.status === "denied" ? "Sign-in was declined. Get a new code to try again." : "This code expired. Get a new one.";
        return;
      }
      tickPairPoll(gen);
    } catch (e) {
      if (gen !== PAIR.gen) return;
      // 2.1.3: on 429, slow down instead of showing "Too many checks" over the form.
      // The password button stays usable; this loop must not write to #lerr.
      if (e.status === 429) PAIR.delay = Math.min(30000, Math.max(6000, (PAIR.delay || 3000) * 2));
      else PAIR.delay = Math.min(15000, (PAIR.delay || 3000) + 2000);
      tickPairPoll(gen);
    }
  }, wait);
}
function showPairCodeEntry() {
  stopPairPoll();
  showAuth(`<div class="auth-box" id="pair-entry">
    <h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1>
    <h2 class="auth-h">Approve a TV</h2>
    <p class="muted">Enter the code shown on the television.</p>
    <label>Code</label><input type="text" id="pair-in" maxlength="8" autocomplete="off" autocapitalize="characters" autofocus>
    <button type="button" class="btn" id="pair-go" tabindex="0">Continue</button>
    <button type="button" class="btn ghost" id="pair-cancel" tabindex="0">Back</button>
    <div class="err" id="lerr"></div>
  </div>`);
  const go = () => {
    const c = ($("#pair-in").value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (c.length !== 6) { $("#lerr").textContent = "Enter the 6-character code from the TV"; return; }
    history.replaceState(null, "", "/pair?code=" + c);
    showPairApprove(c);
  };
  $("#pair-go").onclick = go;
  $("#pair-in").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  $("#pair-cancel").onclick = () => showLogin();
  focusAuth();
}
async function showPairApprove(code) {
  stopAll();
  stopPairPoll();
  try { ME = await api("/api/me", { noAuthRedirect: true }); }
  catch (e) {
    showPasswordLogin({ note: "Sign in to approve this TV, then you'll return to the confirmation." });
    return;
  }
  let info;
  try { info = await api("/api/pair/info?code=" + enc(code), { noAuthRedirect: true }); }
  catch (e) {
    showAuth(`<div class="auth-box" id="pair-bad">
      <h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1>
      <h2 class="auth-h">Can't approve this TV</h2>
      <p class="err">${esc(e.message || "That code is not valid or has expired")}</p>
      <button type="button" class="btn" id="pair-home" tabindex="0">Back</button>
    </div>`);
    $("#pair-home").onclick = () => { history.replaceState(null, "", "/"); boot(); };
    focusAuth();
    return;
  }
  const device = info.device || "A television";
  showAuth(`<div class="auth-box auth-pair-ok" id="pair-ok">
    <h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1>
    <h2 class="auth-h">Approve this TV?</h2>
    <p class="pair-device">You're about to sign <b>${esc(ME.username)}</b> in on:</p>
    <p class="pair-device-name" id="pair-device">${esc(device)}</p>
    <p class="muted">The TV will stay signed in until you sign out on it.</p>
    <div class="pair-actions">
      <button type="button" class="btn" id="pair-approve" tabindex="0">Approve</button>
      <button type="button" class="btn ghost" id="pair-deny" tabindex="0">Don't approve</button>
    </div>
    <div class="err" id="lerr"></div>
  </div>`);
  $("#pair-approve").onclick = async () => {
    $("#pair-approve").disabled = true;
    try {
      await api("/api/pair/approve", { method: "POST", body: { code }, noAuthRedirect: true });
      showAuth(`<div class="auth-box" id="pair-done">
        <h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1>
        <h2 class="auth-h">You're signed in on the TV</h2>
        <p class="muted">${esc(device)} should open the library in a moment.</p>
        <button type="button" class="btn" id="pair-home" tabindex="0">Continue on this device</button>
      </div>`);
      $("#pair-home").onclick = () => { history.replaceState(null, "", "/"); boot(); };
      focusAuth();
    } catch (e) {
      $("#pair-approve").disabled = false;
      $("#lerr").textContent = e.message;
    }
  };
  $("#pair-deny").onclick = async () => {
    try { await api("/api/pair/deny", { method: "POST", body: { code }, noAuthRedirect: true }); } catch (e) {}
    history.replaceState(null, "", "/");
    boot();
  };
  focusAuth();
}
function showSetup() {
  showAuth(`<form class="auth-box" id="setupf"><h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1><h2 class="auth-h">Welcome</h2><div class="muted">Create the administrator account.</div>
    <label>Username</label><input type="text" id="su" value="admin">
    <label>Password (8+ characters)</label><input type="password" id="sp" autocomplete="new-password">
    <label>Repeat password</label><input type="password" id="sp2" autocomplete="new-password">
    <button class="btn" type="submit">Create account</button><div class="err" id="serr"></div></form>`);
  $("#setupf").onsubmit = async (e) => {
    e.preventDefault();
    if ($("#sp").value !== $("#sp2").value) { $("#serr").textContent = "Passwords do not match"; return; }
    try { await api("/api/setup", { method: "POST", body: { username: $("#su").value, password: $("#sp").value }, noAuthRedirect: true }); boot(); }
    catch (err) { $("#serr").textContent = err.message; }
  };
}
function forcePasswordChange() {
  $("#modal").dataset.locked = "1";
  modal(`<h2>Choose a new password</h2><p class="muted">You signed in with a temporary password. Pick your own to continue.</p>
    <div class="form"><label>Current password</label><input type="password" id="pc">
    <label>New password</label><input type="password" id="pn" autocomplete="new-password">
    <label>Repeat</label><input type="password" id="pn2" autocomplete="new-password"></div>
    <div class="err" id="perr"></div><div class="modal-actions"><button class="btn" id="psave">Save password</button></div>`);
  $("#psave").onclick = async () => {
    if ($("#pn").value !== $("#pn2").value) { $("#perr").textContent = "Passwords do not match"; return; }
    try { await api("/api/me/password", { method: "POST", body: { current_password: $("#pc").value, new_password: $("#pn").value } });
      delete $("#modal").dataset.locked; closeModal(); toast("Password changed"); }
    catch (err) { $("#perr").textContent = err.message; }
  };
}

// ---- 1.4.2: server status in the top bar (admins, or everyone when Settings > System allows it)
// one small request every 4 s; stops while the tab is hidden; the server caches the numbers so many tabs are cheap
const SYS = { timer: null, d: null, open: false, pinned: false };
const GB = (b) => (b / 1073741824);
const TB = (b) => (b / 1099511627776);
function fmtGB(b, dp) { const g = GB(b || 0); return g >= 100 ? g.toFixed(0) : g.toFixed(dp == null ? 1 : dp); }
function fmtDisk(b, dp) {
  const n = b || 0;
  if (n >= 0.95 * 1099511627776) {
    const t = TB(n);
    const nDp = dp == null ? (t >= 10 ? 1 : 2) : dp;
    return t.toFixed(nDp) + " TB";
  }
  return fmtGB(n, dp) + " GB";
}
function fmtUptime(s) { const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; }
function cpuPct(d) { return d.cpu == null ? "n/a" : Math.round(d.cpu) + "%"; }
function sysLevel(p, warn, bad) { return p >= bad ? "bad" : p >= warn ? "warn" : "ok"; }
function sysSpark(vals, w, h) {
  if (!vals.length) return "";
  const n = vals.length, step = n > 1 ? w / (n - 1) : w;
  const pts = vals.map((v, i) => `${(i * step).toFixed(1)},${(h - 1 - (Math.max(0, Math.min(100, v)) / 100) * (h - 2)).toFixed(1)}`).join(" ");
  const lastX = ((n - 1) * step).toFixed(1);
  return `<svg class="ss-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polygon points="0,${h} ${pts} ${lastX},${h}" fill="currentColor" fill-opacity="0.18" stroke="none"/><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}
function sysBar(p, lvl) { return `<span class="ss-bar ${lvl}"><i style="width:${Math.max(0, Math.min(100, p)).toFixed(0)}%"></i></span>`; }
function sysRing(pct, lvl, size, icon) {
  const s = size || 48, r = 16, c = 2 * Math.PI * r, p = Math.max(0, Math.min(100, pct || 0));
  const dash = (p / 100) * c;
  const svg = `<svg class="ss-ring" width="${s}" height="${s}" viewBox="0 0 44 44" aria-hidden="true"><circle cx="22" cy="22" r="${r}" fill="none" stroke="currentColor" stroke-opacity=".18" stroke-width="4"/><circle cx="22" cy="22" r="${r}" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-dasharray="${dash.toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 22 22)"/></svg>`;
  if (!icon) return `<span class="ss-ring-wrap ${lvl}">${svg}</span>`;
  return `<span class="ss-ring-wrap ${lvl}">${svg}<span class="ss-ring-ico">${icon}</span></span>`;
}
function shortGpuName(name) {
  // "Intel Corporation DG2 [Arc A310]" -> "Arc A310". Full PCI name stays in the tooltip.
  const s = String(name || "").replace(/\s+/g, " ").trim();
  if (!s) return "";
  const br = s.match(/\[([^\]]+)\]/);
  if (br && br[1].trim()) return br[1].trim();
  return s.replace(/^Intel Corporation\s+/i, "")
    .replace(/^NVIDIA Corporation\s+/i, "NVIDIA ")
    .replace(/^Advanced Micro Devices,?\s*Inc\.?\s*/i, "AMD ")
    .trim();
}
function transcodeLabel(d, opts) {
  const hw = d.hw || {};
  const short = shortGpuName(hw.name);
  const full = String(hw.name || "").replace(/\s+/g, " ").trim();
  const tip = full ? ` title="${esc(full)}"` : "";
  const nameLine = short ? `<div class="ss-gpu-name muted"${tip}>${esc(short)}</div>` : "";
  const nameInline = short ? ` <span class="muted ss-gpu-name"${tip}>(${esc(short)})</span>` : "";
  let main;
  if (hw.streams) main = `<span class="hw-badge">GPU</span> ${esc(hw.label || "GPU")} · ${hw.streams} stream${hw.streams > 1 ? "s" : ""}`;
  else if (hw.method) main = `Idle · GPU (${esc(hw.label || "ready")})`;
  else if ((hw.mode || "off") === "off") main = "Off (CPU)";
  else main = "Idle (CPU)";
  if (opts && opts.parts) return { main, name: (hw.method && !hw.streams) ? nameLine : "" };
  if (hw.method && !hw.streams) return main + nameInline;
  return main;
}
function backgroundLabel(d) {
  const bg = d.background || {};
  const n = Math.max(bg.ffmpeg || 0, bg.running || 0);
  if (!n) return "";
  const kinds = { subtitles: "subtitles", prefetch: "opening clips", remux: "remux plans", cache: "cache" };
  const k = kinds[bg.kind] || "cache";
  return `Background: ${n} job${n > 1 ? "s" : ""} (${k})`;
}
const SS_DISK_ICO = ico(`<path d="M4 6.5h16A1.5 1.5 0 0 1 21.5 8v8A1.5 1.5 0 0 1 20 17.5H4A1.5 1.5 0 0 1 2.5 16V8A1.5 1.5 0 0 1 4 6.5Z"/><path d="M2.5 12h19"/><circle cx="16.5" cy="9.2" r=".7" fill="currentColor" stroke="none"/><circle cx="18.7" cy="9.2" r=".7" fill="currentColor" stroke="none"/>`);
const SS_ACT_ICO = ico(`<path d="M4.5 18.5 9 12l3.2 4.2L15.5 11l4 7.5"/><path d="M4 6.5h16"/>`);
// 1.8: outlined 24px-grid chip and DIMM, same stroke language as the library icons
const SS_CPU_ICO = ico(`<rect x="7.25" y="7.25" width="9.5" height="9.5" rx="1.35"/><rect x="9.85" y="9.85" width="4.3" height="4.3" rx="0.7"/><path d="M9.75 7.25V4.4M12 7.25V4.4M14.25 7.25V4.4"/><path d="M9.75 16.75v2.85M12 16.75v2.85M14.25 16.75v2.85"/><path d="M7.25 9.75H4.4M7.25 12H4.4M7.25 14.25H4.4"/><path d="M16.75 9.75h2.85M16.75 12h2.85M16.75 14.25h2.85"/>`);
const SS_RAM_ICO = ico(`<path d="M3.35 7.6h17.3a1.15 1.15 0 0 1 1.15 1.15v5.5a1.15 1.15 0 0 1-1.15 1.15h-5.05l-.55-1.15h-4.1L10.4 15.4H3.35A1.15 1.15 0 0 1 2.2 14.25v-5.5A1.15 1.15 0 0 1 3.35 7.6Z"/><rect x="4.85" y="9.15" width="3.35" height="2.7" rx="0.45"/><rect x="10.05" y="9.15" width="3.9" height="2.7" rx="0.45"/><rect x="15.8" y="9.15" width="3.35" height="2.7" rx="0.45"/><path d="M5.1 16.85v2.05M6.7 16.85v2.05M8.3 16.85v2.05M11.2 16.85v2.05M12.8 16.85v2.05M14.4 16.85v2.05M17.4 16.85v2.05M19 16.85v2.05"/>`);
function ssMem(d) { return `${fmtGB(d.mem.used)} / ${fmtGB(d.mem.total, 0)} GB`; }
function renderSysstat() {
  const d = SYS.d, box = $("#sysstat");
  if (!d) return;
  box.classList.remove("hidden");
  const memPct = d.mem.total ? 100 * d.mem.used / d.mem.total : 0;
  const cl = sysLevel(d.cpu, 60, 85), ml = sysLevel(memPct, 75, 90);
  const worst = [cl, ml].includes("bad") ? "bad" : [cl, ml].includes("warn") ? "warn" : "ok";
  const hw = d.hw || {}, gpu = hw.streams > 0;
  const ramPct = Math.round(memPct) + "%";
  $("#ss-pill").className = "ss-pill " + worst + (gpu ? " gpu" : "");
  // Toolbar: 18px outlined icons + compact percents on all widths (full RAM size is in the tooltip / panel).
  $("#ss-pill").innerHTML = `${gpu ? `<span class="hw-badge ss-gpu" title="${hw.streams} stream${hw.streams > 1 ? "s" : ""} on the video card (${esc(hw.label || "")})">GPU</span>` : ""}
    <span class="ss-metric" title="CPU ${cpuPct(d)}"><span class="ss-pill-ico ${cl}">${SS_CPU_ICO}</span><b class="${cl}">${cpuPct(d)}</b></span>
    <span class="ss-metric" title="RAM ${ssMem(d)} (${ramPct})"><span class="ss-pill-ico ${ml}">${SS_RAM_ICO}</span><b class="${ml}">${ramPct}</b></span>`;
  $("#ss-pill").title = `Server status -- CPU ${cpuPct(d)}, RAM ${fmtGB(d.mem.used)} of ${fmtGB(d.mem.total)} GB (${ramPct})${gpu ? ` -- ${hw.streams} on the GPU (${hw.label})` : ""}`;
  if (SYS.open) renderSysPanel();
  renderPlayerStat();
}
// 1.4.11: the same numbers, see-through, over the video (no extra requests: reuses the top-bar poll above)
// 1.5.4: plus dropped / total video frames from this browser (getVideoPlaybackQuality), shown to everyone while the
// controls are up -- the quickest way to tell a decoder or display that can't keep up from a slow network or server
function frameStat() {
  if (!P || !video.getVideoPlaybackQuality) return null;
  let q; try { q = video.getVideoPlaybackQuality(); } catch (e) { return null; }
  const tot = (q && q.totalVideoFrames) || 0; if (!tot) return null;
  const dr = q.droppedVideoFrames || 0, pct = 100 * dr / tot;
  const cls = pct >= 5 ? "bad" : pct >= 1 ? "warn" : "";
  return { html: `<span class="k" title="Video frames this browser dropped / showed since the stream started">Dropped</span> <b class="pl-fr ${cls}">${nf(dr)} / ${nf(tot)}</b>`,
           cell: `<span class="k">Dropped</span><div class="row"><b class="pl-fr ${cls}" title="Video frames this browser dropped / showed since the stream started">${nf(dr)} / ${nf(tot)}</b></div>` };
}
// 1.5.4: refresh the frame counter once a second while the controls (and so the pill) are showing
setInterval(() => { if (P && document.getElementById("player") && document.getElementById("player").classList.contains("ov-on")) renderPlayerStat(); }, 1000);
function renderPlayerStat() {
  const el = document.getElementById("pl-ss"); if (!el) return;
  if (!P) { el.classList.add("hidden"); return; }
  const d = SYS.d, fr = frameStat();
  const showSys = !!(d && ME && ME.show_status && P);
  if (!showSys && !fr) { el.classList.add("hidden"); return; }
  if (!showSys) {
    el.className = "pl-ss pl-ss-fr";
    el.innerHTML = fr.html;
    el.title = "";
    el.classList.remove("hidden");
    return;
  }
  const memPct = d.mem.total ? 100 * d.mem.used / d.mem.total : 0;
  const cl = sysLevel(d.cpu, 60, 85), ml = sysLevel(memPct, 75, 90);
  const gpu = !!(d.hw && d.hw.streams);
  const enc = gpu
    ? `<span class="k">Encoder</span><div class="row"><span class="hw-badge" title="${d.hw.streams} stream${d.hw.streams > 1 ? "s" : ""} on the video card (${esc(d.hw.label || "")})">GPU</span></div>`
    : (() => { const t = transcodeLabel(d, { parts: true }); return `<span class="k">Encoder</span><div class="row"><b>${t.main}</b></div>${t.name}`; })();
  el.className = "pl-ss";
  const qCap = P && P.cappedTo ? `Auto-capped to ${qualName(P.cappedTo)}` : (P && P.mode ? (P.mode === "direct" ? "Direct play" : P.mode === "remux" ? "Remux" : qualName(P.mode)) : "");
  el.innerHTML = `<div class="pl-ss-cell"><span class="k">CPU</span><div class="row"><b class="${cl}">${cpuPct(d)}</b></div>${sysBar(d.cpu || 0, cl)}</div>
    <div class="pl-ss-cell"><span class="k">RAM</span><div class="row"><b class="${ml}">${fmtGB(d.mem.used)}/${fmtGB(d.mem.total, 0)} GB</b></div>${sysBar(memPct, ml)}</div>
    <div class="pl-ss-cell">${gpu ? enc : enc}</div>
    <div class="pl-ss-cell">${fr ? fr.cell : `<span class="k">Dropped</span><div class="row"><b>—</b></div>`}</div>
    ${qCap ? `<div class="pl-ss-cap">${qCap}</div>` : ""}`;
  el.title = `Server CPU ${cpuPct(d)}, RAM ${fmtGB(d.mem.used)} of ${fmtGB(d.mem.total)} GB${gpu ? ` -- ${d.hw.streams} on the GPU (${d.hw.label || ""})` : ""}`;
  el.classList.remove("hidden");
}
// read-only hook for tests (and a curious admin console): push numbers into the player panel
function __msSetPlayerStat(d) { if (ME) ME.show_status = true; if (d) SYS.d = d; renderSysstat(); }
function renderSysPanel() {
  const d = SYS.d; if (!d) return;
  const memPct = d.mem.total ? 100 * d.mem.used / d.mem.total : 0;
  const swPct = d.swap.total ? 100 * d.swap.used / d.swap.total : 0;
  const cl = sysLevel(d.cpu, 60, 85), ml = sysLevel(memPct, 75, 90);
  const row = (k, v, bar) => `<div class="ss-row"><span>${k}</span><b>${v}</b>${bar || ""}</div>`;
  const cores = (d.cores || []).map((c, i) => `<i class="${sysLevel(c, 60, 85)}" style="height:${Math.max(6, c).toFixed(0)}%" title="Core ${i}: ${Math.round(c)}%"></i>`).join("");
  const disks = (d.disks || []).map(x => {
    const unknown = !!(x.used_unknown || (x.total && (x.used || 0) <= 0 && x.free >= x.total * 0.99));
    const p = unknown || !x.total ? 0 : 100 * x.used / x.total;
    const tip = esc(x.detail || x.path || x.name || "");
    const note = unknown ? `<div class="ss-disk-note">Used space is not reported by this share</div>` : "";
    return `<div class="ss-disk" title="${tip}"><div class="ss-disk-h"><span class="ss-ico">${SS_DISK_ICO}</span><span class="ss-disk-name">${esc(x.name)}</span><b>${fmtDisk(x.free)} free of ${fmtDisk(x.total, 1)}</b></div>${sysBar(p, unknown ? "ok" : sysLevel(p, 85, 95))}${note}</div>`;
  }).join("");
  const bg = backgroundLabel(d);
  const ff = d.ffmpeg && d.ffmpeg.count
    ? (d.streams ? ` · ${d.ffmpeg.count} ffmpeg (${fmtSize(d.ffmpeg.rss)})` : "")
    : " · no ffmpeg running";
  $("#ss-panel").innerHTML = `<div class="ss-h"><b>Server status</b><span class="muted">up ${fmtUptime(d.uptime_s)}</span></div>
    <div class="ss-gauges">
      <div class="ss-gauge">${sysRing(d.cpu, cl, 48, SS_CPU_ICO)}<div class="ss-g-txt"><span>CPU</span><b class="${cl}">${cpuPct(d)}</b><span>${d.ncpu} cores</span></div></div>
      <div class="ss-gauge">${sysRing(memPct, ml, 48, SS_RAM_ICO)}<div class="ss-g-txt"><span>RAM</span><b class="${ml}">${ssMem(d)}</b><span>${Math.round(memPct)}% used</span></div></div>
    </div>
    <div class="ss-big">${sysSpark((d.history || []).map(x => x[1]), 308, 36).replace("ss-spark", "ss-spark " + cl)}</div>
    ${cores ? `<div class="ss-cores" title="Per core">${cores}</div>` : ""}
    ${row("Load average", d.load.map(x => x.toFixed(2)).join(" &nbsp;"))}
    ${row("Swap", d.swap.total ? `${fmtGB(d.swap.used)} / ${fmtGB(d.swap.total)} GB` : "none", d.swap.total ? sysBar(swPct, sysLevel(swPct, 50, 80)) : "")}
    <div class="ss-sub">Disks</div>${disks || `<div class="muted">-</div>`}
    <div class="ss-sub">Media server</div>
    ${row("Active streams", `${d.streams}${ff}`)}
    ${d.hw ? row("Transcoding", transcodeLabel(d)) : ""}
    ${bg ? `<div class="ss-row"><span class="ss-bg"><span class="ss-ico" style="display:inline-block;vertical-align:-3px;margin-right:4px">${SS_ACT_ICO}</span>${bg}</span><b></b></div>` : ""}
    ${row("App memory", fmtSize(d.app_rss))}
    <div class="ss-foot muted">Refreshes every 4 s${ME && ME.is_admin ? ` · <a href="#/settings/system">Who can see this</a>` : ""}</div>`;
}
function closeSiblingPops(except) {
  // 2.4.2: only one header / page dropdown at a time (profile and status used to overlap).
  if (except !== "sys" && SYS.open) {
    SYS.open = false; SYS.pinned = false;
    const p = document.getElementById("ss-panel"), pill = document.getElementById("ss-pill");
    if (p) p.classList.add("hidden");
    if (pill) pill.setAttribute("aria-expanded", "false");
  }
  if (except !== "acct") {
    const menu = document.getElementById("acct-menu"), av = document.getElementById("m-avatar");
    if (menu && !menu.classList.contains("hidden")) {
      menu.classList.add("hidden");
      if (av) av.setAttribute("aria-expanded", "false");
    }
  }
  if (except !== "more") {
    const menu = document.getElementById("more-menu"), btn = document.getElementById("more");
    if (menu && !menu.hidden) { menu.hidden = true; if (btn) btn.setAttribute("aria-expanded", "false"); }
  }
  if (except !== "ml") {
    const m = document.getElementById("ml-menu"), btn = document.getElementById("ml-more");
    if (m) { m.remove(); if (btn) btn.setAttribute("aria-expanded", "false"); }
  }
}
function setSysOpen(on, pinned) {
  if (on) closeSiblingPops("sys");
  SYS.open = on; if (pinned !== undefined) SYS.pinned = pinned;
  $("#ss-panel").classList.toggle("hidden", !on); $("#ss-pill").setAttribute("aria-expanded", on ? "true" : "false");
  if (on) renderSysPanel();
}
function stopSysstat() { clearTimeout(SYS.timer); SYS.timer = null; SYS.d = null; setSysOpen(false, false); $("#sysstat").classList.add("hidden"); renderPlayerStat(); }
async function pollSysstat() {
  clearTimeout(SYS.timer); SYS.timer = null;
  if (!ME || !ME.show_status) { stopSysstat(); return; }
  if (document.hidden) return;   // resumes on visibilitychange
  try { SYS.d = await api("/api/system/status", { noAuthRedirect: true }); renderSysstat(); }
  catch (e) { if (/admins/.test(e.message)) { ME.show_status = false; stopSysstat(); return; } }
  if (!document.hidden) SYS.timer = setTimeout(pollSysstat, 4000);
}
document.addEventListener("visibilitychange", () => { if (document.hidden) { clearTimeout(SYS.timer); SYS.timer = null; } else if (ME) pollSysstat(); });
(function wireSysstat() {
  const box = $("#sysstat"), hover = window.matchMedia("(hover: hover) and (min-width: 821px)");
  $("#ss-pill").onclick = (e) => { e.stopPropagation(); if (SYS.open && SYS.pinned) setSysOpen(false, false); else setSysOpen(true, true); };
  box.addEventListener("mouseenter", () => { if (hover.matches && !SYS.open) setSysOpen(true, false); });
  box.addEventListener("mouseleave", () => { if (hover.matches && SYS.open && !SYS.pinned) setSysOpen(false); });
  document.addEventListener("click", (e) => { if (SYS.open && !box.contains(e.target)) setSysOpen(false, false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && SYS.open) setSysOpen(false, false); });
})();

function syncTopH() {
  const t = $(".top");
  if (t) document.documentElement.style.setProperty("--top-h", t.offsetHeight + "px");
}
if (typeof ResizeObserver === "function") {
  const mo = new ResizeObserver(syncTopH);
  const attach = () => { const t = $(".top"); if (t && !syncTopH._obs) { mo.observe(t); syncTopH._obs = true; } };
  attach();
  document.addEventListener("DOMContentLoaded", attach);
}
window.addEventListener("resize", syncTopH);

async function boot() {
  const pairCode = pairCodeFromLocation();
  if (pairCode) { await showPairApprove(pairCode); return; }
  const inv = location.hash.match(/^#\/invite\/([A-Za-z0-9_-]{20,200})/);   // 1.9: invite link
  if (inv) { await showJoin(inv[1]); return; }
  try {
    const st = await api("/api/setup-status", { noAuthRedirect: true });
    if (st.needs_setup) { showSetup(); return; }
    ME = await api("/api/me", { noAuthRedirect: true });
  } catch (e) { showLogin(); return; }
  stopPairPoll();
  rememberServer(location.origin, "Movinite" + (ME.version ? " · v" + ME.version : ""));
  hideAuth(); $("#shell").classList.remove("hidden");
  $("#whoami").textContent = ME.username; $("#ver").textContent = "v" + ME.version;
  syncTopH();
  MOB.setup();
  if (window.TV) TV.init();
  SFX.load(ME.username);
  $("#sndbtn").onclick = () => SFX.toggle();
  await refreshLibs();
  if (ME.must_change_pw) forcePasswordChange();
  route();
  pollActivity();
  pollSysstat();
}
$("#logout").onclick = async (e) => { e.preventDefault(); await api("/api/logout", { method: "POST" }).catch(() => {}); ME = null; stopSysstat(); showLogin(); };
$("#menubtn").onclick = () => $("#side").classList.toggle("open");
$("#activity").onclick = () => { location.hash = ME && ME.is_admin ? "#/settings/scans" : "#/settings/libraries"; };

// 1.6: a dot after each network-share library: green online, amber slow / not answering, red offline, grey checking.
// Local-folder libraries get no dot.  The server checks the shares every ~45 s (cached; never remounts anything).
function agoShort(s) { return s == null ? "" : s < 60 ? s + "s ago" : s < 3600 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago"; }
function shareDot(l) {
  const h = l.health; if (!h) return "";
  const cls = { online: "on", slow: "warn", stuck: "warn", offline: "off" }[h.state] || "chk";
  const when = h.age_s != null ? " · checked " + agoShort(h.age_s) : "";
  const t = h.state === "online" ? "Share online" + when
    : h.state === "offline" ? "Share offline: " + (h.reason || "unreachable") + when
    : h.state === "checking" ? "Checking the share…"
    : "Share " + (h.state === "slow" ? "slow" : "not responding") + ": " + (h.reason || "") + when;
  return `<span class="ldot ${cls}" role="img" title="${esc(t)}" aria-label="${esc(t)}"></span>`;
}
const ICO_SHARE = ico(`<path d="M4.25 3.85h15.5A1.6 1.6 0 0 1 21.35 5.45v4.7A1.6 1.6 0 0 1 19.75 11.75H4.25A1.6 1.6 0 0 1 2.65 10.15v-4.7A1.6 1.6 0 0 1 4.25 3.85Z"/><path d="M4.25 13.25h15.5A1.6 1.6 0 0 1 21.35 14.85v4.7A1.6 1.6 0 0 1 19.75 21.15H4.25A1.6 1.6 0 0 1 2.65 19.55v-4.7A1.6 1.6 0 0 1 4.25 13.25Z"/><circle cx="6.55" cy="7.8" r="1.15" fill="currentColor" stroke="none"/><circle cx="6.55" cy="17.2" r="1.15" fill="currentColor" stroke="none"/><path d="M9.4 7.8h8.3"/><path d="M9.4 17.2h8.3"/>`);
const ICO_LOCAL = ico(`<path d="M4.25 3.35h15.5A1.7 1.7 0 0 1 21.45 5.05v8.15A1.7 1.7 0 0 1 19.75 14.9H4.25A1.7 1.7 0 0 1 2.55 13.2V5.05A1.7 1.7 0 0 1 4.25 3.35Z"/><path d="M12 14.9v2.05"/><path d="M5.4 17.85h13.2A1.35 1.35 0 0 1 19.95 19.2v1.15A1.35 1.35 0 0 1 18.6 21.7H5.4A1.35 1.35 0 0 1 4.05 20.35V19.2A1.35 1.35 0 0 1 5.4 17.85Z"/><path d="M8.4 19.7h7.2"/>`);
// 1.7: libraries grouped by the network share they are on (folders on the server itself in a group of their own).
// Groups come in the order of their first library; inside a group the admin order is kept.
function libGroups(libs) {
  const out = [], by = {};
  for (const l of (libs || LIBS)) {
    const k = l.is_remote ? "r" + (l.peer_id || l.peer_name || l.id) : (l.share_id ? "s" + l.share_id : "local");
    if (!by[k]) {
      by[k] = { key: k, share: l.is_remote
        ? { id: l.peer_id, name: l.peer_name || "Shared", kind: "peer", remote: (l.share && l.share.remote) || "" }
        : (l.share_id ? (l.share || { id: l.share_id, name: "Share" }) : null), libs: [] };
      out.push(by[k]);
    }
    by[k].libs.push(l);
  }
  out.forEach(g => { g.name = g.share ? (g.share.name || (g.share.kind === "peer" ? "Shared" : "Network share")) : "This server"; });
  return out;
}
function libsGrouped(libs) { return (libs || LIBS).some(l => l.share_id || l.is_remote); }
// the group's status = its worst library (they share one mount, so normally all the same)
const HSEV = { offline: 4, stuck: 3, slow: 2, checking: 1, online: 0 };
function groupHealthLib(g) {
  let w = null;
  for (const l of g.libs) if (l.health && (!w || (HSEV[l.health.state] || 0) > (HSEV[w.health.state] || 0))) w = l;
  return w;
}
function libDotInGroup(l, g) {   // a library's own dot only when it differs from the share's (e.g. its folder is missing)
  const w = groupHealthLib(g);
  return l.health && w && l.health.state !== w.health.state ? shareDot(l) : "";
}
function navLibsHtml() {
  if (!LIBS.length) return `<div class="muted" style="padding:4px 10px;font-size:13px">No libraries yet</div>`;
  if (!libsGrouped()) return LIBS.map(l => `<a href="#/library/${l.id}" data-nav="lib${l.id}">${KIND_ICON[l.kind] || ""} ${esc(l.name)}${shareDot(l)}</a>`).join("");
  return libGroups().map(g => {
    const w = g.share ? groupHealthLib(g) : null;
    return `<div class="navgrp" data-grp="${g.key}"><div class="navgrp-h" title="${g.share ? esc((g.share.kind ? g.share.kind.toUpperCase() + " share " : "Share ") + (g.share.remote || "")) : "Folders on this server"}"><span class="ng-ic" aria-hidden="true">${g.share ? ICO_SHARE : ICO_LOCAL}</span><span class="ng-n">${esc(g.name)}</span>${w ? shareDot(w) : ""}</div>`
      + g.libs.map(l => `<a class="navgrp-a" href="#/library/${l.id}" data-nav="lib${l.id}">${KIND_ICON[l.kind] || ""} ${esc(l.name)}${libDotInGroup(l, g)}</a>`).join("") + `</div>`;
  }).join("");
}
async function refreshLibs() {
  LIBS = await api("/api/libraries");
  const nav = $("#navlibs"), html = navLibsHtml();
  if (nav.innerHTML !== html) { const on = nav.querySelector("a.active"); nav.innerHTML = html; if (on) { const a = nav.querySelector(`[data-nav="${on.dataset.nav}"]`); if (a) a.classList.add("active"); } }
  $$(".lib-li[data-lib]").forEach(a => { const l = LIBS.find(x => x.id === +a.dataset.lib); const d = a.querySelector(".ldot-slot"); if (l && d) d.innerHTML = shareDot(l); });
}
// keep the dots fresh while the app is open (every 30 s, only when the tab is visible and someone is signed in)
setInterval(() => { if (ME && !document.hidden && LIBS.some(l => l.share_id)) refreshLibs().catch(() => {}); }, 30000);

// ---------------------------------------------------------------- router
window.addEventListener("hashchange", route);
let searchTimer = null;
$("#search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { const q = $("#search").value.trim(); location.hash = q ? "#/search/" + enc(q) : "#/home"; }, 300);
});
function setActive(key) { $$(".side nav a").forEach(a => a.classList.toggle("active", a.dataset.nav === key)); $("#side").classList.remove("open"); MOB.tab(); }

// ---------------------------------------------------------------- 1.5.1: phone layout (bottom tab bar, account menu)
// On phones (<= 820 px, browser and Android app) the menu button is replaced by a bottom tab bar (Home, Libraries,
// Search, My List, Settings) and the top bar gets a search icon, the server-status dot and an account avatar.
const MOB = (() => {
  const menu = $("#acct-menu"), av = $("#m-avatar");
  function tabFor(h) {
    const p = (h || location.hash).replace(/^#\/?/, "").split("/")[0] || "home";
    if (p === "home") return "home";
    if (p === "libraries" || p === "library" || p === "show" || p === "album") return "libraries";
    if (p === "search") return "search";
    if (p === "mylist") return "mylist";
    if (p === "downloads") return "downloads";
    if (p === "settings") return "settings";
    return "";
  }
  function tab() { const t = tabFor(); $$("#tabbar a").forEach(a => { const on = a.dataset.tab === t; a.classList.toggle("on", on); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); }); }
  function sound() { const on = SFX.get().on; $("#acct-sound").textContent = "Poster sounds: " + (on ? "on" : "off"); }
  function open(v) {
    if (v) closeSiblingPops("acct");
    menu.classList.toggle("hidden", !v); av.setAttribute("aria-expanded", v ? "true" : "false");
    if (v) { sound(); const f = [...menu.querySelectorAll("a,button")].find(el => !el.hidden && el.getAttribute("aria-hidden") !== "true"); if (f) f.focus({ preventScroll: true }); }
  }
  function setup() {
    const ini = (ME.username || "?").trim().charAt(0).toUpperCase() || "?";
    av.textContent = ini; $("#acct-ini").textContent = ini;
    $("#acct-name").textContent = ME.username; $("#acct-role").textContent = ME.is_admin ? "Administrator" : "User";
    $("#acct-ver").textContent = "Movinite v" + ME.version;
    $("#acct-settings").hidden = !ME.is_admin;
    $("#tab-set-l").textContent = ME.is_admin ? "Settings" : "Account";
    OFF.applyTabs();   // 2.0: in the Android app (with the download role) Downloads replaces My List in the tab bar
    tab();
  }
  av.onclick = (e) => { e.stopPropagation(); open(menu.classList.contains("hidden")); };
  menu.addEventListener("click", (e) => { if (e.target.closest("a")) open(false); });
  $("#acct-sound").onclick = (e) => { e.stopPropagation(); SFX.toggle(); SFX.drawToggle(); sound(); };
  $("#acct-logout").onclick = () => { open(false); $("#logout").click(); };
  document.addEventListener("click", (e) => { if (!menu.classList.contains("hidden") && !e.target.closest(".acct-w")) open(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.classList.contains("hidden")) { open(false); av.focus(); } });
  window.addEventListener("hashchange", () => open(false));
  $("#m-search").onclick = () => { location.hash = "#/search"; };
  return { setup, tab, tabFor, open };
})();

// a home row title: on phones the whole title (with a ">") opens the full list and the library name sits under it
function rowHead(title, href, opts) {
  opts = opts || {};
  const attrs = opts.attrs || "";
  const t = href ? `<a class="rh-a" href="${href}"${attrs}>${title}<span class="chev" aria-hidden="true">&rsaquo;</span></a>` : title;
  return `<div class="row-head"><h3>${t}${opts.extra || ""}</h3>${href ? `<a class="muted see-all" href="${href}"${attrs}>See all &rsaquo;</a>` : ""}</div>`
    + (opts.sub ? `<div class="row-sub">${opts.sub}</div>` : "");
}

// ---- 1.4.4: horizontal rows page with < > buttons (no scrollbar); swipe still works on touch screens
const HROW_SEL = ".strip, .cast-strip";
function hrowStep(st) {
  const kids = st.children;
  if (kids.length < 2) return Math.max(200, st.clientWidth * 0.9);
  const step = kids[1].offsetLeft - kids[0].offsetLeft;            // card width + gap
  return step > 0 ? Math.max(step, Math.floor(st.clientWidth / step) * step) : st.clientWidth * 0.9;
}
function hrowUpdate(w) {
  const st = w.querySelector(HROW_SEL);
  if (!st) return;
  const max = st.scrollWidth - st.clientWidth;
  w.classList.toggle("fits", max <= 2);
  w.querySelector(".hnav.prev").hidden = st.scrollLeft <= 2;
  w.querySelector(".hnav.next").hidden = st.scrollLeft >= max - 2;
  const art = st.querySelector(".art, .pph");                         // centre the buttons on the posters
  if (art) w.style.setProperty("--nav-y", Math.round(art.getBoundingClientRect().top - w.getBoundingClientRect().top + art.offsetHeight / 2) + "px");
}
function enhanceRows(root) {
  (root || document).querySelectorAll(HROW_SEL).forEach(st => {
    if (st.parentElement.classList.contains("hrow")) { hrowUpdate(st.parentElement); return; }
    const w = document.createElement("div"); w.className = "hrow";
    st.parentNode.insertBefore(w, st); w.appendChild(st);
    w.insertAdjacentHTML("beforeend", `<button class="hnav prev" type="button" aria-label="Scroll left" title="Back">&#8249;</button><button class="hnav next" type="button" aria-label="Scroll right" title="More">&#8250;</button>`);
    const page = (dir) => st.scrollBy({ left: dir * hrowStep(st), behavior: "smooth" });
    w.querySelector(".hnav.prev").onclick = (e) => { e.stopPropagation(); SFX.arrow(-1); page(-1); };
    w.querySelector(".hnav.next").onclick = (e) => { e.stopPropagation(); SFX.arrow(1); page(1); };
    st.addEventListener("scroll", () => { if (!w._raf) w._raf = requestAnimationFrame(() => { w._raf = 0; hrowUpdate(w); }); }, { passive: true });
    st.addEventListener("keydown", (e) => { if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); page(e.key === "ArrowRight" ? 1 : -1); } });
    if (!st.hasAttribute("tabindex")) st.tabIndex = -1;
    hrowUpdate(w);
  });
}
// 1.4.9: settings on phones -- every table cell gets its column name (tables become stacked cards there),
// and the active tab is scrolled into view in the one-line, swipeable tab bar
// 1.4.10: paths may wrap after each "/" (never inside a folder name)
function wbrPath(p) { return esc(p || "").replace(/\//g, "/<wbr>"); }
function settingsMobile(v) {
  if (v.dataset.view !== "settings") return;
  v.querySelectorAll("table").forEach(t => {
    const hd = t.querySelector("tr"); if (!hd || !hd.querySelector("th")) return;
    hd.classList.add("thead-row");
    const names = [...hd.children].map(th => th.textContent.trim());
    t.querySelectorAll("tr").forEach(tr => { if (tr === hd) return; [...tr.children].forEach((td, i) => {
      if (!td.hasAttribute("data-label")) td.setAttribute("data-label", td.colSpan > 1 ? "" : (names[i] || ""));
      // 1.4.10: the value goes in one wrapper so its parts stack instead of becoming side-by-side columns;
      // values with several parts or long text get the label on top and the full card width
      if (td.firstElementChild && td.firstElementChild.classList.contains("cv") && td.children.length === 1) return;
      const cv = document.createElement("div"); cv.className = "cv";
      while (td.firstChild) cv.appendChild(td.firstChild);
      td.appendChild(cv);
      const parts = [...cv.childNodes].filter(n => n.nodeType === 1 ? n.textContent.trim() || n.querySelector("button, input, select") : n.textContent.trim()).length;
      const blocks = [...cv.children].some(e => getComputedStyle(e).display === "block" || e.tagName === "DIV");
      td.classList.toggle("multi", parts > 1 || blocks || cv.textContent.trim().length > 26);
      if (cv.querySelector(".row-actions")) td.classList.add("acts");
      else if (cv.querySelector(".btn") && !cv.textContent.replace(/\s+/g, "").replace([...cv.querySelectorAll(".btn")].map(b => b.textContent.replace(/\s+/g, "")).join(""), "")) td.classList.add("btns");
    }); });
    t.classList.add("stack-tbl");
  });
  const tb = v.querySelector(".set-tabs");
  if (tb && !tb._done) {
    tb._done = true;
    const on = tb.querySelector("button.on");
    if (on && tb.scrollWidth > tb.clientWidth) tb.scrollLeft = on.offsetLeft - (tb.clientWidth - on.offsetWidth) / 2;
    const edges = () => { tb.classList.toggle("more-l", tb.scrollLeft > 2); tb.classList.toggle("more-r", tb.scrollLeft < tb.scrollWidth - tb.clientWidth - 2); };
    tb.addEventListener("scroll", edges, { passive: true }); edges();
  }
}
new MutationObserver(() => { if (!enhanceRows._raf) enhanceRows._raf = requestAnimationFrame(() => { enhanceRows._raf = 0; enhanceRows($("#view")); settingsMobile($("#view")); }); })
  .observe(document.getElementById("view"), { childList: true, subtree: true });
window.addEventListener("resize", () => $$(".hrow").forEach(hrowUpdate));

/* 2.5.2 / 2.5.4: phone details header — transparent over the backdrop and stays that way while you scroll. */
function clearDetailTop() {
  const h = document.documentElement;
  h.classList.remove("detail-top", "detail-top-scrolled");
  h.style.removeProperty("--detail-tint");
  h.style.removeProperty("--detail-tint-rgb");
}
function setDetailTop(imgUrl) {
  if (!imgUrl) { clearDetailTop(); return; }
  document.documentElement.classList.add("detail-top");
  document.documentElement.classList.remove("detail-top-scrolled");
}

async function route() {
  if (!ME) return;
  const h = location.hash.replace(/^#\/?/, "");
  const parts = h.split("/").map(decodeURIComponent);
  const v = $("#view");
  v.dataset.view = parts[0] || "home";   // 1.4.9: lets CSS style the settings pages for phones
  clearDetailTop();
  clearInterval(route._poll); route._live = null; route._token = (route._token || 0) + 1;
  try {
    switch (parts[0]) {
      case "library": setActive("lib" + parts[1]);
        if (parts[2] === "collections") await viewCollections(+parts[1]);
        else if (parts[2] === "smart") await viewSmart(+parts[1], parts[3]);
        else if (parts[2] === "playlists") await viewPlaylists(+parts[1]);
        else if (parts[2] === "playlist") await viewPlaylist(+parts[3], +parts[1]);
        else if (parts[2] === "collection") await viewLibrary(+parts[1], "", +parts[3]);
        else await viewLibrary(+parts[1], parts[2] || ""); break;
      case "playlist": setActive(""); await viewPlaylist(+parts[1]); break;
      case "item": setActive(""); await viewItem(+parts[1]); break;
      case "person": setActive(""); await viewPerson(+parts[1], +parts[2] || 0); break;
      case "show": setActive("lib" + parts[1]); await viewShow(+parts[1], parts[2]); break;
      case "album": setActive("lib" + parts[1]); await viewAlbum(+parts[1], parts[2], parts[3]); break;
      case "search": setActive(""); await viewSearch(parts.slice(1).join("/")); break;
      case "libraries": setActive(""); await viewLibraries(); break;
      case "mylist": setActive(""); await viewMyList(); break;
      case "downloads": setActive(""); await viewDownloads(); break;
      case "settings": setActive("settings"); await viewSettings(parts[1] || ""); break;
      default: setActive("home"); await viewHome();
    }
  } catch (e) {
    if (e.message !== "Not signed in") v.innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`;
  }
  v.scrollTop = route._keepScroll ? v.scrollTop : 0; route._keepScroll = false;
  if (window.TV) TV.afterRoute();
}

// ---------------------------------------------------------------- cards
// 2.5.8: episode cards in home-style rows use the series (or season) portrait poster
function seriesPoster(i) {
  if (!i) return "";
  if (i.show_poster) return i.show_poster;
  if (i.season_poster) return i.season_poster;
  if (i.poster && i.poster !== i.thumb) return i.poster;
  return i.thumb || i.poster || "";
}
function cardItem(i, opts) {
  opts = opts || {};
  // Episode rows use a movie-sized portrait card unless the caller asked for a still (landscape).
  const useSeries = i.kind === "episode" && !opts.landscape;
  const land = !useSeries && (opts.landscape || i.kind === "video" || (!i.poster && i.media_type === "video" && i.kind !== "movie"));
  const img = useSeries ? (seriesPoster(i) || i.thumb || i.poster) : (land ? (i.thumb || i.poster) : (i.poster || i.thumb));
  const pct = i.position && i.duration ? Math.min(100, 100 * i.position / i.duration) : 0;
  let t = i.title, s = (i.year || "") + (i.edition ? ` <span class="ed" title="${esc(i.edition)}">${esc(i.edition)}</span>` : "");
  if (i.kind === "episode") {
    t = opts.showName === false ? i.title : (i.show_title || i.show || i.title);
    const epBit = epCode(i);
    const epName = (!opts.showName && i.title && i.title !== t) ? " · " + esc(i.title) : "";
    s = epBit + (opts.showName === false ? "" : epName);
  }
  if (i.media_type === "audio") { s = i.artist || ""; }
  const cls = land ? "landscape" : (i.media_type === "audio" ? "square" : "");
  const srcName = i.peer_name || i.source_name || "";
  if (opts.resume && i.duration && i.position) {
    const left = Math.max(1, Math.round((i.duration - i.position) / 60));
    const epBit = i.kind === "episode" ? epCode(i) : "";
    const epName = (i.kind === "episode" && i.title && i.title !== t) ? " · " + esc(i.title) : "";
    const leftTxt = (epBit ? epBit + epName + " · " : "") + left + " min left";
    s = `<span class="d-only">${leftTxt}${srcName ? " · " + esc(srcName) : ""}</span><span class="m-only">${epBit || (i.year || left + " min left")}</span>`;
  }
  else if (srcName && i.is_remote) { s = (s ? s + " · " : "") + esc(srcName); }
  // 1.4.3: a poster always opens the details page; the small round button plays (resumes where you stopped)
  const resumeAt = i.position > 30 && !i.watched ? i.position : 0;
  const quick = i.media_type === "audio" ? `<div class="playov" data-play="${i.id}">&#9654;</div>`
    : `<button class="qplay" type="button" data-play="${i.id}" title="${resumeAt ? "Resume from " + fmtDur(resumeAt) : "Play"}" aria-label="${resumeAt ? "Resume" : "Play"} ${esc(t)}">&#9654;</button>`;
  // 1.4.7: info that fades in over the poster on hover / keyboard focus
  const hov = i.media_type === "audio" ? "" : `<div class="hov" aria-hidden="true"><b>${esc(t)}</b><span>${[i.year, i.rating ? "&#9733; " + (+i.rating).toFixed(1) : "", i.duration ? fmtLen(i.duration) : ""].filter(Boolean).join(" · ")}</span></div>`;
  return `<div class="card ${cls}${opts.resume ? " resume" : ""}${i.unavailable ? " unavailable" : ""}" tabindex="0" data-href="#/item/${i.id}"${opts.resume ? ` title="${esc(t)} -- resume from ${fmtDur(i.position || 0)}${i.unavailable ? " (server offline)" : ""}"` : ""} data-id="${i.id}">
    <div class="art"${img ? ` data-bg="${thumbUrl(img)}"${(!land && i.id && i.kind !== "episode" && i.media_type !== "audio") ? ` data-bg-hi="/api/items/${i.id}/poster-large"` : ""}` : ""}>
      ${img ? "" : `<div class="ph">${i.media_type === "audio" ? "&#9835;" : "&#127902;"}</div>`}
      ${i.unavailable ? `<span class="badge off" title="${esc(srcName || "Shared server")} is not reachable">Offline</span>` : (i.watched ? `<span class="badge">&#10003;</span>` : "")}
      ${i.needs_review ? `<span class="badge rv" title="Match needs review">?</span>` : ""}
      ${resBadge(i)}
      ${hov}
      ${pct ? `<div class="bar" style="width:${pct}%"></div>` : ""}
      ${quick}
    </div><div class="t" title="${esc(t)}">${esc(t)}</div><div class="s">${s}</div>${opts.reason && i.reason ? `<div class="why" title="${esc(i.reason)}">${esc(i.reason)}</div>` : ""}</div>`;
}
// 1.7: "4K" / "2K" on the poster; "+1" when the film has more versions (all listed best first in the tooltip)
function resBadge(i) {
  if (i.kind !== "movie" || !i.width) return "";
  const r = resName(i.width, i.height), more = (i.versions || 1) - 1;
  if (!more && r !== "4K" && r !== "2K") return "";
  const t = more ? `${i.versions} versions: ${(i.vres || [r]).join(", ")} -- the best one plays` : r;
  return `<span class="rbadge${r === "4K" ? " k4" : ""}" title="${esc(t)}">${r}${more ? `<small> +${more}</small>` : ""}</span>`;
}
// 1.7: "1,965 movies" for movie libraries (several files of one film count once), else "N items"
function libCountText(l) { return l.film_count != null ? nf(l.film_count) + " movie" + (l.film_count === 1 ? "" : "s") : nf(l.item_count || 0) + " items"; }
function libCountTitle(l) { return l.film_count != null && l.item_count > l.film_count ? ` title="${nf(l.item_count)} files -- ${nf(l.item_count - l.film_count)} are other versions (e.g. 1080p next to 4K)"` : ""; }
function cardShow(libId, s) {
  return `<div class="card" tabindex="0" data-href="#/show/${libId}/${enc(s.show)}"><div class="art"${s.poster ? ` data-bg="${thumbUrl(s.poster)}"` : ""}>
    ${s.poster ? "" : `<div class="ph">&#128250;</div>`}</div>
    <div class="t" title="${esc(s.display_name || s.show)}">${esc(s.display_name || s.show)}</div><div class="s">${s.seasons ? s.seasons + " season" + (s.seasons > 1 ? "s" : "") + " · " : ""}${s.episodes} episodes</div></div>`;
}
function cardAlbum(libId, a) {
  return `<div class="card square" tabindex="0" data-href="#/album/${libId}/${enc(a.artist)}/${enc(a.album)}"><div class="art"${a.poster ? ` data-bg="${thumbUrl(a.poster)}"` : ""}>
    ${a.poster ? "" : `<div class="ph">&#9835;</div>`}<div class="playov" data-playalbum="${libId}|${esc(a.artist)}|${esc(a.album)}">&#9654;</div></div>
    <div class="t" title="${esc(a.album)}">${esc(a.album)}</div><div class="s">${esc(a.artist)}${a.year ? " · " + a.year : ""}</div></div>`;
}
document.addEventListener("click", (e) => {
  const pl = e.target.closest("[data-play]");
  if (pl) { e.stopPropagation(); e.preventDefault(); SFX.play(); playItem(+pl.dataset.play); return; }
  const pa = e.target.closest("[data-playalbum]");
  if (pa) { e.stopPropagation(); e.preventDefault(); const [l, ar, al] = pa.dataset.playalbum.split("|"); playAlbum(+l, ar, al, 0); return; }
  const g = e.target.closest("[data-genre]");
  if (g) { e.stopPropagation(); e.preventDefault(); openGenre(+g.dataset.lib, g.dataset.genre); return; }
  const c = e.target.closest("[data-href]");
  if (c) { if (c.classList.contains("card")) SFX.select(); location.hash = c.dataset.href; }
});
// ---- 1.4.8: interface sounds, synthesised with the Web Audio API (no audio files, nothing to license).
// The audio engine starts on the first click / key press (browser autoplay rules); until then sounds are skipped silently.
// Settings are per user, kept in this browser (localStorage).
const SFX_BUILD = {      // pure builders: (ctx, out, t, v) -- v = pitch variation (-1..1); also used to render the preview WAVs
  env(ctx, t, peak, attack, decay) { const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + attack); g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay); return g; },
  tone(ctx, out, t, f0, f1, type, peak, attack, decay) {
    const o = ctx.createOscillator(); o.type = type; o.frequency.setValueAtTime(f0, t); if (f1 && f1 !== f0) o.frequency.exponentialRampToValueAtTime(f1, t + attack + decay * 0.8);
    const g = SFX_BUILD.env(ctx, t, peak, attack, decay); o.connect(g); g.connect(out); o.start(t); o.stop(t + attack + decay + 0.05);
  },
  noise(ctx, out, t, dur, fA, fB, peak, q) {
    const n = Math.ceil(ctx.sampleRate * dur), b = ctx.createBuffer(1, n, ctx.sampleRate), d = b.getChannelData(0);
    let s = 12345; for (let i = 0; i < n; i++) { s = (s * 1103515245 + 12345) & 0x7fffffff; d[i] = s / 0x3fffffff - 1; }   // deterministic noise
    const src = ctx.createBufferSource(); src.buffer = b;
    const bp = ctx.createBiquadFilter(); bp.type = "bandpass"; bp.Q.value = q || 1.2; bp.frequency.setValueAtTime(fA, t); bp.frequency.exponentialRampToValueAtTime(fB, t + dur);
    const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + dur * 0.35); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(bp); bp.connect(g); g.connect(out); src.start(t); src.stop(t + dur + 0.02);
  },
  hover(ctx, out, t, v) {          // soft tick: a short glassy blip, ~60 ms
    const f = 1850 * (1 + 0.07 * (v || 0));
    SFX_BUILD.tone(ctx, out, t, f, f * 0.82, "triangle", 0.16, 0.003, 0.05);
    SFX_BUILD.tone(ctx, out, t, f * 2, f * 1.7, "sine", 0.04, 0.002, 0.03);
  },
  select(ctx, out, t) {            // open a movie: airy whoosh + two-note chime, ~0.5 s
    SFX_BUILD.noise(ctx, out, t, 0.2, 500, 2600, 0.16, 1.1);
    SFX_BUILD.tone(ctx, out, t + 0.05, 659, 659, "sine", 0.27, 0.006, 0.32);
    SFX_BUILD.tone(ctx, out, t + 0.05, 1318, 1318, "sine", 0.035, 0.006, 0.2);
    SFX_BUILD.tone(ctx, out, t + 0.12, 988, 988, "sine", 0.25, 0.006, 0.42);
    SFX_BUILD.tone(ctx, out, t + 0.12, 1976, 1976, "triangle", 0.025, 0.006, 0.25);
  },
  play(ctx, out, t) {              // Play / Resume: low thump + rising three-note arpeggio, ~0.45 s
    SFX_BUILD.tone(ctx, out, t, 140, 55, "sine", 0.28, 0.004, 0.16);
    [[523, 0], [659, 0.055], [784, 0.11]].forEach(([f, d]) => SFX_BUILD.tone(ctx, out, t + d, f, f, "triangle", 0.13, 0.005, 0.26));
    SFX_BUILD.tone(ctx, out, t + 0.11, 1568, 1568, "sine", 0.03, 0.005, 0.3);
  },
  arrow(ctx, out, t, dir) {        // < > : a quick swish up (>) or down (<), ~0.14 s
    const up = dir >= 0;
    SFX_BUILD.noise(ctx, out, t, 0.14, up ? 900 : 3200, up ? 3200 : 900, 0.4, 1.4);
    SFX_BUILD.tone(ctx, out, t + 0.01, up ? 1100 : 1500, up ? 1500 : 1100, "sine", 0.09, 0.004, 0.08);
  },
};
const SFX = (() => {
  const COARSE = matchMedia("(hover: none), (pointer: coarse)").matches;
  const DEF = { on: true, vol: 0.3, hover: true, select: !COARSE };   // default: on, low volume; phones: no tap sounds
  let ctx = null, master = null, lastHover = 0, user = "", S = Object.assign({}, DEF);
  const key = () => "ms-sound:" + (user || "_");
  function load(u) { user = u || ""; try { S = Object.assign({}, DEF, JSON.parse(localStorage.getItem(key()) || "{}")); } catch (e) { S = Object.assign({}, DEF); } apply(); }
  function save() { try { localStorage.setItem(key(), JSON.stringify(S)); } catch (e) { /* private mode */ } apply(); }
  function apply() { if (master) master.gain.value = S.vol; drawToggle(); }
  function unlock() {
    if (ctx) { if (ctx.state === "suspended") ctx.resume().catch(() => {}); return; }
    const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
    try { ctx = new AC(); master = ctx.createGain(); master.gain.value = S.vol; master.connect(ctx.destination); } catch (e) { ctx = null; }
  }
  ["pointerdown", "keydown", "touchend"].forEach(ev => window.addEventListener(ev, unlock, { capture: true, passive: true }));
  const playing = () => { const p = document.getElementById("player"); return !!(p && !p.classList.contains("hidden")) || !!document.pictureInPictureElement; };   // no sounds over a video (also in PiP)
  function fire(kind, arg, force) {
    if (!ctx || ctx.state !== "running" || !(S.on || force) || S.vol <= 0) return false;
    if (!force && (playing() || (kind === "hover" ? !(S.hover && !COARSE) : !S.select))) return false;
    try { SFX_BUILD[kind](ctx, master, ctx.currentTime + 0.005, arg); if (window.__sfxLog) window.__sfxLog.push(kind); return true; } catch (e) { return false; }
  }
  function hover() { const now = performance.now(); if (now - lastHover < 70) return false; lastHover = now; return fire("hover", Math.random() * 2 - 1); }
  function drawToggle() {
    const b = document.getElementById("sndbtn"); if (!b) return;
    b.setAttribute("aria-pressed", S.on ? "true" : "false");
    b.title = S.on ? "Poster sounds on (click to mute)" : "Poster sounds off (click to turn on)";
    b.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M4 9v6h4l5 4V5L8 9H4z"/>${S.on
      ? `<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M16 9.2a4 4 0 0 1 0 5.6M18.6 6.6a7.6 7.6 0 0 1 0 10.8"/>`
      : `<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M16.5 9.5l5 5M21.5 9.5l-5 5"/>`}</svg>`;
  }
  return {
    load, hover, get: () => Object.assign({}, S), COARSE,
    set(p) { Object.assign(S, p); save(); },
    select: () => fire("select"), play: () => fire("play"), arrow: (dir) => fire("arrow", dir),
    test() { unlock(); setTimeout(() => { fire("hover", 0, true); setTimeout(() => fire("select", 0, true), 220); }, 30); },
    toggle() { S.on = !S.on; save(); if (S.on) { unlock(); setTimeout(() => fire("select"), 30); } },
    state: () => ctx ? ctx.state : "locked", drawToggle,
  };
})();
// hover (mouse only) and keyboard focus on a poster -> tick; entering the same poster's children doesn't re-trigger
document.addEventListener("pointerover", (e) => {
  if (e.pointerType && e.pointerType !== "mouse") return;
  const c = e.target.closest && e.target.closest(".card"); if (!c) return;
  if (e.relatedTarget && c.contains(e.relatedTarget)) return;
  SFX.hover();
});
document.addEventListener("focusin", (e) => { const c = e.target; if (c.classList && c.classList.contains("card") && c.matches(":focus-visible")) SFX.hover(); });
// 1.4.7: posters are keyboard-focusable; Enter opens them like a click
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.classList || !e.target.classList.contains("card") || !e.target.dataset.href) return;
  e.preventDefault(); e.target.click();
});
// ---- 1.4: categories (genres, decades, ratings, tags) for a movie library; kept per library for the session
function catGet(id) { try { return Object.assign({ genres: [], decade: "", cert: "", tag: 0 }, JSON.parse(sessionStorage.getItem("cat" + id) || "{}")); } catch (e) { return { genres: [], decade: "", cert: "", tag: 0 }; } }
function catSet(id, c) { sessionStorage.setItem("cat" + id, JSON.stringify(c)); }
function catQuery(c) { return (c.genres.length ? "&genres=" + enc(c.genres.join("|")) : "") + (c.decade ? "&decade=" + c.decade : "") + (c.cert ? "&cert=" + enc(c.cert) : "") + (c.tag ? "&tag=" + c.tag : ""); }
function catActive(c) { return c.genres.length || c.decade || c.cert || c.tag; }
function openGenre(libId, genre) {
  if (!libId) return;
  catSet(libId, { genres: [genre], decade: "", cert: "", tag: 0 });
  sessionStorage.removeItem("filt" + libId); sessionStorage.removeItem("filter" + libId);
  if (location.hash === "#/library/" + libId) route(); else location.hash = "#/library/" + libId;
}
function catBar(id, d, c) {
  const f = d.facets || { genres: [], decades: [], certifications: [], tags: [] };
  const sel = new Set(c.genres);
  const gs = f.genres.filter(g => g.n || sel.has(g.name));
  c.genres.forEach(g => { if (!gs.find(x => x.name === g)) gs.unshift({ name: g, n: 0 }); });
  const opt = (v, label, cur) => `<option value="${esc(String(v))}"${String(v) === String(cur) ? " selected" : ""}>${label}</option>`;
  let html = `<div class="catbar"><div class="cat-chips" role="group" aria-label="Genres">${gs.length ? gs.map(g => `<button class="gchip${sel.has(g.name) ? " on" : ""}" data-g="${esc(g.name)}" aria-pressed="${sel.has(g.name)}">${esc(g.name)} <span>${nf(g.n)}</span></button>`).join("")
      : `<span class="help">${d.cat_pending ? "Genres appear here as categories are fetched from TMDB." : "No genres yet -- they come from TMDB matches."}</span>`}</div>
    <div class="cat-sel"><select id="cat-dec" title="Decade" aria-label="Decade">${opt("", "Any decade", c.decade)}${f.decades.map(x => opt(x.decade, x.decade + "s (" + nf(x.n) + ")", c.decade)).join("")}</select>
    ${f.certifications.length || c.cert ? `<select id="cat-cert" title="Age rating" aria-label="Age rating">${opt("", "Any rating", c.cert)}${f.certifications.map(x => opt(x.name, esc(x.name) + " (" + nf(x.n) + ")", c.cert)).join("")}</select>` : ""}
    ${f.tags.length || c.tag ? `<select id="cat-tag" title="Tag" aria-label="Tag">${opt(0, "Any tag", c.tag)}${f.tags.map(x => opt(x.id, esc(x.name) + " (" + nf(x.n) + ")", c.tag)).join("")}</select>` : ""}
    ${catActive(c) ? `<button class="btn ghost small" id="cat-clear">Clear</button>` : ""}</div></div>`;
  return html;
}
function bindCatBar(id) {
  const c = catGet(id), go = () => { catSet(id, c); route._keepScroll = true; route(); };
  $$(".catbar [data-g]").forEach(b => b.onclick = () => { const g = b.dataset.g; c.genres = c.genres.includes(g) ? c.genres.filter(x => x !== g) : c.genres.concat([g]); go(); });
  if ($("#cat-dec")) $("#cat-dec").onchange = () => { c.decade = $("#cat-dec").value; go(); };
  if ($("#cat-cert")) $("#cat-cert").onchange = () => { c.cert = $("#cat-cert").value; go(); };
  if ($("#cat-tag")) $("#cat-tag").onchange = () => { c.tag = +$("#cat-tag").value; go(); };
  if ($("#cat-clear")) $("#cat-clear").onclick = () => { catSet(id, {}); route._keepScroll = true; route(); };
}
function cardCollection(libId, c) {
  const yrs = c.year_from ? (c.year_to && c.year_to !== c.year_from ? c.year_from + "–" + c.year_to : c.year_from) : "";
  return `<div class="card coll" tabindex="0" data-href="#/library/${libId}/collection/${c.id}"><div class="art"${c.poster ? ` data-bg="${thumbUrl(c.poster)}"` : ""}>${c.poster ? "" : `<div class="ph">&#127902;</div>`}<span class="badge cnt" title="${c.n} movies in this library">${c.n}</span></div>
    <div class="t" title="${esc(c.name)}">${esc(c.name.replace(/ Collection$/, ""))}</div><div class="s">${c.n} movie${c.n === 1 ? "" : "s"}${yrs ? " · " + yrs : ""}</div></div>`;
}
const SMART = [["recommended", "Recommended"], ["released", "Recently released"], ["added", "Recently added"], ["top", "Top movies"]];
function libTabs(id, cur) {
  // 1.5.3: phones show the short label ("All", "Top") from data-s; the text itself is untouched so wide screens look the same
  const t = (href, key, label) => `<a href="${href}" class="${cur === key ? "on" : ""}"${/ movies$/.test(label) ? ` data-s="${label.replace(/ movies$/, "")}" aria-label="${label}"` : ""}>${label}</a>`;
  return `<div class="tabs libtabs">${t(`#/library/${id}`, "movies", "All movies")}${SMART.map(([k, n]) => t(`#/library/${id}/smart/${k}`, k, n)).join("")}${t(`#/library/${id}/collections`, "collections", "Collections")}</div>`;
}
// ---- 1.5.3: phone library toolbar (<= 820 px, browser and Android app), Plex-style. One compact header row (name + gray
// count, then search / filter / sort icons and an admin "..." menu with Select and Scan), the category tabs as one swipe row,
// a row of removable chips for the filters in use, and a bottom sheet with genres, decade, rating, tag, "show", sort and
// (music) the view. Wide screens never see any of it: the desktop toolbar above stays exactly as it was.
const MLI = {
  search: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M15.5 15.5L21 21" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>`,
  filter: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 5h17l-6.6 8v5.6l-3.8 1.9V13z" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linejoin="round"/></svg>`,
  sort: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.5 4.5v15m0 0L4 16m3.5 3.5L11 16M16.5 19.5v-15m0 0L13 8m3.5-3.5L20 8" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  more: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="2.1" fill="currentColor"/><circle cx="12" cy="12" r="2.1" fill="currentColor"/><circle cx="19" cy="12" r="2.1" fill="currentColor"/></svg>`,
  x: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></svg>`,
};
let ML = null;          // the library page on screen: what the sheet and the chips work on
const MLQ = {};         // search row left open per library (also while it is empty)
function mlSorts(kind, collId) {
  if (kind === "music") return [["title", "Title (A-Z)"], ["added", "Recently added"]];
  const s = collId ? [["title", "Release order"]] : [["poster", "Posters first"], ["title", "Title (A-Z)"]];
  s.push(["added", "Recently added"], ["year", "Year"]);
  if (kind === "movies") s.push(["rating", "TMDB score"]);
  return s;
}
function mlBadge(cat, filt) { return (cat ? cat.genres.length + (cat.decade ? 1 : 0) + (cat.cert ? 1 : 0) + (cat.tag ? 1 : 0) : 0) + (filt ? 1 : 0); }
function mlHead(o) {
  const open = !!(o.search && (o.q || MLQ[o.search + o.id]));
  const b = o.badge || 0;
  return `<div class="mlib" data-lib="${o.id}"><div class="mlib-row"><h2 class="mlib-t">${esc(o.name)}<span class="mlib-n" id="ml-count">${o.count}</span></h2><div class="mlib-acts">`
    + (o.search ? `<button class="ml-ico${open ? " on" : ""}" id="ml-search" type="button" aria-label="Search ${esc(o.name)}" aria-expanded="${open}">${MLI.search}</button>` : "")
    + (o.filter ? `<button class="ml-ico${b ? " on" : ""}" id="ml-filter" type="button" aria-haspopup="dialog" aria-label="Filters${b ? ", " + b + " on" : ""}">${MLI.filter}${b ? `<span class="ml-badge">${b}</span>` : ""}</button>` : "")
    + (o.sort ? `<button class="ml-ico" id="ml-sort" type="button" aria-haspopup="dialog" aria-label="Sort">${MLI.sort}</button>` : "")
    + (o.more ? `<button class="ml-ico" id="ml-more" type="button" aria-haspopup="menu" aria-expanded="false" aria-label="More">${MLI.more}</button>` : "")
    + `</div></div>`
    + (o.search ? `<div class="mlib-q"${open ? "" : " hidden"}>${MLI.search}<input type="search" id="ml-q" placeholder="Search ${esc(o.name)}" value="${esc(o.q || "")}" aria-label="Search ${esc(o.name)}" enterkeyhint="search"><button type="button" id="ml-qx" aria-label="Clear search"${o.q ? "" : " hidden"}>${MLI.x}</button></div>` : "")
    + `</div>`;
}
// o: {id, key: sessionStorage prefix of the search text ("filter" / "cfilter"), menu: [[label, fn]]}
function mlBind(o) {
  const s = $("#ml-search"), qw = $(".mlib-q"), qi = $("#ml-q");
  if (s && qi) {
    let ft;
    const push = (val) => {
      const had = document.activeElement === qi;
      sessionStorage.setItem(o.key + o.id, val); route._keepScroll = true;
      route().then(() => { const f = $("#ml-q"); if (f && had) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } });
    };
    s.onclick = () => {
      const open = qw.hidden; qw.hidden = !open; MLQ[o.key + o.id] = open; s.setAttribute("aria-expanded", open); s.classList.toggle("on", open);
      if (open) qi.focus(); else { clearTimeout(ft); qi.blur(); if (sessionStorage.getItem(o.key + o.id)) push(""); }
    };
    qi.oninput = () => { $("#ml-qx").hidden = !qi.value; clearTimeout(ft); ft = setTimeout(() => push(qi.value), 350); };
    qi.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); qi.blur(); } else if (e.key === "Escape") { e.preventDefault(); s.click(); s.focus(); } };
    $("#ml-qx").onclick = () => { clearTimeout(ft); qi.value = ""; $("#ml-qx").hidden = true; qi.focus(); if (sessionStorage.getItem(o.key + o.id)) push(""); };
  }
  if ($("#ml-filter")) $("#ml-filter").onclick = () => mlSheet("filter");
  if ($("#ml-sort")) $("#ml-sort").onclick = () => mlSheet("sort");
  if ($("#ml-more")) $("#ml-more").onclick = (e) => { e.stopPropagation(); mlMenu(typeof o.menu === "function" ? o.menu() : (o.menu || [])); };
  const t = $(".libtabs a.on");   // the swipe row: bring the current tab into view (Collections is at the far end)
  if (t && t.parentElement.scrollWidth > t.parentElement.clientWidth) {
    const row = t.parentElement, r = t.getBoundingClientRect(), rr = row.getBoundingClientRect();
    if (r.right > rr.right - 14) row.scrollLeft += r.right - rr.right + 14; else if (r.left < rr.left + 14) row.scrollLeft -= rr.left + 14 - r.left;
  }
  $$(".mlib-on [data-rm]").forEach(b => b.onclick = () => mlRemoveFilter(b.dataset.rm));
}
function mlMenu(items) {
  const btn = $("#ml-more"); let m = $("#ml-menu");
  if (m) { m.remove(); btn.setAttribute("aria-expanded", "false"); return; }
  closeSiblingPops("ml");
  m = document.createElement("div"); m.id = "ml-menu"; m.className = "ml-menu"; m.setAttribute("role", "menu");
  m.innerHTML = items.map((it, i) => `<button type="button" role="menuitem" data-i="${i}">${esc(it[0])}</button>`).join("");
  $(".mlib").appendChild(m); btn.setAttribute("aria-expanded", "true");
  const close = (focus) => { m.remove(); btn.setAttribute("aria-expanded", "false"); document.removeEventListener("click", out, true); document.removeEventListener("keydown", key, true); window.removeEventListener("hashchange", close); if (focus === true) btn.focus(); };
  const out = (e) => { if (!m.contains(e.target) && e.target.closest("#ml-more") !== btn) close(); };
  const key = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const bs = [...m.querySelectorAll("button")], i = bs.indexOf(document.activeElement); bs[(i + (e.key === "ArrowDown" ? 1 : bs.length - 1)) % bs.length].focus(); } };
  m.onclick = (e) => { const b = e.target.closest("[data-i]"); if (!b) return; close(); items[+b.dataset.i][1](); };
  setTimeout(() => { document.addEventListener("click", out, true); document.addEventListener("keydown", key, true); window.addEventListener("hashchange", close); }, 0);
  m.querySelector("button").focus();
}
// chips for the filters in use, each with an x; "Clear all" when there is more than one
function mlActive(id, cat, filt, q, facets, collId) {
  const ch = [];
  if (q) ch.push(["q", `&ldquo;${esc(q)}&rdquo;`]);
  if (filt) ch.push(["filt", { review: "Needs review", nomatch: "No TMDB match", edition: "Special editions" }[filt] || esc(filt)]);
  if (cat && !collId) {
    cat.genres.forEach(g => ch.push(["genre:" + g, esc(g)]));
    if (cat.decade) ch.push(["decade", esc(cat.decade) + "s"]);
    if (cat.cert) ch.push(["cert", "Rated " + esc(cat.cert)]);
    if (cat.tag) { const t = ((facets && facets.tags) || []).find(x => +x.id === +cat.tag); ch.push(["tag", "Tag: " + esc(t ? t.name : "#" + cat.tag)]); }
  }
  if (!ch.length) return "";
  return `<div class="mlib-on" role="group" aria-label="Filters in use">${ch.map(([k, l]) => `<button type="button" class="mchip on rm" data-rm="${esc(k)}" aria-label="Remove ${l.replace(/&[lr]dquo;/g, "")}">${l}${MLI.x}</button>`).join("")}${ch.length > 1 ? `<button type="button" class="mlib-clr" data-rm="*">Clear all</button>` : ""}</div>`;
}
function mlRemoveFilter(k) {
  if (!ML) return;
  const id = ML.id, c = catGet(id);
  if (k === "*") { catSet(id, {}); sessionStorage.removeItem("filt" + id); sessionStorage.removeItem("filter" + id); }
  else if (k === "q") sessionStorage.removeItem("filter" + id);
  else if (k === "filt") sessionStorage.removeItem("filt" + id);
  else if (k.startsWith("genre:")) { const g = k.slice(6); c.genres = c.genres.filter(x => x !== g); catSet(id, c); }
  else { c[k] = k === "tag" ? 0 : ""; catSet(id, c); }
  route._keepScroll = true; route();
}
// the bottom sheet: "filter" (everything, applied with Apply) or "sort" (just the sort list, a tap applies it)
function mlSheet(mode) {
  if (!ML || $("#mlsheet")) return;
  const M = ML, opener = document.activeElement;
  const def = { sort: M.defSort, filt: "", view: M.sub, cat: { genres: [], decade: "", cert: "", tag: 0 } };
  let st = { sort: M.sort, filt: M.filt, view: M.sub, cat: JSON.parse(JSON.stringify(M.cat)) };
  const f = (M.d && M.d.facets) || { genres: [], decades: [], certifications: [], tags: [] };
  const isMov = M.kind === "movies", withCat = isMov && !M.collId;
  const chip = (k, v, label, on, n) => `<button type="button" class="mchip${on ? " on" : ""}" data-k="${k}" data-v="${esc(String(v))}" aria-pressed="${on}">${label}${n != null ? ` <span class="n">${nf(n)}</span>` : ""}</button>`;
  const sec = (title, inner) => `<section class="mls-sec">${title ? `<h4>${title}</h4>` : ""}${inner}</section>`;
  const body = () => {
    let h = "";
    const sorts = mlSorts(M.kind, M.collId), cur = M.collId && st.sort === "poster" ? "title" : st.sort;
    if (mode === "sort") return sec("", `<div class="mls-list" role="radiogroup" aria-label="Sort by">${sorts.map(([v, l]) => `<button type="button" class="mls-opt${cur === v ? " on" : ""}" role="radio" aria-checked="${cur === v}" data-k="sort" data-v="${v}">${l}<span class="ck" aria-hidden="true">&#10003;</span></button>`).join("")}</div>`);
    if (M.kind === "music") h += sec("View", `<div class="mls-chips">${chip("view", "", "Albums", st.view === "")}${chip("view", "tracks", "Tracks", st.view === "tracks")}${chip("view", "playlists", "Playlists", st.view === "playlists")}</div>`);
    if (withCat) {
      const sel = new Set(st.cat.genres), gs = f.genres.filter(g => g.n || sel.has(g.name));
      st.cat.genres.forEach(g => { if (!gs.find(x => x.name === g)) gs.unshift({ name: g, n: 0 }); });
      h += sec("Genres", gs.length ? `<div class="mls-chips">${gs.map(g => chip("genre", g.name, esc(g.name), sel.has(g.name), g.n)).join("")}</div>`
        : `<p class="mls-note">${M.d.cat_pending ? "Genres appear here as categories are fetched from TMDB." : "No genres yet -- they come from TMDB matches."}</p>`);
      if (f.decades.length || st.cat.decade) h += sec("Decade", `<div class="mls-chips">${chip("decade", "", "Any", !st.cat.decade)}${f.decades.map(x => chip("decade", x.decade, x.decade + "s", String(st.cat.decade) === String(x.decade), x.n)).join("")}</div>`);
      if (f.certifications.length || st.cat.cert) h += sec("Rating", `<div class="mls-chips">${chip("cert", "", "Any", !st.cat.cert)}${f.certifications.map(x => chip("cert", x.name, esc(x.name), st.cat.cert === x.name, x.n)).join("")}</div>`);
      if (f.tags.length || st.cat.tag) h += sec("Tag", `<div class="mls-chips">${chip("tag", 0, "Any", !st.cat.tag)}${f.tags.map(x => chip("tag", x.id, esc(x.name), +st.cat.tag === +x.id, x.n)).join("")}</div>`);
    }
    if (isMov) {
      const mc = M.lib.meta_counts || {};
      h += sec("Show", `<div class="mls-chips">${chip("filt", "", "All movies", !st.filt)}${chip("filt", "review", "Needs review", st.filt === "review", mc.review || null)}${chip("filt", "nomatch", "No TMDB match", st.filt === "nomatch", mc.nomatch || null)}${chip("filt", "edition", "Special editions", st.filt === "edition")}</div>`);
    }
    h += sec("Sort by", `<div class="mls-chips" role="radiogroup" aria-label="Sort by">${sorts.map(([v, l]) => `<button type="button" class="mchip${cur === v ? " on" : ""}" role="radio" aria-checked="${cur === v}" data-k="sort" data-v="${v}">${l}</button>`).join("")}</div>`
      + (st.filt || (withCat && catActive(st.cat)) ? `<p class="mls-note">While a filter is on, the list is A&ndash;Z.</p>` : ""));
    return h;
  };
  const el = document.createElement("div"); el.id = "mlsheet"; el.className = "mls-wrap mls-" + mode;
  el.innerHTML = `<div class="mls-back"></div><div class="mls" role="dialog" aria-modal="true" aria-labelledby="mls-h"><div class="mls-top"><div class="mls-grip" aria-hidden="true"></div>
    <div class="mls-head"><h3 id="mls-h" tabindex="-1">${mode === "sort" ? "Sort by" : "Filters"}</h3><button type="button" class="ml-ico mls-x" aria-label="Close">${MLI.x}</button></div></div>
    <div class="mls-body">${body()}</div>
    ${mode === "filter" ? `<div class="mls-foot"><button type="button" class="btn ghost" id="mls-reset">Reset</button><button type="button" class="btn" id="mls-apply">Apply</button></div>` : ""}</div>`;
  document.body.appendChild(el); document.documentElement.classList.add("mls-on");
  MLS.el = el; MLS.after = null; MLS.opener = opener;
  try { history.pushState({ mlsheet: 1 }, "", location.href); MLS.pushed = true; } catch (e) { MLS.pushed = false; }
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("open")));
  setTimeout(() => { const h = el.querySelector("#mls-h"); if (h) h.focus({ preventScroll: true }); }, 30);
  const redraw = () => { const b = el.querySelector(".mls-body"), y = b.scrollTop; b.innerHTML = body(); b.scrollTop = y; };
  const apply = () => {
    const id = M.id;
    localStorage.setItem("sort" + id, st.sort);
    if (isMov) { if (st.filt) sessionStorage.setItem("filt" + id, st.filt); else sessionStorage.removeItem("filt" + id); if (withCat) catSet(id, st.cat); }
    mlClose(() => { if (M.kind === "music" && st.view !== M.sub) location.hash = `#/library/${id}${st.view ? "/" + st.view : ""}`; else route(); });
  };
  el.querySelector(".mls-body").onclick = (e) => {
    const b = e.target.closest("[data-k]"); if (!b) return;
    const k = b.dataset.k, v = b.dataset.v;
    if (k === "sort") { st.sort = v; if (mode === "sort") { apply(); return; } }
    else if (k === "filt") st.filt = v;
    else if (k === "view") st.view = v;
    else if (k === "genre") st.cat.genres = st.cat.genres.includes(v) ? st.cat.genres.filter(x => x !== v) : st.cat.genres.concat([v]);
    else if (k === "decade") st.cat.decade = v;
    else if (k === "cert") st.cat.cert = v;
    else if (k === "tag") st.cat.tag = +v;
    redraw();
  };
  el.querySelector(".mls-back").onclick = () => mlClose();
  el.querySelector(".mls-x").onclick = () => mlClose();
  if (mode === "filter") {
    el.querySelector("#mls-apply").onclick = apply;
    el.querySelector("#mls-reset").onclick = () => { st = JSON.parse(JSON.stringify(def)); st.view = M.sub; redraw(); };
  }
  // drag the handle (or the title row) down to close
  const top = el.querySelector(".mls-top"), sh = el.querySelector(".mls");
  let y0 = null, dy = 0;
  top.addEventListener("pointerdown", (e) => { if (e.target.closest("button")) return; y0 = e.clientY; dy = 0; sh.style.transition = "none"; try { top.setPointerCapture(e.pointerId); } catch (x) {} });
  top.addEventListener("pointermove", (e) => { if (y0 === null) return; dy = Math.max(0, e.clientY - y0); sh.style.transform = `translateY(${dy}px)`; });
  const end = () => { if (y0 === null) return; y0 = null; sh.style.transition = ""; if (dy > 90) mlClose(); else sh.style.transform = ""; };
  top.addEventListener("pointerup", end); top.addEventListener("pointercancel", end);
}
const MLS = { el: null, after: null, pushed: false, opener: null };
function mlClose(after) {
  if (!MLS.el) { if (after) after(); return; }
  MLS.after = after || null;
  if (MLS.pushed && history.state && history.state.mlsheet) history.back();   // popstate below finishes the close
  else mlDrop();
}
function mlDrop() {
  const el = MLS.el; if (!el) return;
  MLS.el = null; MLS.pushed = false; el.id = ""; el.classList.remove("open");
  document.documentElement.classList.remove("mls-on");
  setTimeout(() => el.remove(), 260);
  const a = MLS.after, o = MLS.opener; MLS.after = null;
  if (a) a(); else if (o && o.focus && document.contains(o)) o.focus({ preventScroll: true });
}
window.addEventListener("popstate", () => { if (MLS.el) mlDrop(); });   // phone / app Back closes the sheet
window.addEventListener("hashchange", () => { if (MLS.el) { MLS.after = null; mlDrop(); } });
document.addEventListener("keydown", (e) => {
  if (!MLS.el) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); mlClose(); }
  else if (e.key === "Tab") {   // keep the keyboard inside the sheet
    const fs = [...MLS.el.querySelectorAll("button,[tabindex='-1']")].filter(x => x.offsetParent !== null); if (!fs.length) return;
    const i = fs.indexOf(document.activeElement);
    if (e.shiftKey && i <= 0) { e.preventDefault(); fs[fs.length - 1].focus(); } else if (!e.shiftKey && (i === -1 || i === fs.length - 1)) { e.preventDefault(); fs[0].focus(); }
  }
}, true);

async function viewSmart(id, key) {
  const d = await api(`/api/libraries/${id}/smart/${key}?limit=200`);
  const lib = d.library;
  ML = null;
  let html = mlHead({ id, name: lib.name, count: nf(Math.min(d.total, 200)) }) + `<div class="row-head lib-head"><h2>${KIND_ICON[lib.kind] || ""} ${esc(lib.name)} <span class="muted" style="font-size:14px;font-weight:400">${esc(d.title)} · ${nf(Math.min(d.total, 200))}${d.total > 200 ? " of " + nf(d.total) : ""}</span></h2></div>${libTabs(id, key)}`;
  if (d.note) html += `<div class="help" style="margin:-2px 0 14px">${esc(d.note)}${ME.is_admin && (key === "recommended" || key === "top") ? ". Admins can pin or hide a movie from its page (Home rows)." : ""}</div>`;
  html += d.items.length ? `<div class="grid">${d.items.map(i => cardItem(i, { reason: key === "recommended" })).join("")}</div>`
    : `<div class="empty">${key === "released" ? "No release dates yet -- they come from TMDB matches." : key === "top" ? "No movies with enough TMDB votes yet." : "Nothing here yet."}</div>`;
  $("#view").innerHTML = html;
  mlBind({ id, key: "" });
}
async function viewCollections(id) {
  const q = sessionStorage.getItem("cfilter" + id) || "";
  const [d, L] = await Promise.all([api(`/api/libraries/${id}/collections?q=${enc(q)}`), api(`/api/libraries/${id}/items?limit=1`)]);
  const lib = L.library;
  ML = null;
  let html = mlHead({ id, name: lib.name, count: nf(d.collections.length), search: "cfilter", q }) + `<div class="row-head lib-head"><h2>${KIND_ICON[lib.kind] || ""} ${esc(lib.name)} <span class="muted" style="font-size:14px;font-weight:400">${nf(d.collections.length)} collections</span></h2>
    <div class="tools"><input type="search" id="collfilter" placeholder="Filter collections..." value="${esc(q)}" style="width:200px"></div></div>${libTabs(id, "collections")}`;
  if (d.pending) html += `<div class="help" style="margin-bottom:12px">${nf(d.pending)} movies still need their details from TMDB; more collections appear as they arrive.</div>`;
  html += d.collections.length ? `<div class="grid">${d.collections.map(c => cardCollection(id, c)).join("")}</div>`
    : `<div class="empty">No collections${q ? " match that filter" : " yet"}. Movies that belong to a TMDB collection (for example <i>The Matrix Collection</i>) are grouped here.</div>`;
  $("#view").innerHTML = html;
  mlBind({ id, key: "cfilter" });
  let ft; $("#collfilter").oninput = () => { clearTimeout(ft); ft = setTimeout(() => { sessionStorage.setItem("cfilter" + id, $("#collfilter").value); route._keepScroll = true; route().then(() => { const f = $("#collfilter"); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }); }, 350); };
  if (d.pending) { const tok = route._token; route._live = { every: 15000, fn: () => { if (tok === route._token && !$("#collfilter:focus") && !$("#ml-q:focus")) { route._keepScroll = true; route(); } } }; }
}
// bulk tagging (admin): select movies in the grid, then add or remove a tag
const SEL = { on: false, ids: new Set(), lib: 0 };
function selBar() {
  let b = $("#selbar");
  if (!SEL.on) { if (b) b.remove(); return; }
  if (!b) { b = document.createElement("div"); b.id = "selbar"; b.className = "selbar"; document.body.appendChild(b); }
  const n = SEL.ids.size;
  b.innerHTML = `<b>${nf(n)} selected</b><button class="btn ghost small" id="sel-all">Select all shown</button><button class="btn ghost small" id="sel-none"${n ? "" : " disabled"}>Clear</button>
    <span class="sep"></span><input type="text" id="sel-tag" list="sel-tags" placeholder="Tag name, e.g. Kids" aria-label="Tag name"><datalist id="sel-tags"></datalist>
    <button class="btn small" id="sel-add"${n ? "" : " disabled"}>Add tag</button><button class="btn ghost small" id="sel-rem"${n ? "" : " disabled"}>Remove tag</button>
    <span class="sep"></span><button class="btn ghost small" id="sel-done">Done</button>`;
  api("/api/tags").then(ts => { const dl = $("#sel-tags"); if (dl) dl.innerHTML = ts.map(t => `<option value="${esc(t.name)}">`).join(""); SEL.tags = ts; }).catch(() => {});
  $("#sel-all").onclick = () => { $$("#lib-body .card[data-id]").forEach(c => SEL.ids.add(+c.dataset.id)); markSel(); selBar(); };
  $("#sel-none").onclick = () => { SEL.ids.clear(); markSel(); selBar(); };
  $("#sel-done").onclick = () => { SEL.on = false; SEL.ids.clear(); selBar(); route._keepScroll = true; route(); };
  const run = async (add) => {
    const name = $("#sel-tag").value.trim();
    if (!name) { toast("Type a tag name first", true); $("#sel-tag").focus(); return; }
    let body = { item_ids: [...SEL.ids] };
    if (add) body.add = [name];
    else { const t = (SEL.tags || []).find(x => x.name.toLowerCase() === name.toLowerCase()); if (!t) { toast("No tag called " + name, true); return; } body.remove = [t.id]; }
    try { await api("/api/tags/apply", { method: "POST", body }); toast(`${add ? "Added" : "Removed"} “${name}” ${add ? "to" : "from"} ${nf(SEL.ids.size)} movie${SEL.ids.size === 1 ? "" : "s"}`); SEL.ids.clear(); selBar(); route._keepScroll = true; route(); }
    catch (e) { toast(e.message, true); }
  };
  $("#sel-add").onclick = () => run(true); $("#sel-rem").onclick = () => run(false);
  $("#sel-tag").onkeydown = (e) => { if (e.key === "Enter") run(true); };
}
function markSel() { $$("#lib-body .card[data-id]").forEach(c => c.classList.toggle("sel", SEL.ids.has(+c.dataset.id))); document.body.classList.toggle("selecting", SEL.on); }
document.addEventListener("click", (e) => {
  if (!SEL.on) return;
  const c = e.target.closest("#lib-body .card[data-id]");
  if (!c) return;
  e.stopPropagation(); e.preventDefault();
  const i = +c.dataset.id; if (SEL.ids.has(i)) SEL.ids.delete(i); else SEL.ids.add(i);
  markSel(); selBar();
}, true);
window.addEventListener("hashchange", () => { if (SEL.on && !location.hash.startsWith("#/library/" + SEL.lib)) { SEL.on = false; SEL.ids.clear(); selBar(); markSel(); } });

// ---------------------------------------------------------------- views
async function viewHome(live) {
  const v = $("#view");
  const d = await api("/api/home");
  if (live && live !== route._token) return;   // navigated away while loading
  let html = "";
  if (!LIBS.length) {
    html = `<div class="empty"><h2>Welcome!</h2>Add your first library -- a folder on this server or a network share (SMB / NFS).<br><br>
      ${ME.is_admin ? `<button class="btn" id="addlib0">Add a library</button>` : "Ask an administrator to add a library."}</div>`;
    v.innerHTML = html; if ($("#addlib0")) $("#addlib0").onclick = () => addLibraryDialog(); return;
  }
  // 1.4.1: Continue watching first (only when something is part-watched); click resumes where you stopped
  if (d.continue.length) html += rowHead("Continue watching") + `<div class="strip hs cw">${d.continue.map(i => cardItem(i, { resume: true })).join("")}</div>`;
  if (OFF.on()) {   // 2.0: the Downloads tab took My List's place, so My List's recently watched films get a home row
    try { const ml = await api("/api/mylist"); if (window.TV && TV.ingest) TV.ingest({ continue: ml.continue || [], libraries: [], watched: ml.watched || [] }); if (ml.watched.length) html += rowHead("My List", "#/mylist", { sub: "Recently watched" }) + `<div class="strip hs">${ml.watched.slice(0, 20).map(i => cardItem(i)).join("")}</div>`; } catch (e) { /* row is optional */ }
  }
  const nMovieLibs = d.libraries.filter(L => L.library.kind === "movies").length;
  for (const L of d.libraries) {
    const lib = L.library;
    if (L.smart_rows) {   // 1.4.1: Recommended, Recently released, Recently added, Top movies
      for (const R of L.smart_rows) {
        if (!R.items.length && R.key !== "added") continue;
        const mir = (lib.mirrors || []).length && R === L.smart_rows.find(x => x.items.length || x.key === "added") ? ` <span class="muted d-only mirror-note" style="font-size:13px;font-weight:400" title="These libraries hold the same films; each film is shown once">&middot; same films as ${esc(lib.mirrors.join(", "))}</span>` : "";
        html += rowHead(esc(R.title), `#/library/${lib.id}/smart/${R.key}`, { sub: esc(lib.name), extra: (nMovieLibs > 1 || mir ? ` <span class="muted d-only" style="font-size:14px;font-weight:400">in ${esc(lib.name)}</span>` : "") + mir });
        if (R.key === "recommended" && R.note) html += `<div class="help row-note">${esc(R.note)}</div>`;
        html += R.items.length ? `<div class="strip hs">${R.items.map(i => cardItem(i, { reason: R.key === "recommended" })).join("")}</div>` : `<div class="empty">Nothing here yet -- scanning may still be running.</div>`;
      }
    } else html += rowHead(`Recently added in ${esc(lib.name)}`, `#/library/${lib.id}`, { sub: nf(lib.item_count || 0) + " items", extra: (lib.mirrors || []).length ? ` <span class="muted d-only mirror-note" style="font-size:13px;font-weight:400" title="These libraries hold the same shows; each is shown once">&middot; same shows as ${esc(lib.mirrors.join(", "))}</span>` : "" });
    if (L.smart_rows) { /* rows above */ }
    else if (L.albums) html += L.albums.length ? `<div class="strip hs">${L.albums.map(a => cardAlbum(lib.id, a)).join("")}</div>` : `<div class="empty">Nothing here yet</div>`;
    else if (lib.kind === "tv") html += L.items.length ? `<div class="strip hs">${L.items.map(i => cardItem(i)).join("")}</div>` : `<div class="empty">Nothing here yet</div>`;
    else html += L.items.length ? `<div class="strip hs">${L.items.map(i => cardItem(i)).join("")}</div>` : `<div class="empty">Nothing here yet -- scanning may still be running.</div>`;
    for (const G of (L.genre_rows || [])) {   // 1.4: the library's biggest genres
      if (!G.items.length) continue;
      html += rowHead(esc(G.genre), `#/library/${lib.id}`, { attrs: ` data-genre="${esc(G.genre)}" data-lib="${lib.id}"`, extra: ` <span class="muted d-only" style="font-size:14px;font-weight:400">${nf(G.count)}</span>`, sub: `${esc(lib.name)} · ${nf(G.count)} movies` }) + `
        <div class="strip hs">${G.items.map(i => cardItem(i)).join("")}</div>`;
    }
  }
  // 1.5.5: the home page shows Movies and TV Shows only; say where everything else is when that leaves it empty
  if (!html) html = `<div class="empty">Movies and TV shows appear here. Your other libraries are under <a href="#/libraries">Libraries</a>.</div>`;
  if (live) {
    if (viewHome._last === html) return;
    const xs = $$(".strip", v).map(e => e.scrollLeft), top = v.scrollTop;
    v.innerHTML = html; $$(".strip", v).forEach((e, i) => { if (xs[i]) e.scrollLeft = xs[i]; }); v.scrollTop = top;
  } else v.innerHTML = html;
  viewHome._last = html;
  const tok = route._token;
  route._live = { every: 5000, fn: () => viewHome(tok) };
}

async function viewLibrary(id, sub, collId) {
  const v = $("#view");
  const L0 = LIBS.find(l => l.id === id);
  const defSort = L0 && L0.kind === "music" ? "title" : "poster";   // 1.2.1: artwork first by default
  let sort = localStorage.getItem("sort" + id) || defSort;
  if (L0 && L0.kind === "music" && sort === "poster") sort = "title";
  const q = sessionStorage.getItem("filter" + id) || "";
  const filt = sessionStorage.getItem("filt" + id) || "";
  const isMov = L0 && L0.kind === "movies";
  const cat = catGet(id);
  const fq = (filt ? "&filter=" + filt : "") + (isMov ? (collId ? "&collection=" + collId : catQuery(cat)) + "&facets=1" : "");
  const d = await api(`/api/libraries/${id}/items?sort=${sort}&q=${enc(q)}&limit=5000${sub ? "&view=" + sub : ""}${fq}`);
  const lib = d.library;
  d.cat_pending = lib.meta_counts && lib.meta_counts.pending;
  d.cat_note = isMov && !collId && catActive(cat) ? cat.genres : null;
  const scanning = lib.scan && (lib.scan.state === "scanning" || lib.scan.state === "queued");
  const mlCount = (d1) => {   // phone header: what is in the list ("12 of 58" while filtered)
    if (d1.view === "shows") return nf((d1.shows || []).length);
    if (d1.view === "albums") return nf((d1.albums || []).length);
    const n = d1.total != null ? d1.total : (d1.items || []).length;
    const all = d1.library.film_count != null ? d1.library.film_count : d1.library.item_count;   // 1.7: films, not files
    return !collId && lib.kind !== "music" && (q || filt || (isMov && catActive(cat))) ? nf(n) + " of " + nf(all) : nf(collId || lib.kind === "music" ? n : all);
  };
  ML = { id, kind: lib.kind, sub, collId, sort: collId && sort === "poster" ? "title" : sort, defSort, filt, cat, d, lib };
  const mlMore = () => {   // admin "..." menu: the same Select / Scan buttons as the desktop toolbar
    const m = [];
    if (ME.is_admin && lib.kind === "movies") m.push([SEL.on ? "Done selecting" : "Select movies to tag", () => { const b = $("#libselect"); if (b) b.click(); }]);
    if (ME.is_admin) m.push([scanning ? "Scanning..." : "Scan library for new files", () => { const b = $("#libscan"); if (b) b.click(); }]);
    return m;
  };
  let html = mlHead({ id, name: lib.name, count: mlCount(d), search: "filter", q, filter: isMov || lib.kind === "music", badge: isMov ? mlBadge(collId ? null : cat, filt) : 0, sort: true, more: ME.is_admin })
    + `<div class="row-head lib-head"><h2>${KIND_ICON[lib.kind] || ""} ${esc(lib.name)} <span class="muted" style="font-size:14px;font-weight:400" id="lib-count"${libCountTitle(lib)}>${libCountText(lib)}</span></h2>
    <div class="tools"><input type="search" id="libfilter" placeholder="Filter..." value="${esc(q)}" style="width:180px">
    <select id="libsort" title="Sort">${lib.kind !== "music" ? `<option value="poster">${collId ? "Release order" : "Posters first"}</option>` : ""}<option value="title">${collId ? "Release order" : "Title (A-Z)"}</option><option value="added">Recently added</option>${lib.kind !== "music" ? `<option value="year">Year</option>` : ""}${lib.kind === "movies" ? `<option value="rating">TMDB score</option>` : ""}</select>
    ${lib.kind === "movies" ? `<select id="libfilt" title="Show"><option value="">All movies</option><option value="review">Needs review${lib.meta_counts && lib.meta_counts.review ? " (" + nf(lib.meta_counts.review) + ")" : ""}</option><option value="nomatch">No TMDB match${lib.meta_counts && lib.meta_counts.nomatch ? " (" + nf(lib.meta_counts.nomatch) + ")" : ""}</option><option value="edition">Special editions</option></select>` : ""}
    ${lib.kind === "music" ? `<select id="libview"><option value="">Albums</option><option value="tracks">Tracks</option><option value="playlists">Playlists</option></select>` : ""}
    ${ME.is_admin && lib.kind === "movies" ? `<button class="btn ghost small${SEL.on ? " on" : ""}" id="libselect" title="Select movies to tag them">${SEL.on ? "Selecting" : "Select"}</button>` : ""}
    ${ME.is_admin ? `<button class="btn ghost small" id="libscan">${scanning ? "Scanning..." : "Scan"}</button>` : ""}</div></div>`;
  if (lib.kind === "movies") {
    if (collId) {
      const C = d.collection || {};
      html += `<div class="coll-head">${C.poster ? `<div class="cp" style="background-image:url('${thumbUrl(C.poster)}')"></div>` : ""}<div><a class="muted" href="#/library/${id}/collections">&lsaquo; All collections</a>
        <h2>${esc(C.name || "Collection")}</h2><div class="muted">${nf(d.total || 0)} movie${d.total === 1 ? "" : "s"} in this library</div></div></div>`;
    } else html += libTabs(id, "movies") + catBar(id, d, cat);
  }
  html += mlActive(id, isMov ? cat : null, filt, q, d.facets, collId);
  if (!lib.online) html += `<div class="empty" style="margin-bottom:16px">&#9888; The library folder is not reachable right now: ${esc(lib.path)}${lib.share ? " (share " + esc(lib.share.remote) + ")" : ""}</div>`;
  if (collId && sort === "poster") sort = "title";
  let lastBody = libBody(id, lib, d, scanning, filt || (isMov && catActive(cat)) ? "title" : sort, filt);
  html += `<div id="lib-scan-line" data-lib="${id}"></div><div id="lib-body">${lastBody}</div>`;
  v.innerHTML = html;
  if (ACT.d) renderLibScanLine($("#lib-scan-line"), ACT.d.scans.find(x => x.library_id === id), ACT.d.metadata.find(x => x.library_id === id));
  else if (scanning) renderLibScanLine($("#lib-scan-line"), lib.scan, null);
  const url = `/api/libraries/${id}/items?sort=${sort}&q=${enc(q)}&limit=5000${sub ? "&view=" + sub : ""}${fq}`;
  const bodySort = filt || (isMov && catActive(cat)) ? "title" : sort;
  const tok = route._token;
  let lastKey = "";
  const liveKey = (a) => { const s1 = a && a.scans.find(x => x.library_id === id), m1 = a && a.metadata.find(x => x.library_id === id);
    return JSON.stringify([s1 && [s1.state, s1.done, s1.removed], m1 && [m1.state, m1.matched, m1.done]]); };
  lastKey = liveKey(ACT.d);
  route._live = { every: Math.max(4000, lib.item_count * 3), fn: async (a) => {
    const k = liveKey(a); if (k === lastKey) return; lastKey = k;   // nothing new for this library
    const d2 = await api(url);
    if (tok !== route._token || !$("#lib-body")) return;
    d2.cat_pending = d2.library.meta_counts && d2.library.meta_counts.pending;
    d2.cat_note = isMov && !collId && catActive(cat) ? cat.genres : null;
    const body = libBody(id, d2.library, d2, true, bodySort, filt);
    if (lastBody !== body) { lastBody = body; const top = $("#view").scrollTop; $("#lib-body").innerHTML = body; $("#view").scrollTop = top; if (d2.view === "items" && d2.library.kind === "music") bindTrackList(d2.items); markSel(); }
    if (isMov && !collId && $(".catbar") && !$(".catbar select:focus")) { const cb = catBar(id, d2, cat); if ($(".catbar").outerHTML !== cb) { $(".catbar").outerHTML = cb; bindCatBar(id); } }
    $("#lib-count").textContent = libCountText(d2.library);
    if (ML && ML.id === id) { ML.d = d2; ML.lib = d2.library; }
    if ($("#ml-count")) $("#ml-count").textContent = mlCount(d2);
  } };
  bindLibTools(id, sub, sort, d, lib);
  if (isMov && !collId) bindCatBar(id);
  if ($("#libselect")) $("#libselect").onclick = () => { SEL.on = !SEL.on; SEL.lib = id; SEL.ids.clear(); $("#libselect").classList.toggle("on", SEL.on); $("#libselect").textContent = SEL.on ? "Selecting" : "Select"; markSel(); selBar(); };
  if (SEL.on && SEL.lib === id) { markSel(); selBar(); } else if (SEL.on) { SEL.on = false; SEL.ids.clear(); selBar(); }
  mlBind({ id, key: "filter", menu: mlMore });
}
function libBody(id, lib, d, scanning, sort, filt) {
  let html = "";
  if (d.cat_note) html += `<div class="help cat-note" style="margin:-4px 0 12px">${nf(d.total || 0)} movie${d.total === 1 ? "" : "s"}${d.cat_note.length > 1 ? " with all of: " + esc(d.cat_note.join(", ")) : ""}.</div>`;
  if (filt) html += `<div class="help" style="margin:-4px 0 12px">${filt === "review" ? "Matches the automatic matcher was not sure about (low confidence, a year far from the file name's, or only a same-title suggestion). Open one and use <b>Fix match</b> or <b>Accept</b>." : filt === "nomatch" ? "No TMDB match was found for these. Open one and use <b>Fix match</b>." : "Movies with an edition in the file name (Director's Cut, Extended...)."} ${nf((d.items || []).length)} shown.</div>`;
  if (d.view === "shows") {
    html += d.shows.length ? `<div class="grid">${d.shows.map(s => cardShow(id, s)).join("")}</div>` : `<div class="empty">No shows found${scanning ? " yet" : ""}.</div>`;
    if (d.items.length) html += `<h3>Other videos</h3><div class="grid wide">${d.items.map(i => cardItem(i, { landscape: true })).join("")}</div>`;
  } else if (d.view === "albums") {
    html += d.albums.length ? `<div class="grid">${d.albums.map(a => cardAlbum(id, a)).join("")}</div>` : `<div class="empty">No music found${scanning ? " yet" : ""}.</div>`;
  } else if (lib.kind === "music") {
    html += trackList(d.items, true);
  } else {
    const grid = (xs) => `<div class="grid ${lib.kind === "other" ? "wide" : ""}">${xs.map(i => cardItem(i, { landscape: lib.kind === "other" })).join("")}</div>`;
    if (!d.items.length) html += `<div class="empty">No videos found${scanning ? " yet" : ""}.</div>`;
    else if (sort === "poster" && lib.kind === "movies") {
      // 1.2.1: titles with real artwork first; the rest move up live as TMDB finds their posters
      const withArt = d.items.filter(i => i.has_art), rest = d.items.filter(i => !i.has_art);
      if (withArt.length) html += grid(withArt);
      if (rest.length) {
        const m = lib.meta, busy = m && (m.state === "running" || m.state === "queued");
        html += `<div class="row-head art-split"><h3>${withArt.length ? "Without a poster yet" : "No posters yet"} <span class="muted" style="font-size:14px;font-weight:400">${nf(rest.length)}</span></h3>
          <span class="muted">${busy ? "Looking them up on TMDB &mdash; they move up as posters arrive" : (lib.meta_counts && lib.meta_counts.pending ? nf(lib.meta_counts.pending) + " not looked up yet" : "")}</span></div>`;
        html += grid(rest);
      }
    } else html += grid(d.items);
  }
  return html;
}
function bindLibTools(id, sub, sort, d, lib) {
  $("#libsort").value = sort;
  $("#libsort").onchange = () => { localStorage.setItem("sort" + id, $("#libsort").value); route(); };
  if ($("#libfilt")) { $("#libfilt").value = sessionStorage.getItem("filt" + id) || ""; $("#libfilt").onchange = () => { sessionStorage.setItem("filt" + id, $("#libfilt").value); route(); }; }
  if ($("#libview")) { $("#libview").value = sub; $("#libview").onchange = () => { location.hash = `#/library/${id}/${$("#libview").value}`; }; }
  let ft; $("#libfilter").oninput = () => { clearTimeout(ft); ft = setTimeout(() => { sessionStorage.setItem("filter" + id, $("#libfilter").value); route._keepScroll = true; route().then(() => { const f = $("#libfilter"); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }); }, 350); };
  if ($("#libscan")) $("#libscan").onclick = async () => { await api(`/api/libraries/${id}/scan`, { method: "POST" }); toast("Scan started"); pollActivity(); route._keepScroll = true; route(); };
  if (d.view === "items" && lib.kind === "music") bindTrackList(d.items);
}

function trackList(tracks, showAlbum) {
  if (!tracks.length) return `<div class="empty">No tracks.</div>`;
  const plus = ico(`<path d="M12 6.5v11M6.5 12h11"/>`);
  return `<div class="list">${tracks.map((t, n) => `<div class="li" data-track="${n}" data-item="${t.id}">
    <div class="num">${t.track || n + 1}</div><div class="ttl"><div>${esc(t.title)}</div><div class="muted" style="font-size:12.5px">${esc(t.artist || "")}${showAlbum && t.album ? " · " + esc(t.album) : ""}</div></div>
    <div class="dur">${fmtDur(t.duration)}</div>
    <button type="button" class="iconbtn ab-tool tadd" data-add-pl="${t.id}" title="Add to playlist" aria-label="Add to playlist">${plus}</button></div>`).join("")}</div>`;
}
function bindTrackList(tracks, root) {
  const scope = root || document;
  $$(scope === document ? ".list [data-track], .pli-row .li[data-track]" : "[data-track]", scope).forEach(el => {
    if (el.matches && el.matches(".pli-row")) return; // play from the title row, not the chrome
    el.onclick = (e) => {
      if (e.target.closest("[data-add-pl], .pli-handle, .pli-move, [data-rm]")) return;
      if (el.dataset.suppressClick) { delete el.dataset.suppressClick; return; }
      playQueue(tracks, +el.dataset.track);
    };
    let hold;
    const start = (e) => {
      if (e.target.closest("[data-add-pl]")) return;
      clearTimeout(hold);
      hold = setTimeout(() => {
        el.dataset.suppressClick = "1";
        const id = +el.dataset.item || (tracks[+el.dataset.track] && tracks[+el.dataset.track].id);
        if (id) openPlaylistSheet([id]);
      }, 500);
    };
    const cancel = () => clearTimeout(hold);
    el.addEventListener("pointerdown", start);
    el.addEventListener("pointerup", cancel);
    el.addEventListener("pointercancel", cancel);
    el.addEventListener("pointerleave", cancel);
  });
  $$("[data-add-pl]").forEach(b => b.onclick = (e) => { e.stopPropagation(); openPlaylistSheet([+b.dataset.addPl]); });
}

async function viewShow(libId, show) {
  const d = await api(`/api/show?library_id=${libId}&show=${enc(show)}`);
  const cur = +(sessionStorage.getItem("season:" + libId + show) || d.seasons[0].season);
  const season = d.seasons.find(s => s.season === cur) || d.seasons[0];
  const total = d.seasons.reduce((a, s) => a + s.episodes.length, 0);
  const tm = d.tmdb || {};
  const showBg = tm.backdrop || d.poster;
  let html = `${showBg ? `<div class="detail-bg detail-bg-phone" aria-hidden="true"><div class="dbg-img" style="background-image:url('${thumbUrl(showBg)}')"></div></div>` : ""}<div class="hero"${heroStyle(tm.backdrop)}></div><div class="detail"><div class="poster" style="${d.poster ? `background-image:url('${thumbUrl(d.poster)}')` : ""}"></div><div class="info">
    <h1>${esc(tm.title || d.show)}</h1><div class="meta">${d.year ? `<span>${d.year}</span>` : ""}<span>${d.seasons.length} season${d.seasons.length > 1 ? "s" : ""}</span><span>${total} episodes</span></div>
    ${metaChips(tm)}${tm.overview ? `<p class="overview">${esc(tm.overview)}</p>` : ""}
    <div class="actions"><button class="btn" id="playnext">&#9654; ${d.next.position ? "Resume" : "Play"} ${epCode(d.next)}</button>
      ${ME.is_admin ? `<button class="btn ghost" id="fixmatch">Fix match</button>` : ""}
      ${ME.is_admin ? `<button class="btn ghost" id="showart" title="Save posters, season posters, fanart and episode thumbnails into the show's folder">Artwork</button>` : ""}
      ${tm.url ? `<a class="btn ghost" href="${esc(tm.url)}" target="_blank" rel="noopener">TMDB &#8599;</a>` : ""}</div>
    ${tm.id && tm.title && tm.title !== d.show ? `<div class="help" style="margin-bottom:6px">Folder name: ${esc(d.show)}</div>` : ""}
    <div class="tabs">${d.seasons.map(s => `<button data-season="${s.season}" class="${s.season === season.season ? "on" : ""}">${s.season === 0 ? "Specials" : "Season " + s.season}</button>`).join("")}</div>
    <div class="list">${season.episodes.map(e => {
      const pct = e.position && e.duration ? 100 * e.position / e.duration : 0;
      return `<div class="li" data-href="#/item/${e.id}"><div class="thumb" style="${e.thumb ? `background-image:url('${thumbUrl(e.thumb)}')` : ""}">${pct ? `<div class="bar" style="width:${pct}%"></div>` : ""}</div>
        <div class="ttl"><div><b>${e.episode != null ? e.episode + ". " : ""}</b>${esc(e.title)}</div><div class="muted" style="font-size:12.5px">${fmtLen(e.duration)} ${e.watched ? `<span class="w">&#10003; watched</span>` : ""}</div></div>
        <button class="iconbtn" data-play="${e.id}" title="Play">&#9654;</button></div>`; }).join("")}</div></div></div>`;
  $("#view").innerHTML = html;
  $("#playnext").onclick = () => playItem(d.next.id);
  if ($("#fixmatch")) $("#fixmatch").onclick = () => {
    if (!d.tmdb_enabled) { toast("Add a TMDB API key in Settings -> Metadata first", true); return; }
    fixMatchDialog("tv", d.show.replace(/\s*\((19|20)\d\d\)\s*$/, ""), null, (b) => api("/api/show/match", { method: "POST", body: { library_id: libId, show, ...b } }));
  };
  $$("[data-season]").forEach(b => b.onclick = () => { sessionStorage.setItem("season:" + libId + show, b.dataset.season); route._keepScroll = true; route(); });
  // 1.5.5: artwork for TV shows (same dialog as the library's Artwork button, plus "Write for this show")
  if ($("#showart")) $("#showart").onclick = async () => {
    try { const libs = await api("/api/libraries"); const l = libs.find(x => x.id === +libId); if (l) artworkDialog(l, { show }); }
    catch (e) { toast(e.message, true); }
  };
  setDetailTop(showBg ? thumbUrl(showBg) : null);
}

async function viewAlbum(libId, artist, album) {
  const d = await api(`/api/album?library_id=${libId}&artist=${enc(artist)}&album=${enc(album)}`);
  $("#view").innerHTML = `<div class="detail"><div class="poster square" style="${d.poster ? `background-image:url('${thumbUrl(d.poster)}')` : ""}"></div><div class="info">
    <h1>${esc(d.album)}</h1><div class="meta"><span>${esc(d.artist)}</span>${d.year ? `<span>${d.year}</span>` : ""}<span>${d.tracks.length} tracks</span><span>${fmtLen(d.duration)}</span></div>
    <div class="actions"><button class="btn" id="playall">&#9654; Play album</button><button class="btn ghost" id="shuffle">&#8644; Shuffle</button></div>
    ${trackList(d.tracks, false)}</div></div>`;
  bindTrackList(d.tracks);
  $("#playall").onclick = () => playQueue(d.tracks, 0);
  $("#shuffle").onclick = () => playQueue(shuffled(d.tracks), 0);
}
function shuffled(list) {
  const t = (list || []).slice();
  for (let i = t.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [t[i], t[j]] = [t[j], t[i]]; }
  return t;
}
const LOGO_MARK = "/static/logo-mark.png";
function playlistArt(poster, cls) {
  const logo = poster ? "" : " logo";
  const src = poster ? thumbUrl(poster) : LOGO_MARK;
  return `<div class="${cls || "pli-art"}${logo}"><img src="${src}" alt=""></div>`;
}
const ICO_PLAY = ico(`<path d="M8 5.5v13l11-6.5z" fill="currentColor" stroke="none"/>`);
const ICO_SHUFFLE = ico(`<path d="M4.5 7.5h3.4l8.2 9h3.4"/><path d="M16.3 5.8l3.2 1.7-3.2 1.7"/><path d="M16.3 14.8l3.2 1.7-3.2 1.7"/><path d="M4.5 16.5h3.4l2.2-2.4"/><path d="M15.9 9.9l-2.2-2.4"/>`);
function playlistCard(libId, p) {
  const n = p.track_count || 0;
  return `<div class="pli-card-wrap">
    <a class="pli-card" href="#/library/${libId}/playlist/${p.id}">
      ${playlistArt(p.poster)}
      <div class="pli-meta"><b>${esc(p.name)}</b><div class="muted">${n} track${n === 1 ? "" : "s"}${p.duration ? " · " + fmtLen(p.duration) : ""}</div></div>
    </a>
    <div class="pli-card-actions">
      <button type="button" class="btn" data-pl-play="${p.id}"${n ? "" : " disabled"}>${ICO_PLAY} Play</button>
      <button type="button" class="btn ghost" data-pl-shuffle="${p.id}"${n ? "" : " disabled"}>${ICO_SHUFFLE} Shuffle</button>
    </div>
  </div>`;
}
async function playPlaylist(pid, shuffle, start) {
  const d = await api("/api/playlists/" + pid);
  const tracks = d.tracks || [];
  if (!tracks.length) { toast("This playlist is empty", true); return; }
  const idx = start == null ? 0 : Math.max(0, Math.min(start, tracks.length - 1));
  playQueue(shuffle ? shuffled(tracks) : tracks, shuffle ? 0 : idx);
}
async function viewPlaylists(libId) {
  const lib = LIBS.find(l => l.id === libId) || { id: libId, name: "Music", kind: "music" };
  const rows = await api("/api/playlists");
  ML = { id: libId, kind: "music", sub: "playlists", sort: "title", defSort: "title", filt: "", cat: { genres: [], decade: "", cert: "", tag: 0 }, d: { facets: {} }, lib, collId: null };
  $("#view").innerHTML = mlHead({ id: libId, name: lib.name, count: nf(rows.length), search: false, q: "", filter: true, badge: 0, sort: false, more: false })
    + `<div class="row-head lib-head"><h2>${KIND_ICON.music || ""} ${esc(lib.name)} <span class="muted" style="font-size:14px;font-weight:400">Playlists</span></h2>
    <div class="tools"><select id="libview"><option value="">Albums</option><option value="tracks">Tracks</option><option value="playlists">Playlists</option></select></div></div>`
    + `<div class="pli-actions"><button class="btn" id="pl-new" type="button">New playlist</button></div>`
    + (rows.length ? `<div class="pli-grid">${rows.map(p => playlistCard(libId, p)).join("")}</div>`
                  : `<div class="playlist-empty">No playlists yet. Create one to collect tracks you want to hear later.</div>`);
  $("#libview").value = "playlists";
  $("#libview").onchange = () => { location.hash = `#/library/${libId}/${$("#libview").value}`; };
  $("#pl-new").onclick = () => openPlaylistSheet([], () => { location.hash = `#/library/${libId}/playlists`; route(); });
  $$("[data-pl-play]").forEach(b => b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); playPlaylist(+b.dataset.plPlay, false); });
  $$("[data-pl-shuffle]").forEach(b => b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); playPlaylist(+b.dataset.plShuffle, true); });
  mlBind({ id: libId, key: "filter", menu: [] });
}
async function viewPlaylist(pid, libId) {
  const d = await api("/api/playlists/" + pid);
  const lib = libId || (d.tracks[0] && d.tracks[0].library_id);
  const back = lib ? `#/library/${lib}/playlists` : "#/libraries";
  const tracks = d.tracks;
  $("#view").innerHTML = `<div class="detail">${d.poster ? `<div class="poster square" style="background-image:url('${thumbUrl(d.poster)}')"></div>` : `<div class="poster square" style="background-image:url('${LOGO_MARK}');background-size:contain;background-color:#16131c"></div>`}<div class="info">
    <p class="muted"><a href="${back}">&lsaquo; Playlists</a></p>
    <h1 id="pl-name">${esc(d.name)}</h1>
    <div class="meta"><span>${d.track_count} track${d.track_count === 1 ? "" : "s"}</span>${d.duration ? `<span>${fmtLen(d.duration)}</span>` : ""}</div>
    <div class="pli-actions">
      <button class="btn" id="pl-play" type="button"${tracks.length ? "" : " disabled"}>${ICO_PLAY} Play</button>
      <button class="btn ghost" id="pl-shuffle" type="button"${tracks.length ? "" : " disabled"}>${ICO_SHUFFLE} Shuffle</button>
      <button class="btn ghost" id="pl-rename" type="button">Rename</button>
      <button class="btn ghost" id="pl-delete" type="button">Delete</button>
    </div>
    <div id="pl-tracks">${playlistTrackRows(tracks)}</div>
  </div></div>`;
  bindPlaylistDetail(d, lib);
}
function playlistTrackRows(tracks) {
  if (!tracks.length) return `<div class="empty">This playlist is empty.</div>`;
  const up = ico(`<path d="M7 14l5-5 5 5"/>`);
  const down = ico(`<path d="M7 10l5 5 5-5"/>`);
  const x = ico(`<path d="M7 7l10 10M17 7L7 17"/>`);
  return `<div class="list" id="pl-tracklist">${tracks.map((t, n) => `<div class="pli-row" data-entry="${t.entry_id}" data-track="${n}" draggable="true">
    <button type="button" class="pli-handle" title="Drag to reorder" aria-label="Reorder" draggable="false">&#8942;</button>
    <button type="button" class="iconbtn ab-tool pli-play" data-track="${n}" data-item="${t.id}" title="Play from here" aria-label="Play ${esc(t.title)} from this playlist">${ICO_PLAY}</button>
    <div class="li" data-track="${n}" data-item="${t.id}">
      <div class="num">${n + 1}</div>
      <div class="ttl"><div>${esc(t.title)}</div><div class="muted" style="font-size:12.5px">${esc([t.artist, t.album].filter(Boolean).join(" · "))}</div></div>
      <div class="dur">${fmtDur(t.duration)}</div>
    </div>
    <button type="button" class="iconbtn ab-tool pli-move" data-dir="-1" title="Move up" aria-label="Move up"${n === 0 ? " disabled" : ""}>${up}</button>
    <button type="button" class="iconbtn ab-tool pli-move" data-dir="1" title="Move down" aria-label="Move down"${n === tracks.length - 1 ? " disabled" : ""}>${down}</button>
    <button type="button" class="iconbtn ab-tool" data-rm="${t.entry_id}" title="Remove" aria-label="Remove from playlist">${x}</button>
  </div>`).join("")}</div>`;
}
function bindPlaylistDetail(d, lib) {
  const tracks = d.tracks;
  const list = $("#pl-tracklist");
  bindTrackList(tracks, list);
  if ($("#pl-play")) $("#pl-play").onclick = () => playQueue(tracks, 0);
  if ($("#pl-shuffle")) $("#pl-shuffle").onclick = () => playQueue(shuffled(tracks), 0);
  $$(".pli-play", list || document).forEach(b => b.onclick = (e) => {
    e.preventDefault(); e.stopPropagation();
    playQueue(tracks, +b.dataset.track);
  });
  // Touch / phone: HTML5 drag on the row often swallows the tap that should start playback.
  const coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  if (list && coarse) $$(".pli-row", list).forEach(r => { r.draggable = false; });
  $("#pl-rename").onclick = () => modal(`<h2>Rename playlist</h2><label>Name</label><input id="pl-ren" maxlength="80" value="${esc(d.name)}"><div class="modal-actions"><button class="btn ghost" type="button" id="pl-ren-c">Cancel</button><button class="btn" type="button" id="pl-ren-ok">Save</button></div>`, () => {
    $("#pl-ren-c").onclick = closeModal;
    $("#pl-ren").focus(); $("#pl-ren").select();
    const save = async () => {
      try { await api("/api/playlists/" + d.id, { method: "PUT", body: { name: $("#pl-ren").value } }); closeModal(); route(); }
      catch (e) { toast(e.message, true); }
    };
    $("#pl-ren-ok").onclick = save;
    $("#pl-ren").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } };
  });
  $("#pl-delete").onclick = () => modal(`<h2>Delete playlist?</h2><p>Delete <b>${esc(d.name)}</b>? This cannot be undone.</p><div class="modal-actions"><button class="btn ghost" type="button" id="pl-del-c">Cancel</button><button class="btn" type="button" id="pl-del-ok">Delete</button></div>`, () => {
    $("#pl-del-c").onclick = closeModal;
    $("#pl-del-ok").onclick = async () => {
      try { await api("/api/playlists/" + d.id, { method: "DELETE" }); closeModal(); location.hash = lib ? `#/library/${lib}/playlists` : "#/libraries"; }
      catch (e) { toast(e.message, true); }
    };
  });
  $$("[data-rm]").forEach(b => b.onclick = async (e) => {
    e.stopPropagation();
    try { await api(`/api/playlists/${d.id}/tracks/${b.dataset.rm}`, { method: "DELETE" }); route._keepScroll = true; route(); }
    catch (err) { toast(err.message, true); }
  });
  $$(".pli-move").forEach(b => b.onclick = async (e) => {
    e.stopPropagation();
    const row = b.closest(".pli-row");
    const ids = $$(".pli-row").map(r => +r.dataset.entry);
    const i = ids.indexOf(+row.dataset.entry);
    const j = i + (+b.dataset.dir);
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    try { await api(`/api/playlists/${d.id}/order`, { method: "PUT", body: { ids } }); route._keepScroll = true; route(); }
    catch (err) { toast(err.message, true); }
  });
  if (list) {
    let dragEl = null;
    list.addEventListener("dragstart", (e) => {
      dragEl = e.target.closest(".pli-row");
      if (!dragEl) return;
      dragEl.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", dragEl.dataset.entry); } catch (err) {}
    });
    list.addEventListener("dragend", () => { if (dragEl) dragEl.classList.remove("dragging"); dragEl = null; });
    list.addEventListener("dragover", (e) => {
      e.preventDefault();
      const over = e.target.closest(".pli-row");
      if (!dragEl || !over || over === dragEl) return;
      const mid = over.getBoundingClientRect().top + over.offsetHeight / 2;
      if (e.clientY < mid) list.insertBefore(dragEl, over); else list.insertBefore(dragEl, over.nextSibling);
    });
    list.addEventListener("drop", async (e) => {
      e.preventDefault();
      const ids = $$(".pli-row").map(r => +r.dataset.entry);
      try { await api(`/api/playlists/${d.id}/order`, { method: "PUT", body: { ids } }); route._keepScroll = true; route(); }
      catch (err) { toast(err.message, true); }
    });
  }
}

let PLS = { ids: [], after: null };
async function openPlaylistSheet(itemIds, after) {
  PLS.ids = (itemIds || []).slice();
  PLS.after = after || null;
  const box = $("#plsheet");
  box.classList.remove("hidden");
  box.hidden = false;
  $("#plsheet-title").textContent = PLS.ids.length ? "Add to playlist" : "New playlist";
  $("#plsheet-name").value = "";
  await renderPlaylistSheet();
  afChromePoke();
  const inp = $("#plsheet-name"); if (inp) setTimeout(() => inp.focus(), 30);
}
function closePlaylistSheet() {
  const box = $("#plsheet");
  if (!box) return;
  box.classList.add("hidden");
  box.hidden = true;
  const after = PLS.after;
  PLS = { ids: [], after: null };
  if (after) after();
  afChromePoke();
}
async function renderPlaylistSheet() {
  const list = $("#plsheet-list");
  if (!list) return;
  let rows = [];
  try { rows = await api("/api/playlists"); }
  catch (e) { list.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (!rows.length) { list.innerHTML = `<div class="playlist-empty">No playlists yet. Create one above.</div>`; return; }
  list.innerHTML = rows.map(p => `<button type="button" class="plsheet-item" data-pl="${p.id}">
    ${playlistArt(p.poster)}
    <span class="pli-meta"><b>${esc(p.name)}</b><span class="muted">${p.track_count} track${p.track_count === 1 ? "" : "s"}</span></span>
  </button>`).join("");
  $$("#plsheet-list [data-pl]").forEach(b => b.onclick = async () => {
    if (!PLS.ids.length) { toast("Enter a name to create a playlist, or open it from the Music library."); return; }
    try {
      const r = await api(`/api/playlists/${b.dataset.pl}/tracks`, { method: "POST", body: { item_ids: PLS.ids } });
      toast(r.added === 0 ? "Already in this playlist" : "Added to playlist");
      const after = PLS.after; PLS.after = null;
      closePlaylistSheet();
      if (after) after();
    } catch (e) { toast(e.message, true); }
  });
}
function bindPlaylistSheet() {
  if (bindPlaylistSheet.ready) return;
  bindPlaylistSheet.ready = true;
  const box = $("#plsheet"); if (!box) return;
  $("#plsheet-close").onclick = () => closePlaylistSheet();
  box.addEventListener("mousedown", (e) => { if (e.target.id === "plsheet") closePlaylistSheet(); });
  const create = async () => {
    const name = ($("#plsheet-name").value || "").trim();
    if (!name) { toast("Enter a name for the playlist", true); return; }
    try {
      await api("/api/playlists", { method: "POST", body: { name, item_ids: PLS.ids } });
      toast("Playlist created");
      const after = PLS.after; PLS.after = null;
      closePlaylistSheet();
      if (after) after();
      else if (/playlist/.test(location.hash)) route();
    } catch (e) { toast(e.message, true); }
  };
  $("#plsheet-create").onclick = create;
  $("#plsheet-name").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); create(); } else if (e.key === "Escape") closePlaylistSheet(); });
}


// 1.4.5: resolution name from width as well as height (a 1920x800 scope film is 1080p, not 720p)
function resName(w, h) { return w >= 3200 || h >= 2000 ? "4K" : w >= 2400 || h >= 1300 ? "2K" : w >= 1800 || h >= 1000 ? "1080p" : w >= 1200 || h >= 700 ? "720p" : h + "p"; }   // 1.7: + 2K
// 1.4.5: the "..." menu on the details page (click / Enter opens; Esc, outside click or picking an item closes)
function bindMoreMenu() {
  const btn = $("#more"), menu = $("#more-menu"); if (!btn || !menu) return;
  const items = () => $$("#more-menu .mi");
  const open = (focusFirst) => { closeSiblingPops("more"); menu.hidden = false; btn.setAttribute("aria-expanded", "true"); if (focusFirst) (items()[0] || btn).focus(); };
  const close = (refocus) => { if (menu.hidden) return; menu.hidden = true; btn.setAttribute("aria-expanded", "false"); if (refocus) btn.focus(); };
  btn.onclick = (e) => { e.stopPropagation(); menu.hidden ? open(e.detail === 0) : close(false); };
  btn.onkeydown = (e) => { if (e.key === "ArrowDown") { e.preventDefault(); open(true); } else if (e.key === "Escape") close(true); };
  menu.addEventListener("click", (e) => { if (e.target.closest(".mi")) close(false); });
  menu.addEventListener("keydown", (e) => {
    const l = items(), i = l.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); close(true); }
    else if (e.key === "ArrowDown") { e.preventDefault(); l[(i + 1) % l.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); l[(i - 1 + l.length) % l.length].focus(); }
    else if (e.key === "Tab") close(false);
  });
  const outside = (e) => { if (!document.body.contains(menu)) { document.removeEventListener("click", outside); return; } if (!e.target.closest(".more-wrap")) close(false); };
  document.addEventListener("click", outside);
}

async function viewItem(id) {
  const it = await api("/api/items/" + id);
  const pb = it.playback || {};
  const land = it.kind === "episode" || it.kind === "video";
  const img = land ? (it.thumb || it.poster) : (it.poster || it.thumb);
  let title = it.title, sub = [];
  if (it.kind === "episode") { title = it.title; sub.push(`<a href="#/show/${it.library_id}/${enc(it.show)}" style="color:var(--acc-text)">${esc(it.show_title || it.show)}</a>`, epCode(it)); if (it.air_date) sub.push(esc(it.air_date)); }
  if (it.media_type === "audio") { if (it.artist) sub.push(esc(it.artist)); if (it.album) sub.push(`<a style="color:var(--acc-text)" href="#/album/${it.library_id}/${enc(it.album_artist || it.artist || "Unknown artist")}/${enc(it.album)}">${esc(it.album)}</a>`); }
  if (it.year) sub.push(it.year);
  if (it.edition) sub.push(`<span class="ed">${esc(it.edition)}</span>`);
  if (it.duration) sub.push(fmtLen(it.duration));
  if (it.width) sub.push(resName(it.width, it.height));
  // 1.7: other files of this title in the library (best first); a copy on another share when this one is offline
  const vers = it.versions || [];
  const fmtMbps = (b) => b ? (b / 1e6).toFixed(b >= 1e7 ? 0 : 1) + " Mbps" : "";
  const verHtml = vers.length > 1 ? `<div class="vers"><label for="ver-sel">Version</label><select id="ver-sel">${vers.map((v, n) => `<option value="${v.id}"${v.id === it.id ? " selected" : ""}>${[v.res + (n === 0 ? " (best)" : ""), (v.vcodec || "").toUpperCase(), fmtMbps(v.bitrate), v.size ? fmtSize(v.size) : ""].filter(Boolean).join(" · ")}</option>`).join("")}</select><span class="help">${vers.length} files of this ${it.kind === "episode" ? "episode" : "film"} -- highest resolution first</span></div>` : "";
  const offHtml = it.unavailable || (it.is_remote && it.online === false) ? `<div class="vers off"><span class="ldot off"></span> ${esc(it.peer_name || it.source_name || "That shared server")} is not reachable right now. This title stays in Continue watching and will play again when the server is back.</div>` :
    it.offline ? `<div class="vers off"><span class="ldot off"></span> ${it.fallback ? `This library's share is offline -- Play uses the copy in <b>${esc(it.fallback_library || "another library")}</b>.` : "This library's share is offline, and no other library has this title."}</div>` : "";
  const playChip = pb.direct ? `<span class="chip ok">Direct play</span>` : pb.direct_maybe ? `<span class="chip warn">Direct play if your browser supports it, else ${pb.remux ? "remux" : "transcode"}</span>`
    : pb.remux ? `<span class="chip ok" title="The video is copied as-is; only the container${it.acodec && !["aac", "mp3"].includes(it.acodec) ? " and audio" : ""} are converted">Remux (no video re-encode)</span>` : `<span class="chip warn">Will transcode</span>`;
  const canMatch = ME.is_admin && (it.kind === "movie" || it.kind === "episode");
  const auds = (pb.audio_streams || []).map(a => `${a.codec}${a.channels ? " " + a.channels + "ch" : ""}${a.lang ? " (" + a.lang + ")" : ""}`).join(", ");
  const isMovie = it.kind === "movie";
  if (isMovie && it.certification) sub.splice(it.year ? 1 : 0, 0, `<span class="chip cert" title="Age rating">${esc(it.certification)}</span>`);
  if (!it.duration && it.runtime) sub.splice(sub.length - (it.width ? 1 : 0), 0, fmtLen(it.runtime * 60));
  const chipsIt = Object.assign({}, it, { certification: isMovie ? null : it.certification });
  const plink = (p) => `<a href="#/person/${p.id}/${it.library_id}">${esc(p.name)}</a>`;
  const directors = it.directors || [], writers = it.writers || [], cast = it.cast || [], tags = it.tags || [];
  const credLine = isMovie && (directors.length || writers.length) ? `<div class="credits-line">${directors.length ? `<span><span class="muted">Directed by</span> ${directors.map(plink).join(", ")}</span>` : ""}${writers.length ? `<span><span class="muted">Written by</span> ${writers.map(plink).join(", ")}</span>` : ""}</div>` : "";
  const castHtml = !isMovie ? "" : cast.length ? `<div class="cast-strip">${cast.map(p => `<a class="person" href="#/person/${p.id}/${it.library_id}" title="${esc(p.name)}${p.character ? " as " + esc(p.character) : ""}">
      <div class="pph"><span class="ini">${esc(p.name.split(/\s+/).slice(0, 2).map(w => w[0] || "").join(""))}</span>${p.has_photo ? `<img loading="lazy" alt="" src="/api/people/${p.id}/photo" onerror="this.remove()">` : ""}</div>
      <div class="pn">${esc(p.name)}</div>${p.character ? `<div class="pc">${esc(p.character)}</div>` : ""}</a>`).join("")}</div>`
    : `<div class="empty small">${it.credits_pending ? "Cast is being fetched from TMDB in the background -- check back in a few minutes." : it.tmdb ? "No cast information on TMDB." : "Cast comes from TMDB once this movie is matched."}</div>`;
  const simHtml = !isMovie ? "" : (it.similar || []).length ? `<div class="strip sim">${it.similar.map(x => cardItem(x, { reason: true })).join("")}</div>`
    : `<div class="empty small">${it.tmdb ? "No similar movies in your library yet." : "Similar movies appear once this movie is matched on TMDB."}</div>`;
  // 1.4.5: File & playback and the Admin card are gone from the page; their actions live in the "..." menu
  const resLabel = it.width ? (resName(it.width, it.height)) : "";
  const reviewNote = it.needs_review && canMatch ? (it.match_status === "review" ? (it.match_note || "").replace(/([^.])$/, "$1.")
    : `Automatic match${it.match_confidence != null ? ` (confidence ${Math.round(it.match_confidence * 100)}%)` : ""}${it.match_note ? ": " + it.match_note : ""}.`) : "";
  const mi = (id, label, extra) => `<button type="button" class="mi" role="menuitem" id="${id}">${label}${extra || ""}</button>`;
  const ml = (href, label, attrs) => `<a class="mi" role="menuitem" href="${href}"${attrs || ""}>${label}</a>`;
  const adminItems = !ME.is_admin ? [] : [
    canMatch ? mi("fixmatch", it.kind === "episode" ? "Fix show match" : "Fix match", it.needs_review ? ` <span class="mbadge" title="${esc(reviewNote)}">Needs review</span>` : "") : "",
    it.needs_review && canMatch && it.match_candidate ? mi("accept-cand", `Accept suggestion: ${esc(it.match_candidate.title || "TMDB #" + it.match_candidate.id)}${it.match_candidate.year ? " (" + it.match_candidate.year + ")" : ""}`) : "",
    it.needs_review && canMatch && it.match_status === "matched" ? mi("confirm-match", "Match looks right") : "",
    isMovie ? mi("homerows", "Home rows", Object.keys(it.pins || {}).length ? ` <span class="muted">(pinned / hidden)</span>` : "") : "",
    isMovie ? mi("addtag2", "+ Tag") : "",
    isMovie && it.library_id ? ml("#/settings/libraries", "Artwork settings", ' title="Artwork saving is set per library"') : ""].filter(Boolean);
  const userItems = [
    ml(`/api/items/${it.id}/file?download=1`, "Download file"),
    it.tmdb_url ? ml(esc(it.tmdb_url), "TMDB &#8599;", ' target="_blank" rel="noopener"') : "",
    mi("fileinfo", "File info")].filter(Boolean);
  // 1.4.9: the "..." menu (and File info / Download) is for admins only
  const moreMenu = !ME.is_admin ? "" : `<div class="more-wrap"><button type="button" class="btn ghost more-btn" id="more" aria-haspopup="menu" aria-expanded="false" aria-label="More options" title="More options">&#8943;</button>
    <div class="more-menu" id="more-menu" role="menu" hidden>${adminItems.length ? `<div class="mh">Admin</div>${adminItems.join("")}<div class="msep"></div>` : ""}${userItems.join("")}</div></div>`;
  const fileInfoDlg = () => modal(`<h2>File info</h2>
    <div style="margin:4px 0 6px">${playChip}${it.match_status === "unmatched" ? ` <span class="chip" title="Fix match -> Automatic to use TMDB again">TMDB off for this title</span>` : ""}</div>
    <div class="tech">
      <span>File</span><b>${esc(it.filename)}</b>
      ${it.folder ? `<span>Folder</span><b>${esc(it.folder)}</b>` : ""}
      <span>Size</span><b>${fmtSize(it.size)}</b>
      <span>Container</span><b>${esc(it.container || "?")}</b>
      ${resLabel ? `<span>Resolution</span><b>${resLabel}</b>` : ""}
      ${it.vcodec ? `<span>Video</span><b>${esc(it.vcodec)} ${it.width || ""}x${it.height || ""} ${esc(it.pix_fmt || "")}</b>` : ""}
      ${auds ? `<span>Audio</span><b>${esc(auds)}</b>` : ""}
      ${(pb.subtitles || []).length ? `<span>Subtitles</span><b>${esc(pb.subtitles.map(s => s.label).join(", "))}</b>` : ""}
      ${it.bitrate ? `<span>Bitrate</span><b>${Math.round(it.bitrate / 1000)} kbps</b>` : ""}
      <span>Library</span><b>${esc(it.library ? it.library.name : "")}</b>
      ${it.file_title && it.file_title !== it.title ? `<span>Name from file</span><b>${esc(it.file_title)}</b>` : ""}
    </div>
    <div class="modal-actions"><a class="btn ghost" href="/api/items/${it.id}/file?download=1">Download file</a><button class="btn" id="fi-close">Close</button></div>`,
    () => { $("#fi-close").onclick = closeModal; $("#fi-close").focus(); });
  const bgImg = it.backdrop || (isMovie ? it.poster : null);   // 1.4.4: blurred artwork behind the whole page
  $("#view").innerHTML = `${bgImg ? `<div class="detail-bg" aria-hidden="true"><div class="dbg-img" style="background-image:url('${thumbUrl(bgImg)}')"></div></div>` : ""}<div class="hero${bgImg ? " soft" : ""}"${heroStyle(it.backdrop)}></div><div class="detail"><div class="poster ${land ? "landscape" : it.media_type === "audio" ? "square" : ""}" style="${img ? `background-image:${it.poster_large && img === it.poster ? `url('${it.poster_large}'),` : ""}url('${thumbUrl(img)}')` : ""}"></div>
    <div class="info"><h1>${esc(title)}</h1><div class="meta">${sub.map(s => `<span>${s}</span>`).join("")}</div>
    ${metaChips(chipsIt, isMovie ? it.library_id : 0)}
    ${it.tagline ? `<div class="tagline">${esc(it.tagline)}</div>` : ""}
    ${verHtml}${offHtml}
    <div class="actions main-actions">
      ${it.position > 30 ? `<button class="btn big" id="resume">&#9654; Resume from ${fmtDur(it.position)}</button><button class="btn ghost big" id="play">Play from start</button>` : `<button class="btn big" id="play">&#9654; Play</button>`}
      <button class="btn ghost" id="watched">${it.watched ? "Mark unwatched" : "Mark watched"}</button>
      ${OFF.on() && it.media_type === "video" ? `<button class="btn ghost dl-btn" id="dl-btn" data-item="${it.id}">${dlBtnLabel(it.id)}</button>` : ""}
      ${it.next ? `<a class="btn ghost" href="#/item/${it.next.id}">Next: ${epCode(it.next)} &rsaquo;</a>` : ""}
      ${moreMenu}
    </div>
    ${credLine}
    ${it.overview ? `<p class="overview">${esc(it.overview)}</p>` : (it.show_overview ? `<p class="overview muted">${esc(it.show_overview)}</p>` : "")}
    ${it.collection ? `<div class="coll-link">Part of <a href="#/library/${it.library_id}/collection/${it.collection.id}">${esc(it.collection.name || "a collection")} &rsaquo;</a></div>` : ""}
    ${isMovie && tags.length ? `<div class="tagrow">${tags.map(t => `<span class="chip tag"><a href="#/library/${it.library_id}" data-tagid="${t.id}">#${esc(t.name)}</a>${ME.is_admin ? `<button class="x" data-untag="${t.id}" title="Remove tag" aria-label="Remove tag ${esc(t.name)}">&times;</button>` : ""}</span>`).join("")}</div>` : ""}
    </div></div>
    ${isMovie ? `<section class="dsec"><div class="row-head"><h3>Cast</h3>${cast.length ? `<span class="muted">${cast.length} of the top-billed</span>` : ""}</div>${castHtml}</section>
    <section class="dsec"><div class="row-head"><h3>Similar movies</h3></div>${simHtml}</section>` : ""}
    ${it.tmdb ? TMDB_NOTE : ""}`;
  // 1.7: the page's file is played as-is when the user picked it (not the best version); the best one may step
  // down to a lighter version when this server can't transcode it well (see pickVersion)
  const exact = vers.length > 1 && vers[0].id !== it.id;
  $("#play").onclick = () => { SFX.play(); playItem(id, 0, { exact, item: it }); };
  if ($("#ver-sel")) $("#ver-sel").onchange = (e) => { location.hash = "#/item/" + e.target.value; };
  bindMoreMenu();
  if ($("#fileinfo")) $("#fileinfo").onclick = fileInfoDlg;
  if ($("#fixmatch")) $("#fixmatch").onclick = () => {
    if (!it.tmdb_enabled) { toast("Add a TMDB API key in Settings -> Metadata first", true); return; }
    if (it.kind === "episode") fixMatchDialog("tv", it.show.replace(/\s*\((19|20)\d\d\)\s*$/, ""), null, (b) => api("/api/show/match", { method: "POST", body: { library_id: it.library_id, show: it.show, ...b } }));
    else fixMatchDialog("movie", it.file_title || it.title, it.year, (b) => api(`/api/items/${id}/match`, { method: "POST", body: b }));
  };
  if ($("#resume")) $("#resume").onclick = () => { SFX.play(); playItem(id, it.position, { exact, item: it }); };
  if ($("#accept-cand")) $("#accept-cand").onclick = async () => { try { await api(`/api/items/${id}/match`, { method: "POST", body: { accept_candidate: true } }); toast("Match accepted"); route._keepScroll = true; route(); } catch (e) { toast(e.message, true); } };
  if ($("#confirm-match")) $("#confirm-match").onclick = async () => { try { await api(`/api/items/${id}/match`, { method: "POST", body: { tmdb_id: it.tmdb_id } }); toast("Match confirmed"); route._keepScroll = true; route(); } catch (e) { toast(e.message, true); } };
  if ($("#dl-btn")) $("#dl-btn").onclick = () => { const d = OFF.forItem(it.id); if (d && d.state === "ready") { window.MSAndroid.playOffline(d.gid); return; } if (d) { location.hash = "#/downloads"; return; } downloadDialog(it); };
  $("#watched").onclick = async () => { await api(`/api/items/${id}/watched`, { method: "POST", body: { watched: !it.watched } }); route._keepScroll = true; route(); };
  if ($("#homerows")) $("#homerows").onclick = () => {
    const sel = (row) => { const m = (it.pins || {})[row] || 0; return `<select id="pin-${row}">${[[0, "Automatic"], [1, "Always include (pinned first)"], [-1, "Never include"]].map(([v, n]) => `<option value="${v}"${v === m ? " selected" : ""}>${n}</option>`).join("")}</select>`; };
    modal(`<h2>Home rows</h2><div class="form"><label for="pin-recommended">Recommended</label>${sel("recommended")}<label for="pin-top">Top movies</label>${sel("top")}
      <div class="help">Movies are placed in these rows automatically. Use this to pin a favourite or keep one out. Applies to every user; a pinned movie still disappears from someone's Recommended once they have watched it.</div></div><div class="err" id="pin-err"></div>
      <div class="modal-actions"><button class="btn ghost" id="pin-cancel">Cancel</button><button class="btn" id="pin-ok">Save</button></div>`, () => {
      $("#pin-cancel").onclick = closeModal;
      $("#pin-ok").onclick = async () => {
        try { for (const row of ["recommended", "top"]) await api(`/api/items/${it.id}/pin`, { method: "POST", body: { row, mode: +$("#pin-" + row).value } }); closeModal(); toast("Home rows updated"); route._keepScroll = true; route(); }
        catch (e) { $("#pin-err").textContent = e.message; }
      };
    });
  };
  $$("[data-tagid]").forEach(a => a.onclick = (e) => { e.preventDefault(); catSet(it.library_id, { genres: [], decade: "", cert: "", tag: +a.dataset.tagid }); location.hash = "#/library/" + it.library_id; });
  $$("[data-untag]").forEach(b => b.onclick = async () => { await api("/api/tags/apply", { method: "POST", body: { item_ids: [it.id], remove: [+b.dataset.untag] } }); route._keepScroll = true; route(); });
  const tagDlg = () => {
    modal(`<h2>Add a tag</h2><div class="form"><label for="tg-name">Tag</label><input type="text" id="tg-name" list="tg-list" placeholder="e.g. Kids, Christmas, Watch with Dad"><datalist id="tg-list"></datalist>
      <div class="help">Tags are your own categories. To tag many movies at once, use <b>Select</b> on the library page.</div></div><div class="err" id="tg-err"></div>
      <div class="modal-actions"><button class="btn ghost" id="tg-cancel">Cancel</button><button class="btn" id="tg-ok">Add tag</button></div>`, () => {
      api("/api/tags").then(ts => { $("#tg-list").innerHTML = ts.map(t => `<option value="${esc(t.name)}">`).join(""); }).catch(() => {});
      const ok = async () => { const n = $("#tg-name").value.trim(); if (!n) { $("#tg-err").textContent = "Type a tag name"; return; }
        try { await api("/api/tags/apply", { method: "POST", body: { item_ids: [it.id], add: [n] } }); closeModal(); route._keepScroll = true; route(); } catch (e) { $("#tg-err").textContent = e.message; } };
      $("#tg-ok").onclick = ok; $("#tg-name").onkeydown = (e) => { if (e.key === "Enter") ok(); }; $("#tg-cancel").onclick = closeModal; $("#tg-name").focus();
    });
  };
  if ($("#addtag2")) $("#addtag2").onclick = tagDlg;
  setDetailTop(bgImg ? thumbUrl(bgImg) : null);
}

// 1.4.3: an actor / director and the movies in your library they are in
async function viewPerson(id, libId) {
  const d = await api(`/api/people/${id}` + (libId ? `?library_id=${libId}` : ""));
  const p = d.person, ini = esc(p.name.split(/\s+/).slice(0, 2).map(w => w[0] || "").join(""));
  $("#view").innerHTML = `<div class="person-head"><div class="pph big"><span class="ini">${ini}</span>${p.has_photo ? `<img alt="" src="/api/people/${p.id}/photo" onerror="this.remove()">` : ""}</div>
    <div><h2 style="margin:0 0 4px">${esc(p.name)}</h2><div class="muted">${d.items.length} movie${d.items.length === 1 ? "" : "s"} in your library</div>
    <a class="muted" href="https://www.themoviedb.org/person/${p.id}" target="_blank" rel="noopener">TMDB &#8599;</a></div></div>
    ${d.items.length ? `<div class="grid">${d.items.map(i => cardItem(i, { reason: true })).join("")}</div>` : `<div class="empty">No movies with ${esc(p.name)} in this library.</div>`}`;
}

async function viewSearch(q) {
  const v = $("#view");
  if ($("#search").value.trim() !== q) $("#search").value = q;
  // 1.5.1: the Search tab -- a big search box on phones (the top bar has only an icon there)
  if (!$("#m-q", v)) {
    v.innerHTML = `<div class="m-qw"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M15.5 15.5L21 21" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg><input id="m-q" type="search" placeholder="Search movies, shows, music..." autocomplete="off" enterkeyhint="search" aria-label="Search"></div><div id="s-res"></div>`;
    const mq = $("#m-q");
    mq.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { const x = mq.value.trim(); history.replaceState(null, "", "#/search" + (x ? "/" + enc(x) : "")); viewSearch(x); }, 300); });
    if (!q && innerWidth <= 820) setTimeout(() => mq.focus({ preventScroll: true }), 50);
  }
  const mq = $("#m-q");
  if (document.activeElement !== mq && mq.value.trim() !== q) mq.value = q;
  const out = $("#s-res");
  if (!q) { out.innerHTML = `<div class="empty s-hint">Find a movie, show, episode, album or song.</div>`; return; }
  const d = await api("/api/search?q=" + enc(q));
  if (mq.value.trim() && mq.value.trim() !== q && document.activeElement === mq) return;   // a newer search is on its way
  let html = `<h2>Results for "${esc(q)}"</h2>`;
  if (d.items.length) html += `<h3>Movies &amp; videos</h3><div class="grid">${d.items.map(i => cardItem(i)).join("")}</div>`;
  if (d.shows.length) html += `<h3>Shows</h3><div class="grid">${d.shows.map(s => cardShow(s.library_id, s)).join("")}</div>`;
  if (d.episodes.length) html += `<h3>Episodes</h3><div class="grid">${d.episodes.map(i => cardItem(i)).join("")}</div>`;
  if (d.albums.length) html += `<h3>Albums</h3><div class="grid">${d.albums.map(a => cardAlbum(a.library_id, a)).join("")}</div>`;
  if (d.tracks.length) html += `<h3>Tracks</h3>${trackList(d.tracks, true)}`;
  if (!d.items.length && !d.shows.length && !d.episodes.length && !d.albums.length && !d.tracks.length) html += `<div class="empty">Nothing found.</div>`;
  out.innerHTML = html;
  if (d.tracks.length) bindTrackList(d.tracks);
}

// 1.5.1: the Libraries tab -- every library, grouped by share (1.7). 1.7.2: one card each, no Collections / Recommended chips
async function viewLibraries() {
  await refreshLibs();
  const sub = { movies: "Movies", tv: "TV shows", music: "Music", other: "Videos" };
  let html = `<h2 class="pg-h">Libraries</h2>`;
  if (!LIBS.length) html += `<div class="empty">No libraries yet.${ME.is_admin ? ` <a href="#/settings/libraries">Add one in Settings</a>` : ""}</div>`;
  else html += `<div class="lib-list">${libGroups().map(g => (libsGrouped() ? `<div class="lib-grp-h" data-grp="${g.key}"><span class="ng-ic" aria-hidden="true">${g.share ? ICO_SHARE : ICO_LOCAL}</span>${esc(g.name)}${g.share && groupHealthLib(g) ? shareDot(groupHealthLib(g)) : ""}</div>` : "") + g.libs.map(l => `<a class="lib-li" tabindex="0" data-lib="${l.id}" href="#/library/${l.id}"><span class="lib-ic" aria-hidden="true">${KIND_ICON[l.kind] || KIND_ICON.other}</span>
      <span class="lib-tx"><b>${esc(l.name)}<span class="ldot-slot">${shareDot(l)}</span></b><span class="muted">${sub[l.kind] || esc(l.kind)} · ${libCountText(l)}${l.health && l.health.state === "offline" ? ` · <span class="ldot-txt off">share offline</span>` : l.health && (l.health.state === "stuck" || l.health.state === "slow") ? ` · <span class="ldot-txt warn">share ${l.health.state === "slow" ? "slow" : "not responding"}</span>` : ""}</span></span><span class="chev" aria-hidden="true">&rsaquo;</span></a>`).join("")).join("")}</div>`;
  $("#view").innerHTML = html;
}

// 1.5.1: the My List tab -- your films in progress and the ones you watched last
async function viewMyList() {
  const d = await api("/api/mylist");
  if (window.TV && TV.ingest) TV.ingest({ continue: d.continue || [], libraries: [], watched: d.watched || [] });
  let html = `<h2 class="pg-h">My List</h2>`;
  if (d.continue.length) html += rowHead("Continue watching", "", { sub: `${d.continue.length} in progress` }) + `<div class="strip hs cw">${d.continue.map(i => cardItem(i, { resume: true })).join("")}</div>`;
  if (d.watched.length) html += rowHead("Watched", "", { sub: "Most recent first" }) + `<div class="grid">${d.watched.map(i => cardItem(i)).join("")}</div>`;
  if (!d.continue.length && !d.watched.length) html += `<div class="empty">Nothing here yet. Films you start or finish show up here.</div>`;
  $("#view").innerHTML = html;
}

// ---------------------------------------------------------------- 2.0: offline downloads (Android app only)
// The native app exposes window.MSAndroid.offlineCaps / downloads / storageInfo / call / playOffline. Browsers have
// no bridge, so nothing here shows there: the bottom tabs, detail pages and menus stay as they were.
const ICO_DL = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5v11.5M7 10.5l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M4.5 16.5v2.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-2.5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>`;
const ICO_MYLIST = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 3.5h11a1 1 0 0 1 1 1V21l-6.5-4.5L5.5 21V4.5a1 1 0 0 1 1-1z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>`;
const DL_HELP = `<p><b>Downloads stay inside the Movinite app.</b> Films are saved encrypted in the app's own storage and only play in the app's player, with no internet needed.</p>
  <p><b>Each download has a licence</b> from your server that lasts <span class="dl-days">30</span> days. It renews by itself whenever the app reaches the server. If a title is taken off the server, your access changes, or this device is removed, the download is deleted the next time the app connects.</p>
  <p><b>Signing in offline</b> uses your phone's fingerprint, face or screen lock (or a Movinite PIN you set here). If the app hasn't reached the server for 30 days, it signs you out and removes the downloads.</p>
  <p class="dl-warn"><b>This isn't studio-grade protection.</b> It stops casual copying and lets the server owner take downloads back, but someone with a rooted phone and enough know-how could still get at a file. It's meant for family and friends, not for protecting a film studio's rights.</p>`;
const OFF = (() => {
  const B = () => window.MSAndroid;
  const native = () => { try { return !!(B() && typeof B().offlineCaps === "function" && typeof B().call === "function"); } catch (e) { return false; } };
  const on = () => native() && !!(ME && ME.can_download);
  const j = (fn, dflt) => { try { const v = JSON.parse(B()[fn]() || "null"); return v == null ? dflt : v; } catch (e) { return dflt; } };
  let seq = 0; const pend = {};
  window.__msResolve = (id, ok, data) => {
    const p = pend[id]; if (!p) return; delete pend[id];
    let d = data; try { if (typeof d === "string") d = JSON.parse(d); } catch (e) { /* plain text */ }
    if (ok) p.res(d); else { const det = d && (d.detail || d.error || d.message); p.rej(Object.assign(new Error(typeof det === "string" ? det : (det && det.detail) || String(d || "Something went wrong")), { data: d })); }
  };
  function call(name, args, timeoutMs) {
    return new Promise((res, rej) => {
      const id = ++seq; pend[id] = { res, rej };
      try { B().call(id, name, JSON.stringify(args || {})); } catch (e) { delete pend[id]; rej(e); return; }
      setTimeout(() => { if (pend[id]) { delete pend[id]; rej(new Error("The app didn't answer. Try again.")); } }, timeoutMs || 45000);
    });
  }
  const list = () => j("downloads", []);
  const caps = () => j("offlineCaps", {});
  const storage = () => j("storageInfo", {});
  const ACTIVE = ["queued", "preparing", "downloading", "paused", "waiting_wifi", "ready"];
  const forItem = (iid) => list().find(d => d.item_id === iid && ACTIVE.includes(d.state));
  function applyTabs() {
    const a = $('#tabbar a[data-tab="mylist"], #tabbar a[data-tab="downloads"]');
    if (a) {
      if (on()) { a.href = "#/downloads"; a.dataset.tab = "downloads"; a.innerHTML = ICO_DL + "<span>Downloads</span>"; }
      else { a.href = "#/mylist"; a.dataset.tab = "mylist"; a.innerHTML = ICO_MYLIST + "<span>My List</span>"; }
    }
    const m = $("#acct-mylist"); if (m) m.hidden = !on();
    const d = $("#acct-downloads"); if (d) d.hidden = !on();
  }
  window.__msDownloadsChanged = () => {
    try {
      if ((location.hash || "").startsWith("#/downloads")) drawDownloads();
      const b = $("#dl-btn"); if (b) b.innerHTML = dlBtnLabel(+b.dataset.item);
    } catch (e) { /* page changed */ }
  };
  return { native, on, call, list, caps, storage, forItem, applyTabs };
})();

function dlLeft(exp) { if (!exp) return ""; const d = Math.floor((exp - Date.now() / 1000) / 86400); return d < 0 ? "licence expired" : d === 0 ? "expires today" : `expires in ${d} day${d === 1 ? "" : "s"}`; }
function dlBtnLabel(iid) {
  const d = OFF.forItem(iid);
  if (!d) return `${ICO_DL}<span>Download</span>`;
  if (d.state === "ready") return `<span class="dl-ok">&#10003;</span><span>Downloaded</span>`;
  if (d.state === "preparing") return `${ICO_DL}<span>Preparing ${Math.round(100 * (d.prep || 0))}%</span>`;
  if (d.state === "paused" || d.state === "waiting_wifi") return `${ICO_DL}<span>${d.state === "paused" ? "Paused" : "Waiting for Wi-Fi"}</span>`;
  return `${ICO_DL}<span>Downloading ${Math.round(100 * (d.progress || 0))}%</span>`;
}
function dlUsageLine(u) {
  if (!u) return "";
  const t = u.titles_max == null ? `${u.titles} title${u.titles === 1 ? "" : "s"}` : `${u.titles} of ${u.titles_max} titles`;
  const g = u.bytes_max == null ? fmtSize(u.bytes) || "0 GB" : `${(u.bytes / 1073741824).toFixed(1)} / ${Math.round(u.bytes_max / 1073741824)} GB`;
  return `${t} · ${g}`;
}

// the quality sheet: Original (only when this device can play the file), 1080p / 720p / 480p made by the server
async function downloadDialog(it) {
  modal(`<h2>Download for offline</h2><div class="dl-load muted">Checking what this device can play...</div>`);
  let o;
  try { o = await OFF.call("options", { item_id: it.id }); }
  catch (e) { modal(`<h2>Download for offline</h2><div class="err">${esc(e.message)}</div><div class="modal-actions"><button class="btn" id="dl-x">Close</button></div>`, () => { $("#dl-x").onclick = closeModal; }); return; }
  const caps = OFF.caps(), st = OFF.storage();
  const want = caps.quality && caps.quality !== "ask" ? o.profiles.find(p => p.available && p.id.split(".")[0] === caps.quality) : null;
  let pick = (want || o.profiles.find(p => p.id === o.default) || o.profiles.find(p => p.available) || {}).id;
  const free = st.free || 0;
  const row = (p) => `<label class="dl-q${p.available ? "" : " off"}"><input type="radio" name="dlq" value="${esc(p.id)}" ${p.id === pick ? "checked" : ""} ${p.available ? "" : "disabled"}>
      <span class="dl-q-n"><b>${esc(p.label)}</b>${p.id === o.default ? ` <span class="chip pill">Recommended</span>` : ""}<span class="muted">${esc(p.note || "")}</span></span>
      <span class="dl-q-s">${p.bytes ? "about " + fmtSize(p.bytes) : ""}</span></label>`;
  const ex = o.existing;
  const auds = (o.audio || []).length > 1 ? `<label for="dl-aud" class="dl-lbl">Audio</label><select id="dl-aud">${o.audio.map(a => `<option value="${a.index}">${esc(a.label)}${a.codec ? " · " + esc(String(a.codec).toUpperCase()) : ""}${a.channels ? " " + a.channels + "ch" : ""}</option>`).join("")}</select>` : "";
  modal(`<h2>Download for offline</h2><div class="dl-title">${esc(o.title || it.title)}</div>
    ${ex ? `<div class="dl-have"><span class="dl-ok">&#10003;</span> On this device in <b>${esc(ex.quality)}</b>. Delete it first to download another quality.</div>` : ""}
    <div class="dl-qs" role="radiogroup" aria-label="Quality">${o.profiles.map(row).join("")}</div>
    ${auds}
    <div class="dl-meta"><span>${esc(dlUsageLine(o.usage))}</span>${free ? `<span>${fmtSize(free)} free on this device</span>` : ""}</div>
    <div class="dl-warn-sp hidden" id="dl-space">Not enough space on this device for this quality.</div>
    ${caps.wifi_only ? `<div class="help">Downloads use Wi-Fi only (change it in Downloads settings).</div>` : ""}
    <details class="dl-help"><summary>How downloads work</summary>${DL_HELP.replace('<span class="dl-days">30</span>', o.days || 30)}</details>
    <div class="err" id="dl-err"></div>
    <div class="modal-actions">${ex ? `<button class="btn danger" id="dl-del">Delete download</button>` : ""}<button class="btn ghost" id="dl-cancel">Cancel</button>${ex ? "" : `<button class="btn" id="dl-go">${ICO_DL} Download</button>`}</div>`, (box) => {
    box.classList.add("dl-box");
    const size = () => { const p = o.profiles.find(x => x.id === pick); const over = p && free && p.bytes > free; $("#dl-space").classList.toggle("hidden", !over); if ($("#dl-go")) $("#dl-go").disabled = !!over || !p; };
    $$('input[name="dlq"]', box).forEach(r => r.onchange = () => { pick = r.value; size(); });
    size();
    $("#dl-cancel").onclick = closeModal;
    if ($("#dl-del")) $("#dl-del").onclick = async () => { try { await OFF.call("remove", { grant_id: ex.id }); closeModal(); toast("Download deleted"); route._keepScroll = true; route(); } catch (e) { $("#dl-err").textContent = e.message; } };
    if ($("#dl-go")) $("#dl-go").onclick = async () => {
      $("#dl-go").disabled = true; $("#dl-err").textContent = "";
      try {
        const r = await OFF.call("download", { item_id: it.id, profile: pick, audio: $("#dl-aud") ? +$("#dl-aud").value : 0 });
        closeModal();
        toast(r && r.state === "preparing" ? "The server is preparing this download. It starts by itself when ready." : "Downloading " + (o.title || it.title));
        const b = $("#dl-btn"); if (b) b.innerHTML = dlBtnLabel(it.id);
      } catch (e) { $("#dl-err").textContent = e.message; $("#dl-go").disabled = false; }
    };
  });
}

// the Downloads tab (in the app): storage and quota, then Downloading / Ready / Needs attention
let DL_USAGE = null;
async function viewDownloads() {
  if (!OFF.native()) { $("#view").innerHTML = `<h2 class="pg-h">Downloads</h2><div class="empty">Downloads work in the Movinite Android app. <a href="#/mylist">My List</a></div>`; return; }
  if (!ME.can_download) { $("#view").innerHTML = `<h2 class="pg-h">Downloads</h2><div class="empty">Downloading needs the <b>Viewer + Downloads</b> role. Ask the server's admin.</div>`; return; }
  drawDownloads();
  try { DL_USAGE = (await api("/api/devices")).usage; drawDownloads(); } catch (e) { /* quota line stays empty */ }
  try { OFF.call("sync", {}, 20000).then(() => drawDownloads()).catch(() => {}); } catch (e) { /* offline */ }
  const tok = route._token;
  clearInterval(route._poll);
  route._poll = setInterval(() => { if (route._token !== tok) { clearInterval(route._poll); return; } if (OFF.list().some(d => ["queued", "preparing", "downloading"].includes(d.state))) drawDownloads(); }, 2000);
}
function dlCard(d) {
  const img = d.poster_url ? `style="background-image:url('${esc(d.poster_url)}')"` : "";
  const busy = ["queued", "preparing", "downloading", "paused", "waiting_wifi"].includes(d.state);
  const pct = d.state === "preparing" ? (d.prep || 0) : (d.progress || 0);
  const sub = busy ? (d.state === "preparing" ? `Server is preparing ${esc(d.quality)} · ${Math.round(100 * pct)}%${d.queue > 1 ? ` · ${d.queue - 1} ahead` : ""}`
      : d.state === "paused" ? `Paused · ${fmtSize(d.done_bytes) || "0 B"} of ${fmtSize(d.bytes)}`
      : d.state === "waiting_wifi" ? "Waiting for Wi-Fi" : d.state === "queued" ? "Waiting to start"
      : `${fmtSize(d.done_bytes) || "0 B"} of ${fmtSize(d.bytes)} · ${Math.round(100 * pct)}%`)
    : d.state === "ready" ? `${esc(d.quality)} · ${fmtSize(d.bytes)} · ${dlLeft(d.expires_at)}`
    : `<span class="dl-bad">${esc(d.error || ({ failed: "Download failed", expired: "Licence expired. Connect to renew it.", revoked: "Removed by the server" })[d.state] || d.state)}</span>`;
  const resume = d.state === "ready" && d.position > 30 && d.duration ? `<div class="dl-res"><div style="width:${Math.min(100, 100 * d.position / d.duration)}%"></div></div>` : "";
  const acts = d.state === "ready" ? `<button class="btn small" data-dlplay="${d.gid}">&#9654; ${d.position > 30 ? "Resume" : "Play"}</button>`
    : d.state === "downloading" || d.state === "queued" || d.state === "waiting_wifi" ? `<button class="btn ghost small" data-dlpause="${d.gid}">Pause</button>`
    : d.state === "paused" ? `<button class="btn ghost small" data-dlresume="${d.gid}">Resume</button>`
    : d.state === "failed" ? `<button class="btn ghost small" data-dlretry="${d.gid}">Try again</button>` : "";
  return `<div class="dl-card st-${esc(d.state)}" data-gid="${d.gid}"><div class="dl-art" ${img}>${img ? "" : "&#127902;"}${d.state === "ready" ? `<span class="dl-qchip">${esc(String(d.quality || "").replace(" HEVC", ""))}</span>` : ""}</div>
    <div class="dl-body"><div class="dl-t">${esc(d.title)}</div>${d.subtitle ? `<div class="dl-s muted">${esc(d.subtitle)}</div>` : ""}<div class="dl-s">${sub}</div>
      ${busy ? `<div class="dl-prog${d.state === "preparing" ? " prep" : ""}"><div style="width:${Math.max(2, Math.round(100 * pct))}%"></div></div>` : resume}
      <div class="dl-acts">${acts}<button class="iconbtn small dl-more" data-dlmore="${d.gid}" aria-label="More for ${esc(d.title)}" title="More">&#8943;</button></div></div></div>`;
}
function drawDownloads() {
  const v = $("#view"); if (!v || v.dataset.view !== "downloads") return;
  const L = OFF.list(), st = OFF.storage(), caps = OFF.caps();
  const going = L.filter(d => ["queued", "preparing", "downloading", "paused", "waiting_wifi"].includes(d.state));
  const ready = L.filter(d => d.state === "ready");
  const bad = L.filter(d => ["failed", "expired", "revoked"].includes(d.state));
  const used = st.used || 0, total = st.total || 0, free = st.free || 0;
  const pctUsed = total ? Math.min(100, 100 * used / total) : 0, pctOther = total ? Math.min(100 - pctUsed, 100 * (total - free - used) / total) : 0;
  let html = `<div class="dl-head"><h2 class="pg-h">Downloads</h2><button class="iconbtn" id="dl-set" title="Download settings" aria-label="Download settings"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M12 2.8l1.6 2.3 2.7-.7.7 2.7 2.3 1.6-1.2 2.5 1.2 2.5-2.3 1.6-.7 2.7-2.7-.7L12 21.2l-1.6-2.3-2.7.7-.7-2.7-2.3-1.6L5.9 12 4.7 9.5 7 7.9l.7-2.7 2.7.7z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg></button></div>
    <div class="dl-store"><div class="dl-bar"><div class="mv" style="width:${pctUsed}%"></div><div class="ot" style="width:${pctOther}%"></div></div>
      <div class="dl-store-l"><span><i class="k mv"></i>Movinite ${fmtSize(used) || "0 B"}</span><span><i class="k fr"></i>${fmtSize(free) || "?"} free</span>${DL_USAGE ? `<span class="dl-quota">${esc(dlUsageLine(DL_USAGE))}</span>` : ""}</div></div>`;
  if (going.length) html += `<h3 class="dl-sec">Downloading <span class="muted">${going.length}</span></h3><div class="dl-list">${going.map(dlCard).join("")}</div>`;
  if (ready.length) html += `<h3 class="dl-sec">Ready to watch offline <span class="muted">${ready.length}</span></h3><div class="dl-list">${ready.map(dlCard).join("")}</div>`;
  if (bad.length) html += `<h3 class="dl-sec">Needs attention <span class="muted">${bad.length}</span></h3><div class="dl-list">${bad.map(dlCard).join("")}</div>`;
  if (!L.length) html += `<div class="empty dl-empty">${ICO_DL}<b>Nothing downloaded yet</b><span>Open a movie or an episode and tap <b>Download</b> to watch it without internet.</span></div>`;
  html += `<details class="dl-help panel"><summary>How downloads work</summary>${DL_HELP}</details>`;
  html += `<p class="help dl-mylist">Looking for My List? It's on <a href="#/home">Home</a> and in your account menu: <a href="#/mylist">open My List</a>.</p>`;
  v.innerHTML = html;
  $("#dl-set").onclick = () => downloadSettings(caps);
  $$("[data-dlplay]", v).forEach(b => b.onclick = () => { try { window.MSAndroid.playOffline(+b.dataset.dlplay); } catch (e) { toast("Couldn't open the player", true); } });
  const act = (sel, name, msg) => $$(sel, v).forEach(b => b.onclick = async () => { b.disabled = true; try { await OFF.call(name, { grant_id: +Object.values(b.dataset)[0] }); if (msg) toast(msg); } catch (e) { toast(e.message, true); } drawDownloads(); });
  act("[data-dlpause]", "pause"); act("[data-dlresume]", "resume"); act("[data-dlretry]", "retry", "Trying again");
  $$("[data-dlmore]", v).forEach(b => b.onclick = () => dlMore(L.find(d => d.gid === +b.dataset.dlmore)));
}
function dlMore(d) {
  if (!d) return;
  modal(`<h2>${esc(d.title)}</h2><div class="dl-more-l">
      ${d.state === "ready" ? `<button class="btn ghost" id="dm-play">&#9654; Play</button>` : ""}
      ${d.item_id ? `<button class="btn ghost" id="dm-other">Download in another quality</button><a class="btn ghost" href="#/item/${d.item_id}" id="dm-open">Open details</a>` : ""}
      <button class="btn danger" id="dm-del">${["downloading", "queued", "preparing", "paused", "waiting_wifi"].includes(d.state) ? "Cancel download" : "Delete download"}</button></div>
      <div class="help">${d.state === "ready" ? `${esc(d.quality)} · ${fmtSize(d.bytes)} · ${dlLeft(d.expires_at)}` : ""}</div>
      <div class="modal-actions"><button class="btn" id="dm-x">Close</button></div>`, () => {
    $("#dm-x").onclick = closeModal;
    if ($("#dm-open")) $("#dm-open").onclick = closeModal;
    if ($("#dm-play")) $("#dm-play").onclick = () => { closeModal(); window.MSAndroid.playOffline(d.gid); };
    $("#dm-del").onclick = async () => { try { await OFF.call("remove", { grant_id: d.gid }); closeModal(); toast("Download deleted"); drawDownloads(); } catch (e) { toast(e.message, true); } };
    if ($("#dm-other")) $("#dm-other").onclick = async () => {
      if (!confirm(`Delete the ${d.quality} download of "${d.title}" and pick another quality?`)) return;
      try { await OFF.call("remove", { grant_id: d.gid }); closeModal(); downloadDialog({ id: d.item_id, title: d.title }); } catch (e) { toast(e.message, true); }
    };
  });
}
function downloadSettings(caps) {
  const sw = (id, on, title, hint) => `<label class="aw-row" for="${id}"><span class="sw"><input type="checkbox" id="${id}" ${on ? "checked" : ""}><i></i></span><span class="aw-txt"><b>${title}</b><span class="aw-hint">${hint}</span></span></label>`;
  const lockTxt = { biometric: "Fingerprint or face unlock", device: "Your phone's screen lock (PIN, pattern or password)", pin: "A Movinite PIN", none: "Nothing yet" }[caps.lock || "none"];
  modal(`<h2>Download settings</h2>
    ${sw("ds-wifi", caps.wifi_only !== false, "Wi-Fi only", "Don't use mobile data for downloads.")}
    <div class="form"><label for="ds-q">Quality</label><select id="ds-q">${[["ask", "Ask each time (720p suggested)"], ["720p", "Always 720p"], ["1080p", "Always 1080p"]].map(([k, n]) => `<option value="${k}" ${(caps.quality || "ask") === k ? "selected" : ""}>${n}</option>`).join("")}</select>
    ${caps.external_available ? `<label for="ds-loc">Save downloads on</label><select id="ds-loc"><option value="internal" ${caps.storage !== "external" ? "selected" : ""}>This device</option><option value="external" ${caps.storage === "external" ? "selected" : ""}>SD card</option></select>` : ""}</div>
    <h3>Offline sign-in</h3><p class="help">When there's no connection, the app opens your downloads after you unlock with: <b>${esc(lockTxt)}</b>.</p>
    ${sw("ds-pin", !!caps.pin, "Movinite PIN", caps.device_secure ? "Ask for a separate 6-digit PIN too." : "Your phone has no screen lock, so set a PIN to protect offline sign-in.")}
    <div class="modal-actions"><button class="btn danger" id="ds-all">Delete all downloads</button><button class="btn" id="ds-ok">Done</button></div>`, () => {
    const set = (k, val) => OFF.call("setting", { key: k, value: val }).catch(e => toast(e.message, true));
    $("#ds-wifi").onchange = (e) => set("wifi_only", e.target.checked);
    $("#ds-q").onchange = (e) => set("quality", e.target.value);
    if ($("#ds-loc")) $("#ds-loc").onchange = (e) => set("storage", e.target.value);
    $("#ds-pin").onchange = async (e) => { try { await OFF.call(e.target.checked ? "setupPin" : "clearPin", {}, 300000); toast(e.target.checked ? "Movinite PIN set" : "Movinite PIN removed"); } catch (er) { e.target.checked = !e.target.checked; if (er.message !== "cancelled") toast(er.message, true); } };
    $("#ds-all").onclick = async () => { if (!confirm("Delete every download on this device?")) return; try { await OFF.call("deleteAll", {}); closeModal(); toast("All downloads deleted"); drawDownloads(); } catch (e) { toast(e.message, true); } };
    $("#ds-ok").onclick = () => { closeModal(); drawDownloads(); };
  });
}

// Settings > My account > Devices & downloads (any browser): what is downloaded where, so quota can be freed from a laptop
function dlGrantRows(gs, admin) {
  if (!gs.length) return `<div class="muted dl-none">No downloads on this device.</div>`;
  return `<div class="dl-grants">${gs.map(g => `<div class="dl-g"><span class="dl-g-t">${esc(g.title || "#" + g.item_id)}</span>
    <span class="chip pill">${esc(g.quality)}</span><span class="muted">${g.state === "preparing" ? "preparing" + (g.job ? " " + Math.round(100 * g.job.progress) + "%" : "") : g.state === "ready" ? "not downloaded yet" : g.state === "failed" ? "failed" : fmtSize(g.bytes)}${g.state === "downloaded" || g.state === "ready" ? " · " + dlLeft(g.expires_at) : ""}</span>
    <button class="btn ghost small" data-rmgrant="${g.id}">${admin ? "Revoke" : "Remove"}</button></div>`).join("")}</div>`;
}
async function accountDownloads(v) {
  let d;
  try { d = await api("/api/devices"); } catch (e) { return; }
  if (!d.can_download && !d.devices.length) return;
  const box = document.createElement("div");
  box.innerHTML = `<div class="panel dl-acct" style="max-width:760px"><h3 style="margin-top:0">Devices &amp; downloads</h3>
    <p class="help">Phones and tablets with the Movinite app that can keep films for offline viewing. ${esc(dlUsageLine(d.usage))}${d.usage.devices_max != null ? ` · ${d.usage.devices} of ${d.usage.devices_max} devices` : ""}.</p>
    ${d.devices.length ? d.devices.map(dv => `<div class="dl-dev"><div class="row-head"><div><b>${esc(dv.name || "Android device")}</b> <span class="muted">· set up ${fmtWhen(dv.created_at)} · last sync ${ago(dv.last_sync)}</span></div>
      <button class="btn danger small" data-rmdev="${dv.id}">Remove device</button></div>${dlGrantRows(dv.grants, false)}</div>`).join("")
      : `<div class="muted">No devices yet. Sign in to the Movinite Android app and tap Download on a film.</div>`}
    <p class="help">Removing a download frees your quota; the app deletes the file the next time it connects. Removing a device deletes all of its downloads and signs it out of offline mode.</p>
    <details class="dl-help"><summary>How downloads work</summary>${DL_HELP.replace('<span class="dl-days">30</span>', d.days || 30)}</details></div>`;
  v.appendChild(box);
  $$("[data-rmgrant]", box).forEach(b => b.onclick = async () => { try { await api("/api/offline/grants/" + b.dataset.rmgrant, { method: "DELETE" }); toast("Download removed"); route._keepScroll = true; route(); } catch (e) { toast(e.message, true); } });
  $$("[data-rmdev]", box).forEach(b => b.onclick = async () => { if (!confirm("Remove this device? Its downloads are deleted the next time it connects.")) return;
    try { await api("/api/devices/" + b.dataset.rmdev, { method: "DELETE" }); toast("Device removed"); route._keepScroll = true; route(); } catch (e) { toast(e.message, true); } });
}

// Settings > Downloads (admin): limits, the transcode queue, and every user's devices and downloads
async function viewOfflineAdmin(v, html) {
  const d = await api("/api/admin/offline");
  const s = d.settings;
  const num = (id, val, lbl, hint, step) => `<label for="${id}">${lbl}</label><div><input type="number" id="${id}" value="${val}" min="0" step="${step || 1}" style="max-width:120px"> <span class="help">${hint}</span></div>`;
  const lim = (u) => u.role === "admin" ? `<span class="muted">unlimited (admin)</span>` : `${u.usage.titles}${u.limits.titles != null ? " / " + u.limits.titles : ""} titles · ${fmtSize(u.usage.bytes) || "0 B"}${u.limits.gb != null ? " / " + u.limits.gb + " GB" : ""} · ${u.usage.devices}${u.limits.devices != null ? " / " + u.limits.devices : ""} devices`;
  html += `<div class="panel" style="max-width:760px"><h3 style="margin-top:0">Offline downloads</h3>
    <p class="help" style="margin-top:0">People with the <b>Viewer + Downloads</b> role (and admins) can download films in the Movinite Android app to watch without internet. Downloads are encrypted in the app and carry a licence that renews whenever the app connects; you can take them back here at any time. This is trust-based protection for family and friends, not studio-grade DRM.</p>
    <label class="aw-row" for="of-on"><span class="sw"><input type="checkbox" id="of-on" ${s.enabled ? "checked" : ""}><i></i></span><span class="aw-txt"><b>Allow downloads</b><span class="aw-hint">Turning this off removes every download the next time each phone connects.</span></span></label>
    <div class="form of-form">
      ${num("of-titles", s.titles, "Titles per user", "0 = unlimited")}
      ${num("of-gb", s.gb, "GB per user", "0 = unlimited", "0.5")}
      ${num("of-dev", s.devices, "Devices per user", "0 = unlimited")}
      ${num("of-days", s.days, "Licence length (days)", "7 to 90; renewed on every sync")}
      ${num("of-wipe", s.wipe_days, "Offline sign-in window (days)", "7 to 90; after this long without reaching the server the app removes its downloads")}
      ${num("of-cache", s.cache_gb, "Prepared-file cache (GB)", `${fmtSize(d.cache.bytes) || "0 B"} used in ${d.cache.files} file${d.cache.files === 1 ? "" : "s"}; oldest are removed above this`)}
    </div><div class="err" id="of-err"></div><button class="btn" id="of-save">Save</button>
    <p class="help">Admins are always unlimited. Downloads in 1080p, 720p or 480p are prepared by the server on <b>${esc(d.encoder)}</b>, one at a time, and pause whenever someone is watching.</p></div>`;
  html += `<div class="panel" style="max-width:760px"><h3 style="margin-top:0">Being prepared</h3>${d.jobs.length ? `<div class="dl-grants">${d.jobs.map(j => `<div class="dl-g"><span class="dl-g-t">${esc(j.title || "#" + j.item_id)}</span><span class="chip pill">${esc(j.profile.replace(".hevc", " HEVC"))}</span>
      <span class="muted">${j.status === "failed" ? `<span class="dl-bad">failed: ${esc(j.error || "")}</span>` : j.status === "paused" ? "paused while someone watches · " + Math.round(100 * j.progress) + "%" : j.status === "running" ? `${Math.round(100 * j.progress)}% on ${esc((j.encoder || "").toUpperCase())}` : "waiting"} · ${j.waiting} waiting</span></div>`).join("")}</div>` : `<div class="muted">Nothing in the queue.</div>`}</div>`;
  html += `<div class="panel"><h3 style="margin-top:0">Users and devices</h3>${d.users.length ? d.users.map(u => `<div class="dl-user"><div class="row-head"><div><b>${esc(u.username)}</b> ${roleChip(u.role)} <span class="muted">${lim(u)}</span></div>
      ${u.role !== "admin" ? `<button class="btn ghost small" data-uplim="${u.id}">Limits</button>` : ""}</div>
      ${u.devices.length ? u.devices.map(dv => `<div class="dl-dev"><div class="row-head"><div>${esc(dv.name || "Android device")} <span class="muted">· app ${esc(dv.app_version || "?")} · last sync ${ago(dv.last_sync)} · key ${esc(dv.fp_short)}</span></div><button class="btn danger small" data-rmdev="${dv.id}">Remove device</button></div>${dlGrantRows(dv.grants, true)}</div>`).join("") : `<div class="muted dl-none">No devices set up.</div>`}</div>`).join("")
    : `<div class="muted">Nobody has the Viewer + Downloads role yet. Change a role in Users, or pick it when you invite someone.</div>`}</div>`;
  v.innerHTML = html;
  $("#of-save").onclick = async () => {
    try {
      await api("/api/settings/offline", { method: "PUT", body: { enabled: $("#of-on").checked, titles: +$("#of-titles").value, gb: +$("#of-gb").value, devices: +$("#of-dev").value,
        days: +$("#of-days").value, wipe_days: +$("#of-wipe").value, cache_gb: +$("#of-cache").value } });
      toast("Download settings saved"); $("#of-err").textContent = ""; route._keepScroll = true; route();
    } catch (e) { $("#of-err").textContent = e.message; }
  };
  $$("[data-rmgrant]", v).forEach(b => b.onclick = async () => { if (!confirm("Revoke this download? The phone deletes it the next time it connects.")) return;
    try { await api("/api/offline/grants/" + b.dataset.rmgrant, { method: "DELETE" }); toast("Download revoked"); route._keepScroll = true; route(); } catch (e) { toast(e.message, true); } });
  $$("[data-rmdev]", v).forEach(b => b.onclick = async () => { if (!confirm("Remove this device? All of its downloads are deleted the next time it connects.")) return;
    try { await api("/api/devices/" + b.dataset.rmdev, { method: "DELETE" }); toast("Device removed"); route._keepScroll = true; route(); } catch (e) { toast(e.message, true); } });
  $$("[data-uplim]", v).forEach(b => b.onclick = () => {
    const u = d.users.find(x => x.id === +b.dataset.uplim); const o = u.own_limits;
    const f = (id, val, lbl) => `<label for="${id}">${lbl}</label><input type="number" id="${id}" min="0" value="${val == null ? "" : val}" placeholder="server default">`;
    modal(`<h2>Download limits for ${esc(u.username)}</h2><div class="form">${f("ul-t", o.titles, "Titles")}${f("ul-g", o.gb, "GB")}${f("ul-d", o.devices, "Devices")}
      <div class="help">Leave empty to use the server default (${s.titles} titles, ${s.gb} GB, ${s.devices} devices). 0 = unlimited.</div></div><div class="err" id="ul-err"></div>
      <div class="modal-actions"><button class="btn ghost" id="ul-x">Cancel</button><button class="btn" id="ul-ok">Save</button></div>`, () => {
      $("#ul-x").onclick = closeModal;
      $("#ul-ok").onclick = async () => { const val = (id) => $(id).value === "" ? null : +$(id).value;
        try { await api(`/api/users/${u.id}/download-limits`, { method: "PUT", body: { titles: val("#ul-t"), gb: val("#ul-g"), devices: val("#ul-d") } }); closeModal(); toast("Limits saved"); route._keepScroll = true; route(); }
        catch (e) { $("#ul-err").textContent = e.message; } };
    });
  });
}

// ---------------------------------------------------------------- settings
// ---------------------------------------------------------------- 1.9: users, invites, Connect Gmail, devices, activity
const ROLE_NAMES = { admin: "Admin", download: "Viewer + Downloads", view: "Viewer" };
function roleChip(r) { return `<span class="role-chip r-${esc(r)}">${esc(ROLE_NAMES[r] || r)}</span>`; }
function fmtWhen(ts) { if (!ts) return ""; return new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }); }
async function copyText(t, okMsg) {
  try { await navigator.clipboard.writeText(t); toast(okMsg || "Copied"); }
  catch (e) { const ta = document.createElement("textarea"); ta.value = t; document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); toast(okMsg || "Copied"); } catch (e2) { toast("Copy failed; select the text and copy it", true); } ta.remove(); }
}
function libPicker(id, sel) {   // sel: null = all, or a list of library ids
  const all = sel == null;
  return `<div class="lib-pick" id="${id}"><label class="chk"><input type="checkbox" data-all ${all ? "checked" : ""}> <b>All libraries</b> <span class="help">(and any added later)</span></label>
    <div class="lib-pick-list${all ? " off" : ""}">${LIBS.map(l => `<label class="chk"><input type="checkbox" data-lib="${l.id}" ${all || (sel || []).includes(l.id) ? "checked" : ""} ${all ? "disabled" : ""}> ${esc(l.name)} <span class="help">${esc(l.kind)}</span></label>`).join("")}</div></div>`;
}
function bindLibPicker(id) {
  const root = $("#" + id); if (!root) return;
  const all = root.querySelector("[data-all]");
  all.onchange = () => { root.querySelector(".lib-pick-list").classList.toggle("off", all.checked); root.querySelectorAll("[data-lib]").forEach(c => { c.disabled = all.checked; if (all.checked) c.checked = true; }); };
}
function readLibPicker(id) {
  const root = $("#" + id);
  if (root.querySelector("[data-all]").checked) return { all_libraries: true };
  return { all_libraries: false, libraries: [...root.querySelectorAll("[data-lib]:checked")].map(c => +c.dataset.lib) };
}

function inviteResultDialog(r, email) {
  const sent = r.sent;
  modal(`<h2>${sent ? "Invite sent" : "Share this invite"}</h2>
    ${sent ? `<p>Sent to <b>${esc(email)}</b> from ${r.from ? `<b>${esc(r.from_name || "")}</b> &lt;${esc(r.from)}&gt;` : "your email"}. It's in your Sent folder too.</p>`
      : `${r.error ? `<p class="inv-warn">${esc(r.error)}</p>` : r.manual ? `<p class="muted">New link made; nothing was emailed and any earlier link for this invite stops working. Send <b>${esc(email)}</b> this link yourself, or let them scan the code.</p>` : `<p class="muted">Email sending isn't set up, so nothing was emailed. Send <b>${esc(email)}</b> this link yourself, or let them scan the code.</p>`}`}
    <div class="inv-share"><div class="inv-qr" aria-label="QR code for the invite link">${window.MSQR ? MSQR.svg(r.link, 200) : ""}</div>
      <div class="inv-linkbox"><label class="help">Invite link (works once)</label><textarea readonly id="inv-link" rows="3">${esc(r.link)}</textarea>
        <button class="btn" id="inv-copy">Copy link</button>${!sent && !r.manual && (r.reconnect || r.mail === "not_set_up" || r.mail === "disconnected" || r.mail === "needs_reconnect") ? `<a class="btn ghost" href="#/settings/email" id="inv-gm">${r.reconnect ? "Fix email settings" : "Set up email"}</a>` : ""}</div></div>
    <div class="modal-actions"><button class="btn ghost" id="inv-done">Done</button></div>`, () => {
    $("#inv-copy").onclick = () => copyText(r.link, "Invite link copied");
    $("#inv-done").onclick = () => { closeModal(); route(); };
    if ($("#inv-gm")) $("#inv-gm").onclick = () => closeModal();
  });
}

async function inviteDialog() {
  await refreshLibs();
  let ms = { ready: false };
  try { ms = (await api("/api/mail/status")) || ms; } catch (e) { /* not fatal */ }
  const from = ms.ready ? `<div class="inv-from ok"><span class="gm-dot ${ms.status === "auth_failed" || ms.status === "error" ? "warn" : ""}"></span>Will be sent from <b>${esc(ms.from_name || "")}</b> &lt;${esc(ms.from_addr)}&gt;</div>`
    : `<div class="inv-from"><span class="gm-dot off"></span>Email sending isn't set up. You'll get a link and QR code to share yourself. <a href="#/settings/email" id="inv-togm">Set up email</a></div>`;
  modal(`<h2>Invite someone</h2>${from}
    <div class="form"><label for="iv-email">Email</label><input type="text" id="iv-email" inputmode="email" autocomplete="off" placeholder="friend@example.com">
    <label for="iv-role">Role</label><select id="iv-role"><option value="view">Viewer — watch</option><option value="download">Viewer + Downloads — watch, and download for offline (Android app 2.0)</option></select>
    <label>Libraries</label>${libPicker("iv-libs", null)}
    <label for="iv-note">Personal note</label><textarea id="iv-note" rows="3" maxlength="500" placeholder="Optional — shown in the email"></textarea>
    <label for="iv-days">Link expires</label><select id="iv-days"><option value="1">in 24 hours</option><option value="3">in 3 days</option><option value="7" selected>in 7 days</option><option value="30">in 30 days</option></select></div>
    <div class="help">The link works once. Only a fingerprint of it is stored on the server.</div>
    <div class="err" id="iv-err"></div>
    <div class="modal-actions"><button class="btn ghost" id="iv-cancel">Cancel</button><button class="btn" id="iv-go">${ms.ready ? "Send invite" : "Create invite link"}</button></div>`, () => {
    bindLibPicker("iv-libs");
    $("#iv-cancel").onclick = closeModal;
    if ($("#inv-togm")) $("#inv-togm").onclick = () => closeModal();
    $("#iv-email").focus();
    $("#iv-go").onclick = async () => {
      const email = $("#iv-email").value.trim();
      const b = Object.assign({ email, role: $("#iv-role").value, note: $("#iv-note").value, days: +$("#iv-days").value }, readLibPicker("iv-libs"));
      $("#iv-go").disabled = true; $("#iv-go").textContent = ms.ready ? "Sending…" : "Creating…";
      try { const r = await api("/api/invites", { method: "POST", body: b }); inviteResultDialog(r, email); }
      catch (e) { $("#iv-err").textContent = e.message; $("#iv-go").disabled = false; $("#iv-go").textContent = ms.ready ? "Send invite" : "Create invite link"; }
    };
  });
}

function editUserDialog(x) {
  modal(`<h2>${esc(x.username)}</h2>
    <div class="form"><label for="eu-email">Email</label><input type="text" id="eu-email" value="${esc(x.email || "")}" placeholder="optional">
    <label for="eu-role">Role</label><select id="eu-role">${["view", "download", "admin"].map(r => `<option value="${r}" ${x.role === r ? "selected" : ""}>${ROLE_NAMES[r]}</option>`).join("")}</select>
    <label>Libraries</label><div id="eu-libwrap">${libPicker("eu-libs", x.libraries)}</div></div>
    <p class="help">Viewers can watch. Viewer + Downloads will also be able to download for offline use in the Android app (2.0). Admins can change settings, libraries and users, and always see every library.</p>
    <div class="err" id="eu-err"></div>
    <div class="modal-actions">${x.id !== ME.id ? `<button class="btn ghost" id="eu-dis">${x.disabled ? "Turn account on" : "Turn account off"}</button>` : ""}<span style="flex:1"></span><button class="btn ghost" id="eu-cancel">Cancel</button><button class="btn" id="eu-save">Save</button></div>`, () => {
    bindLibPicker("eu-libs");
    const syncAdmin = () => { $("#eu-libwrap").classList.toggle("off", $("#eu-role").value === "admin"); };
    $("#eu-role").onchange = syncAdmin; syncAdmin();
    $("#eu-cancel").onclick = closeModal;
    if ($("#eu-dis")) $("#eu-dis").onclick = async () => {
      if (!x.disabled && !confirm(`Turn off ${x.username}'s account? They are signed out everywhere and can't sign in until you turn it back on.`)) return;
      try { await api("/api/users/" + x.id, { method: "PUT", body: { disabled: !x.disabled } }); closeModal(); toast(x.disabled ? "Account turned on" : "Account turned off"); route(); } catch (e) { $("#eu-err").textContent = e.message; }
    };
    $("#eu-save").onclick = async () => {
      const b = Object.assign({ email: $("#eu-email").value.trim(), role: $("#eu-role").value }, $("#eu-role").value === "admin" ? {} : readLibPicker("eu-libs"));
      try { await api("/api/users/" + x.id, { method: "PUT", body: b }); closeModal(); toast("Saved"); route(); } catch (e) { $("#eu-err").textContent = e.message; }
    };
  });
}

async function devicesDialog(x) {
  const list = await api(`/api/users/${x.id}/sessions`);
  modal(`<h2>${esc(x.username)} — signed-in devices</h2>${deviceRows(list, true)}
    <div class="modal-actions">${list.length ? `<button class="btn danger" id="dv-all">Sign out everywhere</button>` : ""}<span style="flex:1"></span><button class="btn ghost" id="dv-close">Close</button></div>`, () => {
    $("#dv-close").onclick = closeModal;
    if ($("#dv-all")) $("#dv-all").onclick = async () => { try { await api(`/api/users/${x.id}/signout`, { method: "POST" }); toast("Signed out everywhere"); closeModal(); route(); } catch (e) { toast(e.message, true); } };
    $$("[data-endsess]").forEach(b => b.onclick = async () => { try { await api(`/api/users/${x.id}/sessions/${b.dataset.endsess}`, { method: "DELETE" }); b.closest(".dev-row").remove(); toast("Signed out"); } catch (e) { toast(e.message, true); } });
  });
}

const DEV_ICO = { phone: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="2.5" width="10" height="19" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M11 18.5h2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  desk: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="1.8" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M8.5 20h7M12 16v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>` };
function deviceRows(list, admin) {
  if (!list.length) return `<div class="muted">Not signed in anywhere.</div>`;
  return `<div class="dev-list">${list.map(s => `<div class="dev-row${s.current ? " cur" : ""}"><span class="dev-ic">${/Android|iPhone|app/.test(s.device) ? DEV_ICO.phone : DEV_ICO.desk}</span>
    <div class="dev-txt"><b>${esc(s.device)}</b>${s.current ? ` <span class="chip ok pill">this device</span>` : ""}<div class="help">${s.ip ? esc(s.ip) + " · " : ""}last active ${esc(ago(s.last_seen))} · signed in ${esc(fmtWhen(s.created_at))}</div></div>
    ${s.current && !admin ? "" : `<button class="btn ghost small" data-endsess="${esc(s.id)}">Sign out</button>`}</div>`).join("")}</div>`;
}

async function viewUsers(v, html) {
  const [users, inv] = await Promise.all([api("/api/users"), api("/api/invites")]);
  const pending = inv.invites.filter(i => i.state === "pending");
  const older = inv.invites.filter(i => i.state !== "pending").slice(0, 15);
  const ms = inv.mail || {};
  const gmLine = ms.ready && (ms.status === "auth_failed" || ms.status === "error" || ms.status === "needs_reconnect") ? `<span class="gm-dot warn"></span><b>Email sending has a problem</b> — invites fall back to a link you share. <a href="#/settings/email">Fix it</a>`
    : ms.ready ? `<span class="gm-dot"></span>Invites are sent from <b>${esc(ms.from_name || "")}</b> &lt;${esc(ms.from_addr)}&gt; · ${ms.sent_hour || 0}/${ms.hourly_cap} this hour`
    : `<span class="gm-dot off"></span>Email sending isn't set up — invites give you a link and QR code to share. <a href="#/settings/email">Set up email</a>`;
  html += `<div class="panel"><div class="row-head"><h3 style="margin:0">Users</h3><button class="btn" id="u-invite">+ Invite by email</button></div>
    <div class="gm-line">${gmLine}</div>
    <table class="users-tbl"><tr><th>User</th><th>Role</th><th>Libraries</th><th>Last active</th><th>Devices</th><th></th></tr>
    ${users.map(x => `<tr class="${x.disabled ? "u-off" : ""}"><td><b>${esc(x.username)}</b>${x.id === ME.id ? ` <span class="help">(you)</span>` : ""}${x.disabled ? ` <span class="chip bad pill">off</span>` : ""}${x.email ? `<div class="help">${esc(x.email)}</div>` : ""}</td>
      <td>${roleChip(x.role)}</td><td>${x.libraries == null ? `<span class="muted">All</span>` : esc(x.library_names.join(", ") || "none")}</td>
      <td>${x.last_seen ? esc(ago(x.last_seen)) : `<span class="muted">—</span>`}</td><td>${x.devices}</td>
      <td><div class="row-actions"><button class="btn ghost small" data-edit="${x.id}">Edit</button><button class="btn ghost small" data-dev="${x.id}">Devices</button><a class="btn ghost small" href="#/settings/activity" data-act="${x.id}">Activity</a><button class="btn ghost small" data-pw="${x.id}">Set password</button>${x.id !== ME.id ? `<button class="btn danger small" data-deluser="${x.id}">Delete</button>` : ""}</div></td></tr>`).join("")}</table></div>`;
  html += `<div class="panel"><h3 style="margin-top:0">Pending invites</h3>${pending.length ? `<table class="inv-tbl"><tr><th>Email</th><th>Role</th><th>Libraries</th><th>Sent</th><th>Expires</th><th></th></tr>
    ${pending.map(i => `<tr><td>${esc(i.email)}${i.note ? `<div class="help">“${esc(i.note.slice(0, 80))}${i.note.length > 80 ? "…" : ""}”</div>` : ""}</td><td>${roleChip(i.role)}</td><td>${i.libraries == null ? `<span class="muted">All</span>` : esc(i.library_names.join(", "))}</td>
      <td>${(i.sent_via === "gmail" || i.sent_via === "email") && i.sent_at ? `Emailed · ${esc(ago(i.sent_at))}` : i.send_error ? `<span class="inv-warn" title="${esc(i.send_error)}">not emailed</span>` : `link only`}</td><td>${esc(inTime(i.expires_at).replace("in ", ""))}</td>
      <td><div class="row-actions"><button class="btn ghost small" data-resend="${i.id}">${ms.ready ? "Resend" : "New link"}</button><button class="btn ghost small" data-newlink="${i.id}">Copy new link</button><button class="btn danger small" data-revoke="${i.id}">Revoke</button></div></td></tr>`).join("")}</table>`
    : `<div class="muted">None. Press <b>Invite by email</b> to add someone; they choose their own username and password.</div>`}
    ${older.length ? `<details class="inv-old"><summary>Earlier invites (${older.length})</summary><table><tr><th>Email</th><th>Role</th><th>Status</th><th>When</th></tr>${older.map(i => `<tr><td>${esc(i.email)}</td><td>${roleChip(i.role)}</td><td>${i.state === "accepted" ? `<span class="chip ok pill">joined as ${esc(i.accepted_username || "?")}</span>` : `<span class="chip pill">${esc(i.state)}</span>`}</td><td>${esc(fmtWhen(i.accepted_at || i.revoked_at || i.expires_at))}</td></tr>`).join("")}</table></details>` : ""}</div>`;
  html += `<details class="panel add-user"><summary><b>Add a user by hand</b> <span class="help">(you set the password; they change it at first sign-in)</span></summary>
    <div class="form" style="max-width:640px;margin-top:12px"><label>Username</label><input type="text" id="nu"><label>Password</label><input type="password" id="nup" autocomplete="new-password">
    <label>Email</label><input type="text" id="nue" placeholder="optional"><label for="nur">Role</label><select id="nur"><option value="view">Viewer</option><option value="download">Viewer + Downloads</option><option value="admin">Admin</option></select>
    <label>Libraries</label>${libPicker("nu-libs", null)}</div><div class="err" id="nuerr"></div><button class="btn" id="nuadd">Add user</button></details>`;
  v.innerHTML = html;
  bindLibPicker("nu-libs");
  $("#u-invite").onclick = () => inviteDialog();
  $("#nuadd").onclick = async () => { try { await api("/api/users", { method: "POST", body: Object.assign({ username: $("#nu").value, password: $("#nup").value, email: $("#nue").value, role: $("#nur").value }, readLibPicker("nu-libs")) }); toast("User added"); route(); } catch (e) { $("#nuerr").textContent = e.message; } };
  $$("[data-deluser]").forEach(b => b.onclick = async () => { if (!confirm("Delete this user? Their playlists and watch progress are removed too.")) return; try { await api("/api/users/" + b.dataset.deluser, { method: "DELETE" }); route(); } catch (e) { toast(e.message, true); } });
  $$("[data-pw]").forEach(b => b.onclick = async () => { const pw = prompt("New password (8+ characters). Other users must change it at next sign-in:"); if (!pw) return; try { await api(`/api/users/${b.dataset.pw}/password`, { method: "POST", body: { password: pw } }); toast("Password set"); } catch (e) { toast(e.message, true); } });
  $$("[data-edit]").forEach(b => b.onclick = () => editUserDialog(users.find(x => x.id === +b.dataset.edit)));
  $$("[data-dev]").forEach(b => b.onclick = () => devicesDialog(users.find(x => x.id === +b.dataset.dev)));
  $$("[data-act]").forEach(a => a.onclick = () => { sessionStorage.setItem("actFilter", JSON.stringify({ user: +a.dataset.act })); });
  $$("[data-revoke]").forEach(b => b.onclick = async () => { if (!confirm("Revoke this invite? The link stops working.")) return; try { await api("/api/invites/" + b.dataset.revoke, { method: "DELETE" }); toast("Invite revoked"); route(); } catch (e) { toast(e.message, true); } });
  $$("[data-resend]").forEach(b => b.onclick = async () => { const i = pending.find(x => x.id === +b.dataset.resend); try { const r = await api(`/api/invites/${i.id}/resend`, { method: "POST", body: { send: true } }); inviteResultDialog(r, i.email); } catch (e) { toast(e.message, true); } });
  $$("[data-newlink]").forEach(b => b.onclick = async () => { const i = pending.find(x => x.id === +b.dataset.newlink); if (!confirm("Make a new link for " + i.email + "? The old link stops working.")) return; try { const r = await api(`/api/invites/${i.id}/resend`, { method: "POST", body: { send: false } }); inviteResultDialog(r, i.email); } catch (e) { toast(e.message, true); } });
}

async function viewEmail(v, html, q) {
  const s = await api("/api/settings/email");
  const m = s.smtp || {};
  const isG = (m.provider || "gmail") === "gmail";
  const mchip = m.status === "ok" ? `<span class="chip ok pill">Working</span>` : m.status === "untested" ? `<span class="chip pill">Saved — not tested</span>`
    : m.status === "auth_failed" || m.status === "error" ? `<span class="chip warn pill">Problem</span>` : `<span class="chip pill">Not set up</span>`;
  const usingOAuth = s.mail_method === "gmail_oauth";
  html += `<div class="panel sm-panel"><div class="row-head"><h3 style="margin:0">Send invites from your email</h3>${usingOAuth ? `<span class="chip pill">Not in use — Connect Gmail is selected below</span>` : mchip}</div>
    <p class="help" style="margin-top:6px">Invites go out from your own address, so people see a name they know and replies come straight to you. The password is stored encrypted on this server and is never shown again.</p>
    ${m.last_error && !usingOAuth ? `<p class="inv-warn">${esc(m.last_error)}</p>` : ""}
    ${m.configured && !usingOAuth ? `<div class="gm-line"><span class="gm-dot ${m.status === "ok" ? "" : m.status === "untested" ? "off" : "warn"}"></span>Invites are sent as <b>${esc(m.from_name || m.suggested_from_name || "")}</b> &lt;${esc(m.from_addr)}&gt; · ${m.sent_hour}/${m.hourly_cap} this hour, ${m.sent_day}/${m.daily_cap} today${m.last_used ? " · last sent " + esc(ago(m.last_used)) : ""}</div>` : ""}
    <div class="form sm-form" style="max-width:760px">
      <label for="sm-prov">Send with</label><select id="sm-prov"><option value="gmail" ${isG ? "selected" : ""}>Gmail (app password)</option><option value="custom" ${isG ? "" : "selected"}>Other email (SMTP server)</option></select>
      <label for="sm-user" id="sm-user-l">${isG ? "Gmail address" : "Username"}</label><input type="text" id="sm-user" value="${esc(m.user || "")}" placeholder="${isG ? "you@gmail.com" : "you@example.com"}" autocomplete="off" spellcheck="false" inputmode="email">
      <label for="sm-pw" id="sm-pw-l">${isG ? "App password" : "Password"}</label><div><input type="password" id="sm-pw" placeholder="${m.password_saved ? "••••••••  saved — type to replace" : (isG ? "abcd efgh ijkl mnop" : "")}" autocomplete="new-password" spellcheck="false">
        <div class="help sm-g ${isG ? "" : "hidden"}">Not your normal Gmail password: a 16-letter <b>app password</b>. Turn on <b>2-Step Verification</b>, then create one at <a href="${esc(m.app_password_url)}" target="_blank" rel="noopener">myaccount.google.com/apppasswords</a> (name it "Movinite"). Spaces are fine. <a href="/static/gmail-setup.html" target="_blank" rel="noopener">Step-by-step guide</a></div></div>
      <label for="sm-name">From name</label><div><input type="text" id="sm-name" value="${esc(m.from_name || m.suggested_from_name || "")}" maxlength="80" placeholder="Your name"><div class="help">Shown as the sender, e.g. <b>${esc(m.from_name || m.suggested_from_name || "Your Name")}</b> &lt;${esc(m.from_addr || (isG ? "you@gmail.com" : "you@example.com"))}&gt;. Use the name on your Google account so people recognise it.</div></div>
      <label for="sm-host" class="sm-c ${isG ? "hidden" : ""}">SMTP server</label><input type="text" id="sm-host" class="sm-c ${isG ? "hidden" : ""}" value="${esc(isG ? "" : m.host || "")}" placeholder="smtp.example.com" spellcheck="false">
      <label for="sm-port" class="sm-c ${isG ? "hidden" : ""}">Port</label><input type="number" id="sm-port" class="sm-c ${isG ? "hidden" : ""}" min="1" max="65535" value="${esc(isG ? 587 : m.port || 587)}" style="max-width:120px">
      <label for="sm-sec" class="sm-c ${isG ? "hidden" : ""}">Security</label><select id="sm-sec" class="sm-c ${isG ? "hidden" : ""}">${[["starttls", "STARTTLS (usually port 587)"], ["ssl", "SSL/TLS (usually port 465)"], ["none", "None (not recommended)"]].map(([k, l]) => `<option value="${k}" ${(m.security || "starttls") === k && !isG ? "selected" : ""}>${l}</option>`).join("")}</select>
      <label for="sm-from" class="sm-c ${isG ? "hidden" : ""}">From address</label><input type="text" id="sm-from" class="sm-c ${isG ? "hidden" : ""}" value="${esc(isG ? "" : m.from_addr || "")}" placeholder="same as username" spellcheck="false">
    </div>
    <p class="help sm-g ${isG ? "" : "hidden"}">Gmail sends through <code>smtp.gmail.com:587</code> (STARTTLS). The From address is always your Gmail address, with replies going to it too.</p>
    ${m.crypto === false ? `<p class="inv-warn">This server is missing the Python <code>cryptography</code> package, so the password can't be stored safely. Re-run update.sh.</p>` : ""}
    <div class="err" id="sm-err"></div>
    <div class="gm-actions"><button class="btn" id="sm-save">Save</button><button class="btn ghost" id="sm-test" ${m.configured ? "" : "disabled"}>Send test email to myself</button>${m.configured || m.password_saved ? `<button class="btn ghost danger" id="sm-del">Remove</button>` : ""}</div>
  </div>`;
  html += `<div class="panel"><h3 style="margin-top:0">Invite links</h3><div class="form" style="max-width:760px">
    <label for="em-pub">Public address</label><div><input type="text" id="em-pub" value="${esc(s.public_url)}" placeholder="https://movies.example.com"><div class="help">Used in invite links (and the Connect Gmail redirect). Empty: the address you're using now (<code>${esc(s.effective_base_url)}</code>).</div></div>
    <label for="em-name">Server name</label><input type="text" id="em-name" value="${esc(s.server_name === "Movinite" ? "" : s.server_name)}" placeholder="Movinite" maxlength="60">
    <label for="em-hcap">Invites per hour</label><input type="number" id="em-hcap" min="1" max="2000" value="${s.hourly_cap}" style="max-width:120px">
    <label for="em-dcap">Invites per day</label><input type="number" id="em-dcap" min="1" max="2000" value="${s.daily_cap}" style="max-width:120px"></div>
    <div class="err" id="em-err"></div><button class="btn" id="em-save">Save</button></div>`;
  const me = s.me || {};
  let adv = "";
  if (q.connected) toast("Gmail connected" + (me.email ? " as " + me.email : ""));
  const st = me.status || "disconnected";
  const stChip = st === "connected" ? `<span class="chip ok pill">Connected</span>` : st === "needs_reconnect" ? `<span class="chip warn pill">Needs reconnect</span>` : `<span class="chip pill">Not connected</span>`;
  const credsOk = s.client_id && s.client_secret_saved;
  adv += `<div class="panel gm-panel"><div class="row-head"><h3 style="margin:0">Connect Gmail</h3>${stChip}</div>
    <p class="help" style="margin-top:6px">Invites go out from your own Gmail, so people see a name they know and replies come straight to you. Movinite can <b>only send</b> email — it can't read, search or delete your mail. Your Google password is never seen by Movinite.</p>
    ${st === "connected" ? `<div class="gm-who"><span class="gm-av">${esc((me.display_name || me.email || "?").slice(0, 1).toUpperCase())}</span><div><b>${esc(me.display_name || "")}</b><div class="help">${esc(me.email)} · connected ${esc(fmtWhen(me.connected_at))}${me.last_used ? " · last sent " + esc(ago(me.last_used)) : ""}</div><div class="help">Invites show as from <b>${esc(me.display_name || me.email)}</b> &lt;${esc(me.email)}&gt; (the name on this Google account). Sent: ${me.sent_hour}/${me.hourly_cap} this hour, ${me.sent_day}/${me.daily_cap} today.</div></div></div>
      <div class="gm-actions"><button class="btn ghost" id="gm-test">Send test invite to myself</button><button class="btn ghost" id="gm-re">Reconnect</button><button class="btn danger" id="gm-off">Disconnect Gmail</button></div>`
    : `${st === "needs_reconnect" && me.last_error ? `<p class="inv-warn">${esc(me.last_error)}</p>` : ""}
      <div class="gm-actions"><button class="btn gm-connect" id="gm-connect" ${credsOk ? "" : "disabled"}><span class="g-ic" aria-hidden="true">G</span>Connect Gmail</button>${credsOk ? "" : `<span class="help">Add the Google OAuth client below first.</span>`}</div>`}
    ${!s.redirect_ok && credsOk && st !== "connected" ? `<div class="gm-paste"><b>This page isn't open at an https address</b>, so Google can't send you straight back here.
      <ol><li>Open Movinite at its public https address, e.g. ${esc(s.public_url || "https://movies.example.com")}, and connect there, <b>or</b></li>
      <li>Use the copy-paste method: press <b>Connect with copy-paste</b>, sign in with Google, and when the browser ends on a page that can't load (address starting <code>${esc(s.paste_redirect_uri)}</code>), copy that whole address and paste it here.</li></ol>
      <button class="btn ghost" id="gm-pastego">Connect with copy-paste</button>
      <div class="gm-paste-in hidden" id="gm-pastebox"><input type="text" id="gm-pasteurl" placeholder="${esc(s.paste_redirect_uri)}?state=…&code=…"><button class="btn" id="gm-pastesave">Finish connecting</button></div><div class="err" id="gm-pasteerr"></div></div>` : ""}
    ${s.accounts && s.accounts.filter(a => a.user_id !== ME.id).length ? `<div class="help" style="margin-top:10px">Other admins: ${s.accounts.filter(a => a.user_id !== ME.id).map(a => `${esc(a.username)} (${esc(a.email)}, ${esc(a.status)})`).join(" · ")}</div>` : ""}
  </div>`;
  adv += `<div class="panel"><h3 style="margin-top:0">Google OAuth client (for Connect Gmail)</h3>
    <p class="help" style="margin-top:0">Each Movinite server uses its own free Google Cloud project for now (about 10 minutes, once). Follow <a href="/static/gmail-setup.html" target="_blank" rel="noopener" style="color:var(--acc-text)">the setup guide</a>, then paste the client ID and secret here. The secret is stored encrypted on this server and is never shown again.</p>
    <div class="form" style="max-width:760px"><label for="gm-cid">Client ID</label><input type="text" id="gm-cid" value="${esc(s.client_id)}" placeholder="1234567890-abc….apps.googleusercontent.com" autocomplete="off" spellcheck="false">
    <label for="gm-sec">Client secret</label><input type="password" id="gm-sec" placeholder="${s.client_secret_saved ? "••••••••  saved — type to replace" : "GOCSPX-…"}" autocomplete="new-password" spellcheck="false">
    <label>Redirect URI</label><div class="gm-uri"><code id="gm-uri">${esc(s.redirect_uri)}</code><button class="btn ghost small" data-copy="${esc(s.redirect_uri)}">Copy</button>${s.redirect_ok ? "" : ` <span class="chip warn pill" title="Google only accepts https addresses (or localhost)">not https</span>`}</div>
    <label>Also add</label><div class="gm-uri"><code>${esc(s.paste_redirect_uri)}</code><button class="btn ghost small" data-copy="${esc(s.paste_redirect_uri)}">Copy</button> <span class="help">for the copy-paste method</span></div>
    <label>Scopes</label><div class="help">${s.scopes.map(x => `<code>${esc(x)}</code>`).join(" ")}</div></div>
    ${s.crypto ? "" : `<p class="inv-warn">This server is missing the Python <code>cryptography</code> package, so secrets can't be stored safely. Re-run update.sh.</p>`}
    <div class="err" id="gm-err"></div><button class="btn" id="gm-save">Save credentials</button></div>`;
  html += `<details class="panel adv-mail" ${usingOAuth || q.connected ? "open" : ""}><summary><b>Advanced: Connect Gmail with Google sign-in (OAuth)</b> <span class="help">— instead of an app password; needs a Google Cloud project</span></summary>
    <div class="form" style="max-width:760px;margin-top:12px"><label>Send invites with</label><div class="mm-pick">
      <label class="chk"><input type="radio" name="mm" value="smtp" ${usingOAuth ? "" : "checked"}> App password / SMTP (above)</label>
      <label class="chk"><input type="radio" name="mm" value="gmail_oauth" ${usingOAuth ? "checked" : ""}> Connect Gmail (below)</label></div></div>
    ${adv}</details>`;
  v.innerHTML = html;
  const prov = () => $("#sm-prov").value;
  $("#sm-prov").onchange = () => {
    const g = prov() === "gmail";
    $$(".sm-c").forEach(e => e.classList.toggle("hidden", g)); $$(".sm-g").forEach(e => e.classList.toggle("hidden", !g));
    $("#sm-user-l").textContent = g ? "Gmail address" : "Username"; $("#sm-pw-l").textContent = g ? "App password" : "Password";
    $("#sm-user").placeholder = g ? "you@gmail.com" : "you@example.com";
  };
  $("#sm-save").onclick = async () => {
    const body = { provider: prov(), user: $("#sm-user").value.trim(), from_name: $("#sm-name").value.trim() };
    if ($("#sm-pw").value) body.password = $("#sm-pw").value;
    if (prov() === "custom") Object.assign(body, { host: $("#sm-host").value.trim(), port: +$("#sm-port").value, security: $("#sm-sec").value, from_addr: $("#sm-from").value.trim() });
    $("#sm-save").disabled = true;
    try { await api("/api/settings/smtp", { method: "PUT", body }); $("#sm-pw").value = ""; toast("Saved — press Send test email to check it"); route(); }
    catch (e) { $("#sm-err").textContent = e.message; } $("#sm-save").disabled = false;
  };
  $("#sm-test").onclick = async () => { $("#sm-test").disabled = true; $("#sm-err").textContent = ""; try { const r = await api("/api/smtp/test", { method: "POST" }); toast("Test email sent to " + r.to + " — check your inbox"); route(); } catch (e) { $("#sm-err").textContent = e.message; } $("#sm-test").disabled = false; };
  if ($("#sm-del")) $("#sm-del").onclick = async () => { if (!confirm("Remove the saved email address and password? Invites will give you a link to share instead.")) return; try { await api("/api/settings/smtp", { method: "DELETE" }); toast("Removed"); route(); } catch (e) { toast(e.message, true); } };
  $$("input[name=mm]").forEach(r => r.onchange = async () => { try { await api("/api/settings/email", { method: "PUT", body: { mail_method: r.value } }); toast(r.value === "smtp" ? "Invites use the app password / SMTP" : "Invites use Connect Gmail"); route(); } catch (e) { toast(e.message, true); } });
  $$("[data-copy]").forEach(b => b.onclick = () => copyText(b.dataset.copy, "Copied"));
  $("#gm-save").onclick = async () => { try { await api("/api/settings/email", { method: "PUT", body: { client_id: $("#gm-cid").value.trim(), client_secret: $("#gm-sec").value } }); $("#gm-sec").value = ""; toast("Credentials saved"); route(); } catch (e) { $("#gm-err").textContent = e.message; } };
  $("#em-save").onclick = async () => { try { await api("/api/settings/email", { method: "PUT", body: { public_url: $("#em-pub").value.trim(), server_name: $("#em-name").value.trim(), hourly_cap: +$("#em-hcap").value, daily_cap: +$("#em-dcap").value } }); toast("Saved"); route(); } catch (e) { $("#em-err").textContent = e.message; } };
  const go = async (paste) => { try { const r = await api("/api/gmail/connect", { method: "POST", body: { paste } }); if (paste) { $("#gm-pastebox").classList.remove("hidden"); window.open(r.url, "_blank", "noopener"); } else location.href = r.url; } catch (e) { toast(e.message, true); } };
  if ($("#gm-connect")) $("#gm-connect").onclick = () => go(!s.redirect_ok);
  if ($("#gm-re")) $("#gm-re").onclick = () => go(!s.redirect_ok);
  if ($("#gm-pastego")) $("#gm-pastego").onclick = () => go(true);
  if ($("#gm-pastesave")) $("#gm-pastesave").onclick = async () => { try { await api("/api/gmail/paste", { method: "POST", body: { url: $("#gm-pasteurl").value } }); toast("Gmail connected"); route(); } catch (e) { $("#gm-pasteerr").textContent = e.message; } };
  if ($("#gm-test")) $("#gm-test").onclick = async () => { $("#gm-test").disabled = true; try { const r = await api("/api/gmail/test", { method: "POST" }); toast("Test email sent to " + r.to); } catch (e) { toast(e.message, true); } $("#gm-test").disabled = false; };
  if ($("#gm-off")) $("#gm-off").onclick = async () => { if (!confirm("Disconnect Gmail? Movinite's access is revoked at Google and its saved sign-in is deleted.")) return; try { const r = await api("/api/gmail", { method: "DELETE" }); toast(r.revoked ? "Gmail disconnected" : "Disconnected here; also remove Movinite at myaccount.google.com > Security", !r.revoked); route(); } catch (e) { toast(e.message, true); } };
}

// ---- Settings > Activity
const UACT = {
  login: ["Signed in", "in"], login_failed: ["Sign-in failed", "warn"], logout: ["Signed out", "out"], password_changed: ["Changed password", "key"],
  session_revoked: ["Signed out a device", "out"], signed_out_everywhere: ["Signed out everywhere", "out"],
  play_start: ["Started", "play"], play_stop: ["Stopped", "stop"],
  invite_created: ["Created an invite", "mail"], invite_sent: ["Emailed an invite", "mail"], invite_send_failed: ["Invite email failed", "warn"], invite_accepted: ["Joined from an invite", "user"],
  invite_revoked: ["Revoked an invite", "mail"], user_created: ["Added a user", "user"], user_deleted: ["Deleted a user", "user"], role_changed: ["Changed a role", "user"],
  libraries_changed: ["Changed library access", "user"], user_disabled: ["Turned an account off", "user"], user_enabled: ["Turned an account on", "user"], password_reset: ["Set a password", "key"],
  gmail_connected: ["Connected Gmail", "mail"], gmail_disconnected: ["Disconnected Gmail", "mail"], gmail_error: ["Gmail problem", "warn"], email_error: ["Email sending problem", "warn"], email_test: ["Sent a test email", "mail"],
  library_added: ["Added a library", "lib"], library_removed: ["Removed a library", "lib"], scan_started: ["Started a scan", "lib"], settings_changed: ["Changed settings", "gear"], server_started: ["Server started", "gear"],
  device_registered: ["Set up a device for downloads", "dl"], device_revoked: ["Removed a download device", "dl"], download_requested: ["Asked to download", "dl"],
  download_ready: ["Download prepared", "dl"], download_started: ["Started downloading", "dl"], download_complete: ["Downloaded", "dl"],
  download_deleted: ["Deleted a download", "dl"], download_revoked: ["Download taken back", "warn"], download_failed: ["Download failed", "warn"]
};
const ACT_ICO = { dl: `<path d="M12 4v10.5M7.5 10l4.5 4.5 4.5-4.5M5 17v2h14v-2" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>`, play: `<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>`, stop: `<rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor"/>`,
  in: `<path d="M10 17l5-5-5-5M15 12H3M14 4h5a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>`,
  out: `<path d="M14 17l5-5-5-5M19 12H8M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>`,
  warn: `<path d="M12 4l9 16H3z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><path d="M12 10v4M12 17v.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
  key: `<circle cx="8" cy="12" r="3.5" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M11.5 12H20M17 12v3" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>`,
  mail: `<rect x="3" y="5.5" width="18" height="13" rx="2" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M3.5 7l8.5 6 8.5-6" fill="none" stroke="currentColor" stroke-width="1.9"/>`,
  user: `<circle cx="12" cy="8.5" r="3.6" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>`,
  lib: `<path d="M5 4v16M10 4v16M15 4.5l4.5 15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
  gear: `<circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>` };
function actIcon(k) { const t = (UACT[k] || [k, "gear"])[1]; return `<span class="act-ic t-${t}"><svg viewBox="0 0 24 24" aria-hidden="true">${ACT_ICO[t] || ACT_ICO.gear}</svg></span>`; }
function actDetail(e) {
  const d = e.detail || {};
  const bits = [];
  if (e.kind === "play_start" || e.kind === "play_stop") {
    if (d.mode) bits.push({ transcode: "Transcode", remux: "Remux", direct: "Direct play", music: "Music" }[d.mode] || d.mode);
    if (d.quality && d.quality !== "remux" && d.quality !== "audio") bits.push(d.quality);
    if (d.watched_s) bits.push("watched " + fmtLen(d.watched_s));
  }
  if ((e.kind || "").startsWith("download_") && d.quality) bits.push(d.quality);
  if ((e.kind || "").startsWith("download_") && d.bytes) bits.push(fmtSize(d.bytes));
  if (d.offline) bits.push("while offline");
  if (d.email) bits.push(d.email);
  if (d.username) bits.push(d.username);
  if (d.role) bits.push(ROLE_NAMES[d.role] || d.role);
  if (d.from && d.to) bits.push(`${ROLE_NAMES[d.from] || d.from} → ${ROLE_NAMES[d.to] || d.to}`);
  if (d.reason) bits.push(d.reason);
  if (d.keys) bits.push(d.keys.join(", "));
  if (d.devices != null) bits.push(d.devices + " device" + (d.devices === 1 ? "" : "s"));
  return bits.map(esc).join(" · ");
}
function actRow(e) {
  const what = (UACT[e.kind] || [e.kind])[0];
  return `<div class="act-row g-${esc(e.group)}">${actIcon(e.kind)}<div class="act-main"><div><b>${esc(e.actor || "Server")}</b> <span class="act-what">${esc(what)}</span>${e.title ? ` <span class="act-title">${esc(e.title)}</span>` : ""}</div>
    <div class="help">${esc(new Date(e.ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }))}${e.device ? " · " + esc(e.device) : ""}${e.ip ? " · " + esc(e.ip) : ""}${actDetail(e) ? " · " + actDetail(e) : ""}</div></div></div>`;
}
function actDays(events) {
  let out = "", last = "";
  const today = new Date().toDateString(), yest = new Date(Date.now() - 86400000).toDateString();
  for (const e of events) {
    const d = new Date(e.ts * 1000), k = d.toDateString();
    if (k !== last) { last = k; out += `<div class="act-day">${k === today ? "Today" : k === yest ? "Yesterday" : esc(d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }))}</div>`; }
    out += actRow(e);
  }
  return out;
}
function nowCard(n) {
  const it = n.item || {}, t = n.transcode;
  const title = it.show ? `${it.show} ${epCode(it)}` : it.title;
  const mode = n.mode === "transcode" || (t && t.profile !== "remux" && n.mode !== "direct") ? (t && t.encoder && t.encoder !== "cpu" ? `<span class="hw-badge">GPU</span> Transcode` : "Transcode (CPU)") : n.mode === "remux" ? "Remux" : n.mode === "music" ? "Music" : "Direct play";
  const pct = n.progress != null ? Math.max(0, Math.min(100, n.progress * 100)) : null;
  return `<div class="np-card"><div class="np-art"${it.poster || it.thumb ? ` style="background-image:url('${thumbUrl(it.poster || it.thumb)}')"` : ""}></div>
    <div class="np-txt"><div class="np-title">${esc(title || "?")}</div><div class="np-user"><span class="gm-av sm">${esc((n.username || "?").slice(0, 1).toUpperCase())}</span>${esc(n.username || "?")}</div>
    <div class="help">${mode}${n.profile && n.profile !== "remux" && n.profile !== "audio" ? " · " + esc(n.profile) : ""}${t && t.paused ? " · buffered ahead" : ""}</div>
    <div class="help">${esc(n.device || "")}${n.ip ? " · " + esc(n.ip) : ""} · ${esc(fmtLen(Math.max(1, Date.now() / 1000 - n.started)))}</div>
    ${pct != null ? `<div class="np-bar"><i style="width:${pct.toFixed(1)}%"></i></div>` : ""}</div>
    <button class="iconbtn np-stop" title="Stop this stream" aria-label="Stop ${esc(n.username)}'s stream" data-npstop="${n.user_id}:${it.id}">&#9632;</button></div>`;
}
async function viewUserActivity(v, html) {
  let f = {}; try { f = JSON.parse(sessionStorage.getItem("actFilter") || "{}"); } catch (e) { f = {}; }
  const qs = () => { const p = new URLSearchParams(); if (f.user) p.set("user", f.user); if (f.group) p.set("group", f.group); if (f.q) p.set("q", f.q);
    if (f.from) p.set("since", Math.floor(new Date(f.from + "T00:00").getTime() / 1000)); if (f.to) p.set("until", Math.floor(new Date(f.to + "T00:00").getTime() / 1000) + 86400); return p.toString(); };
  const [now, list, sum, users] = await Promise.all([api("/api/admin/activity/now"), api("/api/admin/activity?limit=100&" + qs()), api("/api/admin/activity/summary?days=30"), api("/api/users")]);
  html += `<div class="panel np-panel"><div class="row-head"><h3 style="margin:0">Now playing</h3><span class="help" id="np-count">${now.now.length ? now.now.length + " stream" + (now.now.length === 1 ? "" : "s") : ""}</span></div>
    <div class="np-grid" id="np-grid">${now.now.length ? now.now.map(nowCard).join("") : `<div class="muted">Nothing is playing right now.</div>`}</div></div>`;
  html += `<div class="panel"><h3 style="margin-top:0">Last 30 days</h3><div class="act-sum">${sum.users.map(x => `<button class="act-user${f.user === x.id ? " on" : ""}" data-fuser="${x.id}"><span class="gm-av sm">${esc(x.username.slice(0, 1).toUpperCase())}</span><span><b>${esc(x.username)}</b><span class="help">${x.plays} play${x.plays === 1 ? "" : "s"} · ${x.hours} h · ${x.last_active ? esc(ago(x.last_active)) : "never"}</span></span></button>`).join("")}</div></div>`;
  html += `<div class="panel"><div class="act-filters">
      <select id="af-user" aria-label="User"><option value="">Everyone</option>${users.map(x => `<option value="${x.id}" ${f.user === x.id ? "selected" : ""}>${esc(x.username)}</option>`).join("")}</select>
      <select id="af-group" aria-label="Type"><option value="">All activity</option>${[["playback", "Playback"], ["signin", "Sign-ins"], ["accounts", "Users & invites"], ["downloads", "Downloads"], ["server", "Server"]].map(([k, n]) => `<option value="${k}" ${f.group === k ? "selected" : ""}>${n}</option>`).join("")}</select>
      <input type="date" id="af-from" value="${esc(f.from || "")}" aria-label="From"><input type="date" id="af-to" value="${esc(f.to || "")}" aria-label="To">
      <input type="search" id="af-q" value="${esc(f.q || "")}" placeholder="Search titles, devices, IPs" aria-label="Search">
      <a class="btn ghost small" id="af-csv" href="/api/admin/activity/export.csv?${esc(qs())}" download>Export CSV</a></div>
    <div class="act-list" id="act-list">${list.events.length ? actDays(list.events) : `<div class="muted" style="padding:14px 0">No activity${qs() ? " matches these filters" : " yet"}.</div>`}</div>
    ${list.more ? `<button class="btn ghost" id="act-more">Show older</button>` : ""}
    <div class="act-ret"><label for="af-ret">Keep activity for</label><select id="af-ret">${[[30, "30 days"], [90, "90 days"], [180, "180 days"], [365, "1 year"], [0, "forever"]].map(([d, n]) => `<option value="${d}" ${list.retention_days === d ? "selected" : ""}>${n}</option>`).join("")}</select>
      <span class="help">Failed sign-ins are kept 30 days, and IP addresses are cleared after 30 days.</span></div></div>`;
  v.innerHTML = html;
  const setF = (k, val) => { if (val === "" || val == null) delete f[k]; else f[k] = val; sessionStorage.setItem("actFilter", JSON.stringify(f)); route._keepScroll = true; route(); };
  $("#af-user").onchange = (e) => setF("user", e.target.value ? +e.target.value : "");
  $("#af-group").onchange = (e) => setF("group", e.target.value);
  $("#af-from").onchange = (e) => setF("from", e.target.value);
  $("#af-to").onchange = (e) => setF("to", e.target.value);
  let qt; $("#af-q").oninput = (e) => { clearTimeout(qt); qt = setTimeout(() => setF("q", e.target.value.trim()), 400); };
  $$("[data-fuser]").forEach(b => b.onclick = () => setF("user", f.user === +b.dataset.fuser ? "" : +b.dataset.fuser));
  $("#af-ret").onchange = async (e) => { try { await api("/api/admin/activity/settings", { method: "PUT", body: { retention_days: +e.target.value } }); toast("Saved"); } catch (err) { toast(err.message, true); } };
  let oldest = list.events.length ? list.events[list.events.length - 1].id : 0, shown = list.events.slice();
  if ($("#act-more")) $("#act-more").onclick = async () => { const r = await api(`/api/admin/activity?limit=100&before_id=${oldest}&` + qs()); shown = shown.concat(r.events); if (r.events.length) oldest = r.events[r.events.length - 1].id; $("#act-list").innerHTML = actDays(shown); if (!r.more) $("#act-more").remove(); };
  const bindStops = () => $$("[data-npstop]").forEach(b => b.onclick = async () => { const [uid, iid] = b.dataset.npstop.split(":").map(Number); if (!confirm("Stop this stream?")) return; try { await api("/api/admin/activity/stop", { method: "POST", body: { user_id: uid, item_id: iid } }); toast("Stream stopped"); } catch (e) { toast(e.message, true); } });
  bindStops();
  const tok = route._token;
  route._poll = setInterval(async () => {
    if (route._token !== tok || document.hidden) return;
    try { const n = await api("/api/admin/activity/now"); if (route._token !== tok) return;
      $("#np-grid").innerHTML = n.now.length ? n.now.map(nowCard).join("") : `<div class="muted">Nothing is playing right now.</div>`;
      $("#np-count").textContent = n.now.length ? n.now.length + " stream" + (n.now.length === 1 ? "" : "s") : ""; bindStops(); } catch (e) { /* ignore */ }
  }, 5000);
}

async function accountExtras(v) {
  const [sess, act] = await Promise.all([api("/api/me/sessions"), api("/api/me/activity?limit=15")]);
  const box = document.createElement("div");
  box.innerHTML = `<div class="panel" style="max-width:760px"><div class="row-head"><h3 style="margin:0">Signed-in devices</h3>${sess.length > 1 ? `<button class="btn ghost small" id="dv-others">Sign out all other devices</button>` : ""}</div>
    <p class="help">Phones, tablets and browsers signed in to your account. Sign out any you don't recognise, then change your password.</p>${deviceRows(sess, false)}</div>
    <div class="panel" style="max-width:760px"><h3 style="margin-top:0">My recent activity</h3><div class="act-list">${act.events.length ? actDays(act.events) : `<div class="muted">Nothing yet.</div>`}</div>
    <p class="help">Admins can see activity on this server, including what you play. It is kept ${act.retention_days ? act.retention_days + " days" : "until an admin clears it"}.</p></div>`;
  const ref = v.querySelector(".panel:nth-of-type(2)");
  v.insertBefore(box, ref ? ref.nextSibling : null);
  if ($("#dv-others")) $("#dv-others").onclick = async () => { try { const r = await api("/api/me/sessions/others", { method: "POST" }); toast(`Signed out ${r.signed_out} other device${r.signed_out === 1 ? "" : "s"}`); route(); } catch (e) { toast(e.message, true); } };
  $$("[data-endsess]", box).forEach(b => b.onclick = async () => { try { await api("/api/me/sessions/" + b.dataset.endsess, { method: "DELETE" }); b.closest(".dev-row").remove(); toast("Signed out"); } catch (e) { toast(e.message, true); } });
}

async function networkPanel(v) {
  const n = await api("/api/settings/network");
  const box = document.createElement("div");
  box.className = "panel"; box.id = "net-panel";
  box.innerHTML = `<h3 style="margin-top:0">Reverse proxy</h3>
    <p class="help" style="margin-top:0">If Movinite sits behind a proxy (for example OpenResty or nginx, with Cloudflare in front), list the proxy's address so the server sees each visitor's real address. Sign-in limits and Activity use it.</p>
    ${n.untrusted_proxy ? `<div class="inv-warn">Requests are arriving through <b>${esc(n.untrusted_proxy.ip)}</b> with forwarded-address headers, but it isn't trusted yet, so every visitor looks like ${esc(n.untrusted_proxy.ip)}. <button class="btn small" id="net-trust" data-ip="${esc(n.untrusted_proxy.ip)}">Trust ${esc(n.untrusted_proxy.ip)}</button></div>` : ""}
    <div class="form" style="max-width:760px"><label for="net-tp">Trusted proxies</label><div><input type="text" id="net-tp" value="${esc(n.trusted_proxies)}" placeholder="e.g. 192.0.2.10"><div class="help">IP addresses or networks, comma-separated. 127.0.0.1 is always trusted${n.env ? `; also from .env: ${esc(n.env)}` : ""}.</div></div>
    <label>You are seen as</label><b>${esc(n.your_ip)}${n.peer && n.peer !== n.your_ip ? ` <span class="help">(via ${esc(n.peer)})</span>` : ""}</b></div>
    <div class="err" id="net-err"></div><button class="btn" id="net-save">Save</button>`;
  v.appendChild(box);
  const save = async (spec) => { try { await api("/api/settings/network", { method: "PUT", body: { trusted_proxies: spec } }); toast("Saved"); route(); } catch (e) { $("#net-err").textContent = e.message; } };
  $("#net-save").onclick = () => save($("#net-tp").value.trim());
  if ($("#net-trust")) $("#net-trust").onclick = (e) => { const cur = $("#net-tp").value.trim(); save(cur ? cur + ", " + e.target.dataset.ip : e.target.dataset.ip); };
}

// ---- the page an invited person opens (no sign-in needed)
async function showJoin(token) {
  stopAll();
  let p;
  try { p = await api("/api/invite/" + enc(token), { noAuthRedirect: true }); }
  catch (e) { showAuth(`<div class="auth-box join-box"><h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1><h2 class="auth-h">Invite not valid</h2><p class="muted">${esc(e.message)}</p><button class="btn" id="jn-login">Go to sign in</button></div>`);
    $("#jn-login").onclick = () => { location.hash = "#/home"; boot(); }; return; }
  const libs = p.all_libraries ? "all libraries" : p.libraries.join(", ");
  showAuth(`<form class="auth-box join-box" id="joinf"><h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1>
    <h2 class="auth-h">${esc(p.inviter)} invited you</h2><div class="muted">to ${esc(p.server)} as <b>${esc(p.role_label)}</b> · ${esc(libs)}</div>
    ${p.note ? `<div class="join-note">${esc(p.note)}</div>` : ""}
    <label>Email</label><input type="text" value="${esc(p.email)}" disabled>
    <label for="ju">Choose a username</label><input type="text" id="ju" autocomplete="username" value="${esc((p.email.split("@")[0] || "").replace(/[^A-Za-z0-9._-]/g, "").slice(0, 40))}">
    <label for="jp">Choose a password (8+ characters)</label><input type="password" id="jp" autocomplete="new-password">
    <label for="jp2">Repeat password</label><input type="password" id="jp2" autocomplete="new-password">
    <button class="btn" type="submit">Join</button><div class="err" id="jerr"></div>
    <div class="help" style="margin-top:8px">This invite works once and expires ${esc(fmtWhen(p.expires_at))}. You can sign in later with your username or your email.</div></form>`);
  $("#joinf").onsubmit = async (e) => {
    e.preventDefault();
    if ($("#jp").value !== $("#jp2").value) { $("#jerr").textContent = "Passwords do not match"; return; }
    try { await api("/api/invite/" + enc(token) + "/accept", { method: "POST", body: { username: $("#ju").value.trim(), password: $("#jp").value }, noAuthRedirect: true });
      history.replaceState(null, "", "/#/home"); boot(); }
    catch (err) { $("#jerr").textContent = err.message; }
  };
}


// ---------------------------------------------------------------- 2.1 Settings > Sharing
async function viewSharing() {
  const d = await api("/api/sharing");
  const me = d.me || {};
  const libs = d.libraries || [];
  const peers = d.peers || [];
  const codes = d.codes || [];
  const remote = d.remote || [];
  const outgoing = peers.filter(p => p.status === "active" && (p.direction === "outgoing" || p.direction === "both") && (p.grants || []).length);
  const fmtLim = (g) => [g.max_quality, g.max_streams ? g.max_streams + " streams" : "", g.can_download ? "downloads on" : ""].filter(Boolean).join(" · ");
  const peerCard = (p) => `<div class="panel share-card" data-peer="${p.id}">
    <div class="row-head"><h3 style="margin:0">${esc(p.name || "Server")}</h3>
      <span class="muted">${esc(p.fingerprint || "")}${p.live_streams ? " · " + p.live_streams + " live" : ""}</span></div>
    <p class="muted" style="margin:0 0 8px">${esc(p.url || "No address")} · ${esc(p.status)}</p>
    ${(p.grants || []).map(g => `<div class="share-grant">${esc(g.name)} <span class="muted">${esc(fmtLim(g))}</span></div>`).join("")}
    <div class="row-head" style="margin-top:10px"><button class="btn danger" data-stop="${p.id}">Stop sharing</button></div>
  </div>`;
  const remCard = (r) => `<div class="panel share-card" data-remote="${r.id}">
    <div class="row-head"><h3 style="margin:0">${esc(r.name)}</h3><span class="chip">${esc(r.peer_name || "Shared")}</span></div>
    <p class="muted" style="margin:0 0 8px">${r.item_count || 0} titles · ${r.online ? "online" : "offline"}${r.last_sync ? " · synced " + agoShort(Math.max(0, (Date.now()/1000) - r.last_sync)) : ""}</p>
    <div class="row-head"><button class="btn" data-rsync="${r.id}">Sync now</button>
      <button class="btn danger" data-rremove="${r.id}">Remove</button></div>
  </div>`;
  const pending = codes.filter(c => c.status === "pending");
  return `<div class="panel"><div class="row-head"><h3 style="margin:0">This server</h3></div>
      <p class="help" style="margin-top:0">Share a library with another Movinite server by sending a one-time link. After that, the two servers trust each other with a signed identity (no central service). Public addresses must use HTTPS; a LAN address may use plain HTTP.</p>
      <form id="share-name" class="row-head" style="gap:8px;align-items:center">
        <label class="muted">Name</label>
        <input name="name" value="${esc(me.name || "")}" maxlength="80" style="max-width:16em">
        <button class="btn" type="submit">Save</button>
        <span class="muted">${esc(me.fingerprint || "")}</span>
      </form>
    </div>
    <div class="panel"><div class="row-head"><h3 style="margin:0">Libraries I share</h3>
      <button class="btn" id="share-make">Share libraries</button></div>
      ${outgoing.length ? outgoing.map(peerCard).join("") : `<p class="muted">You are not sharing any libraries yet.</p>`}
      ${pending.length ? `<p class="muted" style="margin-top:12px">Unused share links</p>` + pending.map(c => `<div class="share-grant">${(c.libraries||[]).map(l=>esc(l.name)).join(", ")} · expires ${c.expires_at ? new Date(c.expires_at*1000).toLocaleString() : ""} <button class="btn small danger" data-revcode="${c.id}">Revoke</button></div>`).join("") : ""}
    </div>
    <div class="panel"><div class="row-head"><h3 style="margin:0">Shared with me</h3>
      <button class="btn" id="share-add">Add a shared library</button></div>
      ${remote.length ? remote.map(remCard).join("") : `<p class="muted">No libraries from other servers yet.</p>`}
    </div>
    <div id="share-wiz"></div>`;
}
function bindSharing() {
  const box = $("#share-wiz");
  const redraw = () => route();
  const form = $("#share-name");
  if (form) form.onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/sharing/name", { method: "PUT", body: { name: form.name.value } }); toast("Server name saved"); redraw(); }
    catch (err) { toast(err.message || "Could not save the name", true); }
  };
  const make = $("#share-make");
  if (make) make.onclick = async () => {
    const d = await api("/api/sharing");
    const libs = d.libraries || [];
    box.innerHTML = `<div class="panel"><h3 style="margin-top:0">Share libraries</h3>
      <p class="help">Tick the libraries, choose whether the other server can only stream or also download, then create a link. It works once and expires in 48 hours.</p>
      ${libs.map(l => `<label class="aw-row"><input type="checkbox" name="slib" value="${l.id}"> ${esc(l.name)}</label>`).join("") || "<p class='muted'>No libraries yet.</p>"}
      <p><label class="muted">Permission</label>
        <select id="share-perm"><option value="stream">Stream</option><option value="download">Stream + Download</option></select>
        <label class="muted" style="margin-left:12px">Max quality</label>
        <select id="share-q"><option>1080p</option><option>720p</option><option>480p</option><option value="original">Original / 4K</option></select>
      </p>
      <button class="btn" id="share-go">Create share link</button>
      <button class="btn ghost" id="share-cancel">Cancel</button>
      <div id="share-result"></div>
    </div>`;
    $("#share-cancel").onclick = () => { box.innerHTML = ""; };
    $("#share-go").onclick = async () => {
      const ids = $$("input[name=slib]:checked").map(x => +x.value);
      if (!ids.length) { toast("Pick at least one library", true); return; }
      try {
        const r = await api("/api/sharing/codes", { method: "POST", body: {
          libraries: ids, perms: $("#share-perm").value, max_quality: $("#share-q").value
        }});
        const link = r.link || "";
        $("#share-result").innerHTML = `<p>Send this link or the code <b class="share-code">${esc(r.code)}</b></p>
          <p><input readonly value="${esc(link)}" style="width:100%" id="share-link"><button class="btn" id="share-copy">Copy link</button></p>
          <p class="muted">This server's fingerprint is ${esc(r.fingerprint || "")}. The code expires in 48 hours and can be used once.</p>`;
        $("#share-copy").onclick = async () => { try { await navigator.clipboard.writeText(link); toast("Link copied"); } catch (_) { $("#share-link").select(); } };
      } catch (err) { toast(err.message || "Could not create a link", true); }
    };
  };
  const add = $("#share-add");
  if (add) add.onclick = () => {
    box.innerHTML = `<div class="panel"><h3 style="margin-top:0">Add a shared library</h3>
      <p class="help">Paste the share link, or the other server's address and the code.</p>
      <p><input id="share-in-link" placeholder="https://media.example.com/#/share/7K3Q-M9PX-2TQA" style="width:100%"></p>
      <p class="muted">or</p>
      <p><input id="share-in-url" placeholder="https://media.example.com" style="width:60%">
         <input id="share-in-code" placeholder="7K3Q-M9PX-2TQA" style="width:35%"></p>
      <button class="btn" id="share-preview">Continue</button>
      <button class="btn ghost" id="share-cancel2">Cancel</button>
      <div id="share-prev"></div>
    </div>`;
    $("#share-cancel2").onclick = () => { box.innerHTML = ""; };
    $("#share-preview").onclick = async () => {
      try {
        const r = await api("/api/sharing/accept", { method: "POST", body: {
          link: $("#share-in-link").value, url: $("#share-in-url").value, code: $("#share-in-code").value
        }});
        const h = r.hello || {};
        const offered = (h.offered || []).map(l => `${esc(l.name)} (${l.item_count || 0})`).join(", ");
        $("#share-prev").innerHTML = `<p><b>${esc(h.name || "Other server")}</b> wants to share: ${offered || "no libraries"}.</p>
          <p class="muted">Fingerprint ${esc(h.fingerprint || "")}</p>
          <button class="btn" id="share-confirm">Accept</button>`;
        $("#share-confirm").onclick = async () => {
          try {
            await api("/api/sharing/accept", { method: "POST", body: {
              link: $("#share-in-link").value, url: r.url || $("#share-in-url").value, code: $("#share-in-code").value,
              confirm: true, my_url: location.origin
            }});
            toast("Libraries added");
            redraw();
          } catch (err) { toast(err.message || "Could not accept", true); }
        };
      } catch (err) { toast(err.message || "Could not reach the other server", true); }
    };
  };
  $$("[data-stop]").forEach(b => b.onclick = async () => {
    if (!confirm("Stop sharing with this server? Playback tickets fail right away.")) return;
    try { await api("/api/sharing/peers/" + b.dataset.stop + "/stop", { method: "POST", body: {} }); toast("Sharing stopped"); redraw(); }
    catch (err) { toast(err.message || "Could not stop sharing", true); }
  });
  $$("[data-revcode]").forEach(b => b.onclick = async () => {
    try { await api("/api/sharing/codes/" + b.dataset.revcode, { method: "DELETE" }); toast("Link revoked"); redraw(); }
    catch (err) { toast(err.message || "Could not revoke", true); }
  });
  $$("[data-rremove]").forEach(b => b.onclick = async () => {
    if (!confirm("Remove this shared library from this server?")) return;
    try { await api("/api/sharing/remote/" + b.dataset.rremove, { method: "DELETE" }); toast("Removed"); redraw(); }
    catch (err) { toast(err.message || "Could not remove", true); }
  });
  $$("[data-rsync]").forEach(b => b.onclick = async () => {
    try { await api("/api/sharing/remote/" + b.dataset.rsync + "/sync", { method: "POST", body: {} }); toast("Catalog updated"); redraw(); }
    catch (err) { toast(err.message || "Sync failed", true); }
  });
}


async function viewSettings(tab) {
  // 1.4.9: non-admins only see their own tabs.  1.5.5: Poster Sounds has its own tab (for everyone).
  // 1.6: fixed left-to-right order; viewers get the same relative order; an unknown / hidden tab opens the first one
  // 1.9: + Activity (users) and Email (Connect Gmail); "Scan activity" is now "Scans"
  const tq = {}; if (tab && tab.includes("?")) { new URLSearchParams(tab.split("?")[1]).forEach((v, k) => { tq[k] = v; }); tab = tab.split("?")[0]; }
  const ALL_TABS = [["libraries", "Libraries", 1], ["scans", "Scans", 1], ["activity", "Activity", 1], ["sounds", "Poster Sounds", 0], ["metadata", "Metadata", 1],
    ["transcoding", "Transcoding", 1], ["users", "Users", 1], ["downloads", "Downloads", 1], ["sharing", "Sharing", 1], ["email", "Email", 1], ["account", "My account", 0], ["system", "System", 1]];
  const tabs = ALL_TABS.filter(t => ME.is_admin || !t[2]).map(t => [t[0], t[1]]);
  if (!tabs.some(t => t[0] === tab)) tab = tabs[0][0];
  let html = `<h2>Settings</h2><div class="tabs set-tabs" role="tablist" aria-label="Settings sections">${tabs.map(([k, n]) => `<button role="tab" aria-selected="${k === tab}" class="${k === tab ? "on" : ""}" data-href="#/settings/${k}">${n}</button>`).join("")}</div>`;
  const v = $("#view");
  if (tab === "libraries") {
    await refreshLibs();
    html += `<div class="panel"><div class="row-head"><h3 style="margin:0">Libraries</h3>${ME.is_admin ? `<button class="btn" id="addlib">+ Add library</button>` : ""}</div>
      ${LIBS.length ? `<div class="tbl-wrap"><table class="lib-tbl"><tr>${ME.is_admin && LIBS.length > 1 ? `<th class="ord-h" title="Drag a row, or use the arrows, to change the order libraries are listed in everywhere">Order</th>` : ""}<th>Name</th><th>Type</th><th>Source</th><th>Items</th><th>Last scan</th><th>Auto scan</th><th></th></tr>
      ${libGroups().map((g, gi, GS) => {
        const cols = (ME.is_admin && LIBS.length > 1 ? 1 : 0) + 7;
        const w = g.share ? groupHealthLib(g) : null;
        const head = !libsGrouped() ? "" : `<tr class="grp-row" data-grp="${g.key}"><td colspan="${cols}"><div class="grp-h"><span class="ng-ic" aria-hidden="true">${g.share ? ICO_SHARE : ICO_LOCAL}</span><b>${esc(g.name)}</b>${w ? shareDot(w) : ""}<span class="muted grp-sub">${g.share ? "network share" : "folders on this server"} · ${g.libs.length} librar${g.libs.length > 1 ? "ies" : "y"}</span>
          ${ME.is_admin && g.share ? `<button class="btn ghost small" data-renshare="${g.share.id}" title="Change the name shown for this share in the side menu">Rename</button>` : ""}
          ${ME.is_admin && GS.length > 1 ? `<span class="grp-mv"><button class="iconbtn small" data-gup="${g.key}" title="Move this group up" aria-label="Move ${esc(g.name)} up" ${gi === 0 ? "disabled" : ""}>&#9650;</button><button class="iconbtn small" data-gdown="${g.key}" title="Move this group down" aria-label="Move ${esc(g.name)} down" ${gi === GS.length - 1 ? "disabled" : ""}>&#9660;</button></span>` : ""}</div></td></tr>`;
        return head + g.libs.map((l, li) => {
        const sc = l.scan || {}; const busy = sc.state === "scanning" || sc.state === "queued";
        const src = l.share ? `<div class="src-share"><span class="src-kind">${l.share.kind.toUpperCase()}</span> <span class="path">${wbrPath(l.share.remote)}</span> ${l.share.mounted ? `<span class="chip ok pill">mounted &middot; ${l.share.mount_mode === "rw" ? "writable" : "read-only"}</span>` : `<span class="chip bad pill">not mounted</span>`}</div>${l.share.last_error ? `<div class="help" style="color:var(--bad)">${esc(l.share.last_error)}</div>` : ""}` : esc(l.path) + (l.online ? "" : ` <span class="chip bad">offline</span>`);
        const ord = ME.is_admin && LIBS.length > 1 ? `<td class="ord"><span class="drag" title="Drag to move" aria-hidden="true">&#8942;&#8942;</span>
          <button class="iconbtn small" data-up="${l.id}" title="Move up" aria-label="Move ${esc(l.name)} up" ${li === 0 ? "disabled" : ""}>&#9650;</button><button class="iconbtn small" data-down="${l.id}" title="Move down" aria-label="Move ${esc(l.name)} down" ${li === g.libs.length - 1 ? "disabled" : ""}>&#9660;</button></td>` : "";
        return `<tr data-lib="${l.id}" data-grp="${g.key}"${ord ? ` draggable="true"` : ""}>${ord}<td><a href="#/library/${l.id}"><b>${esc(l.name)}</b></a></td><td>${l.kind}</td><td class="src">${src}<div class="help path">${wbrPath(l.path)}</div></td><td>${l.item_count}</td>
        <td>${busy ? `scanning ${sc.done || 0}/${sc.total || "?"}<div class="prog"><div style="width:${sc.total ? 100 * sc.done / sc.total : 5}%"></div></div>` : ago(l.last_scan) + `<div class="help">${esc(l.last_scan_result || "")}</div>`}</td>
        <td>${intervalName(l.scan_interval_h)}${l.next_scan && !busy ? `<div class="help">next ${inTime(l.next_scan)}</div>` : ""}</td>
        <td>${ME.is_admin ? `<div class="row-actions"><button class="btn ghost small" data-scan="${l.id}">Scan</button><button class="btn ghost small" data-full="${l.id}" title="Re-probe every file and regenerate thumbnails">Full rescan</button>
          <span class="sep"></span>${l.share ? `<button class="btn ghost small" data-remount="${l.share.id}">Remount</button><button class="btn ghost small" data-editshare="${l.share.id}">Credentials</button>` : ""}
          ${l.kind === "movies" || l.kind === "tv" ? `<button class="btn ghost small" data-artwork="${l.id}" title="Save posters / fanart / .nfo into the ${l.kind === "tv" ? "show" : "movie"} folders">Artwork${l.art_write ? " &#10003;" : ""}</button>` : ""}
          <button class="btn ghost small" data-editlib="${l.id}">Edit</button><button class="btn danger small" data-dellib="${l.id}">Remove</button></div>` : ""}</td></tr>`; }).join(""); }).join("")}</table></div>${libsGrouped() ? `<div class="help" style="margin-top:8px">Libraries are grouped by the share they are on. Use the arrows on a share's heading to move the whole group; a library moves within its group.</div>` : ""}` : `<div class="empty">No libraries yet.</div>`}</div>`;
    v.innerHTML = html;
    if ($("#addlib")) $("#addlib").onclick = () => addLibraryDialog();
    $$("[data-scan]").forEach(b => b.onclick = async () => { await api(`/api/libraries/${b.dataset.scan}/scan`, { method: "POST" }); toast("Scan queued"); pollActivity(); route._keepScroll = true; route(); });
    $$("[data-full]").forEach(b => b.onclick = async () => { await api(`/api/libraries/${b.dataset.full}/scan?full=true`, { method: "POST" }); toast("Full rescan queued"); pollActivity(); route._keepScroll = true; route(); });
    $$("[data-remount]").forEach(b => b.onclick = async () => { b.disabled = true; try { await api(`/api/shares/${b.dataset.remount}/remount`, { method: "POST" }); toast("Share mounted"); } catch (e) { toast(e.message, true); } route._keepScroll = true; route(); });
    $$("[data-editshare]").forEach(b => b.onclick = () => editShareDialog(LIBS.find(l => l.share && l.share.id === +b.dataset.editshare).share));
    $$("[data-editlib]").forEach(b => b.onclick = () => editLibraryDialog(LIBS.find(l => l.id === +b.dataset.editlib)));
    $$("[data-artwork]").forEach(b => b.onclick = () => artworkDialog(LIBS.find(l => l.id === +b.dataset.artwork)));
    $$("[data-dellib]").forEach(b => b.onclick = async () => {
      const l = LIBS.find(x => x.id === +b.dataset.dellib);
      if (!confirm(`Remove library "${l.name}"? Your media files are NOT deleted; only the library entry${l.share ? " and the share mount" : ""}.`)) return;
      await api("/api/libraries/" + l.id, { method: "DELETE" }); toast("Library removed"); await refreshLibs(); route();
    });
    // 1.6: library order -- drag a row (desktop) or the up / down arrows (touch, phone); one order for everyone
    const saveOrder = async (ids) => {
      try { LIBS = await api("/api/libraries/order", { method: "PUT", body: { ids } }); await refreshLibs(); toast("Library order saved"); }
      catch (e) { toast(e.message, true); }
      route._keepScroll = true; route();
    };
    // 1.7: the order is saved group by group (a share's libraries stay together)
    const flat = (gs) => gs.flatMap(g => g.libs.map(l => l.id));
    const ids0 = () => flat(libGroups());
    const move = (id, d) => {
      const gs = libGroups(), g = gs.find(x => x.libs.some(l => l.id === id)); if (!g) return;
      const i = g.libs.findIndex(l => l.id === id), j = i + d; if (j < 0 || j >= g.libs.length) return;
      [g.libs[i], g.libs[j]] = [g.libs[j], g.libs[i]]; saveOrder(flat(gs));
    };
    const gmove = (key, d) => { const gs = libGroups(), i = gs.findIndex(g => g.key === key), j = i + d; if (i < 0 || j < 0 || j >= gs.length) return; [gs[i], gs[j]] = [gs[j], gs[i]]; saveOrder(flat(gs)); };
    $$("[data-up]").forEach(b => b.onclick = () => move(+b.dataset.up, -1));
    $$("[data-down]").forEach(b => b.onclick = () => move(+b.dataset.down, 1));
    $$("[data-gup]").forEach(b => b.onclick = () => gmove(b.dataset.gup, -1));
    $$("[data-gdown]").forEach(b => b.onclick = () => gmove(b.dataset.gdown, 1));
    $$("[data-renshare]").forEach(b => b.onclick = () => {
      const s = (LIBS.find(l => l.share && l.share.id === +b.dataset.renshare) || {}).share; if (!s) return;
      modal(`<h2>Rename share</h2><div class="form"><label for="rs-name">Name shown in the side menu</label><input type="text" id="rs-name" maxlength="60" value="${esc(s.name || "")}">
        <div class="help">Only the label changes. The share's address, login and write setting stay as they are.</div></div>
        <div class="err" id="rs-err"></div><div class="modal-actions"><button class="btn ghost" id="rs-cancel">Cancel</button><button class="btn" id="rs-save">Save</button></div>`,
        () => { $("#rs-name").focus(); $("#rs-name").select(); });
      $("#rs-cancel").onclick = closeModal;
      $("#rs-save").onclick = async () => {
        try { await api(`/api/shares/${s.id}/name`, { method: "PUT", body: { name: $("#rs-name").value } }); closeModal(); toast("Share renamed"); await refreshLibs(); route._keepScroll = true; route(); }
        catch (e) { $("#rs-err").textContent = e.message; }
      };
    });
    let dragId = null;
    $$(".lib-tbl tr[draggable]").forEach(tr => {
      tr.addEventListener("dragstart", (e) => { dragId = +tr.dataset.lib; viewSettings._drag = true; tr.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", String(dragId)); } catch (_) {} });
      tr.addEventListener("dragend", () => { viewSettings._drag = false; tr.classList.remove("dragging"); $$(".lib-tbl tr.drop-before, .lib-tbl tr.drop-after").forEach(x => x.classList.remove("drop-before", "drop-after")); });
      tr.addEventListener("dragover", (e) => {
        if (dragId == null) return;
        const src = $(`.lib-tbl tr[data-lib="${dragId}"]`); if (src && src.dataset.grp !== tr.dataset.grp) return;   // 1.7: stay in the share's group
        e.preventDefault();
        const r = tr.getBoundingClientRect(), after = e.clientY > r.top + r.height / 2;
        $$(".lib-tbl tr.drop-before, .lib-tbl tr.drop-after").forEach(x => x.classList.remove("drop-before", "drop-after"));
        tr.classList.add(after ? "drop-after" : "drop-before");
      });
      tr.addEventListener("drop", (e) => {
        e.preventDefault(); const target = +tr.dataset.lib, after = tr.classList.contains("drop-after");
        viewSettings._drag = false;
        if (dragId == null || dragId === target) { dragId = null; return; }
        const src = $(`.lib-tbl tr[data-lib="${dragId}"]`); if (src && src.dataset.grp !== tr.dataset.grp) { dragId = null; return; }
        const ids = ids0().filter(i => i !== dragId); let k = ids.indexOf(target); if (after) k++;
        ids.splice(k, 0, dragId); dragId = null; saveOrder(ids);
      });
    });
    route._live = { every: 3000, fn: () => { if (!$(".modal:not(.hidden)") && !viewSettings._drag) { route._keepScroll = true; route(); } } };
  } else if (tab === "scans") {
    v.innerHTML = html + `<div id="scans-panel"><div class="muted">Loading...</div></div>`;
    const tok = route._token;
    const draw = async () => {
      const [libs, act] = await Promise.all([api("/api/libraries"), api("/api/activity")]);
      if (tok !== route._token) return;
      const logsArr = await Promise.all(libs.map(l => api(`/api/libraries/${l.id}/scan/log?n=40`).catch(() => [])));
      if (tok !== route._token || !$("#scans-panel")) return;
      const stuck = {}; $$(".scanlog").forEach(el => { stuck[el.dataset.lib] = el.scrollHeight - el.scrollTop - el.clientHeight > 30 ? el.scrollTop : null; });
      $("#scans-panel").innerHTML = libs.length ? libs.map((l, i) => {
        const st = l.scan || {}, busy = st.state === "scanning" || st.state === "queued";
        const m = act.metadata.find(x => x.library_id === l.id) || l.meta;
        const pct = scanPct(st);
        const el = st.started_at ? ((st.finished_at || act.now) - st.started_at) : 0;
        const chip = busy ? `<span class="chip warn">${st.state === "queued" ? "queued" : st.cancel ? "cancelling" : st.phase === "discovering" ? "discovering files" : "processing"}</span>`
          : st.state === "error" ? `<span class="chip bad">error</span>` : st.state === "cancelled" ? `<span class="chip">cancelled</span>` : st.state === "done" ? `<span class="chip ok">done</span>` : `<span class="chip">idle</span>`;
        const stat = (k, v) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`;
        const lines = logsArr[i] || [];
        return `<div class="panel"><div class="row-head"><h3 style="margin:0">${KIND_ICON[l.kind] || ""} ${esc(l.name)} ${chip}</h3>
          <div class="tools">${busy ? `<button class="btn danger small" data-cancel="${l.id}" ${st.cancel ? "disabled" : ""}>Cancel scan</button>`
            : `<button class="btn ghost small" data-scan="${l.id}">Scan now</button><button class="btn ghost small" data-full="${l.id}">Full rescan</button>`}</div></div>
          ${busy ? `<div style="margin:12px 0 4px">${scanText(st, false)}</div><div class="prog wide"><div class="${pct == null ? "indet" : ""}" style="${pct == null ? "" : `width:${pct}%`}"></div></div>`
            : `<div class="help" style="margin-top:8px">Last scan: ${ago(l.last_scan)}${l.last_scan_result ? " &middot; " + esc(l.last_scan_result) : ""}${l.next_scan ? " &middot; next " + inTime(l.next_scan) : " &middot; automatic scans off"}</div>`}
          ${st.started_at ? `<div class="stats">${stat("files found", nf(st.found))}${stat("new / changed", nf(st.total))}${stat("unchanged (skipped)", nf(st.unchanged))}${stat("processed", nf(st.done))}
            ${stat("added", nf(st.added))}${stat("updated", nf(st.updated))}${stat("removed", nf(st.removed))}${stat("errors", nf(st.errors))}
            ${stat("files / min", busy ? nf(st.rate_per_min) : "-")}${stat("ETA", busy && st.eta_s ? fmtEta(st.eta_s) : "-")}${stat("elapsed", fmtEta(el) || "-")}${stat("workers", st.workers || "-")}</div>` : ""}
          ${busy && st.current && st.current.length ? `<div class="help">Working on: ${esc(st.current.join(" · "))}</div>` : ""}
          ${st.last_error ? `<div class="help" style="color:var(--bad);margin-top:6px">Last error: ${esc(st.last_error)}</div>` : ""}
          ${m && (l.kind === "movies" || l.kind === "tv") ? `<div class="help" style="margin-top:6px">Posters (TMDB): ${m.state === "running" || m.state === "queued" ? metaText(m, false) : m.state === "error" ? `<span style="color:var(--bad)">${esc(m.error || "error")}</span>` : "idle"}${l.meta_counts ? ` &middot; ${nf(l.meta_counts.matched)} of ${nf(l.meta_counts.total)} ${l.meta_counts.unit} matched` : ""}${l.meta_counts && l.meta_counts.review ? ` &middot; <a style="color:var(--acc-text)" href="#/library/${l.id}" onclick="sessionStorage.setItem('filt${l.id}','review')">${nf(l.meta_counts.review)} need review</a>` : ""}</div>` : ""}
          ${(() => { const aw = (act.artwork || []).find(x => x.library_id === l.id) || l.artwork; if (!aw) return "";
            const run = aw.state === "running" || aw.state === "queued";
            return `<div class="help" style="margin-top:6px">Artwork to folders: ${run ? artText(aw, false) + ` <button class="btn danger small" data-awstop="${l.id}">Stop</button>` : aw.state === "error" ? `<span style="color:var(--bad)">${esc(aw.error || "error")}</span>` : aw.state + ` &middot; ${nf(aw.written)} files written, ${nf(aw.skipped)} skipped${aw.errors ? ", " + nf(aw.errors) + " errors" : ""}`}${aw.last_error ? ` <span style="color:var(--bad)">(${esc(aw.last_error)})</span>` : ""}</div>`; })()}
          ${lines.length ? `<details ${busy || stuck[l.id] !== undefined ? "open" : ""}><summary class="help" style="cursor:pointer;margin-top:10px">Recent log (${lines.length})</summary>
            <div class="scanlog" data-lib="${l.id}">${lines.map(x => `<div class="ll ${x.level}"><span>${new Date(x.t * 1000).toLocaleTimeString()}</span> ${esc(x.msg)}</div>`).join("")}</div></details>` : ""}
        </div>`; }).join("") : `<div class="empty">No libraries yet.</div>`;
      $$(".scanlog").forEach(el => { const k = stuck[el.dataset.lib]; el.scrollTop = k == null ? el.scrollHeight : k; });
      $$("[data-awstop]").forEach(b => b.onclick = async () => { b.disabled = true; await api(`/api/libraries/${b.dataset.awstop}/artwork/cancel`, { method: "POST" }); toast("Stopping..."); });
      $$("[data-cancel]").forEach(b => b.onclick = async () => { if (!confirm("Stop this scan? Items found so far are kept.")) return; b.disabled = true; try { await api(`/api/libraries/${b.dataset.cancel}/scan/cancel`, { method: "POST" }); toast("Cancelling..."); } catch (e) { toast(e.message, true); } draw(); });
      $$("#scans-panel [data-scan]").forEach(b => b.onclick = async () => { await api(`/api/libraries/${b.dataset.scan}/scan`, { method: "POST" }); toast("Scan queued"); pollActivity(); draw(); });
      $$("#scans-panel [data-full]").forEach(b => b.onclick = async () => { if (!confirm("Re-read every file and regenerate thumbnails? This takes a while on big libraries.")) return; await api(`/api/libraries/${b.dataset.full}/scan?full=true`, { method: "POST" }); toast("Full rescan queued"); pollActivity(); draw(); });
    };
    await draw();
    route._live = { every: 2000, fn: draw };
  } else if (tab === "metadata") {
    const [st, libs] = [await api("/api/settings"), await api("/api/libraries")];
    const mlibs = libs.filter(l => l.kind === "movies" || l.kind === "tv");
    const pend = (l) => l.meta_counts && l.meta_counts.pending ? `<div class="help" style="color:var(--warn,#e0a03a)">${nf(l.meta_counts.pending)} not looked up yet</div>` : "";
    const metaCell = (l) => { const m = l.meta; if (!m) return l.meta_counts && l.meta_counts.total ? `${nf(l.meta_counts.matched)} of ${nf(l.meta_counts.total)} ${l.meta_counts.unit} matched${pend(l)}` : `<span class="muted">-</span>`;
      if (m.state === "running" || m.state === "queued") return `matching ${m.done || 0}/${m.total || "?"}<div class="prog"><div style="width:${m.total ? 100 * m.done / m.total : 5}%"></div></div>`;
      if (m.state === "error") return `<span style="color:var(--bad)">${esc(m.error || "error")}</span>`;
      const c = l.meta_counts;
      return `${c ? `${nf(c.matched)} of ${nf(c.total)} ${c.unit}` : `${m.matched || 0} of ${m.total || 0}`} matched <div class="help">${ago(m.finished_at)}</div>${pend(l)}`; };
    html += `<div class="panel" style="max-width:760px"><h3 style="margin-top:0">TMDB (posters, descriptions, episode titles)</h3>
      <p class="help" style="margin-top:0">Get a free key at <a style="color:var(--acc-text)" href="https://www.themoviedb.org/settings/api" target="_blank" rel="noopener">themoviedb.org/settings/api</a> (sign up, then Settings &rarr; API). Paste either the <b>API Key</b> (v3) or the <b>API Read Access Token</b> (v4). Without a key, titles come from the file and folder names.</p>
      <div class="form"><label>API key or token</label><div><input type="password" id="tk" autocomplete="off" placeholder="${st.tmdb_key_set ? "saved: " + esc(st.tmdb_key_masked) + (st.tmdb_key_source === "env" ? " (from .env)" : "") + " -- paste a new one to replace" : "paste your TMDB key"}"></div>
      <label>Language</label><input type="text" id="tl" value="${esc(st.tmdb_language)}" placeholder="en-US" style="max-width:140px">
      <label for="te">Use TMDB</label><label class="chk"><input type="checkbox" id="te" ${st.tmdb_enabled ? "checked" : ""}> <span class="help">turn off to show file names only (the key stays saved)</span></label></div>
      <div class="err" id="tkerr"></div>
      <div class="actions" style="margin-bottom:0"><button class="btn" id="tksave">Save</button><button class="btn ghost" id="tktest">Test key</button>
      ${st.tmdb_key_source === "settings" ? `<button class="btn danger" id="tkdel">Remove key</button>` : ""}</div>${TMDB_NOTE}</div>
      <div class="panel"><h3 style="margin-top:0">Libraries</h3>${mlibs.length ? `<table><tr><th>Library</th><th>Type</th><th>Items</th><th>Metadata</th><th></th></tr>
      ${mlibs.map(l => `<tr><td><b>${esc(l.name)}</b></td><td>${l.kind}</td><td>${l.item_count}</td><td>${metaCell(l)}</td>
        <td style="white-space:nowrap"><button class="btn small" data-matchmeta="${l.id}" ${st.tmdb_key_set && st.tmdb_enabled && !(l.meta && (l.meta.state === "running" || l.meta.state === "queued")) ? "" : "disabled"} title="Look up only titles that have no metadata yet">Match missing</button>
        <button class="btn ghost small" data-refmeta="${l.id}" ${st.tmdb_key_set && st.tmdb_enabled ? "" : "disabled"} title="Re-download metadata for every title (manual matches are kept)">Refresh metadata</button></td></tr>`).join("")}</table>`
        : `<div class="muted">No movie or TV libraries.</div>`}
      <p class="help">New and changed files are matched automatically after each scan. Use <b>Fix match</b> on a movie or show page when TMDB picked the wrong title.</p></div>`;
    v.innerHTML = html;
    const save = async (body) => { $("#tkerr").textContent = ""; $("#tksave").disabled = true;
      try { await api("/api/settings", { method: "PUT", body }); toast("Saved"); route._keepScroll = true; route(); }
      catch (e) { $("#tkerr").textContent = e.message; $("#tksave").disabled = false; } };
    $("#tksave").onclick = () => { const b = { tmdb_language: $("#tl").value.trim() || "en-US", tmdb_enabled: $("#te").checked }; if ($("#tk").value.trim()) b.tmdb_key = $("#tk").value.trim(); save(b); };
    $("#tktest").onclick = async () => { $("#tkerr").textContent = ""; $("#tktest").disabled = true;
      try { const r = await api("/api/settings/tmdb-test", { method: "POST", body: { tmdb_key: $("#tk").value.trim() } }); r.ok ? toast("TMDB key works") : ($("#tkerr").textContent = r.message); }
      catch (e) { $("#tkerr").textContent = e.message; } $("#tktest").disabled = false; };
    if ($("#tkdel")) $("#tkdel").onclick = () => { if (confirm("Remove the saved TMDB key? Already-downloaded posters and descriptions stay.")) save({ tmdb_key: "" }); };
    $$("[data-matchmeta]").forEach(b => b.onclick = async () => { b.disabled = true; try { const r = await api(`/api/libraries/${b.dataset.matchmeta}/match-metadata`, { method: "POST" }); toast(r.queued ? "Looking up posters" : "Already running"); pollActivity(); } catch (e) { toast(e.message, true); } route._keepScroll = true; route(); });
    $$("[data-refmeta]").forEach(b => b.onclick = async () => { b.disabled = true; try { await api(`/api/libraries/${b.dataset.refmeta}/refresh-metadata`, { method: "POST" }); toast("Refreshing metadata"); } catch (e) { toast(e.message, true); } route._keepScroll = true; route(); });
    if (mlibs.some(l => l.meta && (l.meta.state === "running" || l.meta.state === "queued")))
      route._poll = setInterval(() => { if (!document.activeElement || document.activeElement.tagName !== "INPUT") { route._keepScroll = true; route(); } }, 3000);
  } else if (tab === "account") {
    const capOn = qualityCapOn(), capNow = capBaseFromPx(displayLongPx()) || "1080p";
    const capHint = `This device is about ${displayLongPx() || "?"} pixels on the long side, so the cap is ${capNow}. A 1080p-class tablet will not be sent 4K, even if that quality was saved earlier. Turn this off to allow a higher quality here.`;
    html += `<div class="panel" style="max-width:560px"><h3 style="margin-top:0">Sign out</h3>
      <p class="help">Sign out of Movinite on this device. On a television you can also open the account button in the top-right corner.</p>
      <button class="btn danger" type="button" id="acct-page-logout" tabindex="0">Sign out</button></div>`;
    html += `<div class="panel" style="max-width:560px"><h3 style="margin-top:0">This device</h3>
      <label class="aw-row" for="qcap-on"><span class="sw"><input type="checkbox" id="qcap-on" ${capOn ? "checked" : ""}><i></i></span><span class="aw-txt"><b>Cap quality to this screen</b><span class="aw-hint">${capHint}</span></span></label>
      <label for="d4k">This display</label>
      <select id="d4k">${[["auto","Auto (recommended)"],["on","This is a 4K display"],["off","This is 1080p or smaller"]].map(([k,l]) => `<option value="${k}" ${display4kPref()===k?"selected":""}>${l}</option>`).join("")}</select>
      <div class="help">A 4K television's web view often reports 1920×1080. Auto treats a TV as 4K so 4K remux and transcode stay available. Saved in this browser.</div></div>`;
    const asi = !!(ME && ME.auto_skip_intro), asc = !!(ME && ME.auto_skip_credits);
    html += `<div class="panel" style="max-width:560px"><h3 style="margin-top:0">Playback</h3>
      <label class="aw-row" for="askip-i"><span class="sw"><input type="checkbox" id="askip-i" ${asi ? "checked" : ""}><i></i></span><span class="aw-txt"><b>Auto-skip intros</b><span class="aw-hint">When an opening is detected, jump past it. A Skip Intro button still appears if this is off. Saved for your account on every device.</span></span></label>
      <label class="aw-row" for="askip-c"><span class="sw"><input type="checkbox" id="askip-c" ${asc ? "checked" : ""}><i></i></span><span class="aw-txt"><b>Auto-skip credits</b><span class="aw-hint">When the credits start, show the Up Next card (or jump to the end if there is no next episode). Saved for your account.</span></span></label></div>`;
    html += `<div class="panel" style="max-width:560px"><h3 style="margin-top:0">Change password</h3><div class="form">
      <label>Current password</label><input type="password" id="cp"><label>New password</label><input type="password" id="np" autocomplete="new-password">
      <label>Repeat</label><input type="password" id="np2" autocomplete="new-password"></div><div class="err" id="cperr"></div>
      <button class="btn" id="cpsave">Change password</button></div>`;
    html += `<p class="help" style="max-width:560px">Sounds for posters and buttons are in <a style="color:var(--acc-text)" href="#/settings/sounds">Poster Sounds</a>.</p>`;
    v.innerHTML = html;
    $("#acct-page-logout").onclick = () => $("#logout").click();
    accountExtras(v).then(() => accountDownloads(v)).catch(() => {});
    $("#qcap-on").onchange = () => { setQualityCap($("#qcap-on").checked); toast($("#qcap-on").checked ? "Quality will be capped to this screen" : "Screen cap off on this device"); };
    if ($("#d4k")) $("#d4k").onchange = () => { setDisplay4k($("#d4k").value); toast($("#d4k").value === "on" ? "This display is treated as 4K" : $("#d4k").value === "off" ? "This display is treated as 1080p or smaller" : "Display size is automatic"); };
    const saveSkip = async (el, key, onMsg, offMsg) => {
      const on = el.checked;
      try {
        const r = await api("/api/me/prefs", { method: "PUT", body: { [key]: on ? 1 : 0 } });
        if (ME) { ME.auto_skip_intro = r.auto_skip_intro; ME.auto_skip_credits = r.auto_skip_credits; }
        toast(on ? onMsg : offMsg);
      } catch (e) { el.checked = !on; toast(e.message, true); }
    };
    if ($("#askip-i")) $("#askip-i").onchange = () => saveSkip($("#askip-i"), "auto_skip_intro", "Intros will be skipped automatically", "Intros will not be skipped automatically");
    if ($("#askip-c")) $("#askip-c").onchange = () => saveSkip($("#askip-c"), "auto_skip_credits", "Credits will open Up Next automatically", "Credits will not be skipped automatically");
    $("#cpsave").onclick = async () => {
      if ($("#np").value !== $("#np2").value) { $("#cperr").textContent = "Passwords do not match"; return; }
      try { await api("/api/me/password", { method: "POST", body: { current_password: $("#cp").value, new_password: $("#np").value } }); toast("Password changed"); $("#cperr").textContent = ""; ["#cp", "#np", "#np2"].forEach(s => $(s).value = ""); }
      catch (e) { $("#cperr").textContent = e.message; }
    };
  } else if (tab === "sounds") {
    const so = SFX.get();
    const swr = (id, on, title, hint) => `<label class="aw-row" for="${id}"><span class="sw"><input type="checkbox" id="${id}" ${on ? "checked" : ""}><i></i></span><span class="aw-txt"><b>${title}</b><span class="aw-hint">${hint}</span></span></label>`;
    html += `<div class="panel snd-panel" style="max-width:560px"><h3 style="margin-top:0">Poster Sounds</h3>
      <p class="help" style="margin-top:0">Little sounds as you browse: a tick when you move onto a poster, a chime when you open a movie or show, a rising tone for Play and a swish for the row arrows. Made in the browser; never while a video plays.</p>
      ${swr("snd-on", so.on, "Poster sounds", "All of the sounds below. Also switched with the speaker button in the top bar and in your account menu.")}
      ${swr("snd-hover", so.hover, "Hover sounds", SFX.COARSE ? "A soft tick when the mouse moves onto a poster (not on touch screens, so off on this device)." : "A soft tick when the mouse moves onto a poster or you Tab to one.")}
      ${swr("snd-select", so.select, "Select sounds", "A chime when you open a movie, a rising tone for Play / Resume and a swish for the < > row buttons.")}
      <div class="aw-row aw-static snd-vol"><span class="snd-vol-l">Volume</span><input type="range" id="snd-vol" min="0" max="100" step="5" value="${Math.round(so.vol * 100)}" aria-label="Sound volume"><span id="snd-vol-n" class="muted">${Math.round(so.vol * 100)}%</span>
        <button class="btn ghost small" id="snd-test" type="button">Test</button></div>
      <div class="help">Saved for your account in this browser.</div></div>`;
    v.innerHTML = html;
    const sndSync = () => { const o = SFX.get(); ["snd-hover", "snd-select", "snd-vol", "snd-test"].forEach(i => { $("#" + i).disabled = !o.on; }); $(".snd-panel").classList.toggle("off", !o.on); };
    $("#snd-on").onchange = (e) => { SFX.set({ on: e.target.checked }); sndSync(); };
    $("#snd-hover").onchange = (e) => SFX.set({ hover: e.target.checked });
    $("#snd-select").onchange = (e) => SFX.set({ select: e.target.checked });
    $("#snd-vol").oninput = (e) => { SFX.set({ vol: +e.target.value / 100 }); $("#snd-vol-n").textContent = e.target.value + "%"; };
    $("#snd-vol").onchange = () => SFX.test();
    $("#snd-test").onclick = () => SFX.test();
    sndSync();
  } else if (tab === "users") {
    await viewUsers(v, html);
  } else if (tab === "downloads") {
    await viewOfflineAdmin(v, html);
  } else if (tab === "sharing") {
    html += await viewSharing();
    v.innerHTML = html;
    bindSharing();
  } else if (tab === "email") {
    await viewEmail(v, html, tq);
  } else if (tab === "activity") {
    await viewUserActivity(v, html);
  } else if (tab === "transcoding") {
    await viewTranscoding(v, html);
  } else if (tab === "system") {
    const [s, cfg] = await Promise.all([api("/api/system"), api("/api/settings")]);
    html += `<div class="panel"><h3 style="margin-top:0">Server status in the top bar</h3>
      <label class="aw-row" for="ss-all"><span class="sw"><input type="checkbox" id="ss-all" ${cfg.status_all_users ? "checked" : ""}><i></i></span>
      <span class="aw-txt"><b>Show server status to all users</b><span class="aw-hint">CPU and memory in the top-right corner, with details on click. Off: only admins see it.</span></span></label></div>`;
    html += `<div class="panel"><h3 style="margin-top:0">System</h3><div class="tech" style="font-size:14px">
      <span>Version</span><b>${esc(s.version)}</b><span>ffmpeg</span><b>${esc(s.ffmpeg)}</b><span>Data folder</span><b class="path">${wbrPath(s.data_dir)}</b>
      <span>Free space (data)</span><b>${s.data_disk_free_gb} GB</b><span>Libraries / items</span><b>${s.libraries} / ${s.items}</b>
      <span>Share mount helper</span><b>${s.mount_helper ? "installed" : "NOT installed (re-run install.sh)"}</b>
      <span>TMDB metadata</span><b>${s.tmdb && s.tmdb.enabled ? "on" : "off (no key)"}${s.tmdb && s.tmdb.stats ? ` · ${s.tmdb.stats.requests || 0} requests since start` : ""}</b></div>
      <h3>Active transcodes</h3>${s.transcodes.length ? `<table><tr><th>Title</th><th>Quality</th><th>Encoder</th><th>State</th><th>Segment</th><th>Idle</th></tr>${s.transcodes.map(t => `<tr><td>${esc(t.title)}</td><td>${t.profile === "remux" ? "remux (video copied)" : t.profile}</td><td>${encName(t)}</td><td>${t.running ? (t.paused ? "paused (buffered ahead)" : "running") : "finished"}</td><td>${t.last_req}</td><td>${t.idle_s}s</td></tr>`).join("")}</table>` : `<div class="muted">None</div>`}</div>`;
    v.innerHTML = html;
    await networkPanel(v).catch(() => {});
    $("#ss-all").onchange = async (e) => { try { await api("/api/settings", { method: "PUT", body: { status_all_users: e.target.checked } }); toast(e.target.checked ? "Server status is shown to everyone" : "Server status is shown to admins only"); } catch (err) { e.target.checked = !e.target.checked; toast(err.message, true); } };
    route._poll = setInterval(() => { const a = document.activeElement; if (a && (a.tagName === "INPUT" || a.tagName === "SELECT")) return; route._keepScroll = true; route(); }, 5000);
  }
}

// ---------------------------------------------------------------- 1.5.2 hardware transcoding (Settings > Transcoding)
const HW_LABEL = { auto: "Auto", qsv: "Intel QSV", vaapi: "VAAPI", nvenc: "NVIDIA NVENC", off: "Off (CPU)", cpu: "CPU" };
function encName(t) {
  if (!t || t.profile === "remux" || t.stage === "copy") return "copy";
  if (!t.encoder || t.encoder === "cpu") return t.fallback ? `CPU <span class="chip warn pill" title="${esc(t.fallback)}">fell back</span>` : "CPU (libx264)";
  return `<span class="hw-badge">GPU</span> ${HW_LABEL[t.encoder] || esc(t.encoder)}${t.stage === "enc" ? ` <span class="help">(CPU decode)</span>` : ""}`;
}
async function viewTranscoding(v, head) {
  const tok = route._token;
  let st = await api("/api/hw");
  let cfg = await api("/api/settings").catch(() => ({}));
  const render = () => {
    const det = st.detect || { cards: [] };
    const cards = det.cards || [];
    const usable = cards.filter(c => (c.methods || []).length);
    const act = st.active || {};
    const setup = st.setup || {};
    const tests = {}; (st.tests || []).forEach(t => tests[t.method + "|" + t.device] = t);
    const opt = (k) => `<option value="${k}" ${st.mode === k ? "selected" : ""}>${HW_LABEL[k]}</option>`;
    const devOpts = [`<option value="">First suitable card</option>`].concat(usable.filter(c => c.render).map(c =>
      `<option value="${esc(c.render)}" ${st.device === c.render ? "selected" : ""}>${esc(c.name)} (${esc(c.render.replace(/^.*\/dri\//, ""))})</option>`)).join("");
    const testCell = (m, dev) => {
      const t = tests[m + "|" + dev];
      const res = !t ? "" : t.ok ? `<span class="chip ok pill">passed &middot; ${t.fps || "?"} fps</span>` : `<span class="chip bad pill">failed</span>`;
      return `<div class="hw-test"><button class="btn ghost small" data-hwtest="${m}" data-dev="${esc(dev)}">Test ${HW_LABEL[m]}</button><span class="hw-res" data-res="${m}|${esc(dev)}">${res}</span></div>
        ${t && !t.ok ? `<div class="help hw-err">${esc(t.error || "")}${t.hint ? `<br><b>${esc(t.hint)}</b>` : ""}</div>` : ""}`;
    };
    const cardRows = cards.map(c => `<tr><td><b>${esc(c.name)}</b><div class="help">PCI ${esc((c.slot || "").replace(/^0000:/, ""))}${c.pci_id ? ` [${esc(c.pci_id)}]` : ""}${c.driver ? ` &middot; driver ${esc(c.driver)}` : ""}</div></td>
      <td>${c.render ? `<span class="path">${esc(c.render)}</span>` : c.vendor === "10de" ? "CUDA" : `<span class="muted">none</span>`}</td>
      <td>${(c.methods || []).length ? c.methods.map(m => `<span class="chip">${HW_LABEL[m]}</span>`).join(" ") : `<span class="muted">${esc(c.note || "no video encoder")}</span>`}${(c.methods || []).length && c.note ? `<div class="help">${esc(c.note)}</div>` : ""}</td>
      <td>${(c.methods || []).map(m => testCell(m, m === "nvenc" ? (c.render || "nvidia") : c.render)).join("") || ""}</td></tr>`).join("");
    const nowUse = act.method ? `<span class="hw-badge">GPU</span> <b>${HW_LABEL[act.method]}</b> on ${esc(act.name || act.device || "")}` :
      st.mode === "off" ? `<b>CPU (libx264)</b> <span class="help">hardware transcoding is off</span>` :
      st.held && st.held.length ? `<b>CPU (libx264)</b> <span class="chip warn pill">GPU paused after a failure</span>` :
      act.resolving ? `<span class="muted">checking the video card...</span>` : `<b>CPU (libx264)</b> <span class="help">no working video card found</span>`;
    const lf = st.last_failure || {};
    const setBy = setup.by ? `Set by ${esc(setup.by)} on ${new Date(setup.at * 1000).toLocaleString()}${setup.mode ? ` &rarr; ${HW_LABEL[setup.mode] || esc(setup.mode)}` : ""}` : "";
    const userSet = setup.changed_by_user_at ? ` &middot; changed here ${new Date(setup.changed_by_user_at * 1000).toLocaleString()}` : "";
    const streams = st.streams || [];
    v.innerHTML = head + `<div class="panel hw-panel"><h3 style="margin-top:0">Hardware transcoding</h3>
      <p class="help" style="margin-top:-4px">Let a video card convert videos that the browser or app cannot play directly. It uses far less CPU, so more people can watch at once.
        If the card fails on a video, that stream stays on the fallback (the reason is logged) and other streams keep using the card.</p>
      <div class="form hw-form">
        <label for="hw-mode">Hardware transcoding</label><select id="hw-mode">${["auto", "qsv", "vaapi", "nvenc", "off"].map(opt).join("")}</select>
        <label for="hw-dev">Video card</label><select id="hw-dev" ${usable.length ? "" : "disabled"}>${devOpts}</select>
        <label>In use now</label><div class="hw-now">${nowUse}</div>
        <label for="hw-max">Max simultaneous transcodes</label>
        <input id="hw-max" type="number" min="1" max="32" step="1" value="${st.max_transcodes || 4}">
      </div>
      <p class="help">The same account can play on more than one device. This is the server-wide cap (hardware and software). The default is 4. A message is logged when a new stream would go over it.</p>
      <div class="help hw-modes">Auto picks the first method that passes a test: VAAPI, then Intel QSV, then NVIDIA NVENC. ${setBy}${userSet}</div>
      <div class="err" id="hw-err"></div>
      <div class="hw-acts"><button class="btn" id="hw-save">Save</button><button class="btn ghost" id="hw-scan">Scan for video cards again</button></div></div>
      <div class="panel"><div class="row-head"><h3 style="margin:0">Detected video cards</h3><span class="muted">${cards.length} found</span></div>
      ${cards.length ? `<div class="tbl-wrap"><table class="hw-tbl"><tr><th>Card</th><th>Device</th><th>Methods</th><th>Test</th></tr>${cardRows}</table></div>` : `<div class="empty">No video card found. Videos are converted on the CPU.</div>`}
      <div class="help" style="margin-top:8px">ffmpeg encoders: ${(det.encoders || []).map(e => esc(e)).join(", ") || "none"}</div></div>
      <div class="panel"><h3 style="margin-top:0">Streams right now</h3>${streams.length ? `<table><tr><th>Title</th><th>Quality</th><th>Encoder</th></tr>${streams.map(t => `<tr><td>${esc(t.title || "")}</td><td>${t.profile}</td><td>${encName(t)}</td></tr>`).join("")}</table>` : `<div class="muted">None</div>`}
      ${lf.at ? `<div class="help hw-last">Last fallback ${ago(lf.at)}: ${HW_LABEL[lf.method] || esc(lf.method)} (${lf.stage === "full" ? "GPU decode" : "GPU encode"}) &rarr; ${lf.stage === "full" ? "CPU decode + GPU encode" : "CPU"}<br><span class="path">${esc(lf.reason || "")}</span></div>` : ""}
      ${(st.held || []).map(h => `<div class="help" style="color:var(--warn)">${HW_LABEL[h.method]} is paused until ${new Date((h.since + 600) * 1000).toLocaleTimeString()} after it failed. Save or a passing test turns it back on now.</div>`).join("")}</div>
      <div class="panel"><h3 style="margin-top:0">Opening-clip cache</h3>
        <p class="help" style="margin-top:0">When the server is idle, it pre-makes the first 6 seconds at 1080p for recently added movies and titles in Continue Watching, so they start almost instantly. Oldest clips are removed first when the cache is full.</p>
        <div class="form hw-form">
          <label for="pf-gb">Cache size (GB)</label>
          <input id="pf-gb" type="number" min="0" max="100" step="0.5" value="${cfg.prefetch_cache_gb != null ? cfg.prefetch_cache_gb : 2}">
        </div>
        <div class="help">${cfg.prefetch_cache_clips || 0} clip${(cfg.prefetch_cache_clips||0)===1?"":"s"} using ${((cfg.prefetch_cache_bytes||0)/1048576).toFixed(1)} MB. 0 GB turns this off. Default is 2 GB.</div>
        <div class="err" id="pf-err"></div>
        <div class="hw-acts"><button class="btn" id="pf-save">Save cache size</button></div></div>
      <div class="panel"><h3 style="margin-top:0">HDR to SDR tone mapping</h3>
        <p class="help" style="margin-top:0">When a title is <b>HDR10 or HLG</b> and has to be transcoded, convert it to SDR on the GPU (<code>tonemap_vaapi</code>). This is off by default until it has been checked on a real HDR film on this server (a library sample during planning was 10-bit SDR, which must not be tone-mapped). 10-bit SDR (bt709) is never tone-mapped.</p>
        <label class="chk"><input type="checkbox" id="hdr-tm" ${cfg.hdr_tonemap ? "checked" : ""}> Enable GPU tone mapping for HDR10 / HLG</label>
        <div class="err" id="hdr-tm-err"></div>
        <div class="hw-acts"><button class="btn" id="hdr-tm-save">Save</button></div></div>
      <div class="panel"><h3 style="margin-top:0">Seek-bar thumbnails</h3>
        <p class="help" style="margin-top:0">When the server is idle, it builds a strip of preview pictures for the seek bar (about one every 10 seconds) on the GPU. Oldest titles are removed first when the cache is full. 0 GB turns this off.</p>
        <div class="form hw-form">
          <label for="tp-gb">Cache size (GB)</label>
          <input id="tp-gb" type="number" min="0" max="100" step="0.5" value="${cfg.trickplay_cache_gb != null ? cfg.trickplay_cache_gb : 3}">
        </div>
        <div class="help">${cfg.trickplay_cache_titles || 0} title${(cfg.trickplay_cache_titles||0)===1?"":"s"} using ${((cfg.trickplay_cache_bytes||0)/1048576).toFixed(1)} MB. Default is 3 GB.</div>
        <div class="err" id="tp-err"></div>
        <div class="hw-acts"><button class="btn" id="tp-save">Save cache size</button></div></div>`;
    $("#hw-save").onclick = async () => {
      $("#hw-err").textContent = "";
      try { st = await api("/api/hw", { method: "PUT", body: { mode: $("#hw-mode").value, device: $("#hw-dev").value, max_transcodes: $("#hw-max").value } }); toast("Hardware transcoding: " + HW_LABEL[st.mode]); render(); }
      catch (e) { $("#hw-err").textContent = e.message; }
    };
    if ($("#pf-save")) $("#pf-save").onclick = async () => {
      $("#pf-err").textContent = "";
      try { cfg = await api("/api/settings", { method: "PUT", body: { prefetch_cache_gb: $("#pf-gb").value } }); toast("Opening-clip cache: " + cfg.prefetch_cache_gb + " GB"); render(); }
      catch (e) { $("#pf-err").textContent = e.message; }
    };
    if ($("#hdr-tm-save")) $("#hdr-tm-save").onclick = async () => {
      $("#hdr-tm-err").textContent = "";
      try { cfg = await api("/api/settings", { method: "PUT", body: { hdr_tonemap: $("#hdr-tm").checked } }); toast($("#hdr-tm").checked ? "HDR tone mapping on" : "HDR tone mapping off"); render(); }
      catch (e) { $("#hdr-tm-err").textContent = e.message; }
    };
    if ($("#tp-save")) $("#tp-save").onclick = async () => {
      $("#tp-err").textContent = "";
      try { cfg = await api("/api/settings", { method: "PUT", body: { trickplay_cache_gb: $("#tp-gb").value } }); toast("Seek-bar cache: " + cfg.trickplay_cache_gb + " GB"); render(); }
      catch (e) { $("#tp-err").textContent = e.message; }
    };
    $("#hw-scan").onclick = async (e) => { e.target.disabled = true; e.target.textContent = "Scanning..."; try { st = await api("/api/hw/scan", { method: "POST" }); toast("Scan finished"); } catch (er) { toast(er.message, true); } render(); };
    $$("[data-hwtest]").forEach(b => b.onclick = async () => {
      const cell = b.parentElement.querySelector(".hw-res");
      b.disabled = true; cell.innerHTML = `<span class="spin"></span> testing...`;
      try { await api("/api/hw/test", { method: "POST", body: { method: b.dataset.hwtest, device: b.dataset.dev } }); } catch (e) { toast(e.message, true); }
      st = await api("/api/hw"); render();
    });
  };
  render();
  // keep "In use now" / streams fresh without a full re-render while the admin is picking options
  route._poll = setInterval(async () => {
    if (route._token !== tok || document.hidden) return;
    const a = document.activeElement;
    if (a && (a.id === "hw-mode" || a.id === "hw-dev")) return;
    if ($(".hw-res .spin")) return;
    try { const n = await api("/api/hw"); if (route._token !== tok) return; const m = $("#hw-mode").value, d = $("#hw-dev").value; st = n; render(); $("#hw-mode").value = m; $("#hw-dev").value = d; } catch (e) {}
  }, 5000);
}

function addLibraryDialog() {
  let stype = "local";
  modal(`<h2>Add library</h2><div class="form">
    <label>Name</label><input type="text" id="al-name" placeholder="Movies">
    <label>Type</label><div class="seg" id="al-kind"><button data-k="movies" class="on">${KIND_ICON.movies}<span>Movies</span></button><button data-k="tv">${KIND_ICON.tv}<span>TV shows</span></button><button data-k="music">${KIND_ICON.music}<span>Music</span></button><button data-k="other">${KIND_ICON.other}<span>Other videos</span></button></div>
    <label>Source</label><div class="seg" id="al-src"><button data-s="local" class="on">Folder on this server</button><button data-s="smb">SMB / Windows share</button><button data-s="nfs">NFS share</button></div>
    <div class="full" id="al-srcform"></div>
    <label>Automatic scan</label><select id="al-int">${intervalOpts(6)}</select>
  </div><div class="err" id="al-err"></div>
  <div class="modal-actions"><button class="btn ghost" id="al-cancel">Cancel</button><button class="btn" id="al-save">Add library</button></div>`, (box) => {
    let kind = "movies";
    $$("#al-kind button").forEach(b => b.onclick = () => { kind = b.dataset.k; $$("#al-kind button").forEach(x => x.classList.toggle("on", x === b)); if (!$("#al-name").value || $("#al-name").dataset.auto) { $("#al-name").value = (b.querySelector("span") || b).textContent.trim(); $("#al-name").dataset.auto = "1"; } });
    $("#al-name").oninput = () => delete $("#al-name").dataset.auto;
    const browseBtn = `<button class="btn ghost fp-open" type="button" id="al-browse"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M10 4l2 2h8a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2z"/></svg><span>Browse</span></button>`;
    // 1.5.3: "Existing connection" -- reuse a share that is already set up (its login stays on the server)
    let conns = [], connId = null;
    const conn = () => conns.find(c => c.id === connId) || null;
    const kindNow = () => stype === "existing" ? (conn() || {}).kind || "smb" : stype;
    const connWho = (c) => c.kind === "nfs" ? "NFS" : c.guest ? "guest" : "as " + esc(c.username) + (c.domain ? " (" + esc(c.domain) + ")" : "");
    const renderSrc = () => {
      const f = $("#al-srcform");
      if (stype === "existing") {
        const c = conn() || conns[0]; connId = c.id;
        f.innerHTML = `<div class="form"><label>Connection</label><div class="conn-list" role="radiogroup" aria-label="Existing connections">${conns.map(x => `<button type="button" class="conn${x.id === connId ? " on" : ""}" role="radio" aria-checked="${x.id === connId}" data-id="${x.id}">
            <span class="conn-k">${x.kind.toUpperCase()}</span><span class="conn-t"><b>${esc(x.remote)}</b><span>${connWho(x)}${x.libraries.length ? " · " + esc(x.libraries.join(", ")) : ""}</span></span></button>`).join("")}</div>
          <label>Share</label><input type="text" id="al-remote" value="${esc(c.remote)}" placeholder="${esc(c.kind === "smb" ? "//" + c.host + "/Share" : c.host + ":/export")}">
          <label>Sub-folder</label><div class="fp-field"><input type="text" id="al-sub" placeholder="Movies (optional)">${browseBtn}</div>
          <div class="full help">Uses the login already saved for this connection, so there's nothing to type again (the password never leaves the server). <b>Browse</b> opens the share; go <b>Up</b> to pick another share on ${esc(c.host)} with the same login.</div></div>`;
        $$("#al-srcform .conn").forEach(b => b.onclick = () => { connId = +b.dataset.id; renderSrc(); });
        $("#al-browse").onclick = openBrowse;
        return;
      }
      if (stype === "local") {
        f.innerHTML = `<div class="form"><label>Folder</label><div><div class="fp-field"><input type="text" id="al-path" placeholder="/mnt/media/movies">${browseBtn}</div>
          <div class="help">A local disk or a share you already mounted yourself (e.g. via /etc/fstab). The service user must be able to read it.</div></div></div>`;
      } else if (stype === "smb") {
        f.innerHTML = `<div class="form"><label>Share path</label><input type="text" id="al-remote" placeholder="//192.0.2.10 or //192.0.2.10/Media">
          <label>Username</label><input type="text" id="al-user" placeholder="leave empty for guest" autocomplete="off">
          <label>Password</label><input type="password" id="al-pass" autocomplete="new-password">
          <label>Domain</label><input type="text" id="al-dom" placeholder="optional (WORKGROUP)">
          <label>SMB version</label><select id="al-ver"><option value="">auto</option><option value="vers=3.1.1">3.1.1</option><option value="vers=3.0">3.0</option><option value="vers=2.1">2.1</option><option value="vers=2.0">2.0</option><option value="vers=1.0">1.0 (old NAS)</option></select>
          <label>Sub-folder</label><div class="fp-field"><input type="text" id="al-sub" placeholder="Movies (optional)">${browseBtn}</div>
          <div class="full help">Fill in the address and login, then <b>Browse</b> to pick the folder (just the server, like //192.0.2.10, lists its shares first). Mounted read-only at /srv/media-server/shares/&lt;id&gt; with a systemd mount unit, so it comes back after a reboot. The password is kept in a root-only file in /etc/media-server/credentials, not in the database.</div></div>`;
      } else {
        f.innerHTML = `<div class="form"><label>Export</label><input type="text" id="al-remote" placeholder="192.0.2.10 or 192.0.2.10:/volume1/media">
          <label>NFS version</label><select id="al-ver"><option value="">auto</option><option value="nfsvers=4.1">4.1</option><option value="nfsvers=4">4</option><option value="nfsvers=3">3</option></select>
          <label>Sub-folder</label><div class="fp-field"><input type="text" id="al-sub" placeholder="Movies (optional)">${browseBtn}</div>
          <div class="full help">Browse lists the server's exports and folders. Mounted read-only at /srv/media-server/shares/&lt;id&gt;. The NFS server must allow this server's IP.</div></div>`;
      }
      $("#al-browse").onclick = openBrowse;
    };
    // 1.4.14: Browse -> folder picker. The login is sent with each request (POST body) and never stored here.
    const srcNow = () => {
      if (stype === "local") return { type: "local" };
      if (stype === "existing") return { type: "existing", share_id: connId, remote: $("#al-remote").value.trim() };
      const o = { type: stype, remote: $("#al-remote").value.trim(), options: $("#al-ver").value };
      if (stype === "smb") { o.username = $("#al-user").value; o.password = $("#al-pass").value; o.domain = $("#al-dom").value; }
      return o;
    };
    const applyKind = (k) => { if (!k) return; const b = $(`#al-kind button[data-k="${k}"]`); if (b && kind !== k) b.click(); };
    const openBrowse = () => {
      $("#al-err").textContent = "";
      const src = srcNow();
      const sk = kindNow();
      if (stype !== "local" && !src.remote) { $("#al-err").textContent = sk === "smb" ? "Enter the share address first, e.g. //192.0.2.10" : "Enter the NFS server first, e.g. 192.0.2.10"; $("#al-remote").focus(); return; }
      let base = src;   // becomes //host/share once a share is picked from the list
      folderPicker({
        title: stype === "local" ? "Choose a folder on this server" : "Choose the media folder",
        start: stype === "local" ? ($("#al-path").value.trim() || "/mnt") : $("#al-sub").value.trim(),
        load: async (path, pick) => {
          let s = base;
          if (pick) { s = Object.assign({}, base, { remote: sk === "smb" ? base.remote.replace(/\/+$/, "") + "/" + pick : base.remote.replace(/:.*$/, "") + ":" + pick }); path = ""; }
          const d = await api("/api/browse", { method: "POST", body: { source: stype === "local" ? { type: "local", path } : s, path } });
          if (d.mode === "dirs") base = Object.assign({}, s, { remote: d.remote || s.remote });
          return d;
        },
        upToShares: (d) => stype !== "local" && d.mode === "dirs" && !d.path,
        onBack: () => { const r = (base.remote || src.remote); base = Object.assign({}, src, { remote: sk === "smb" ? (r.match(/^(?:smb:)?\/*[^/]+/i) || [r])[0].replace(/^(?:smb:)?\/*/i, "//") : r.replace(/:.*$/, "") }); },
        fallback: stype === "local" ? "/" : "",
        onSelect: (d) => {
          if (stype === "local") $("#al-path").value = d.path;
          else { $("#al-remote").value = d.remote; $("#al-sub").value = d.path || ""; }
          applyKind(d.suggest);
        }
      });
    };
    const bindSrc = () => $$("#al-src button").forEach(b => b.onclick = () => { stype = b.dataset.s; $$("#al-src button").forEach(x => x.classList.toggle("on", x === b)); renderSrc(); });
    bindSrc();
    renderSrc();
    api("/api/connections").then(cs => {
      if (!cs || !cs.length || !$("#al-src")) return;
      conns = cs;
      $("#al-src").insertAdjacentHTML("afterbegin", `<button data-s="existing">Existing connection</button>`);
      bindSrc();
      if (stype === "local" && !($("#al-path") && $("#al-path").value)) $("#al-src button[data-s=existing]").click();   // reuse first
    }).catch(() => {});
    $("#al-name").value = "Movies"; $("#al-name").dataset.auto = "1";
    $("#al-cancel").onclick = closeModal;
    $("#al-save").onclick = async () => {
      const src = { type: stype };
      if (stype === "existing") { src.share_id = connId; src.remote = $("#al-remote").value; src.subpath = $("#al-sub").value; }
      else if (stype === "local") src.path = $("#al-path").value;
      else { src.remote = $("#al-remote").value; src.subpath = $("#al-sub").value; src.options = $("#al-ver").value;
        if (stype === "smb") { src.username = $("#al-user").value; src.password = $("#al-pass").value; src.domain = $("#al-dom").value; } }
      const btn = $("#al-save"); btn.disabled = true; btn.textContent = stype === "local" ? "Adding..." : "Mounting...";
      let r; try { r = await api("/api/libraries", { method: "POST", body: { name: $("#al-name").value, kind, source: src, scan_interval_h: +$("#al-int").value } });
        closeModal(); toast("Library added -- scanning now"); await refreshLibs(); pollActivity(); location.hash = "#/library/" + (r && r.id ? r.id : ""); route(); }
      catch (e) { $("#al-err").textContent = e.message; btn.disabled = false; btn.textContent = "Add library"; }
    };
  });
}

function editLibraryDialog(l) {
  const sh = l.share, mp = sh && sh.mount_point ? sh.mount_point.replace(/\/+$/, "") : null;
  const sub0 = mp && l.path.startsWith(mp) ? l.path.slice(mp.length).replace(/^\/+/, "") : "";
  modal(`<h2>Edit library</h2><div class="form"><label>Name</label><input type="text" id="el-name" value="${esc(l.name)}">
    <label>Automatic scan</label><select id="el-int">${intervalOpts(l.scan_interval_h)}</select>
    <label>${sh ? "Sub-folder" : "Folder"}</label><div><div class="fp-field"><input type="text" id="el-path" value="${esc(sh ? sub0 : l.path)}" placeholder="${sh ? "(the whole share)" : "/mnt/media/movies"}">
      <button class="btn ghost fp-open" type="button" id="el-browse"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M10 4l2 2h8a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2z"/></svg><span>Browse</span></button></div>
      <div class="help">${sh ? "On " + esc(sh.remote) + " (the share stays mounted as it is). " : ""}Changing the folder starts a full rescan.</div></div></div><div class="err" id="el-err"></div>
    <div class="modal-actions"><button class="btn ghost" id="el-cancel">Cancel</button><button class="btn" id="el-save">Save</button></div>`);
  $("#el-browse").onclick = () => folderPicker({ title: "Choose the library folder", start: $("#el-path").value.trim(),
    load: (path) => api("/api/libraries/" + l.id + "/browse?path=" + enc(path || "")),
    onSelect: (d) => { $("#el-path").value = d.path || ""; } });
  $("#el-cancel").onclick = closeModal;
  $("#el-save").onclick = async () => {
    const body = { name: $("#el-name").value, scan_interval_h: +$("#el-int").value };
    const pv = $("#el-path").value.trim();
    if (sh) { if (pv !== sub0) body.subpath = pv; } else if (pv && pv !== l.path) body.path = pv;
    try { await api("/api/libraries/" + l.id, { method: "PUT", body }); closeModal(); if (body.subpath !== undefined || body.path) { toast("Folder changed -- rescanning"); pollActivity(); } await refreshLibs(); route(); } catch (e) { $("#el-err").textContent = e.message; } };
}

// 1.4.14: folder picker (sits above the Add / Edit library window). opts.load(path, pickShare) -> {mode, remote, path,
// parent, dirs:[{name, videos}], videos, suggest}; mode "shares" lists the server's shares / exports first.
function folderPicker(opts) {
  const old = document.getElementById("fp"); if (old) old.remove();
  const el = document.createElement("div"); el.id = "fp"; el.className = "fp-wrap";
  el.innerHTML = `<div class="fp" role="dialog" aria-modal="true" aria-labelledby="fp-t">
    <div class="fp-head"><h3 id="fp-t">${esc(opts.title || "Choose a folder")}</h3><button class="fp-x" type="button" aria-label="Close">&#10005;</button></div>
    <nav class="fp-crumbs" aria-label="Folder path"></nav>
    <div class="fp-body" aria-live="polite"><ul class="fp-list" role="listbox" aria-label="Folders"></ul></div>
    <div class="fp-foot"><button class="btn ghost fp-up" type="button">&#8593; Up</button><span class="fp-here muted"></span>
      <button class="btn fp-sel" type="button">Select this folder</button></div></div>`;
  document.body.appendChild(el);
  const $f = (q) => el.querySelector(q);
  let cur = null, busy = false, seq = 0;
  const close = () => { el.remove(); document.removeEventListener("keydown", onKey, true); };
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  el.addEventListener("mousedown", (e) => { if (e.target === el) close(); });
  $f(".fp-x").onclick = close;
  const ERR_ICON = { auth: "&#128274;", denied: "&#9940;", unreachable: "&#128268;", notfound: "&#128269;", bad: "&#9888;", unavailable: "&#9888;" };
  const ERR_HINT = { auth: "Check the username, password and domain, then try again.", denied: "Use an account that may read this folder, or ask the NAS admin.",
    unreachable: "Check the address, that the NAS is on, and the SMB/NFS version.", notfound: "Go up and pick another folder.", unavailable: "You can still type the sub-folder by hand." };
  const crumbs = (d) => {
    const nav = $f(".fp-crumbs"); nav.innerHTML = "";
    const add = (label, path, last) => { const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.className = last ? "on" : "";
      if (last) b.setAttribute("aria-current", "page"); else b.onclick = () => go(path); nav.appendChild(b); };
    if (!d) return;
    if (d.mode === "shares") { add(d.remote || "Server", "", true); return; }
    const isAbs = (d.path || "").startsWith("/") && d.via === "local";
    if (isAbs) { const parts = d.path.split("/").filter(Boolean); add("/", "/", !parts.length); parts.forEach((p, i) => add(p, "/" + parts.slice(0, i + 1).join("/"), i === parts.length - 1)); }
    else { const parts = (d.path || "").split("/").filter(Boolean); add(d.remote || "Share", "", !parts.length); parts.forEach((p, i) => add(p, parts.slice(0, i + 1).join("/"), i === parts.length - 1)); }
    nav.scrollLeft = 99999;
  };
  const render = (d) => {
    cur = d; crumbs(d);
    const ul = $f(".fp-list"); ul.innerHTML = "";
    const shares = d.mode === "shares";
    if (!d.dirs.length) ul.innerHTML = `<li class="fp-empty">${shares ? "No shares found on this server." : "No sub-folders here."}</li>`;
    d.dirs.forEach(x => { const li = document.createElement("li"); li.setAttribute("role", "option"); li.tabIndex = 0; li.className = "fp-row";
      li.innerHTML = `<span class="fp-ic" aria-hidden="true">${shares ? "&#128450;" : "&#128193;"}</span><span class="fp-n">${esc(x.name)}</span>` +
        (x.videos ? `<span class="fp-c">${x.videos} video${x.videos === 1 ? "" : "s"}</span>` : (x.comment ? `<span class="fp-c">${esc(x.comment)}</span>` : "")) + `<span class="fp-go" aria-hidden="true">&#8250;</span>`;
      const open = () => shares ? go("", x.name) : go(d.via === "local" && (d.path || "").startsWith("/") ? (d.path === "/" ? "" : d.path) + "/" + x.name : (d.path ? d.path + "/" : "") + x.name);
      li.onclick = open; li.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } else if (e.key === "ArrowDown" && li.nextElementSibling) li.nextElementSibling.focus(); else if (e.key === "ArrowUp" && li.previousElementSibling) li.previousElementSibling.focus(); };
      ul.appendChild(li); });
    if (d.truncated) ul.insertAdjacentHTML("beforeend", `<li class="fp-empty">Showing the first ${d.dirs.length} folders.</li>`);
    $f(".fp-up").disabled = shares ? true : (d.parent === null || d.parent === undefined) && !d.backToShares;
    $f(".fp-sel").disabled = shares;
    $f(".fp-here").textContent = shares ? "Pick a share" : (d.videos ? d.videos + " video" + (d.videos === 1 ? "" : "s") + " in this folder" : (d.dirs.length + " folder" + (d.dirs.length === 1 ? "" : "s")));
  };
  const fail = (e, path, pick) => {
    const code = e.code || "unreachable";
    $f(".fp-list").innerHTML = `<li class="fp-err" role="alert"><span class="fp-ic">${ERR_ICON[code] || "&#9888;"}</span><div><b>${esc(e.message)}</b><div class="muted">${ERR_HINT[code] || ""}</div>
      <div class="fp-err-act"><button class="btn ghost small" type="button" id="fp-retry">Try again</button><button class="btn ghost small" type="button" id="fp-close2">Edit the login</button></div></div></li>`;
    el.querySelector("#fp-retry").onclick = () => go(path, pick);
    el.querySelector("#fp-close2").onclick = close;
    $f(".fp-sel").disabled = true; $f(".fp-up").disabled = !(cur && cur.mode === "dirs");
    $f(".fp-here").textContent = "";
  };
  const go = async (path, pick) => {
    const my = ++seq; busy = true; el.classList.add("busy");
    $f(".fp-list").innerHTML = `<li class="fp-load"><span class="fp-spin" aria-hidden="true"></span>${pick ? "Connecting to " + esc(pick) + "..." : cur ? "Loading..." : "Connecting..."}</li>`;
    $f(".fp-sel").disabled = true;
    try {
      const d = await opts.load(path, pick);
      if (my !== seq) return;
      if (opts.upToShares && opts.upToShares(d)) d.backToShares = true;
      render(d);
      const first = $f(".fp-row"); if (first && matchMedia("(pointer:fine)").matches) first.focus({ preventScroll: true });
    } catch (e) {
      if (my !== seq) return;
      if (!cur && e.code === "notfound" && opts.fallback !== undefined && (path || "") !== opts.fallback) { go(opts.fallback); return; }
      fail({ message: e.message, code: e.code || guessCode(e.message) }, path, pick);
    } finally { if (my === seq) { busy = false; el.classList.remove("busy"); } }
  };
  const guessCode = (m) => /password/i.test(m) ? "auth" : /denied/i.test(m) ? "denied" : /exist|not found|no share/i.test(m) ? "notfound" : /needs|install|helper/i.test(m) ? "unavailable" : "unreachable";
  $f(".fp-up").onclick = () => {
    if (!cur || cur.mode !== "dirs") return;
    if (cur.backToShares) { if (opts.onBack) opts.onBack(); go(""); return; }
    if (cur.parent !== null && cur.parent !== undefined) go(cur.parent);
  };
  $f(".fp-sel").onclick = () => { if (!cur || cur.mode !== "dirs") return; opts.onSelect(cur); close(); };
  go(opts.start || "");
}

// 1.3: save artwork into the movie folders (opt-in per library; the share must allow writing)
// 1.3.1: redesigned as three steps (share access / what to save / run); behaviour unchanged
// 1.5.5: TV libraries too (show poster / fanart / tvshow.nfo, season posters, episode thumbnails); opened from a show's
// page it also offers "Write for this show" (opts.show)
function artworkDialog(l, opts0 = {}) {
  const sh = l.share, tv = l.kind === "tv", oneShow = tv ? opts0.show : null;
  const W = tv ? { things: "shows", folders: "show folders", all: "Write artwork for all matched shows" } : { things: "movies", folders: "movie folders", all: "Write artwork for all matched movies" };
  const a = l.artwork || {};
  const busy = a.state === "running" || a.state === "queued";
  const row = (id, title, hint, on, extra = "") => `<label class="aw-row" for="${id}">
      <span class="sw"><input type="checkbox" id="${id}" ${on ? "checked" : ""} ${extra}><i></i></span>
      <span class="aw-txt"><b>${title}</b><span class="aw-hint">${hint}</span></span></label>`;
  modal(`<div class="aw">
    <div class="aw-head"><h2>Save artwork to ${W.folders}</h2>
      <p class="aw-lead">${tv ? "Puts the TMDB show poster and season posters (and, if you like, fanart, an info file and episode thumbnails) into each matched show's folder" : "Puts the TMDB poster (and, if you like, fanart and an info file) next to each matched movie"} so Kodi, Jellyfin and Plex can use it too. Video files are never changed.</p></div>
    <div class="aw-body">
      ${sh ? `<section class="aw-step">
        <div class="aw-step-h"><span class="aw-num">1</span><h3>Share access</h3><span id="aw-mode"></span></div>
        ${row("aw-rw", "Allow writing (artwork only)", `Remounts <span class="aw-code">${esc(sh.remote)}</span> read-write. Your other shares stay read-only.`, sh.allow_write)}
        <details class="aw-details"><summary>Details</summary>
          <p>Movinite only ever creates poster, fanart and .nfo files. While writing is allowed, though, anything running as the <span class="aw-code">media-server</span> user could change files on this share, so leave it off if you don't need folder artwork.</p>
          <p>The share's user must also be allowed to write on the NAS. If it isn't, you'll see a message right away and nothing is written. Turning this off remounts the share read-only; files already written stay.</p>
        </details>
        <div class="err" id="aw-rwerr"></div>
      </section>` : `<section class="aw-step">
        <div class="aw-step-h"><span class="aw-num">1</span><h3>Folder access</h3><span class="chip">Local folder</span></div>
        <p class="aw-p">This library is a local folder: the <span class="aw-code">media-server</span> user needs write permission in it.</p>
      </section>`}
      <section class="aw-step">
        <div class="aw-step-h"><span class="aw-num">2</span><h3>What to save</h3></div>
        ${row("aw-poster", tv ? "Show and season posters" : "Poster", "Always included when artwork is saved.", true, "disabled")}
        ${row("aw-fan", "Fanart (backdrop)", "The wide background image, saved as fanart.jpg.", l.art_fanart)}
        ${row("aw-nfo", ".nfo info file", tv ? "tvshow.nfo with title, year, plot, genres and TMDB / IMDb ids for Kodi, Jellyfin and Plex." : "Title, year, plot, genres and TMDB / IMDb ids for Kodi, Jellyfin and Plex.", l.art_nfo)}
        ${tv ? row("aw-th", "Episode thumbnails", "The TMDB still of each episode, saved next to the episode as &lt;file name&gt;-thumb.jpg.", l.art_thumbs) : ""}
        ${tv ? `<div class="aw-row aw-static"><span class="aw-ico">&#128193;</span><span class="aw-txt"><b>Naming</b><span class="aw-hint">In the show's folder (the first folder under the library):</span>
          <span class="aw-names"><span>Show</span><span class="aw-chips"><span class="aw-code">poster.jpg</span><span class="aw-code">fanart.jpg</span><span class="aw-code">tvshow.nfo</span></span>
          <span>Seasons</span><span class="aw-chips"><span class="aw-code">season01-poster.jpg</span><span class="aw-code">season-specials-poster.jpg</span></span>
          <span>Episodes</span><span class="aw-chips"><span class="aw-code">&lt;file name&gt;-thumb.jpg</span></span></span></span></div>`
        : `<div class="aw-row aw-static"><span class="aw-ico">&#128193;</span><span class="aw-txt"><b>Naming</b><span class="aw-hint">Chosen per movie, automatically:</span>
          <span class="aw-names"><span>Movie in its own folder</span><span class="aw-chips"><span class="aw-code">poster.jpg</span><span class="aw-code">fanart.jpg</span><span class="aw-code">movie.nfo</span></span>
          <span>Folder shared with other movies</span><span class="aw-chips"><span class="aw-code">&lt;file name&gt;-poster.jpg</span><span class="aw-code">&lt;file name&gt;.nfo</span></span></span></span></div>`}
        ${row("aw-on", "Save automatically for new matches", `Newly matched ${W.things} get their artwork without you doing anything.`, l.art_write)}
        ${row("aw-ow", "Overwrite existing files", "Replace poster.jpg / fanart.jpg / .nfo that are already there. Off: existing files are never touched.", l.art_overwrite)}
      </section>
      <section class="aw-step">
        <div class="aw-step-h"><span class="aw-num">3</span><h3>Run</h3></div>
        <p class="aw-p" id="aw-why"></p>
        <div class="aw-run">
          <button class="btn ghost" id="aw-preview">Preview (dry run)</button>
          ${oneShow ? `<button class="btn" id="aw-run1">Write for this show</button>` : ""}
          <button class="btn${oneShow ? " ghost" : ""}" id="aw-run">${busy ? "Saving artwork&hellip;" : W.all}</button>
          ${busy ? `<button class="btn danger" id="aw-stop">Stop</button>` : ""}
        </div>
        ${a.state === "error" ? `<div class="err">Last run: ${esc(a.error || "")}</div>` : ""}
        <div class="err" id="aw-err"></div><div id="aw-prev"></div>
      </section>
    </div>
    <div class="aw-foot"><span class="aw-dirty" id="aw-dirty"></span>
      <button class="btn ghost" id="aw-cancel">Close</button><button class="btn" id="aw-save" disabled>Save settings</button></div>
  </div>`, box => box.classList.add("modal-art"));

  const ids = ["aw-fan", "aw-nfo", "aw-on", "aw-ow"].concat(tv ? ["aw-th"] : []);
  const opts = () => Object.assign({ art_write: $("#aw-on").checked, art_fanart: $("#aw-fan").checked, art_nfo: $("#aw-nfo").checked, art_overwrite: $("#aw-ow").checked }, tv ? { art_thumbs: $("#aw-th").checked } : {});
  let saved = JSON.stringify(opts());
  const dirty = () => JSON.stringify(opts()) !== saved;
  const writable = () => !sh || sh.mount_mode === "rw";
  const refresh = () => {
    if ($("#aw-mode")) $("#aw-mode").innerHTML = sh.mount_mode === "rw" ? `<span class="chip ok">Writable</span>` : sh.mount_mode === "ro" ? `<span class="chip warn">Read-only</span>` : `<span class="chip bad">Not mounted</span>`;
    const d = dirty();
    $("#aw-save").disabled = !d;
    $("#aw-dirty").textContent = d ? "Unsaved changes" : "";
    $("#aw-run").disabled = busy || d || !writable();
    if ($("#aw-run1")) $("#aw-run1").disabled = busy || d || !writable();
    $("#aw-why").innerHTML = busy ? "Artwork is being saved now; progress is shown at the top of the page."
      : !writable() ? "Turn on <b>Allow writing</b> in step 1 to write files. You can preview first."
      : d ? "Save your settings first." : "Preview lists every file first and writes nothing. Writing runs in the background with progress at the top of the page.";
  };
  ids.forEach(id => $("#" + id).addEventListener("change", refresh));
  refresh();
  const save = async () => {
    const r = await api("/api/libraries/" + l.id, { method: "PUT", body: opts() });
    Object.assign(l, r); saved = JSON.stringify(opts()); refresh();
    if (r.write_ok === false) $("#aw-err").textContent = r.write_message;
    return r;
  };
  $("#aw-cancel").onclick = () => { closeModal(); route._keepScroll = true; route(); };
  $("#aw-save").onclick = async () => { $("#aw-err").textContent = ""; try { await save(); toast("Artwork settings saved"); } catch (e) { $("#aw-err").textContent = e.message; } };
  if ($("#aw-rw")) $("#aw-rw").onchange = async (e) => {
    const on = e.target.checked; $("#aw-rwerr").textContent = "";
    if (on && !confirm("Remount " + sh.remote + " read-write?\n\nMovinite only creates poster / fanart / .nfo files, but the share will be writable by the service user until you turn this off.")) { e.target.checked = false; return; }
    e.target.disabled = true;
    try {
      const r = await api(`/api/shares/${sh.id}/access`, { method: "POST", body: { allow_write: on } });
      sh.allow_write = on; sh.mount_mode = r.mount_mode;
      toast(on ? "Share is now writable" : "Share is read-only again");
      if (on && r.write_ok === false) $("#aw-rwerr").textContent = r.write_message;
    } catch (err) { e.target.checked = !on; $("#aw-rwerr").textContent = err.message; }
    e.target.disabled = false; refresh();
  };
  $("#aw-preview").onclick = async () => {
    $("#aw-err").textContent = "";
    $("#aw-prev").innerHTML = `<div class="aw-p muted">Checking folders&hellip;</div>`;
    try {
      if (dirty()) await save();
      const r = await api(`/api/libraries/${l.id}/artwork/preview?limit=400${oneShow ? "&show=" + enc(oneShow) : ""}`);
      const root = (l.path || "").replace(/\/+$/, "") + "/";
      const rel = p => esc(p.startsWith(root) ? p.slice(root.length) : p);
      const s = r.summary; const todo = r.actions.filter(x => x.action !== "skip");
      const skips = r.actions.filter(x => x.action === "skip");
      $("#aw-prev").innerHTML = `<div class="aw-result">
        <div class="aw-sum"><span class="chip ok">${nf(s.create)} to create</span><span class="chip ${s.overwrite ? "warn" : ""}">${nf(s.overwrite)} to overwrite</span><span class="chip">${nf(s.skip)} skipped</span><span class="muted">${nf(r.items)} matched ${W.things} &middot; dry run, nothing written</span></div>
        <div class="aw-root">Paths are inside <span class="aw-code">${esc(l.path)}</span></div>
        ${r.writable ? "" : `<div class="aw-warn">${sh && sh.mount_mode !== "rw" ? "The share is read-only right now, so nothing can be written yet. Turn on <b>Allow writing</b> in step 1 first." : esc(r.write_message)}</div>`}
        <div class="aw-list">${todo.slice(0, 300).map(x => `<div><span class="aw-act ${x.action}">${x.action}</span><span title="${esc(x.path)}">${rel(x.path)}</span></div>`).join("")}
        ${todo.length > 300 ? `<div class="muted">&hellip; and ${nf(todo.length - 300)} more</div>` : ""}
        ${skips.slice(0, 60).map(x => `<div class="muted"><span class="aw-act">skip</span><span title="${esc(x.path)}">${rel(x.path)} &mdash; ${esc(x.reason || "")}</span></div>`).join("")}
        ${!todo.length && !skips.length ? `<div class="muted">Nothing to do.</div>` : ""}</div></div>`;
    } catch (e) { $("#aw-prev").innerHTML = ""; $("#aw-err").textContent = e.message; }
  };
  $("#aw-run").onclick = async () => {
    $("#aw-err").textContent = "";
    try {
      if (!$("#aw-on").checked && !confirm(`'Save automatically for new matches' is off, so new matches won't be written later. ${W.all} once now?`)) return;
      await api(`/api/libraries/${l.id}/artwork/write`, { method: "POST" });
      toast("Saving artwork -- progress is shown at the top"); pollActivity(); closeModal(); route._keepScroll = true; route();
    } catch (e) { $("#aw-err").textContent = e.message; }
  };
  if ($("#aw-run1")) $("#aw-run1").onclick = async () => {
    $("#aw-err").textContent = "";
    try {
      await api(`/api/libraries/${l.id}/artwork/write`, { method: "POST", body: { show: oneShow } });
      toast("Saving artwork for this show -- progress is shown at the top"); pollActivity(); closeModal(); route._keepScroll = true; route();
    } catch (e) { $("#aw-err").textContent = e.message; }
  };
  if ($("#aw-stop")) $("#aw-stop").onclick = async () => { await api(`/api/libraries/${l.id}/artwork/cancel`, { method: "POST" }); toast("Stopping..."); closeModal(); };
}

function editShareDialog(s) {
  modal(`<h2>Share settings</h2><div class="form"><label>${s.kind === "smb" ? "Share path" : "Export"}</label><input type="text" id="es-remote" value="${esc(s.remote)}">
    ${s.kind === "smb" ? `<label>Username</label><input type="text" id="es-user" value="${esc(s.username || "")}"><label>Password</label><input type="password" id="es-pass" placeholder="re-enter the password" autocomplete="new-password">` : ""}
    <label>Options</label><input type="text" id="es-opt" value="${esc(s.options || "")}" placeholder="e.g. vers=3.0"></div>
    <div class="err" id="es-err"></div><div class="modal-actions"><button class="btn ghost" id="es-cancel">Cancel</button><button class="btn" id="es-save">Save &amp; remount</button></div>`);
  $("#es-cancel").onclick = closeModal;
  $("#es-save").onclick = async () => {
    const body = { remote: $("#es-remote").value, options: $("#es-opt").value };
    if (s.kind === "smb") { body.username = $("#es-user").value; body.password = $("#es-pass").value; }
    $("#es-save").disabled = true;
    try { await api("/api/shares/" + s.id, { method: "PUT", body }); closeModal(); toast("Share remounted"); route(); }
    catch (e) { $("#es-err").textContent = e.message; $("#es-save").disabled = false; }
  };
}

// ---------------------------------------------------------------- video player
const video = $("#video");
let hls = null, P = null; // P = current playback state
// 1.7.7: stable per-browser id so the same login on two devices can transcode at once
function playerId() {
  try {
    let id = localStorage.getItem("player_id");
    if (!id || !/^[a-zA-Z0-9_-]{8,64}$/.test(id)) {
      id = (crypto.randomUUID && crypto.randomUUID() || (Date.now().toString(36) + Math.random().toString(36).slice(2))).replace(/-/g, "");
      localStorage.setItem("player_id", id);
    }
    return id;
  } catch (e) { return "anon" + String(Date.now()).slice(-10); }
}
function nativeDecoderCaps() {
  try {
    if (window.MSAndroid && typeof MSAndroid.decoderCaps === "function") {
      const raw = MSAndroid.decoderCaps();
      return (typeof raw === "string") ? JSON.parse(raw) : raw;
    }
  } catch (e) {}
  return null;
}
function nativePlaySupported() {
  try { return !!(window.MSAndroid && typeof MSAndroid.playNative === "function"); } catch (e) { return false; }
}
function clientCaps() {
  if (clientCaps._c) return clientCaps._c;
  const v = document.createElement("video");
  const tests = {
    hvc1_l153: 'video/mp4; codecs="hvc1.1.6.L153.B0"',
    hvc1_main10: 'video/mp4; codecs="hvc1.2.4.L153.B0"',
    hev1_main10: 'video/mp4; codecs="hev1.2.4.L153.B0"',
    hvc1_l120: 'video/mp4; codecs="hvc1.1.6.L120.90"',
    mkv: "video/x-matroska",
    ac3: 'audio/mp4; codecs="ac-3"',
    eac3: 'audio/mp4; codecs="ec-3"',
    aac: 'audio/mp4; codecs="mp4a.40.2"'
  };
  const el = {}, mse = {};
  Object.keys(tests).forEach(k => {
    try { el[k] = v.canPlayType(tests[k]) || ""; } catch (e) { el[k] = ""; }
    try { mse[k] = !!(window.MediaSource && MediaSource.isTypeSupported(tests[k])); } catch (e) { mse[k] = false; }
  });
  const nat = nativeDecoderCaps();
  let hevc_mse = !!(mse.hvc1_l153 || mse.hvc1_main10 || mse.hev1_main10 || mse.hvc1_l120);
  let hevc_el = el.hvc1_l153 || el.hvc1_main10 || el.hev1_main10 || el.hvc1_l120 || "";
  // 2.2: 5.1 AAC uses the same codec string as stereo AAC; offer surround when AAC plays.
  // 2.4: a native player also reports real AudioCapabilities / MediaCodec support.
  let surr = !!(mse.aac || el.aac);
  if (nat) {
    if (nat.hevc || nat.hevc10) { hevc_el = hevc_el || "native"; hevc_mse = hevc_mse || !!nat.hevc; }
    if (nat.ac3) el.ac3 = el.ac3 || "native";
    if (nat.eac3) el.eac3 = el.eac3 || "native";
    if (nat.surr || nat.ac3 || nat.eac3 || nat.dts || nat.truehd) surr = true;
  }
  return (clientCaps._c = { hevc_mse, hevc_el, el, mse, surr, ua: navigator.userAgent || "", hlsjs: !!(window.Hls && Hls.isSupported()), native: nat });
}
function capsQuery() {
  const c = clientCaps();
  const n = c.native || {};
  const parts = ["player=" + encodeURIComponent(playerId()),
    "hevc=" + ((c.hevc_mse || c.hevc_el || n.hevc) ? "1" : "0"),
    "hevc_mse=" + (c.hevc_mse ? "1" : "0"),
    "hevc_el=" + encodeURIComponent(c.hevc_el || "no"),
    "mkv=" + ((c.el.mkv || n.mkv || nativePlaySupported()) ? "1" : "0"),
    "ac3=" + ((c.el.ac3 || n.ac3) ? "1" : "0"),
    "eac3=" + ((c.el.eac3 || n.eac3) ? "1" : "0"),
    "surr=" + (c.surr ? "6" : "0"),
    "hlsjs=" + (c.hlsjs ? "1" : "0")];
  if (nativePlaySupported() || n.native) parts.push("native=1");
  if (n.hevc10) parts.push("hevc10=1");
  if (n.av1) parts.push("av1=1");
  if (n.vp9) parts.push("vp9=1");
  if (n.dts) parts.push("dts=1");
  if (n.truehd) parts.push("truehd=1");
  if (n.hdr10 || n.hdr) parts.push("hdr10=1");
  if (n.hlg) parts.push("hlg=1");
  if (n.dv) parts.push("dv=1");
  if (n.ac3 || n.eac3) parts.push("acopy=1");
  if (n.maxh) parts.push("maxh=" + (+n.maxh || 0));
  return parts.join("&");
}
// 1.7.8: cap quality to this screen (and a MediaCapabilities decode limit when available)
const Q_LONG = { "360p": 640, "480p": 854, "720p": 1280, "1080p": 1920, "1440p": 2560, "2160p": 3840 };
function qualityCapOn() { try { return localStorage.getItem("qualityCap") !== "off"; } catch (e) { return true; } }
function setQualityCap(on) { try { localStorage.setItem("qualityCap", on ? "auto" : "off"); } catch (e) {} }
function isTvMode() { return !!(document.documentElement && document.documentElement.classList.contains("tv-mode")); }
function display4kPref() { try { return localStorage.getItem("display4k") || "auto"; } catch (e) { return "auto"; } }
function setDisplay4k(v) { try { localStorage.setItem("display4k", v); } catch (e) {} }
function displayLongPx() {
  const dpr = window.devicePixelRatio || 1;
  const css = Math.max(screen.width || 0, screen.height || 0);
  if (!css) return 0;
  const pref = display4kPref();
  const phys = Math.round(css * Math.max(dpr, 1));
  const dec = (probeDecoders._d && Math.max(+probeDecoders._d.maxHevc || 0, +probeDecoders._d.maxH264 || 0)) || 0;
  if (pref === "on") return Math.max(css, phys, 3840);
  if (pref === "off") {
    // Desktop/phone 1.7.8 rule: a WebView that already reports physical 1920 must not be doubled.
    if (css >= 1920) return css;
    return phys || css;
  }
  // auto
  if (isTvMode()) {
    // A 4K television's WebView often reports 1920x1080 with dpr 1 or 2.
    if (dec >= 2160) return Math.max(css, phys, 3840);
    if (phys >= 2560) return phys;
    if (css >= 2560) return css;
    if (dpr > 1 && css >= 1280) return Math.max(phys, 3840);
    // 1080p CSS on TV: do not cap at 1080p; the user can set "This display is 1080p".
    if (css >= 1920) return 3840;
    return Math.max(phys, css);
  }
  if (css >= 1920) return css;
  return phys || css;
}
function capBaseFromPx(px) {
  if (!px) return null;
  let cap = "360p";
  ["360p", "480p", "720p", "1080p", "1440p", "2160p"].forEach(p => { if (Q_LONG[p] <= px + 16) cap = p; });
  return cap;
}
async function probeDecoders() {
  if (probeDecoders._d) return probeDecoders._d;
  if (probeDecoders._p) return probeDecoders._p;
  probeDecoders._p = (async () => {
    const out = { maxHevc: 0, maxH264: 0 };
    // The Android WebView bridge (window.MSAndroid) has no MediaCodec list; skip it if absent.
    try {
      if (window.MSAndroid && typeof MSAndroid.decoderCaps === "function") {
        const raw = MSAndroid.decoderCaps();
        const j = (typeof raw === "string") ? JSON.parse(raw) : raw;
        if (j && (j.maxHevc || j.maxH264 || j.max || j.maxh)) {
          const mh = +j.maxHevc || +j.max || +j.maxh || 0;
          out.maxHevc = +j.maxHevc || mh;
          out.maxH264 = +j.maxH264 || +j.max || mh;
        }
      }
    } catch (e) {}
    const mc = navigator.mediaCapabilities && navigator.mediaCapabilities.decodingInfo;
    if (mc) {
      const sizes = { 2160: [3840, 2160], 1440: [2560, 1440], 1080: [1920, 1080] };
      const ok = async (codec, w, h, br) => {
        try {
          const r = await navigator.mediaCapabilities.decodingInfo({
            type: "media-source",
            video: { contentType: "video/mp4; codecs=\"" + codec + "\"", width: w, height: h, bitrate: br, framerate: 30 }
          });
          return !!(r && r.supported && r.smooth);
        } catch (e) { return false; }
      };
      for (const h of [2160, 1440, 1080]) {
        const wh = sizes[h], br = h >= 2160 ? 8000000 : h >= 1440 ? 5000000 : 4000000;
        if (await ok("hvc1.1.6.L153.B0", wh[0], wh[1], br) || await ok("hvc1.2.4.L153.B0", wh[0], wh[1], br))
          out.maxHevc = Math.max(out.maxHevc, h);
        if (await ok("avc1.640028", wh[0], wh[1], br))
          out.maxH264 = Math.max(out.maxH264, h);
      }
    }
    probeDecoders._d = out;
    return out;
  })();
  return probeDecoders._p;
}
try { probeDecoders(); } catch (e) {}
function decMaxPx() {
  const d = probeDecoders._d;
  if (!d) return 0;
  const hs = [d.maxHevc, d.maxH264].filter(Boolean);
  if (!hs.length) return 0;
  const h = Math.max.apply(null, hs);
  return h >= 2160 ? 3840 : h >= 1440 ? 2560 : h >= 1080 ? 1920 : 1280;
}
function deviceLimitPx() {
  if (!qualityCapOn()) return 0;
  const a = displayLongPx() || 0, b = decMaxPx() || 0;
  if (a && b) return Math.min(a, b);
  return a || b;
}
function deviceCapBase() { return capBaseFromPx(deviceLimitPx()); }
function capQuery() {
  const parts = [capsQuery(), "disp=" + (displayLongPx() || 0)];
  const dec = qualityCapOn() ? decMaxPx() : 0;
  if (dec) parts.push("dec=" + dec);
  if (!qualityCapOn()) parts.push("nocap=1");
  if (clientCaps().surr) parts.push("surr=6");
  const b = burnStreamIndex();
  if (b) parts.push("burn=" + b);
  return parts.join("&");
}
function itemCapQuery() {
  const q = [];
  const disp = displayLongPx();
  if (disp) q.push("disp=" + disp);
  const dec = qualityCapOn() ? decMaxPx() : 0;
  if (dec) q.push("dec=" + dec);
  if (!qualityCapOn()) q.push("nocap=1");
  return q.length ? "?" + q.join("&") : "";
}
function subByKey(key) {
  if (!P || !P.it || !P.it.playback || !key) return null;
  return (P.it.playback.subtitles || []).find(s => s.key === key) || null;
}
function isBurnSub(key) {
  const s = subByKey(key);
  return !!(s && (s.burn || s.kind === "image"));
}
function burnStreamIndex() {
  const key = ($("#pl-subs") && $("#pl-subs").value) || (P && P.subKey) || "";
  if (!isBurnSub(key)) return 0;
  const n = parseInt(String(key).replace(/^s/, ""), 10);
  return (isFinite(n) && n > 0) ? n : 0;
}
function canRemux(pb) {
  if (!pb || !pb.remux) return false;
  if (!pb.remux_codec || pb.remux_codec === "h264") return true;
  if (pb.remux_codec === "hevc") return !!(clientCaps().hevc_mse || clientCaps().hevc_el);
  return false;
}
function canDirect(it) {
  const pb = it.playback;
  if (pb.direct) {
    if (pb.mime === "video/x-matroska") return "try";   // most browsers play h264/aac mkv, but not all
    const t = video.canPlayType(pb.mime === "video/quicktime" ? "video/mp4" : pb.mime);
    return t ? "yes" : "try";
  }
  if (pb.direct_maybe) {
    if (it.vcodec === "hevc" && !clientCaps().hevc_el && !clientCaps().hevc_mse) return "no";
    if (it.acodec === "ac3" && !video.canPlayType('audio/mp4; codecs="ac-3"')) return "no";
    if (it.acodec === "eac3" && !video.canPlayType('audio/mp4; codecs="ec-3"')) return "no";
    return "try";
  }
  return "no";
}

// 1.7: which file of the title to play.  Default: the one asked for (the best version when it came from a poster).
//  - its share is offline -> the copy on a share that is up;
//  - a saved transcode quality (e.g. 720p) -> the smallest version still at least that big (less work, same result);
//  - no GPU 2K/4K transcoding and the big file can't be played as-is here -> a smaller version that can.
const Q_RANK = { "2160p": 4, "1440p": 3, "1080p": 2, "720p": 1 };
function vRank(v) { const r = resName(v.width, v.height); return r === "4K" ? 4 : r === "2K" ? 3 : r === "1080p" ? 2 : r === "720p" ? 1 : 0; }
function pickVersion(it, opts) {
  const vs = it.versions || [];
  if (opts.exact || vs.length < 2 || vs[0].id !== it.id) return null;
  const saved = String(localStorage.getItem("quality") || "auto").split(".")[0];
  if (Q_RANK[saved] != null || /^\d+p$/.test(saved)) {
    const want = Q_RANK[saved] != null ? Q_RANK[saved] : 0;
    const ok = vs.filter(v => vRank(v) >= want);
    const v = ok[ok.length - 1];
    if (v && v.id !== it.id && want < vRank(vs[0])) return { id: v.id, why: `the ${v.res} version (your quality is set to ${saved})` };
    return null;
  }
  const capB = deviceCapBase();
  if (capB && Q_RANK[capB] != null && vRank(vs[0]) > Q_RANK[capB]) {
    const want = Q_RANK[capB];
    const ok = vs.filter(v => vRank(v) >= want);
    const v = (ok.length ? ok[ok.length - 1] : vs[vs.length - 1]);
    if (v && v.id !== it.id) return { id: v.id, why: `the ${v.res} version (this screen is capped at ${capB})` };
  }
  const pb = it.playback;
  if (vRank(vs[0]) >= 3 && canDirect(it) === "no" && !pb.remux && !(pb.hires || []).length) {
    const v = vs.slice(1).find(x => x.playback.remux || canDirect({ playback: x.playback, vcodec: x.vcodec, acodec: x.acodec }) !== "no");
    if (v) return { id: v.id, why: `the ${v.res} version (plays without transcoding the ${vs[0].res} file on this server)` };
  }
  return null;
}

// 2.2: seek-bar sprite sheets (loaded in the background; timestamps still work if they are not ready)
const TP = { id: 0, data: null };
function loadTrickplay(id) {
  TP.id = id; TP.data = null;
  const th = $("#pl-tip-th"); if (th) th.classList.add("hidden");
  api("/api/items/" + id + "/trickplay").then(j => {
    if (!P || P.it.id !== id || !j || !j.count || !(j.sheets || []).length) return;
    TP.data = j;
  }).catch(() => {});
}
function showTrickplayTip(at) {
  const th = $("#pl-tip-th"); if (!th) return;
  const d = TP.data;
  if (!d || !d.count || !(d.sheets || []).length) { th.classList.add("hidden"); return; }
  const iv = d.interval || 10;
  const i = Math.min(d.count - 1, Math.max(0, Math.floor((at || 0) / iv)));
  const cols = d.columns || 10, rows = d.rows || 10, w = d.width || 160, h = d.height || 90;
  const per = cols * rows;
  const sheet = Math.min(d.sheets.length - 1, Math.floor(i / per));
  const idx = i % per;
  const c = idx % cols, r = Math.floor(idx / cols);
  th.style.width = w + "px"; th.style.height = h + "px";
  th.style.backgroundImage = "url(" + d.sheets[sheet] + ")";
  th.style.backgroundSize = (cols * w) + "px " + (rows * h) + "px";
  th.style.backgroundPosition = (-c * w) + "px " + (-r * h) + "px";
  th.classList.remove("hidden");
}

// 2.2: Up Next countdown (episodes / titles with it.next). Cancel leaves the current title at the end.
const UP = {
  shown: false, cancelled: false, left: 15, tid: 0,
  reset() {
    this.shown = false; this.cancelled = false; this.left = 15;
    if (this.tid) { clearInterval(this.tid); this.tid = 0; }
    const box = $("#pl-upnext"); if (box) box.classList.add("hidden");
  },
  hide() {
    if (this.tid) { clearInterval(this.tid); this.tid = 0; }
    const box = $("#pl-upnext"); if (box) box.classList.add("hidden");
    this.shown = false;
  },
  tick() {
    if (!P || !P.it || !P.it.next || this.cancelled || this.shown) return;
    const d = (isFinite(video.duration) && video.duration > 0) ? video.duration : (P.it.duration || 0);
    const t = video.currentTime || 0;
    if (d > 30 && d - t <= 15 && d - t >= 0) this.show(Math.max(1, Math.ceil(d - t)));
  },
  show(secs) {
    if (!P || !P.it || !P.it.next || this.cancelled) return;
    const n = P.it.next;
    const box = $("#pl-upnext"); if (!box) { this.go(); return; }
    this.shown = true; this.left = secs || 15;
    const title = n.kind === "episode" ? ((n.show ? n.show + " · " : "") + (n.episode_code || "") + " " + (n.title || "")).trim() : (n.title || "Next");
    $("#pl-upnext-title").textContent = title;
    const art = $("#pl-upnext-art");
    const poster = n.thumb || n.poster || n.backdrop;
    art.style.backgroundImage = poster ? ("url(" + (poster.indexOf("/") === 0 ? poster : thumbUrl(poster)) + ")") : "";
    box.classList.remove("hidden");
    const tick = () => {
      if (!P || this.cancelled) { this.hide(); return; }
      $("#pl-upnext-sub").textContent = "Starts in " + this.left + "s";
      if (this.left <= 0) { this.go(); return; }
      this.left -= 1;
    };
    tick();
    if (this.tid) clearInterval(this.tid);
    this.tid = setInterval(tick, 1000);
    const play = $("#pl-upnext-play"), cancel = $("#pl-upnext-cancel");
    if (play) play.onclick = () => this.go();
    if (cancel) cancel.onclick = () => this.cancel();
    try { if (isTvMode() && play) play.focus(); } catch (e) {}
  },
  go() {
    if (!P || !P.it || !P.it.next) return;
    const n = P.it.next.id;
    this.hide();
    saveProgress(true);
    teardownVideo(true);
    playItem(n, 0);
  },
  cancel() {
    this.cancelled = true;
    this.hide();
  }
};

function loadMarkers(it) {
  if (!it || !it.id) return;
  const apply = (j) => { if (P && P.it && P.it.id === it.id && j) P.it.markers = j; };
  if (it.markers) apply(it.markers);
  api("/api/items/" + it.id + "/markers").then(apply).catch(() => {});
}

// 2.3: Skip Intro / Skip Credits (ties into the Up Next card)
const SK = {
  autoIntro: false, autoCred: false, shownIntro: false, shownCred: false, poll: 0,
  reset() {
    this.shownIntro = false; this.shownCred = false;
    this.autoIntro = !!(typeof ME !== "undefined" && ME && ME.auto_skip_intro);
    this.autoCred = !!(typeof ME !== "undefined" && ME && ME.auto_skip_credits);
    this.hideIntro(); this.hideCredits();
    if (this.poll) { clearInterval(this.poll); this.poll = 0; }
    if (P && P.it && P.it.markers && P.it.markers.status === "pending") {
      this.poll = setInterval(() => { if (!P) { clearInterval(SK.poll); SK.poll = 0; return; } loadMarkers(P.it); }, 20000);
    }
  },
  markers() { return (P && P.it && P.it.markers) || {}; },
  hideIntro() { const b = $("#pl-skip-intro"); if (b) b.classList.add("hidden"); this.shownIntro = false; },
  hideCredits() { const b = $("#pl-skip-credits"); if (b) b.classList.add("hidden"); this.shownCred = false; },
  hide() { this.hideIntro(); this.hideCredits(); },
  inIntro(t) {
    const m = this.markers();
    return m.intro_start != null && m.intro_end != null && t >= m.intro_start - 0.25 && t < m.intro_end - 0.4;
  },
  inCredits(t, d) {
    const m = this.markers();
    if (m.credits_start == null) return false;
    return t >= m.credits_start - 0.25 && (!d || t < d - 0.2);
  },
  skipIntro() {
    if (!P) return;
    const m = this.markers();
    if (m.intro_end == null) return;
    video.currentTime = Math.max(0, m.intro_end);
    P.lastSave = 0;
    this.hideIntro();
    try { if (typeof OV !== "undefined") OV.show(); } catch (e) {}
  },
  skipCredits() {
    if (!P) return;
    this.hideCredits();
    if (P.it && P.it.next) {
      if (typeof UP !== "undefined") UP.show(15);
      try { if (isTvMode() && $("#pl-upnext-play")) $("#pl-upnext-play").focus(); } catch (e) {}
    } else {
      const d = (isFinite(video.duration) && video.duration > 0) ? video.duration : (P.it.duration || 0);
      if (d) video.currentTime = Math.max(0, d - 0.4);
    }
  },
  tick() {
    if (!P) return;
    const t = video.currentTime || 0;
    const d = (isFinite(video.duration) && video.duration > 0) ? video.duration : (P.it.duration || 0);
    const m = this.markers();
    if (this.inIntro(t)) {
      if (this.autoIntro && !P.didAutoIntro) {
        P.didAutoIntro = true;
        this.skipIntro();
        return;
      }
      if (!this.shownIntro) {
        const b = $("#pl-skip-intro");
        if (b) { b.classList.remove("hidden"); this.shownIntro = true; try { if (isTvMode()) { if (typeof TV !== "undefined" && TV.focus) TV.focus(b); else b.focus(); } } catch (e) {} }
      }
    } else if (this.shownIntro) this.hideIntro();
    if (this.inCredits(t, d)) {
      if (this.autoCred && !P.didAutoCred) {
        P.didAutoCred = true;
        this.skipCredits();
        return;
      }
      if (!this.shownCred) {
        const b = $("#pl-skip-credits");
        if (b) { b.classList.remove("hidden"); this.shownCred = true; try { if (isTvMode() && !this.shownIntro) { if (typeof TV !== "undefined" && TV.focus) TV.focus(b); else b.focus(); } } catch (e) {} }
      }
    } else if (this.shownCred) this.hideCredits();
  }
};

/** 2.4.3: the native Android player calls this when ExoPlayer cannot play
 *  (after trying HEVC, then H.264) so playback continues in the in-page player. */
function playInWebPlayer(id, startAt) {
  try { toast("Opening the in-page player"); } catch (e) {}
  return playItem(id, startAt, { forceWeb: true });
}

async function playItem(id, startAt, opts) {
  opts = opts || {};
  try { probeDecoders(); } catch (e) {}   // 1.7.9: do not block first open on the decoder probe
  const capQ = itemCapQuery();
  let it = (opts.item && opts.item.id === id && opts.item.playback) ? opts.item : await api("/api/items/" + id + capQ);
  if (it.unavailable || (it.is_remote && it.online === false)) {
    toast((it.peer_name || it.source_name || "That shared server") + " is not reachable right now", true);
    return;
  }
  if (it.offline && it.fallback) { toast(`Share offline -- playing the copy in ${it.fallback_library || "another library"}`); it = await api("/api/items/" + it.fallback + capQ); id = it.id; }
  else if (it.media_type === "video") {
    const pv = pickVersion(it, opts);
    if (pv) { const it2 = await api("/api/items/" + pv.id + capQ).catch(() => null); if (it2) { it = it2; id = it.id; toast("Playing " + pv.why); } }
  }
  if (it.media_type === "audio") { playQueue([it], 0); return; }
  if (startAt === undefined) startAt = it.position > 30 ? it.position : 0;
  // 2.4: the Android TV (and phone) app hands Play to the native ExoPlayer. Browse stays in the WebView.
  if (!opts.forceWeb && nativePlaySupported() && it.media_type === "video") {
    try {
      const sub = (function(){ try { return localStorage.getItem("pl-subs") || ""; } catch (e) { return ""; } })();
      const raw = window.MSAndroid.playNative(JSON.stringify({
        item_id: it.id, start: startAt || 0, audio: 0, sub: sub
      }));
      const r = (typeof raw === "string" && raw) ? JSON.parse(raw) : raw;
      if (!r || r.ok !== false) return;
    } catch (e) { /* fall through to the in-page player (and to the 2.0.2 app, which has no playNative) */ }
  }
  stopAudio();
  if (P) { saveProgress(); PIP.leave(); teardownVideo(true); }   // 1.4.12: another film picked while one plays in picture-in-picture
  P = { it, start: startAt || 0, mode: null, audio: 0, lastSave: 0, triedDirect: false };
  const pb = it.playback;
  $("#pl-title").textContent = it.kind === "episode" ? `${it.show} · ${epCode(it)} · ${it.title}` : it.title + (it.year ? ` (${it.year})` : "");
  const dmode = canDirect(it);
  const q = $("#pl-quality");
  const saved = localStorage.getItem("quality") || "auto";
  // 1.5.3: 2K / 4K (GPU servers, sources at least that big): HEVC when this device plays it, else H.264
  const hi = (pb.hires || []).map(p => hiresMode(p));
  const remuxOk = canRemux(pb);
  q.innerHTML = `${dmode !== "no" ? `<option value="direct">Original (direct play)</option>` : ""}${remuxOk ? `<option value="remux">Original (remux, no re-encode)</option>` : ""}`
    + hi.map(m => `<option value="${m}">Transcode ${qualName(m)}</option>`).join("")
    + (pb.hires_off ? pb.hires_off.profiles.map(p => `<option value="" disabled data-note="${esc(pb.hires_off.note)}">${qualName(p)} &ndash; needs GPU transcoding</option>`).join("") : "")
    + pb.profiles.map(p => `<option value="${p}">Transcode ${p}</option>`).join("");
  // 1.7.7: like Plex, prefer direct play or remux when this device can play the original codec.
  // A saved 720p/1080p choice is still honored (bandwidth). A saved 2K/4K transcode no longer
  // skips remux/direct, which is what caused 4K-to-4K GPU transcodes of HEVC files.
  let mode;
  const savedHi = hi.find(m => m.split(".")[0] === String(saved).split(".")[0]);
  if (pb.profiles.includes(saved)) mode = saved;
  else if (dmode !== "no") mode = "direct";
  else if (remuxOk) mode = "remux";
  else if (savedHi) mode = savedHi;
  else if (saved === "remux" && remuxOk) mode = "remux";
  else mode = pb.profiles[0];
  const capB = pb.device_cap || deviceCapBase();
  const modeBase = String(mode).split(".")[0];
  if (capB && mode !== "direct" && mode !== "remux" && (Q_RANK[modeBase] || 0) > (Q_RANK[capB] || 0)) {
    mode = (hi.find(m => m.split(".")[0] === capB) || (pb.profiles.includes(capB) ? capB : pb.profiles[0]));
  }
  const wantedBase = String(saved === "auto" ? (hi[0] || "2160p") : saved).split(".")[0];
  P.cap = capB || null;
  P.cappedTo = (capB && (mode === capB || String(mode).split(".")[0] === capB) &&
    ((saved === "auto" && (Q_RANK[wantedBase] || 0) > (Q_RANK[capB] || 0)) ||
     (Q_RANK[String(saved).split(".")[0]] || 0) > (Q_RANK[capB] || 0) ||
     ((saved === "direct" || saved === "remux" || saved === "auto") && pb.source_fits_cap === false)))
    ? capB : null;
  if (P.cappedTo && capB) {
    const capOpt = [...q.options].find(o => o.value === mode || o.value.split(".")[0] === capB);
    if (capOpt && !/capped/i.test(capOpt.textContent)) capOpt.textContent = capOpt.textContent + " · Auto-capped to " + capB;
  }
  const wantSub = (function(){ try { return localStorage.getItem("pl-subs") || ""; } catch (e) { return ""; } })();
  const subIsBurn = (P.it.playback.subtitles || []).some(s => s.key === wantSub && (s.burn || s.kind === "image"));
  if (subIsBurn && (mode === "direct" || mode === "remux")) {
    mode = savedHi || (hi[0] || pb.profiles[0]);
  }
  const a = $("#pl-audio");
  a.innerHTML = pb.audio_streams.map((s, i) => `<option value="${i}">${esc((s.title || s.lang || "Audio " + (i + 1)) + " · " + s.codec + (s.channels ? " " + s.channels + "ch" : ""))}</option>`).join("");
  a.classList.toggle("hidden", pb.audio_streams.length < 2);
  const sb = $("#pl-subs");
  sb.innerHTML = `<option value="">Subtitles off</option>` + pb.subtitles.map(s => `<option value="${s.key}">${esc(s.label)}</option>`).join("");
  sb.classList.toggle("hidden", !pb.subtitles.length);
  try {
    const want = localStorage.getItem("pl-subs");
    if (want && [...sb.options].some(o => o.value === want)) sb.value = want;
  } catch (e) {}
  if (pb.subtitles.length) prefetchSubs(pb.subtitles.filter(s => !s.burn && s.kind !== "image").map(s => s.key));
  $("#pl-next").classList.toggle("hidden", !it.next);
  video.controls = false;          // 1.4.13: our own bar replaces the browser's controls
  BAR.closePop();
  $("#player").classList.remove("hidden");
  startStream(mode, P.start);
  BAR.sync(); BAR.draw(P.start); ROT.open();
  OV.show();     // 1.4.11: show the big buttons for a moment so they're discoverable
  loadTrickplay(it.id);
  UP.reset();
  SK.reset();
  loadMarkers(it);
}

function setStatus(t) {
  const el = $("#pl-status"); if (el) el.textContent = t || "";
  const s = $("#pl-wait-s"); if (s) s.textContent = t || "";
}
function showWait(title) {
  const box = $("#pl-wait"); if (!box) return;
  const h = $("#pl-wait-t"); if (h) h.textContent = title || "Starting…";
  box.classList.remove("hidden");
}
function hideWait() { const box = $("#pl-wait"); if (box) box.classList.add("hidden"); }
function modeLabel(m) {
  const cap = P && P.cappedTo ? ` · Auto-capped to ${qualName(P.cappedTo)}` : "";
  return (m === "direct" ? "Direct play" : m === "remux" ? "Remux (original video)" : `Transcoding ${qualName(m)}`)
    + cap + (P && P.it.playback.hdr && m !== "direct" && m !== "remux" ? hdrNote() : "");
}
// 1.5.3: 2K / 4K names, HEVC support, HDR note
function qualName(m) { const [b, vc] = String(m).split("."); return (b === "2160p" ? "4K (2160p)" : b === "1440p" ? "2K (1440p)" : b) + (vc === "hevc" ? " HEVC" : ""); }
function hevcOK() {
  if (hevcOK.v !== undefined) return hevcOK.v;
  const c = clientCaps();
  return (hevcOK.v = !!(c.hevc_mse || c.hevc_el));
}
function hiresMode(p) { return hevcOK() ? p + ".hevc" : p; }
function hdrNote() {
  const hdr = P && P.it && P.it.playback && P.it.playback.hdr;
  if (!hdr) return "";
  if (P.it.playback.hdr_tonemap) return " · " + hdr + " with GPU tone-mapping";
  return " · " + hdr + " without tone-mapping (colors may look flat)";
}

function startStream(mode, at) {
  if (!P) return;
  const it = P.it;
  teardownVideo(false);
  P.mode = mode;
  $("#pl-quality").value = mode;
  const subKey = $("#pl-subs").value;
  if (mode === "direct") {
    P.triedDirect = true;
    showWait("Starting direct play");
    setStatus("Direct play");
    video.src = `/api/items/${it.id}/file`;
    video.addEventListener("loadedmetadata", function onMeta() {
      video.removeEventListener("loadedmetadata", onMeta);
      if (it.vcodec && video.videoWidth === 0) { fallback("browser cannot decode the video"); return; }
      if (at) video.currentTime = at;
    });
  } else {
    showWait(mode === "remux" ? "Starting remux" : ("Starting transcode · " + qualName(mode)));
    setStatus(modeLabel(mode));
    const seg = (it.playback && it.playback.seg) || 2;
    const url = `/api/items/${it.id}/hls/${mode}/index.m3u8?audio=${P.audio}&${capQuery()}&start=${Math.floor((at || 0) / seg)}`;
    if (window.Hls && Hls.isSupported()) {
      hls = new Hls({ startPosition: at || 0, maxBufferLength: 30, maxMaxBufferLength: 120, startFragPrefetch: true, fragLoadingTimeOut: 90000, fragLoadingMaxRetry: 4, manifestLoadingTimeOut: 30000, xhrSetup: (xhr) => { xhr.withCredentials = true; } });
      hls.on(Hls.Events.ERROR, (ev, data) => {
        if (data.fatal) {
          if (P && P.mode === "remux") { fallback("remux failed: " + data.details); return; }
          if (P && /^(2160p|1440p)/.test(P.mode)) { const d = data.details; if (!P.downing) { P.downing = true; setTimeout(() => { if (P) { P.downing = false; hiresDown(d); } }, 0); } return; }   // 1.5.3: step down (after hls.js finishes this event)
          if (data.type === Hls.ErrorTypes.NETWORK_ERROR) { setStatus("Network error, retrying..."); hls.startLoad(); }
          else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) { hls.recoverMediaError(); }
          else { setStatus("Playback error: " + data.details); }
        }
      });
      hls.loadSource(url); hls.attachMedia(video);
      const reUp = () => { if (P && $("#pl-subs").value) addSubTrack($("#pl-subs").value, { keep: true }); };
      hls.on(Hls.Events.MEDIA_ATTACHED, reUp);
      hls.on(Hls.Events.MANIFEST_PARSED, reUp);
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;  // Safari native HLS
      video.addEventListener("loadedmetadata", function onMeta() { video.removeEventListener("loadedmetadata", onMeta); if (at) video.currentTime = at; });
    } else { setStatus("This browser cannot play HLS"); return; }
  }
  if (P) P.burning = isBurnSub(subKey);
  if (subKey) addSubTrack(subKey);
  video.play().catch(() => {});
}

// 1.5.3: a 2K / 4K stream that fails: HEVC -> H.264 at the same size -> the usual best transcode
function hiresDown(reason) {
  if (!P) return;
  const at = video.currentTime || P.start, pb = P.it.playback;
  const next = P.mode.endsWith(".hevc") ? P.mode.split(".")[0] : pb.profiles[0];
  if (P.mode.endsWith(".hevc")) hevcOK.v = false;   // this device / server pair can't do HEVC: H.264 from now on
  toast(`${qualName(P.mode)} failed (${reason}), switching to ${qualName(next)}`, true);
  const q = $("#pl-quality");
  if (next !== pb.profiles[0] && ![...q.options].some(o => o.value === next)) {
    const o = [...q.options].find(o => o.value === P.mode); if (o) { o.value = next; o.textContent = "Transcode " + qualName(next); }
  }
  startStream(next, at);
}
function fallback(reason) {
  if (!P || (P.mode !== "direct" && P.mode !== "remux")) return;
  const at = video.currentTime || P.start;
  const next = P.mode === "direct" && canRemux(P.it.playback) && !P.triedRemux ? "remux" : P.it.playback.profiles[0];
  if (next === "remux") P.triedRemux = true;
  toast((next === "remux" ? "Switching to remux (" : "Switching to transcoding (") + reason + ")");
  startStream(next, at);
}
video.addEventListener("error", () => {
  if (P && P.mode === "direct") fallback("direct play failed");
  else if (P && P.mode === "remux" && !hls) fallback("remux failed");
  else if (P) setStatus("Playback error");
});
["playing", "canplay", "loadeddata"].forEach(ev => video.addEventListener(ev, () => { hideWait(); }));
video.addEventListener("waiting", () => {
  if (!P || video.seeking) return;
  if (video.currentTime > 0.2) showWait("Buffering…");
  else showWait($("#pl-wait-t") && $("#pl-wait-t").textContent ? $("#pl-wait-t").textContent : "Starting…");
  setStatus("Waiting for the first picture…");
});
video.addEventListener("playing", () => { if (P) setStatus(modeLabel(P.mode)); });

// 1.7.5: fetch+cache WebVTT and paint a custom overlay. <track src> is slow to appear after
// an HLS attachMedia / quality change (the element is often dropped) and first-time ffmpeg
// conversion of embedded subs can take a while; caching + re-applying after MEDIA_ATTACHED
// and on seek keeps captions prompt and visible. Native tracks stay mode=hidden so we don't
// draw twice; the overlay is the WebView-safe fallback (::cue is often ignored there).
const SUB = { key: "", cues: [], cache: {}, gen: 0, waiting: false };
function parseTs(s) {
  s = String(s || "").trim().replace(",", ".");
  const p = s.split(":").map(Number);
  if (p.some(n => !isFinite(n))) return 0;
  if (p.length === 3) return p[0] * 3600 + p[1] * 60 + p[2];
  if (p.length === 2) return p[0] * 60 + p[1];
  return p[0] || 0;
}
function parseVtt(text) {
  const out = [];
  const body = String(text || "").replace(/^\uFEFF/, "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const parts = body.split(/\n\n+/);
  for (const part of parts) {
    const lines = part.split("\n").filter((l, i) => i === 0 ? !/^WEBVTT/i.test(l) : true);
    let i = 0;
    if (lines[0] && !/-->/.test(lines[0])) i = 1;
    const m = (lines[i] || "").match(/([\d:.]+)\s*-->\s*([\d:.]+)/);
    if (!m) continue;
    const textLines = lines.slice(i + 1).filter(l => l && !/^NOTE\b/.test(l) && !/^STYLE\b/.test(l));
    if (!textLines.length) continue;
    out.push({ start: parseTs(m[1]), end: parseTs(m[2]), text: textLines.join("\n") });
  }
  return out;
}
function subCacheKey(id, key) { return id + ":" + key; }
function cueBox() { return document.getElementById("pl-cues"); }
function paintCues() {
  const el = cueBox(); if (!el) return;
  if (!P || !SUB.key) { el.classList.add("hidden"); el.innerHTML = ""; return; }
  if (SUB.waiting && !SUB.cues.length) {
    el.innerHTML = `<span class="cue wait">Loading subtitles…</span>`;
    el.classList.remove("hidden");
    return;
  }
  const t = video.currentTime || 0;
  const on = SUB.cues.filter(c => t >= c.start && t < c.end);
  if (!on.length) { el.classList.add("hidden"); el.innerHTML = ""; return; }
  el.innerHTML = on.map(c => `<span class="cue">${esc(c.text)}</span>`).join("");
  el.classList.remove("hidden");
}
async function fetchVtt(id, key) {
  // 1.7.9: 202 means the server is extracting in the background — retry instead of blocking the first encode
  for (let i = 0; i < 24; i++) {
    const r = await fetch(`/api/items/${id}/subs/${key}.vtt`, { credentials: "same-origin" });
    if (r.status === 202) { await new Promise(res => setTimeout(res, 400 + i * 200)); continue; }
    if (!r.ok) throw new Error("sub " + r.status);
    return r.text();
  }
  throw new Error("sub timeout");
}
function prefetchSubs(keys) {
  if (!P || !keys || !keys.length) return;
  const id = P.it.id;
  keys.slice(0, 2).forEach(key => {
    const ck = subCacheKey(id, key);
    if (SUB.cache[ck] || !key) return;
    fetchVtt(id, key)
      .then(t => { SUB.cache[ck] = parseVtt(t); if (SUB.key === key && P && P.it.id === id) { SUB.cues = SUB.cache[ck]; SUB.waiting = false; paintCues(); } })
      .catch(() => {});
  });
}
async function addSubTrack(key, opts) {
  opts = opts || {};
  $$("track", video).forEach(t => t.remove());
  SUB.key = key || "";
  try { if (key) localStorage.setItem("pl-subs", key); else if (!opts.keep) localStorage.setItem("pl-subs", ""); } catch (e) {}
  if (isBurnSub(key)) { SUB.cues = []; SUB.waiting = false; paintCues(); return; }
  if (!key || !P) { SUB.cues = []; SUB.waiting = false; paintCues(); return; }
  const ck = subCacheKey(P.it.id, key);
  if (SUB.cache[ck]) { SUB.cues = SUB.cache[ck]; SUB.waiting = false; paintCues(); return; }
  if (!opts.keep) { SUB.cues = []; SUB.waiting = true; paintCues(); }
  const gen = ++SUB.gen, id = P.it.id;
  try {
    const cues = parseVtt(await fetchVtt(id, key));
    SUB.cache[ck] = cues;
    if (SUB.gen !== gen || !P || P.it.id !== id || SUB.key !== key) return;
    SUB.cues = cues; SUB.waiting = false; paintCues();
  } catch (e) {
    if (SUB.gen === gen) { SUB.waiting = false; if (!SUB.cues.length) { const el = cueBox(); if (el) { el.innerHTML = ""; el.classList.add("hidden"); } } }
  }
}
["timeupdate", "seeked", "seeking", "loadedmetadata"].forEach(ev => video.addEventListener(ev, paintCues));
$("#pl-subs").onchange = () => {
  const key = $("#pl-subs").value;
  const wasBurn = !!(P && P.burning);
  const nowBurn = isBurnSub(key);
  try { if (key) localStorage.setItem("pl-subs", key); else localStorage.setItem("pl-subs", ""); } catch (e) {}
  if (P && (wasBurn || nowBurn)) {
    const pb = P.it.playback;
    let mode = P.mode;
    if (nowBurn && (mode === "direct" || mode === "remux")) {
      const hi = (pb.hires || []).map(p => hiresMode(p));
      mode = hi[0] || pb.profiles[0];
    }
    P.burning = nowBurn;
    startStream(mode, video.currentTime || P.start);
    return;
  }
  addSubTrack(key);
};
$("#pl-quality").onchange = () => {
  let m = $("#pl-quality").value; localStorage.setItem("quality", m === "direct" ? "auto" : m);
  if (isBurnSub($("#pl-subs").value) && (m === "direct" || m === "remux")) {
    const pb = P.it.playback;
    const hi = (pb.hires || []).map(p => hiresMode(p));
    m = hi[0] || pb.profiles[0];
    toast("Image subtitles are burned in, so this title is transcoded");
  }
  startStream(m, video.currentTime || P.start);
};
$("#pl-audio").onchange = () => {
  P.audio = +$("#pl-audio").value;
  // a non-default audio track needs the server (direct play can't switch tracks reliably): remux if possible
  const pb = P.it.playback;
  const m = P.mode === "direct" ? (P.audio === 0 ? "direct" : (pb.remux ? "remux" : pb.profiles[0])) : P.mode;
  startStream(m, video.currentTime || P.start);
};

function saveProgress(ended) {
  if (!P || !video.duration) return;
  if (!P.played && !ended) return;   // 1.4.1: a stream that never started must not wipe the saved resume point
  const pos = video.currentTime; const dur = isFinite(video.duration) ? video.duration : P.it.duration;
  api(`/api/items/${P.it.id}/progress`, { method: "POST", body: { position: pos, duration: dur, ended: !!ended } }).catch(() => {});
}
video.addEventListener("timeupdate", () => { if (P && Date.now() - P.lastSave > 10000) { P.lastSave = Date.now(); saveProgress(); } });
video.addEventListener("pause", () => saveProgress());
video.addEventListener("ended", () => { saveProgress(true); if (P && P.it.next && !UP.cancelled) UP.go(); });
video.addEventListener("timeupdate", () => { if (P) { UP.tick(); SK.tick(); } });
video.addEventListener("waiting", () => { if (P && P.mode !== "direct") setStatus(`${modeLabel(P.mode)} · buffering...`); });
video.addEventListener("playing", () => { if (P) { P.played = true; setStatus(modeLabel(P.mode)); } setTimeout(() => setStatus(""), 4000); });

function teardownVideo(stopServer) {
  if (hls) { hls.destroy(); hls = null; }
  video.removeAttribute("src"); $$("track", video).forEach(t => t.remove()); video.load();
  hideWait();
  try { if (typeof SK !== "undefined") SK.hide(); } catch (e) {}
  if (stopServer && P) api(`/api/items/${P.it.id}/stop?player=${encodeURIComponent(playerId())}`, { method: "POST" }).catch(() => {});
}
function closePlayer() {
  if (!P) return;
  PIP.leave(); saveProgress(); teardownVideo(true); P = null; PIP.tell();
  OV.reset(); UP.reset(); SK.reset();
  SUB.key = ""; SUB.cues = []; SUB.waiting = false; paintCues();
  $("#player").classList.add("hidden"); ROT.close();
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  route._keepScroll = true; route();
}
$("#pl-close").onclick = closePlayer;
$("#pl-next").onclick = () => { if (P && P.it.next) { saveProgress(); const n = P.it.next.id; teardownVideo(true); playItem(n, 0); } };
if ($("#pl-skip-intro")) $("#pl-skip-intro").onclick = () => SK.skipIntro();
if ($("#pl-skip-credits")) $("#pl-skip-credits").onclick = () => SK.skipCredits();
document.addEventListener("keydown", (e) => {
  const typing = e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA";
  if ((e.key === "m" || e.key === "M") && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
    const audioOpen = $("#audiobar") && !$("#audiobar").classList.contains("hidden");
    if ((!P || PIP.minimized()) && audioOpen) { e.preventDefault(); toggleAudioMute(); return; }
  }
  if (!P || PIP.minimized() || typing) return;   // in PiP the page is free for browsing
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (!["Shift", "Control", "Alt", "Meta"].includes(e.key)) OV.show();   // 1.4.12: any key brings the controls back
  if (e.key === "Escape" && BAR.popOpen()) BAR.closePop();
  else if (e.key === "Escape" && !fsEl()) closePlayer();
  else if (e.key === "m" || e.key === "M") BAR.toggleMute();
  else if (e.key === "p" || e.key === "P") { e.preventDefault(); PIP.toggle(); }
  else if (e.key === " " || e.key === "k") {
    if (e.target.tagName === "BUTTON" && e.key === " ") return;   // a focused button handles Space itself
    e.preventDefault(); togglePlay(); OV.show();
  }
  else if (e.key === "ArrowRight" || e.key === "l") { e.preventDefault(); skip(10, "right"); }
  else if (e.key === "ArrowLeft" || e.key === "j") { e.preventDefault(); skip(-10, "left"); }
  else if (e.key === "f") toggleFullscreen();
});

// 1.7.5: pinch out to fill the screen (object-fit: cover), pinch in to fit (contain).
// Remembered per device. Also in the Quality/settings menu as Fit / Fill.
function videoFit() { try { return localStorage.getItem("pl-videofit") === "fill" ? "fill" : "fit"; } catch (e) { return "fit"; } }
function setVideoFit(mode) {
  const fill = mode === "fill";
  const pl = document.getElementById("player");
  if (pl) pl.classList.toggle("fit-fill", fill);
  try { localStorage.setItem("pl-videofit", fill ? "fill" : "fit"); } catch (e) {}
  try { BAR.sync(); } catch (e) {}
}

// ---------------------------------------------------------------- 1.4.11: on-screen controls
// Tap / click the picture: show or hide big Back 10 s / Play-Pause / Forward 10 s buttons and the see-through server status.
// They fade after ~3 s while playing (stay while paused). Double-tap the left or right side to skip (again and again).
// Full screen is the whole player (not the bare <video>) so the buttons stay on top, also in the Android app.
function fsEl() { return document.fullscreenElement || document.webkitFullscreenElement || null; }
function togglePlay() { if (!P) return; if (video.paused) video.play().catch(() => {}); else video.pause(); }
function skip(d, side) {
  if (!P) return;
  const dur = isFinite(video.duration) && video.duration > 0 ? video.duration : (P.it.duration || 0);
  let t = (video.currentTime || 0) + d;
  if (dur) t = Math.min(t, Math.max(0, dur - 0.5));
  t = Math.max(0, t);
  video.currentTime = t;          // HLS (transcode / remux) playlists cover the whole film, so this seeks like direct play
  P.lastSave = 0;                 // the next timeupdate saves the new resume point
  if (side) OV.ripple(side, d);
  OV.show();
}
function toggleFullscreen() {
  const pl = $("#player");
  if (ROT.pseudoOn()) { ROT.manualExit(); return; }   // 1.5.0: the rotate fallback counts as full screen too
  if (fsEl()) { (document.exitFullscreen || document.webkitExitFullscreen).call(document); return; }
  const req = pl.requestFullscreen || pl.webkitRequestFullscreen;
  if (req) {
    Promise.resolve(req.call(pl, { navigationUI: "hide" })).then(() => {
      try { screen.orientation && screen.orientation.lock && screen.orientation.lock("landscape").catch(() => {}); } catch (e) {}
    }).catch(() => {});
  } else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();   // iPhone: only the bare video can go full screen
}
// ---------------------------------------------------------------- 1.5.0: rotate a phone / tablet = full screen
// While the player is open on a touch device, turning it sideways makes the player full screen and turning it back
// upright leaves full screen. Browsers may refuse full screen without a tap: then the player fills the screen with
// CSS ("pseudo full screen") and real full screen is tried again on the next tap. Leaving full screen by hand while
// sideways is respected until the next rotation. Never on desktop.
const ROT = (() => {
  const pl = $("#player");
  const touch = matchMedia("(hover: none) and (pointer: coarse)").matches || /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  const lq = matchMedia("(orientation: landscape)");
  let last = null, mine = false, manual = false, pseudo = false, leaving = false;
  const landscape = () => { try { if (screen.orientation && screen.orientation.type) return screen.orientation.type.startsWith("landscape"); } catch (e) {} return lq.matches; };
  const active = () => touch && P && !$("#player").classList.contains("hidden") && !(typeof PIP !== "undefined" && PIP.minimized()) && !document.documentElement.classList.contains("android-pip");
  // Movinite Android app 1.4+: let it follow the phone's rotation (and go immersive sideways) while the player is open
  function app(open) { try { if (window.MSAndroid && typeof window.MSAndroid.player === "function") window.MSAndroid.player(!!open); } catch (e) {} }
  function setPseudo(on) {
    pseudo = !!on; document.documentElement.classList.toggle("pl-pseudo-fs", pseudo);
    if (pseudo) { try { window.scrollTo(0, 0); } catch (e) {} }
  }
  function real() {
    const req = pl.requestFullscreen || pl.webkitRequestFullscreen;
    if (!req) return Promise.reject(new Error("no fullscreen"));
    try { return Promise.resolve(req.call(pl, { navigationUI: "hide" })); } catch (e) { return Promise.reject(e); }
  }
  function enter() {
    if (fsEl()) return;
    mine = true;
    real().then(() => setPseudo(false)).catch(() => { if (active() && landscape()) setPseudo(true); });
  }
  function exit() {
    setPseudo(false);
    if (fsEl()) { leaving = true; try { (document.exitFullscreen || document.webkitExitFullscreen).call(document).catch(() => {}); } catch (e) {} }
    mine = false;
  }
  function check(force) {
    const l = landscape();
    if (!force && l === last) return;
    last = l; manual = false;
    if (!active()) return;
    if (l) enter(); else exit();
    if (typeof OV !== "undefined") OV.show();
  }
  if (screen.orientation && screen.orientation.addEventListener) screen.orientation.addEventListener("change", () => check());
  if (lq.addEventListener) lq.addEventListener("change", () => check()); else if (lq.addListener) lq.addListener(() => check());
  window.addEventListener("orientationchange", () => setTimeout(() => check(), 120));
  const onFs = () => {
    if (fsEl()) { setPseudo(false); return; }
    if (leaving) { leaving = false; return; }
    if (mine && active() && landscape()) manual = true;     // left full screen by hand while sideways: stay out
    mine = false;
  };
  document.addEventListener("fullscreenchange", onFs); document.addEventListener("webkitfullscreenchange", onFs);
  // the fallback: any tap on the player (a user gesture) retries real full screen
  pl.addEventListener("pointerup", () => { if (pseudo && !manual && active() && landscape() && !fsEl()) { mine = true; real().then(() => setPseudo(false)).catch(() => {}); } }, true);
  return {
    open() { document.documentElement.classList.add("pl-open"); last = landscape(); manual = false; app(true); if (active() && last) enter(); },
    close() { document.documentElement.classList.remove("pl-open"); setPseudo(false); mine = false; manual = false; app(false); },
    manualExit() { manual = true; setPseudo(false); if (fsEl()) { leaving = true; (document.exitFullscreen || document.webkitExitFullscreen).call(document); } mine = false; },
    pseudoOn: () => pseudo, isTouch: () => touch, state: () => ({ touch, landscape: landscape(), pseudo, mine, manual, fs: !!fsEl() }),
    check
  };
})();
window.__msRot = { state: ROT.state };   // read-only: lets tests (and curious admins) see the rotate state
const OV = (() => {
  const pl = $("#player"), tap = $("#pl-tap");
  let hideT = null, tapT = null, lastTap = 0, lastSide = "", lastMove = 0, moveShown = 0, rip = { left: null, right: null }, ripSum = { left: 0, right: 0 };
  let pinch0 = 0, pinchedAt = 0;
  const isOn = () => pl.classList.contains("ov-on");
  const top = pl.querySelector(".pl-top");
  let overTop = false;
  // 1.4.12: keep everything up while a top-bar picker is open / focused or the mouse is over the top bar
  const bar = $("#pl-bar");
  // 1.4.12/1.4.13: keep everything up while a menu (Quality / Subtitles / Audio) is open, the seek bar is dragged,
  // or the mouse rests on the top or bottom bar
  const held = () => overTop || BAR.busy() || (window.TV && TV.on && document.activeElement && pl.contains(document.activeElement));
  function arm() { clearTimeout(hideT); hideT = null; if (!video.paused) hideT = setTimeout(() => { if (held()) arm(); else hide(); }, 3000); }
  // subtitles move up above the bottom bar while it is shown, and back down when it fades
  function liftCues() {
    const on = pl.classList.contains("ov-on"), bar = $("#pl-bar"), vh = video.getBoundingClientRect().height;
    // cue lines are about 5.3% of the picture high; count lines from the bottom (-1 = last line)
    const n = on && vh ? -(Math.ceil((bar.getBoundingClientRect().height - 8) / (vh * 0.053)) + 1) : null;
    [...video.textTracks].forEach(t => { if (t.mode !== "showing" || !t.cues) return;
      [...t.cues].forEach(c => { try {
        if (n) { if (c.line !== n) c.line = n; } else if (c.line !== "auto") c.line = "auto";
      } catch (e) {} }); });
  }
  video.textTracks.addEventListener("addtrack", (e) => e.track.addEventListener("cuechange", liftCues));
  video.textTracks.addEventListener("change", liftCues);
  function show() { if (!P) return; const was = pl.classList.contains("ov-on"); pl.classList.add("ov-on"); renderPlayerStat(); arm(); if (!was) liftCues(); }
  function hide() { clearTimeout(hideT); hideT = null; pl.classList.remove("ov-on"); BAR.closePop(); liftCues();
    const a = document.activeElement;   // no focus ring left on an invisible button
    if (a && pl.contains(a) && a.tagName === "BUTTON") a.blur(); }
  function reset() { hide(); clearTimeout(tapT); lastTap = 0; ["left", "right"].forEach(s => { clearTimeout(rip[s]); ripSum[s] = 0; $("#pl-rip-" + s[0]).classList.remove("on"); }); }
  function ripple(side, d) {
    const el = $("#pl-rip-" + side[0]);
    ripSum[side] = el.classList.contains("on") ? ripSum[side] + d : d;
    el.querySelector("b").textContent = (ripSum[side] > 0 ? "+" : "\u2212") + Math.abs(ripSum[side]) + "s";
    el.classList.add("on"); clearTimeout(rip[side]);
    rip[side] = setTimeout(() => { el.classList.remove("on"); ripSum[side] = 0; }, 650);
  }
  tap.addEventListener("click", (e) => {
    if (!P) return;
    if (Date.now() - pinchedAt < 450) return;   // a pinch just happened: don't toggle/skip
    if (BAR.popOpen()) { BAR.closePop(); return; }   // a tap beside an open menu just closes it
    const r = tap.getBoundingClientRect(), x = (e.clientX - r.left) / (r.width || 1);
    const side = x < 0.35 ? "left" : x > 0.65 ? "right" : "mid";
    const now = Date.now();
    if (side !== "mid" && side === lastSide && now - lastTap < 320) {      // double (or more) tap on a side: skip
      clearTimeout(tapT); tapT = null; lastTap = now;
      skip(side === "left" ? -10 : 10, side);
      return;
    }
    lastTap = now; lastSide = side;
    clearTimeout(tapT);
    // a mouse that just moved over the picture already showed the controls: the click keeps them up instead of hiding them
    const toggle = () => (isOn() && Date.now() - moveShown > 600) ? hide() : show();
    if (side === "mid") { toggle(); return; }
    tapT = setTimeout(() => { tapT = null; toggle(); }, 300);   // wait: it may become a double-tap
  });
  tap.addEventListener("dblclick", (e) => e.preventDefault());
  // 1.7.5: pinch-to-zoom (two fingers). touch-action:none lets this run in the Android WebView too.
  const pinchDist = (ev) => {
    const a = ev.touches[0], b = ev.touches[1];
    return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
  };
  tap.addEventListener("touchstart", (e) => {
    if (e.touches.length === 2) {
      pinch0 = pinchDist(e) || 1; pinchedAt = Date.now();
      clearTimeout(tapT); tapT = null; lastTap = 0;
      e.preventDefault();
    }
  }, { passive: false });
  tap.addEventListener("touchmove", (e) => {
    if (!pinch0 || e.touches.length !== 2) return;
    e.preventDefault();
    const scale = pinchDist(e) / pinch0;
    if (scale > 1.12) { setVideoFit("fill"); pinchedAt = Date.now(); }
    else if (scale < 0.88) { setVideoFit("fit"); pinchedAt = Date.now(); }
  }, { passive: false });
  tap.addEventListener("touchend", (e) => { if (e.touches.length < 2) pinch0 = 0; });
  tap.addEventListener("touchcancel", () => { pinch0 = 0; });
  // mouse: moving over the picture shows the controls (desktop)
  pl.addEventListener("pointermove", (e) => { if (e.pointerType !== "mouse" || !P) return; const n = Date.now(); if (n - lastMove < 250) return; lastMove = n; if (!isOn()) moveShown = n; show(); });
  const btn = (id, fn) => $(id).addEventListener("click", (e) => { e.stopPropagation(); fn(); });
  btn("#pl-back", () => skip(-10, null));
  btn("#pl-fwd", () => skip(10, null));
  btn("#pl-pp", () => { togglePlay(); show(); });
  btn("#pl-fs", () => toggleFullscreen());
  const pp = () => { const paused = video.paused; pl.classList.toggle("paused", paused); $("#pl-pp").setAttribute("aria-label", paused ? "Play" : "Pause"); $("#pl-bplay").setAttribute("aria-label", paused ? "Play" : "Pause"); };
  video.addEventListener("play", () => { pp(); arm(); });
  video.addEventListener("pause", () => { pp(); if (P) show(); });
  video.addEventListener("loadstart", pp);
  pl.addEventListener("focusin", () => { if (P) show(); });
  video.addEventListener("seeking", () => { if (P && isOn()) arm(); });
  document.addEventListener("fullscreenchange", () => { if (P) show(); });
  document.addEventListener("webkitfullscreenchange", () => { if (P) show(); });
  // the top bar floats over the picture; the status pill sits just under it, whatever its height (it wraps on phones)
  const setTopH = () => { pl.style.setProperty("--pltop", Math.max(40, top.offsetHeight - 16) + "px"); pl.style.setProperty("--plbar", Math.max(56, bar.offsetHeight - 20) + "px"); };
  if (window.ResizeObserver) { const ro = new ResizeObserver(setTopH); ro.observe(top); ro.observe(bar); } else window.addEventListener("resize", setTopH);
  // the mouse resting over the top bar (title included) keeps it up
  pl.addEventListener("pointermove", (e) => { if (e.pointerType !== "mouse") return; const was = overTop;
    overTop = e.clientY <= top.getBoundingClientRect().bottom - 12 || e.clientY >= bar.getBoundingClientRect().top + 20;
    if (was && !overTop && P && isOn()) arm(); });
  pl.addEventListener("pointerleave", () => { overTop = false; });
  return { show, hide, reset, ripple, held, isOn, arm };
})();

// ---------------------------------------------------------------- 1.4.13: our own see-through bottom bar
// Seek bar (buffered, hover time, drag), time, play, -/+10 s, volume; on the right Quality (+ speed), Subtitles, Audio,
// PiP and Full screen as real buttons. The hidden <select>s stay the source of truth (startStream / onchange use them).
const BAR = (() => {
  const pl = $("#player"), seek = $("#pl-seek"), prog = $("#pl-prog"), buf = $("#pl-buf"), knob = $("#pl-knob"), tip = $("#pl-tip");
  const time = $("#pl-time"), pop = $("#pl-pop"), stage = $("#pl-stage");
  let drag = false, popFor = null, rate = 1;
  const dur = () => (isFinite(video.duration) && video.duration > 0) ? video.duration : ((P && P.it.duration) || 0);
  const fmt = (t) => { t = Math.max(0, Math.floor(t || 0)); const h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, s2 = t % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s2).padStart(2, "0"); };
  function draw(at) {
    const d = dur(), t = at !== undefined ? at : video.currentTime || 0, f = d ? Math.min(1, t / d) : 0;
    prog.style.width = (f * 100) + "%"; knob.style.left = (f * 100) + "%";
    time.textContent = fmt(t) + " / " + fmt(d);
    seek.setAttribute("aria-valuemax", Math.round(d)); seek.setAttribute("aria-valuenow", Math.round(t)); seek.setAttribute("aria-valuetext", fmt(t));
    let end = 0; const b = video.buffered;
    for (let i = 0; i < b.length; i++) if (b.start(i) <= t + 1 && b.end(i) > end) end = b.end(i);
    buf.style.width = (d ? Math.min(100, end / d * 100) : 0) + "%";
  }
  ["timeupdate", "progress", "durationchange", "loadedmetadata", "seeking", "emptied"].forEach(ev => video.addEventListener(ev, () => { if (!drag) draw(); }));
  // seek: click or drag; works the same for direct play and HLS (the playlist covers the whole film)
  const frac = (e) => { const r = seek.getBoundingClientRect(); return Math.min(1, Math.max(0, (e.clientX - r.left) / (r.width || 1))); };
  seek.addEventListener("pointerdown", (e) => { if (!P || !dur()) return; e.preventDefault(); e.stopPropagation(); drag = true; seek.classList.add("drag");
    try { seek.setPointerCapture(e.pointerId); } catch (x) {} draw(frac(e) * dur()); });
  seek.addEventListener("pointermove", (e) => {
    if (!P || !dur()) return;
    const f = frac(e); const at = f * dur();
    const tt = $("#pl-tip-t"); if (tt) tt.textContent = fmt(at); else tip.textContent = fmt(at);
    tip.style.left = (f * 100) + "%"; tip.classList.remove("hidden");
    showTrickplayTip(at);
    if (drag) draw(at);
  });
  const end = (e) => { if (!drag) return; drag = false; seek.classList.remove("drag"); tip.classList.add("hidden");
    const t = frac(e) * dur(); video.currentTime = Math.min(t, Math.max(0, dur() - 0.5)); if (P) P.lastSave = 0; draw(); OV.show(); };
  seek.addEventListener("pointerup", end); seek.addEventListener("pointercancel", (e) => { drag = false; seek.classList.remove("drag"); tip.classList.add("hidden"); });
  seek.addEventListener("pointerleave", () => { if (!drag) tip.classList.add("hidden"); });
  seek.addEventListener("click", (e) => e.stopPropagation());
  seek.addEventListener("keydown", (e) => {   // a focused seek bar: Home / End / Page keys (arrows are the player's own +/-10 s)
    if (!P) return;
    const d = dur(); let t = null;
    if (e.key === "Home") t = 0; else if (e.key === "End") t = d - 1; else if (e.key === "PageUp") t = video.currentTime + 60; else if (e.key === "PageDown") t = video.currentTime - 60;
    if (t !== null) { e.preventDefault(); e.stopPropagation(); video.currentTime = Math.max(0, Math.min(t, d - 0.5)); P.lastSave = 0; OV.show(); }
  });
  const btn = (id, fn) => $(id).addEventListener("click", (e) => { e.stopPropagation(); fn(e); OV.show(); });
  btn("#pl-bplay", () => togglePlay());
  btn("#pl-bback", () => skip(-10, null));
  btn("#pl-bfwd", () => skip(10, null));
  // volume (remembered in this browser)
  const vol = $("#pl-vol"), mute = $("#pl-mute");
  try { const v = parseFloat(localStorage.getItem("pl-vol")); if (v >= 0 && v <= 1) video.volume = v; video.muted = localStorage.getItem("pl-muted") === "1"; } catch (e) {}
  const drawVol = () => { vol.value = video.muted ? 0 : video.volume; mute.classList.toggle("pl-mute-on", video.muted || video.volume === 0);
    mute.setAttribute("aria-label", video.muted ? "Unmute" : "Mute"); mute.title = video.muted ? "Unmute (M)" : "Mute (M)"; };
  video.addEventListener("volumechange", () => { drawVol(); try { localStorage.setItem("pl-vol", String(video.volume)); localStorage.setItem("pl-muted", video.muted ? "1" : "0"); } catch (e) {} });
  vol.addEventListener("input", () => { video.volume = +vol.value; video.muted = +vol.value === 0; OV.show(); });
  vol.addEventListener("click", (e) => e.stopPropagation());
  function toggleMute() { video.muted = !video.muted; if (!video.muted && video.volume === 0) video.volume = 0.5; }
  btn("#pl-mute", toggleMute);
  drawVol();
  // ---- the three menus
  const q = $("#pl-quality"), subs = $("#pl-subs"), aud = $("#pl-audio");
  const RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
  // "en" -> "English (en)" for bare language codes; anything else as it is
  function langName(t) { const c = (t || "").trim(); if (!/^[a-z]{2,3}(-[A-Za-z]{2})?$/.test(c)) return c;
    try { const n = new Intl.DisplayNames(["en"], { type: "language" }).of(c); return n && n !== c ? n + " (" + c + ")" : c; } catch (e) { return c; } }
  function qLabel(v) { return v === "direct" || v === "remux" ? "Original" : /^2160p/.test(v) ? "4K" : /^1440p/.test(v) ? "2K" : v; }
  function sync() {
    $("#pl-bq-t").textContent = qLabel(q.value) + (rate !== 1 ? " · " + rate + "×" : "");
    $("#pl-bq").title = "Quality: " + ((q.selectedOptions[0] || {}).textContent || "") + " · speed " + rate + "×";
    $("#pl-bcc").classList.toggle("on", !!subs.value);
    $("#pl-bcc").title = subs.options.length > 1 ? "Subtitles: " + ((subs.selectedOptions[0] || {}).textContent || "off") : "Subtitles (none for this film)";
    $("#pl-baud").classList.toggle("hidden", aud.options.length < 2);
    if (popFor) render(popFor);
  }
  function item(label, checked, fn, cls) {
    const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "menuitemradio"); b.setAttribute("aria-checked", checked ? "true" : "false");
    if (cls) b.className = cls;
    b.innerHTML = `<span class="ck">${checked ? "✓" : ""}</span><span>${esc(label)}</span>`;
    b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
    return b;
  }
  const pick = (sel, v) => { if (sel.value !== v) { sel.value = v; sel.dispatchEvent(new Event("change")); } sync(); };
  function render(kind) {
    const keep = (document.activeElement && pop.contains(document.activeElement)) ? (document.activeElement.textContent || "") : "";
    pop.innerHTML = "";
    const h = (t) => { const x = document.createElement("h4"); x.textContent = t; pop.appendChild(x); };
    if (kind === "q") {
      h("Quality");
      [...q.options].forEach(o => {
        if (o.disabled) { const b = item(o.textContent, false, () => toast(o.dataset.note || "Not available")); b.classList.add("off"); b.setAttribute("aria-disabled", "true"); b.title = o.dataset.note || ""; pop.appendChild(b); return; }
        pop.appendChild(item(o.textContent, o.value === q.value, () => { pick(q, o.value); closePop(); }));
      });
      h("Picture");
      pop.appendChild(item("Fit (whole picture)", videoFit() !== "fill", () => { setVideoFit("fit"); render("q"); }));
      pop.appendChild(item("Fill (cover the screen)", videoFit() === "fill", () => { setVideoFit("fill"); render("q"); }));
      h("Speed");
      const sp = document.createElement("div"); sp.className = "sp";
      RATES.forEach(r => { const b = item(r === 1 ? "Normal" : r + "×", r === rate, () => { setRate(r); render("q"); }); b.querySelector(".ck").remove(); sp.appendChild(b); });
      pop.appendChild(sp);
    } else if (kind === "cc") {
      h("Subtitles");
      if (subs.options.length < 2) { const n = document.createElement("div"); n.className = "muted"; n.style.cssText = "padding:8px 12px 12px;font-size:14px"; n.textContent = "No subtitles found for this film."; pop.appendChild(n); }
      else [...subs.options].forEach(o => pop.appendChild(item(o.value ? langName(o.textContent) : "Off", o.value === subs.value, () => { pick(subs, o.value); closePop(); })));
    } else if (kind === "aud") {
      h("Audio");
      [...aud.options].forEach(o => pop.appendChild(item(o.textContent, o.value === aud.value, () => { pick(aud, o.value); closePop(); })));
    }
    if (keep && window.TV && TV.on && !pop.classList.contains("hidden")) {
      const again = [...pop.querySelectorAll("button")].find(b => b.textContent === keep)
        || pop.querySelector('[aria-checked="true"]') || pop.querySelector("button");
      if (again) { try { TV.focus(again); } catch (e) { try { again.focus({ preventScroll: true }); } catch (e2) {} } }
    }
  }
  function openPop(kind, anchor) {
    if (popFor === kind) { closePop(); return; }
    popFor = kind; render(kind); pop.classList.remove("hidden"); pop.dataset.kind = kind;
    $$(".pl-bar .pl-cb").forEach(b => b.setAttribute("aria-expanded", "false")); anchor.setAttribute("aria-expanded", "true");
    // place it above its button, right-aligned with it (phones: a bottom sheet, from the CSS)
    const sr = stage.getBoundingClientRect(), br = anchor.getBoundingClientRect();
    pop.style.top = "auto"; pop.style.left = "auto";
    pop.style.right = Math.max(8, sr.right - br.right) + "px";
    pop.style.bottom = Math.max(8, sr.bottom - br.top + 8) + "px";
    OV.show();
    const first = pop.querySelector('[aria-checked="true"]') || pop.querySelector("button");
    if (first && (!SFX.COARSE || (window.TV && TV.on))) first.focus({ preventScroll: true });
  }
  function closePop() {
    if (!popFor) return;
    const anchor = $(`.pl-bar [aria-expanded="true"]`);
    popFor = null; pop.classList.add("hidden"); pop.innerHTML = "";
    $$(".pl-bar .pl-cb").forEach(b => b.setAttribute("aria-expanded", "false"));
    if (anchor && window.TV && TV.on) { try { TV.focus(anchor); } catch (e) { try { anchor.focus({ preventScroll: true }); } catch (e2) {} } }
    else if (P && OV.isOn()) OV.arm();
  }
  function setRate(r) { rate = r; video.defaultPlaybackRate = r; video.playbackRate = r; sync(); }
  video.addEventListener("loadedmetadata", () => { if (video.playbackRate !== rate) video.playbackRate = rate; });
  btn("#pl-bq", (e) => openPop("q", e.currentTarget));
  btn("#pl-bcc", (e) => openPop("cc", e.currentTarget));
  btn("#pl-baud", (e) => openPop("aud", e.currentTarget));
  pop.addEventListener("click", (e) => e.stopPropagation());
  pop.addEventListener("keydown", (e) => {
    const items = [...pop.querySelectorAll("button")], i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); e.stopPropagation(); const n = items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]; if (n) n.focus(); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); const a = $(`.pl-bar [aria-expanded="true"]`); closePop(); if (a) a.focus(); }
  });
  let shutAt = 0;   // a press outside closed the menu: the click that follows must not also toggle the overlay
  document.addEventListener("pointerdown", (e) => { if (popFor && !pop.contains(e.target) && !e.target.closest(".pl-bar .pl-cb")) { closePop(); shutAt = Date.now(); } }, true);
  [q, subs, aud].forEach(sel => sel.addEventListener("change", sync));
  video.addEventListener("loadstart", sync);
  return { sync, draw, closePop, popOpen: () => !!popFor || Date.now() - shutAt < 600, busy: () => drag || !!popFor, toggleMute, setRate, rate: () => rate };
})();
setVideoFit(videoFit());

// ---------------------------------------------------------------- 1.4.12: picture in picture
// Chrome / Edge / Safari / Android Chrome: the PiP button (or P) pops the film out into a small always-on-top window and
// the player gets out of the way so you can keep browsing; a chip at the bottom right brings it back or stops it.
// The Android app does PiP natively (bridge MSAndroid.pip). Firefox has no PiP API for pages: it has its own toggle.
const PIP = (() => {
  const pl = $("#player"), btn = $("#pl-pip"), chip = $("#pip-chip"), hint = $("#pl-hint");
  const bridge = () => { try { return !!(window.MSAndroid && window.MSAndroid.pip && window.MSAndroid.pipAvailable && window.MSAndroid.pipAvailable()); } catch (e) { return false; } };
  const api = () => !!(document.pictureInPictureEnabled && video.requestPictureInPicture && !video.disablePictureInPicture);
  const firefox = /Firefox\//.test(navigator.userAgent);
  let hintT = null, nativeOn = false;
  function mode() { return bridge() ? "android" : api() ? "api" : firefox ? "firefox" : "none"; }
  function setup() {
    const m = mode();
    btn.classList.toggle("hidden", m === "none");
    btn.title = m === "firefox" ? "Picture in picture: in Firefox press Ctrl+Shift+] (Cmd+Option+Shift+] on a Mac), or use Firefox's own PiP toggle"
                                : "Picture in picture (P)";
    btn.dataset.mode = m;
  }
  function say(t) { hint.textContent = t; hint.classList.remove("hidden"); clearTimeout(hintT); hintT = setTimeout(() => hint.classList.add("hidden"), 5000); }
  const active = () => document.pictureInPictureElement === video || nativeOn;
  function enter() {
    if (!P) return;
    const m = mode();
    if (m === "android") { try { window.MSAndroid.pip(video.videoWidth || 16, video.videoHeight || 9); } catch (e) {} return; }
    if (m === "firefox") { say("Firefox: press Ctrl+Shift+] (Cmd+Option+Shift+] on a Mac) for picture-in-picture"); return; }
    if (m !== "api") return;
    if (video.readyState < 1) { say("Wait a moment for the film to start, then try again"); return; }
    video.requestPictureInPicture().catch((e) => say("Picture-in-picture isn't available here (" + (e && e.message || e) + ")"));
  }
  function leave() {   // also used when the player closes or another film starts
    if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {});
    minimize(false);
  }
  function toggle() { if (document.pictureInPictureElement === video) leave(); else enter(); }
  function minimize(on) {
    pl.classList.toggle("pip-min", on); pl.classList.toggle("in-pip", on);
    chip.classList.toggle("hidden", !on);
    if (on && P) $("#pip-chip-t").textContent = "Playing in picture-in-picture: " + (P.it.title || "");
  }
  video.addEventListener("enterpictureinpicture", () => { if (!P) { leave(); return; } OV.hide(); minimize(true); });
  video.addEventListener("leavepictureinpicture", () => { minimize(false); if (P) { OV.show(); saveProgress(); } });   // back to the full player
  btn.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
  $("#pip-chip-back").onclick = () => leave();
  $("#pip-chip-close").onclick = () => closePlayer();
  // Android app: native PiP shrinks the whole app window, so show only the picture in it
  window.__msAndroidPip = (on) => { nativeOn = !!on; document.documentElement.classList.toggle("android-pip", nativeOn); if (nativeOn) OV.hide(); else if (P) OV.show(); };
  // tell the Android app whether a film is playing, so Home can shrink it into a PiP window
  const tell = () => { if (!bridge()) return; try { window.MSAndroid.playing(!!(P && !video.paused && !video.ended), video.videoWidth || 16, video.videoHeight || 9); } catch (e) {} };
  ["play", "playing", "pause", "ended", "emptied", "loadedmetadata"].forEach(ev => video.addEventListener(ev, tell));
  setup();
  return { setup, toggle, leave, active, minimized: () => pl.classList.contains("pip-min"), mode, tell };
})();
window.addEventListener("beforeunload", () => saveProgress());

// ---------------------------------------------------------------- audio player
const audio = $("#audio");
let Q = { list: [], idx: -1, hls: null, mode: null };
function playAlbum(libId, artist, album, idx) {
  api(`/api/album?library_id=${libId}&artist=${enc(artist)}&album=${enc(album)}`).then(d => playQueue(d.tracks, idx || 0));
}
async function playQueue(list, idx) {
  if (P) closePlayer();
  Q.list = (list || []).slice();
  Q.idx = idx || 0;
  await loadTrack();
}
async function loadTrack() {
  const t0 = Q.list[Q.idx]; if (!t0) return;
  const t = t0.playback ? t0 : await api("/api/items/" + t0.id);
  Q.list[Q.idx] = t;
  if (Q.hls) { Q.hls.destroy(); Q.hls = null; }
  $("#audiobar").classList.remove("hidden"); document.documentElement.classList.add("ab-open");
  $("#ab-title").textContent = t.title; $("#ab-sub").textContent = [t.artist, t.album].filter(Boolean).join(" · ");
  const hasArt = !!t.poster;
  $("#ab-art").src = hasArt ? thumbUrl(t.poster) : LOGO_MARK;
  const st = $("#ab-stage"); if (st) st.classList.toggle("logo", !hasArt);
  const direct = t.playback.direct && audio.canPlayType(t.playback.mime) !== "";
  Q.mode = direct ? "direct" : "hls";
  if (direct) audio.src = `/api/items/${t.id}/file`;
  else {
    const url = `/api/items/${t.id}/hls/audio/index.m3u8`;
    if (window.Hls && Hls.isSupported()) { Q.hls = new Hls({ xhrSetup: (x) => { x.withCredentials = true; } }); Q.hls.loadSource(url); Q.hls.attachMedia(audio); }
    else audio.src = url;
  }
  eqResume();
  audio.play().catch(() => {});
  $$(".li.playing").forEach(el => el.classList.remove("playing"));
  document.title = t.title + " · Movinite";
  syncAbButtons();
  if ("mediaSession" in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist || "", album: t.album || "", artwork: [{ src: t.poster ? thumbUrl(t.poster) : LOGO_MARK }] });
    navigator.mediaSession.setActionHandler("nexttrack", nextTrack); navigator.mediaSession.setActionHandler("previoustrack", prevTrack);
  }
}
function nextTrack() { if (Q.idx < Q.list.length - 1) { Q.idx++; loadTrack(); } }
function prevTrack() { if (audio.currentTime > 4) audio.currentTime = 0; else if (Q.idx > 0) { Q.idx--; loadTrack(); } }
audio.addEventListener("error", () => {
  const t = Q.list[Q.idx];
  if (Q.mode === "direct" && t) { Q.mode = "hls"; const url = `/api/items/${t.id}/hls/audio/index.m3u8`; if (window.Hls && Hls.isSupported()) { Q.hls = new Hls(); Q.hls.loadSource(url); Q.hls.attachMedia(audio); audio.play().catch(() => {}); } }
});
audio.addEventListener("ended", () => { const t = Q.list[Q.idx]; if (t) api(`/api/items/${t.id}/progress`, { method: "POST", body: { position: t.duration || 0, duration: t.duration || 0, ended: true } }).catch(() => {}); nextTrack(); });
audio.addEventListener("play", () => { $("#ab-play").classList.add("playing"); $("#ab-play").setAttribute("aria-label", "Pause"); eqResume(); if (document.documentElement.classList.contains("af-open")) vizStart(); });
audio.addEventListener("pause", () => { $("#ab-play").classList.remove("playing"); $("#ab-play").setAttribute("aria-label", "Play"); });
audio.addEventListener("timeupdate", () => {
  const d = isFinite(audio.duration) ? audio.duration : (Q.list[Q.idx] || {}).duration || 0;
  $("#ab-cur").textContent = fmtDur(audio.currentTime); $("#ab-dur").textContent = fmtDur(d);
  if (!$("#ab-range").dragging) $("#ab-range").value = d ? Math.round(1000 * audio.currentTime / d) : 0;
  syncAbButtons();
});
$("#ab-range").addEventListener("input", () => { $("#ab-range").dragging = true; });
$("#ab-range").addEventListener("change", () => {
  const d = isFinite(audio.duration) ? audio.duration : (Q.list[Q.idx] || {}).duration || 0;
  audio.currentTime = d * $("#ab-range").value / 1000; $("#ab-range").dragging = false;
});
$("#ab-play").onclick = () => { eqResume(); audio.paused ? audio.play() : audio.pause(); };
$("#ab-next").onclick = () => { eqResume(); nextTrack(); };
$("#ab-prev").onclick = () => { eqResume(); prevTrack(); };
$("#ab-close").onclick = stopAudio;

/* 1.8.1: music mute + volume. Remembers the last non-zero level. M toggles mute. */
const AB_VOL_KEY = "ab-vol", AB_MUTE_KEY = "ab-muted";
let abLastVol = 1, abVolPop = false;
function abSavedVol() {
  try {
    const v = parseFloat(localStorage.getItem(AB_VOL_KEY));
    if (isFinite(v) && v > 0 && v <= 1) return v;
  } catch (e) {}
  return 1;
}
function abSavedMuted() {
  try { return localStorage.getItem(AB_MUTE_KEY) === "1"; } catch (e) { return false; }
}
function abPersistVol() {
  try {
    if (audio.volume > 0) localStorage.setItem(AB_VOL_KEY, String(audio.volume));
    localStorage.setItem(AB_MUTE_KEY, audio.muted || audio.volume === 0 ? "1" : "0");
  } catch (e) {}
}
function abSyncVol() {
  const muted = !!(audio.muted || audio.volume === 0);
  const shown = Math.round((muted ? 0 : audio.volume) * 100);
  const percent = Math.round((audio.muted ? 0 : audio.volume) * 100);
  const v = Math.round((audio.muted ? abLastVol : (audio.volume || 0)) * 100);
  const slider = audio.muted ? Math.round(abLastVol * 100) : Math.round(audio.volume * 100);
  ["#ab-vol", "#ab-vol-v"].forEach(sel => {
    const el = $(sel); if (!el) return;
    if (document.activeElement !== el) el.value = String(slider);
  });
  const btn = $("#ab-mute");
  if (btn) {
    btn.classList.toggle("muted", muted);
    btn.setAttribute("aria-pressed", muted ? "true" : "false");
    btn.setAttribute("aria-label", muted ? "Unmute" : "Mute");
    btn.title = muted ? "Unmute (M)" : "Mute (M)";
  }
  const wrap = $("#ab-volw"); if (wrap) wrap.classList.toggle("is-muted", muted);
}
function abSetVolume(pct, fromUser) {
  const v = Math.max(0, Math.min(100, +pct)) / 100;
  audio.volume = v;
  if (v > 0) { abLastVol = v; audio.muted = false; }
  else audio.muted = true;
  if (fromUser) abPersistVol();
  abSyncVol();
}
function toggleAudioMute() {
  if (audio.muted || audio.volume === 0) {
    audio.muted = false;
    if (audio.volume === 0) audio.volume = abLastVol || abSavedVol() || 0.5;
    if (audio.volume > 0) abLastVol = audio.volume;
  } else {
    if (audio.volume > 0) abLastVol = audio.volume;
    audio.muted = true;
  }
  abPersistVol();
  abSyncVol();
}
function abSetVolPop(on) {
  abVolPop = !!on;
  const pop = $("#ab-vol-pop"), btn = $("#ab-vol-open");
  if (pop) pop.classList.toggle("hidden", !abVolPop);
  if (btn) btn.setAttribute("aria-expanded", abVolPop ? "true" : "false");
  const wrap = $("#ab-volw"); if (wrap) wrap.classList.toggle("open", abVolPop);
}
function abInitVol() {
  abLastVol = abSavedVol();
  audio.volume = abLastVol;
  audio.muted = abSavedMuted();
  abSyncVol();
}
abInitVol();
if ($("#ab-mute")) $("#ab-mute").onclick = (e) => { e.stopPropagation(); toggleAudioMute(); };
["#ab-vol", "#ab-vol-v"].forEach(sel => {
  const el = $(sel); if (!el) return;
  el.addEventListener("input", () => abSetVolume(el.value, true));
  el.addEventListener("change", () => abSetVolume(el.value, true));
});
if ($("#ab-vol-open")) $("#ab-vol-open").onclick = (e) => { e.stopPropagation(); abSetVolPop(!abVolPop); };
document.addEventListener("click", (e) => { if (abVolPop && !e.target.closest("#ab-volw")) abSetVolPop(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && abVolPop) abSetVolPop(false); });
audio.addEventListener("volumechange", abSyncVol);
$("#ab-stage").onclick = openAudioFull;
$("#ab-art").onclick = openAudioFull;
$("#ab-meta").onclick = openAudioFull;
$("#ab-back").onclick = closeAudioFull;
$("#ab-eq").onclick = () => { if (window.matchMedia("(max-width:820px)").matches) openAudioFull(); eqResume(); toggleEqPanel(); afChromePoke(); };
$("#ab-add").onclick = (e) => { e.stopPropagation(); const cur = Q.list[Q.idx]; if (cur && cur.id) openPlaylistSheet([cur.id]); };
$("#ab-viz-toggle").onclick = (e) => { e.stopPropagation(); VIZ.on = !VIZ.on; vizSave(); vizStart(); afChromePoke(); };
function syncAbButtons() {
  const n = (Q.list || []).length, i = Q.idx;
  $("#ab-prev").disabled = n === 0 || (i <= 0 && audio.currentTime <= 4);
  $("#ab-next").disabled = n === 0 || i >= n - 1;
}
const AF_HIDE_MS = 3000;
let afHideT = 0;
function afChromePoke() {
  const root = document.documentElement;
  if (!root.classList.contains("af-open")) return;
  root.classList.remove("af-chrome-off");
  clearTimeout(afHideT);
  const eqOpen = $("#eqpanel") && !$("#eqpanel").classList.contains("hidden");
  const sheetOpen = $("#plsheet") && !$("#plsheet").classList.contains("hidden");
  if (eqOpen || sheetOpen) return;
  afHideT = setTimeout(() => {
    if (!document.documentElement.classList.contains("af-open")) return;
    const eq2 = $("#eqpanel") && !$("#eqpanel").classList.contains("hidden");
    const sh2 = $("#plsheet") && !$("#plsheet").classList.contains("hidden");
    if (eq2 || sh2) return;
    document.documentElement.classList.add("af-chrome-off");
  }, AF_HIDE_MS);
}
function openAudioFull() {
  if ($("#audiobar").classList.contains("hidden")) return;
  document.documentElement.classList.add("af-open");
  afChromePoke();
  vizStart();
}
function closeAudioFull() {
  document.documentElement.classList.remove("af-open", "af-chrome-off", "viz-on");
  clearTimeout(afHideT);
  hideEqPanel();
  vizStop();
}
function stopAudio() {
  audio.pause(); if (Q.hls) { Q.hls.destroy(); Q.hls = null; }
  audio.removeAttribute("src"); audio.load(); Q = { list: [], idx: -1, hls: null, mode: null };
  closeAudioFull();
  $("#audiobar").classList.add("hidden"); document.documentElement.classList.remove("ab-open"); document.title = "Movinite";
  $("#ab-play").classList.remove("playing");
  vizStop();
}

/* 1.7.3: music equalizer via the Web Audio API. Only #audio is connected; the video element is left alone. */
const EQ_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
const EQ_LABELS = ["32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];
const EQ_PRESETS = {
  Flat: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "Bass Boost": [7, 5, 3, 1, 0, 0, 0, 0, 0, 0],
  "Treble Boost": [0, 0, 0, 0, 0, 0, 2, 4, 6, 7],
  Vocal: [-2, -1, 0, 2, 4, 4, 3, 1, 0, -1],
  Rock: [5, 3, -2, -3, -1, 1, 3, 4, 4, 3],
  Pop: [-1, 2, 4, 3, 0, -1, 1, 2, 3, 2],
  Jazz: [3, 2, 1, 2, -2, -2, 0, 1, 2, 3],
  Classical: [4, 3, 2, 0, 0, 0, -1, 2, 3, 4],
  Dynamic: [6, 5, 3, 0, -2, -2, 0, 3, 5, 6]
};
const EQ_STORE = "movinite-eq-v1";
const EQ = {
  ctx: null, src: null, filters: [], wet: null, dry: null, comp: null, makeup: null,
  compGain: null, directGain: null, on: true, preset: "Flat",
  bands: EQ_PRESETS.Flat.slice(), ready: false,
  ok: !!(window.AudioContext || window.webkitAudioContext)
};
function eqLoad() {
  try {
    const s = JSON.parse(localStorage.getItem(EQ_STORE) || "null");
    if (s && Array.isArray(s.bands) && s.bands.length === 10) {
      EQ.bands = s.bands.map(n => Math.max(-12, Math.min(12, +n || 0)));
      EQ.on = s.on !== false;
      EQ.preset = typeof s.preset === "string" ? s.preset : "Custom";
    }
  } catch (e) {}
}
function eqSave() {
  try { localStorage.setItem(EQ_STORE, JSON.stringify({ on: EQ.on, preset: EQ.preset, bands: EQ.bands })); } catch (e) {}
}
function eqResume() {
  if (!EQ.ok) return;
  eqEnsure();
  if (EQ.ctx && EQ.ctx.state === "suspended") EQ.ctx.resume().catch(() => {});
}
function eqEnsure() {
  if (!EQ.ok || EQ.ready) return EQ.ready;
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    /* same-origin /api/ streams (and HLS on this host). Do not set crossOrigin: a
       credentialed request without CORS would be silenced by createMediaElementSource. */
    const src = ctx.createMediaElementSource(audio);
    const filters = EQ_FREQS.map((f, i) => {
      const b = ctx.createBiquadFilter();
      if (i === 0) { b.type = "lowshelf"; b.frequency.value = f; }
      else if (i === EQ_FREQS.length - 1) { b.type = "highshelf"; b.frequency.value = f; }
      else { b.type = "peaking"; b.frequency.value = f; b.Q.value = 1; }
      b.gain.value = 0;
      return b;
    });
    for (let i = 0; i < filters.length - 1; i++) filters[i].connect(filters[i + 1]);
    const directGain = ctx.createGain();
    const compGain = ctx.createGain();
    const makeup = ctx.createGain();
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -24; comp.knee.value = 12; comp.ratio.value = 2.5;
    comp.attack.value = 0.02; comp.release.value = 0.25;
    makeup.gain.value = 1;
    const wet = ctx.createGain(), dry = ctx.createGain();
    src.connect(filters[0]);
    src.connect(dry);
    filters[filters.length - 1].connect(directGain);
    filters[filters.length - 1].connect(compGain);
    compGain.connect(comp); comp.connect(makeup);
    directGain.connect(wet); makeup.connect(wet);
    wet.connect(ctx.destination); dry.connect(ctx.destination);
    Object.assign(EQ, { ctx, src, filters, wet, dry, comp, makeup, compGain, directGain, ready: true });
    eqApply(false);
    return true;
  } catch (e) {
    console.warn("equalizer", e);
    EQ.ok = false;
    return false;
  }
}
function eqNamedPreset() {
  const keys = Object.keys(EQ_PRESETS);
  for (let i = 0; i < keys.length; i++) {
    const g = EQ_PRESETS[keys[i]];
    if (g.every((v, j) => Math.abs(v - EQ.bands[j]) < 0.21)) return keys[i];
  }
  return "Custom";
}
function eqApply(save) {
  if (EQ.ready) {
    EQ.filters.forEach((f, i) => { f.gain.value = EQ.on ? EQ.bands[i] : 0; });
    const dyn = EQ.on && EQ.preset === "Dynamic";
    if (EQ.directGain) EQ.directGain.gain.value = (EQ.on && !dyn) ? 1 : 0;
    if (EQ.compGain) EQ.compGain.gain.value = dyn ? 1 : 0;
    if (EQ.makeup) EQ.makeup.gain.value = dyn ? 1.41 : 1; /* ~+3 dB makeup, modest so it doesn't clip */
    if (EQ.wet) EQ.wet.gain.value = EQ.on ? 1 : 0;
    if (EQ.dry) EQ.dry.gain.value = EQ.on ? 0 : 1;
  }
  if (save !== false) eqSave();
  eqPaint();
}
function eqPaint() {
  const pan = $("#eqpanel");
  if (!pan) return;
  pan.classList.toggle("off", !EQ.on);
  const on = $("#eq-on"); if (on) on.checked = EQ.on;
  $$("#eq-presets .eq-preset").forEach(b => b.classList.toggle("on", b.dataset.preset === EQ.preset));
  $$("#eq-bands input[data-eq]").forEach(inp => {
    const i = +inp.dataset.eq;
    if (Math.abs(+inp.value - EQ.bands[i]) > 0.01) inp.value = EQ.bands[i];
    const lab = inp.parentNode.querySelector(".eq-val");
    if (lab) lab.textContent = (EQ.bands[i] > 0 ? "+" : "") + (+EQ.bands[i].toFixed(1)).toString().replace(/\.0$/, "");
  });
  const eqBtn = $("#ab-eq");
  if (eqBtn) eqBtn.classList.toggle("on", EQ.on && !pan.classList.contains("hidden"));
}
function eqBuild() {
  const host = $("#eq-bands"), presets = $("#eq-presets");
  if (!host || host.dataset.ready) return;
  host.dataset.ready = "1";
  EQ_FREQS.forEach((f, i) => {
    const lab = document.createElement("label");
    lab.className = "eq-band";
    lab.innerHTML = `<span class="eq-val" data-i="${i}">0</span>`
      + `<input type="range" min="-12" max="12" step="0.5" value="0" orient="vertical" data-eq="${i}" aria-label="${EQ_LABELS[i]} hertz">`
      + `<span class="eq-hz">${EQ_LABELS[i]}</span>`;
    host.appendChild(lab);
  });
  Object.keys(EQ_PRESETS).concat(["Custom"]).forEach(name => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "eq-preset"; b.dataset.preset = name; b.textContent = name;
    presets.appendChild(b);
  });
  presets.addEventListener("click", e => {
    const b = e.target.closest(".eq-preset"); if (!b) return;
    eqResume();
    if (b.dataset.preset === "Custom") return;
    EQ.preset = b.dataset.preset;
    EQ.bands = EQ_PRESETS[EQ.preset].slice();
    eqApply();
  });
  host.addEventListener("input", e => {
    const inp = e.target.closest("input[data-eq]"); if (!inp) return;
    eqResume();
    EQ.bands[+inp.dataset.eq] = +inp.value;
    EQ.preset = eqNamedPreset();
    eqApply();
  });
  $("#eq-on").onchange = () => { eqResume(); EQ.on = $("#eq-on").checked; eqApply(); };
  $("#eq-reset").onclick = () => { eqResume(); EQ.preset = "Flat"; EQ.bands = EQ_PRESETS.Flat.slice(); eqApply(); };
  $("#eq-close").onclick = hideEqPanel;
}
function toggleEqPanel() {
  const pan = $("#eqpanel");
  if (pan.classList.contains("hidden")) {
    eqBuild(); eqResume(); pan.classList.remove("hidden"); eqPaint();
  } else hideEqPanel();
}
function hideEqPanel() {
  $("#eqpanel").classList.add("hidden");
  const eqBtn = $("#ab-eq"); if (eqBtn) eqBtn.classList.remove("on");
}
eqLoad();
eqBuild();
bindPlaylistSheet();

/* 1.7.6: beat-reactive visualizer, tapped from the existing EQ graph (one AudioContext). */
const VIZ_STORE = "movinite-viz-v1";
const VIZ = { on: true, raf: 0, data: null, bassHist: [], lastBeat: 0, mock: null };
function vizReduced() {
  return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}
function vizLoad() {
  try {
    const s = JSON.parse(localStorage.getItem(VIZ_STORE) || "null");
    if (s && typeof s.on === "boolean") VIZ.on = s.on;
  } catch (e) {}
}
function vizSave() {
  try { localStorage.setItem(VIZ_STORE, JSON.stringify({ on: VIZ.on })); } catch (e) {}
}
function vizAttach() {
  if (!EQ.ready) return false;
  if (EQ.analyser) return true;
  try {
    const an = EQ.ctx.createAnalyser();
    an.fftSize = 256;
    an.smoothingTimeConstant = 0.72;
    EQ.src.connect(an);
    EQ.analyser = an;
    VIZ.data = new Uint8Array(an.frequencyBinCount);
    return true;
  } catch (e) {
    console.warn("visualizer", e);
    return false;
  }
}
function vizWanted() {
  return VIZ.on && !vizReduced() && document.documentElement.classList.contains("af-open") && !document.hidden;
}
function vizPaintToggle() {
  document.documentElement.classList.toggle("viz-on", !!(VIZ.on && !vizReduced() && document.documentElement.classList.contains("af-open")));
  const btn = $("#ab-viz-toggle");
  if (btn) { btn.classList.toggle("on", VIZ.on); btn.setAttribute("aria-pressed", VIZ.on ? "true" : "false"); }
}
function vizStart() {
  vizPaintToggle();
  if (!vizWanted()) { vizStop(); vizPaintToggle(); return; }
  eqEnsure();
  vizAttach();
  if (VIZ.raf) return;
  const tick = (now) => {
    VIZ.raf = requestAnimationFrame(tick);
    if (!vizWanted()) { vizStop(); vizPaintToggle(); return; }
    vizDraw(now);
  };
  VIZ.raf = requestAnimationFrame(tick);
}
function vizStop() {
  if (VIZ.raf) { cancelAnimationFrame(VIZ.raf); VIZ.raf = 0; }
  const st = $("#ab-stage"); if (st) st.classList.remove("pulse");
}
/* theme hues for the beat ring: accent, deep purple, lavender, magenta, indigo */
const VIZ_HUES = [
  [150, 55, 250],   /* #9637FA */
  [106, 22, 196],   /* #6A16C4 */
  [212, 187, 255],  /* #D4BBFF */
  [224, 48, 200],   /* magenta */
  [79, 70, 229]     /* indigo */
];
function vizLerp(a, b, t) {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}
function vizHue(t) {
  const n = VIZ_HUES.length;
  const x = (((t % 1) + 1) % 1) * n;
  const i = Math.floor(x);
  return vizLerp(VIZ_HUES[i], VIZ_HUES[(i + 1) % n], x - i);
}
function vizBarRgb(pos, freqT, energy, beat) {
  let c = vizHue(pos);
  if (freqT < 0.35) {
    const w = ((0.35 - freqT) / 0.35) * (0.3 + energy * 0.45);
    c = vizLerp(c, [232, 64, 200], w);
    const b = 1 + energy * 0.4 + beat * 0.2;
    c = [Math.min(255, c[0] * b), Math.min(255, c[1] * b), Math.min(255, c[2] * b)];
  } else if (freqT > 0.55) {
    const w = ((freqT - 0.55) / 0.45) * (0.35 + energy * 0.3);
    c = vizLerp(c, [212, 187, 255], w);
    const b = 1 + energy * 0.25;
    c = [Math.min(255, c[0] * b), Math.min(255, c[1] * b), Math.min(255, c[2] * b)];
  } else {
    const b = 1 + energy * 0.28 + beat * 0.1;
    c = [Math.min(255, c[0] * b), Math.min(255, c[1] * b), Math.min(255, c[2] * b)];
  }
  return c.map((x) => Math.round(x));
}
function vizRgba(c, a) {
  return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + a + ")";
}
function vizDraw(now) {
  const cv = $("#ab-viz"), st = $("#ab-stage");
  if (!cv || !st) return;
  const ctx = cv.getContext("2d");
  if (!ctx) return;
  const size = Math.min(st.clientWidth || 300, 640) * 2;
  if (cv.width !== size) { cv.width = size; cv.height = size; }
  const w = cv.width, h = cv.height, cx = w / 2, cy = h / 2;
  ctx.clearRect(0, 0, w, h);
  let bins = VIZ.mock;
  if (!bins && EQ.analyser && VIZ.data) { EQ.analyser.getByteFrequencyData(VIZ.data); bins = VIZ.data; }
  if (!bins) return;
  const n = 48, inner = Math.min(w, h) * 0.33, maxLen = Math.min(w, h) * 0.16;
  let bass = 0, nb = 0;
  const top = Math.min(6, bins.length - 1);
  for (let i = 1; i <= top; i++) { bass += bins[i] || 0; nb++; }
  bass = nb ? bass / nb : 0;
  VIZ.bassHist.push(bass);
  if (VIZ.bassHist.length > 24) VIZ.bassHist.shift();
  const avg = VIZ.bassHist.reduce((a, b) => a + b, 0) / VIZ.bassHist.length;
  const beat = Math.max(0, Math.min(1, (bass / 255) * (bass > avg ? 1.15 : 0.85)));
  const spin = (now || 0) / 14000; /* one slow turn around the palette ~14s */
  /* faint ambient wash on the ring, not the whole page */
  const wash = vizHue(spin);
  const glow = ctx.createRadialGradient(cx, cy, inner * 0.35, cx, cy, inner + maxLen * 1.85);
  glow.addColorStop(0, vizRgba(wash, (0.03 + beat * 0.07).toFixed(3)));
  glow.addColorStop(0.55, vizRgba(wash, (0.07 + beat * 0.1).toFixed(3)));
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);
  ctx.lineCap = "round";
  const lw = Math.max(3, w / 140);
  for (let i = 0; i < n; i++) {
    const idx = Math.min(bins.length - 1, 1 + Math.floor(i * (bins.length * 0.55) / n));
    const v = (bins[idx] || 0) / 255;
    const freqT = i / (n - 1);
    const ang = (i / n) * Math.PI * 2 - Math.PI / 2;
    const len = maxLen * (0.12 + v * 0.88);
    const rgb = vizBarRgb(i / n + spin, freqT, v, beat);
    const alpha = 0.42 + v * 0.58;
    ctx.shadowColor = vizRgba(rgb, 0.75);
    ctx.shadowBlur = 10 + v * 14 + beat * 8;
    ctx.strokeStyle = vizRgba(rgb, alpha.toFixed(3));
    ctx.lineWidth = lw;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(ang) * inner, cy + Math.sin(ang) * inner);
    ctx.lineTo(cx + Math.cos(ang) * (inner + len), cy + Math.sin(ang) * (inner + len));
    ctx.stroke();
  }
  ctx.shadowBlur = 0;
  ctx.shadowColor = "transparent";
  ctx.beginPath();
  ctx.arc(cx, cy, inner - 6, 0, Math.PI * 2);
  ctx.strokeStyle = vizRgba(vizHue(spin + 0.15), 0.28 + beat * 0.15);
  ctx.lineWidth = 2;
  ctx.stroke();
  if (bass > 88 && bass > avg * 1.28 && now - VIZ.lastBeat > 180) {
    VIZ.lastBeat = now;
    st.classList.add("pulse");
    setTimeout(() => st.classList.remove("pulse"), 140);
  }
}
vizLoad();
document.addEventListener("visibilitychange", () => {
  if (document.hidden) vizStop();
  else if (document.documentElement.classList.contains("af-open")) vizStart();
});
if ($("#audiobar")) {
  const poke = () => { if (document.documentElement.classList.contains("af-open")) afChromePoke(); };
  $("#audiobar").addEventListener("pointerdown", poke);
  $("#audiobar").addEventListener("touchstart", poke, { passive: true });
  $("#audiobar").addEventListener("mousemove", poke);
  $("#audiobar").addEventListener("keydown", poke);
}

function stopAll() { if (P) { PIP.leave(); teardownVideo(true); P = null; OV.reset(); $("#player").classList.add("hidden"); } stopAudio(); }

window.__msSetPlayerStat = function (d) { if (ME) ME.show_status = true; if (d) SYS.d = d; renderSysstat(); };
window.setVideoFit = setVideoFit;
window.paintCues = paintCues;
window.__msSubReady = function () { return !!(SUB && SUB.key && SUB.cues && SUB.cues.length); };
window.__msOpenAudioFull = openAudioFull;
window.__msCloseAudioFull = closeAudioFull;
window.__msAfChromePoke = afChromePoke;
window.__msVizSet = function (on) { VIZ.on = !!on; vizSave(); vizStart(); };
window.__msVizInject = function (arr, t) { VIZ.mock = arr ? new Uint8Array(arr) : null; if (arr) vizDraw(t != null ? t : performance.now()); };
window.__msVizTick = function () { vizDraw(performance.now()); };
window.openPlaylistSheet = openPlaylistSheet;

/* 1.9.1: Android TV / remote spatial navigation.
   Cards already have tabindex=0 and Enter-to-open (1.4.7), but a TV remote sends
   arrow keys, not Tab, and nothing moved focus between posters, the sidebar, or
   the player bar. This module turns those arrows into spatial focus, with a large
   purple focus ring, OK to select, and Back to go back. */

// 2.0.1 tests: open the video player on a short clip without going through the library (fake login only).
function openDummyPlayer(url) {
  if (P && typeof closePlayer === "function") { try { closePlayer(); } catch (e) {} }
  P = { it: { id: 0, title: "Test Film", year: 2024, kind: "movie", duration: 30, position: 0, next: null,
              playback: { profiles: ["720p"], hires: [], direct: true } },
        start: 0, mode: "direct", audio: 0, lastSave: 0, triedDirect: false };
  $("#pl-title").textContent = "Test Film (2024)";
  const q = $("#pl-quality");
  if (q) q.innerHTML = '<option value="direct" selected>Original</option><option value="720p">Transcode 720p</option>';
  const v = video;
  try { v.pause(); } catch (e) {}
  v.removeAttribute("src");
  try { v.load(); } catch (e) {}
  v.muted = true;
  v.src = url;
  const play = () => { v.play().catch(() => {}); };
  v.addEventListener("loadeddata", play, { once: true });
  play();
  $("#player").classList.remove("hidden");
  $("#player").classList.toggle("paused", !!v.paused);
  if (typeof BAR !== "undefined" && BAR.sync) BAR.sync();
  if (typeof OV !== "undefined") OV.show();
  if (window.TV && TV.afterRoute) TV.afterRoute();
}
window.__msOpenDummyPlayer = openDummyPlayer;

const TV = {
  on: false,
  _bound: false,
  detect() {
    try { if (localStorage.getItem("msTvMode") === "1") return true; } catch (e) {}
    // 2.0: the Android app answers isTv() from the system's UI mode, so a tablet with the app isn't mistaken for a TV
    try { if (window.MSAndroid && typeof MSAndroid.isTv === "function") return !!MSAndroid.isTv(); } catch (e) {}
    const ua = navigator.userAgent || "";
    if (/AndroidTV|Android TV|GoogleTV|Google TV|BRAVIA|AFT[A-Z0-9]|SHIELD Android TV|SmartTV|Smart-TV|HbbTV|CrKey|AppleTV|FireTV|TV Safari/i.test(ua)) return true;
    // Android WebView on a TV often includes "Mobile" in the UA, so don't require its absence.
    // The installed app identifies itself as MediaServerAndroid. A short phone side is under 500px.
    const app = /MediaServerAndroid|MoviniteAndroid/i.test(ua);
    const android = /Android/i.test(ua);
    const noHover = window.matchMedia && window.matchMedia("(hover: none)").matches;
    const wide = Math.max(window.innerWidth || 0, (screen && screen.width) || 0) >= 900;
    const shortSide = Math.min(window.innerWidth || 0, window.innerHeight || 0, (screen && Math.min(screen.width, screen.height)) || 9999);
    if ((app || (android && noHover)) && wide && shortSide >= 500) return true;
    return false;
  },
  prepare() {
    this.on = this.detect();
    document.documentElement.classList.toggle("tv-mode", this.on);
    this.fitLayout();
  },
  // Layout at 1920×1080 CSS pixels, then scale to the WebView's CSS viewport
  // (window.innerWidth / innerHeight — not physical pixels). On a 4K TV, Android
  // often reports 960×540 (DPR 4) or 1920×1080 (DPR 2).
  fitLayout() {
    const root = document.documentElement;
    const targetW = 1920, targetH = 1080;
    if (!this.on) {
      root.classList.remove("tv-scaled");
      root.style.removeProperty("--tv-scale");
      root.style.removeProperty("--tv-layout-w");
      root.style.removeProperty("--tv-layout-h");
      return;
    }
    const w = window.innerWidth || targetW;
    const h = window.innerHeight || targetH;
    const s = w / targetW;
    if (s > 0.98 && s < 1.02) {
      root.classList.remove("tv-scaled");
      root.style.removeProperty("--tv-scale");
      root.style.removeProperty("--tv-layout-w");
      root.style.removeProperty("--tv-layout-h");
      return;
    }
    root.classList.add("tv-scaled");
    root.style.setProperty("--tv-scale", String(s));
    root.style.setProperty("--tv-layout-w", targetW + "px");
    root.style.setProperty("--tv-layout-h", Math.max(targetH, Math.round(h / s)) + "px");
  },
  init() {
    this.prepare();
    if (!this.on || this._bound) return;
    this._bound = true;
    document.addEventListener("keydown", (e) => this.onKey(e), true);
    const onResize = () => { const was = this.on; this.prepare(); if (this.on && !was) this.afterRoute(); };
    window.addEventListener("resize", onResize);
    try { if (window.visualViewport) visualViewport.addEventListener("resize", onResize); } catch (e) {}
  },
  typing(e) {
    const t = e.target;
    if (!t || !t.tagName) return false;
    const tag = t.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT") return true;
    if (tag === "INPUT") {
      const ty = (t.type || "text").toLowerCase();
      return !/^(button|submit|reset|checkbox|radio|range|file|color|hidden)$/.test(ty);
    }
    return t.isContentEditable;
  },
  visible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    if (el.disabled || el.getAttribute("aria-disabled") === "true") return false;
    if (el.closest("[hidden]")) return false;
    let n = el;
    while (n && n !== document.documentElement) {
      if (n.classList && n.classList.contains("hidden")) return false;
      n = n.parentElement;
    }
    const st = window.getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden" || st.opacity === "0") return false;
    const r = el.getBoundingClientRect();
    return r.width >= 2 && r.height >= 2;
  },
  isSearchChrome(el) {
    if (!el) return false;
    if (el.id === "search" || el.id === "m-search" || el.id === "m-q") return true;
    return !!(el.closest && el.closest(".m-qw"));
  },
  isDetailView() {
    const h = (location.hash || "").replace(/^#\/?/, "");
    return /^(item|show|album)(\/|$)/.test(h);
  },
  detailPrimaryAction() {
    return $("#resume") || $("#play") || $("#playnext") || $("#playall") || $("#pl-play")
      || $("#view .main-actions .btn, #view .actions .btn, #view .pli-actions .btn");
  },
  rememberOrigin(el) {
    if (!el) return;
    const href = (el.dataset && el.dataset.href) || el.getAttribute("href") || "";
    const itemId = (el.dataset && (el.dataset.id || el.dataset.item)) || (href.match(/item\/(\d+)/) || [])[1] || "";
    this._origin = { fromHash: location.hash, href, itemId: String(itemId || "") };
  },
  originEl() {
    const o = this._origin;
    if (!o) return null;
    if (o.itemId) {
      const by = document.querySelector(`#view .card[data-href="#/item/${o.itemId}"], #view .card[data-id="${o.itemId}"]`);
      if (by && this.visible(by)) return by;
    }
    if (o.href) {
      const el = document.querySelector(`#view [data-href="${o.href}"]`);
      if (el && this.visible(el)) return el;
    }
    return null;
  },
  leaveDetail() { return this.back(); },
  detailZones(items) {
    const inView = items.filter((el) => el.closest && el.closest("#view"));
    const actions = inView.filter((el) => el.closest(".actions, .main-actions, .pli-actions") && !el.closest(".list, .cast-strip, .strip.sim"));
    const mid = inView.filter((el) =>
      (el.closest(".tabs") && el.tagName === "BUTTON")
      || (el.closest(".list") && (el.classList.contains("li") || el.matches(".li, [data-href], [data-track]")))
      || el.closest("#pl-tracks")
      || el.classList.contains("pli-row")
    ).filter((el) => !actions.includes(el));
    const cast = inView.filter((el) => el.closest(".cast-strip") && (el.classList.contains("person") || el.closest("a.person")));
    const similar = inView.filter((el) => el.closest(".strip.sim") && el.classList.contains("card"));
    const zones = [];
    if (actions.length) zones.push(actions);
    if (mid.length) zones.push(mid);
    if (cast.length) zones.push(cast);
    if (similar.length) zones.push(similar);
    return zones;
  },
  moveInDetail(dir, cur, items) {
    const zones = this.detailZones(items);
    const zi = zones.findIndex((z) => z.includes(cur));
    if (zi < 0) return false;
    if (dir === "left" || dir === "right") {
      const next = this.nearest(cur, zones[zi], dir);
      if (next) this.focus(next);
      return true;
    }
    const nextIn = this.nearest(cur, zones[zi], dir);
    if (nextIn) { this.focus(nextIn, dir === "up" ? { block: "center" } : undefined); return true; }
    if (dir === "down") {
      for (let i = zi + 1; i < zones.length; i++) {
        if (zones[i].length) { this.focus(zones[i][0]); return true; }
      }
      return true;
    }
    if (zi === 0) { this.leaveDetail(); return true; }
    const last = zones.length - 1;
    if (zi === last && zones[0] && zones[0].length) {
      this.focus(this.detailPrimaryAction() || zones[0][0], { block: "center" });
      return true;
    }
    for (let i = zi - 1; i >= 0; i--) {
      if (zones[i].length) {
        this.focus(i === 0 ? (this.detailPrimaryAction() || zones[i][0]) : zones[i][0], { block: "center" });
        return true;
      }
    }
    this.leaveDetail();
    return true;
  },
  headerItems(items) {
    items = items || this.candidates();
    return items.filter((el) => el.closest && el.closest(".top") && !el.closest("#acct-menu") && !el.closest("#ss-panel"));
  },
  acctMenuOpen() {
    const am = document.getElementById("acct-menu");
    return !!(am && !am.classList.contains("hidden"));
  },
  acctMenuItems(items) {
    items = items || this.candidates();
    return items.filter((el) => el.closest && el.closest("#acct-menu"));
  },
  isTopContentRow(cur, items) {
    if (!cur) return false;
    if (cur.closest && cur.closest(".side")) {
      const nav = items.filter((el) => el.closest && el.closest(".side nav"));
      return nav[0] === cur;
    }
    const viewItems = items.filter((el) => el.closest && el.closest("#view") && !this.isSearchChrome(el));
    if (!viewItems.includes(cur)) return false;
    const topMost = Math.min(...viewItems.map((el) => el.getBoundingClientRect().top));
    return cur.getBoundingClientRect().top <= topMost + 48;
  },
  candidates() {
    const playerOn = $("#player") && !$("#player").classList.contains("hidden");
    const modalOn = $("#modal") && !$("#modal").classList.contains("hidden");
    const authOn = $("#auth") && !$("#auth").classList.contains("hidden");
    let sel;
    if (authOn) sel = "#auth button, #auth input, #auth a, #auth [tabindex='0']";
    else if (modalOn) sel = "#modal button, #modal a, #modal input, #modal select, #modal [tabindex='0'], #modal [data-href]";
    else if (playerOn) {
      const z = this.playerControls();
      const seen = new Set(), out = [];
      for (const el of [...(z.skip || []), ...(z.upn || []), ...z.menu, ...z.top, ...z.mid, ...z.seek, ...z.row]) {
        if (el && !seen.has(el)) { seen.add(el); out.push(el); }
      }
      return out;
    }
    else sel = [
      ".side nav a", "#navlibs a",
      "#tabbar a",
      "#view .card", "#view .lib-li", "#view .person", "#view [data-href]", "#view .gchip", "#view .btn:not([disabled])",
      "#view .set-tabs button", "#view .libtabs a", "#view .tabs button", "#view .li[data-href]", "#view .list .li",
      "#view .see-all", "#view .rh-a",
      "#view .pli-row", "#view .iconbtn", "#view select",
      "#menubtn", "#sndbtn", "#ss-pill", "#m-avatar", "#m-search", "#search",
      "#logout",
      "#acct-menu:not(.hidden) a, #acct-menu:not(.hidden) button",
      "#acct-page-logout",
      "#audiobar:not(.hidden) button, #audiobar:not(.hidden) [tabindex='0']",
      "#pip-chip:not(.hidden) button"
    ].join(",");
    return [...document.querySelectorAll(sel)].filter((el) => this.visible(el));
  },
  overlap(a1, a2, b1, b2) { return Math.max(0, Math.min(a2, b2) - Math.max(a1, b1)); },
  nearest(cur, items, dir) {
    const a = cur.getBoundingClientRect();
    const acx = a.left + a.width / 2, acy = a.top + a.height / 2;
    let best = null, bestScore = Infinity;
    for (const el of items) {
      if (el === cur) continue;
      const b = el.getBoundingClientRect();
      const bcx = b.left + b.width / 2, bcy = b.top + b.height / 2;
      let primary, secondary, ov;
      if (dir === "right") {
        if (bcx <= acx + 4 && b.left <= a.left + 4) continue;
        primary = Math.max(0, b.left - a.right);
        if (b.left < a.right) primary = Math.max(8, bcx - acx);
        secondary = Math.abs(bcy - acy);
        ov = this.overlap(a.top, a.bottom, b.top, b.bottom);
      } else if (dir === "left") {
        if (bcx >= acx - 4 && b.right >= a.right - 4) continue;
        primary = Math.max(0, a.left - b.right);
        if (a.left < b.right) primary = Math.max(8, acx - bcx);
        secondary = Math.abs(bcy - acy);
        ov = this.overlap(a.top, a.bottom, b.top, b.bottom);
      } else if (dir === "down") {
        if (bcy <= acy + 4 && b.top <= a.top + 4) continue;
        primary = Math.max(0, b.top - a.bottom);
        if (b.top < a.bottom) primary = Math.max(8, bcy - acy);
        secondary = Math.abs(bcx - acx);
        ov = this.overlap(a.left, a.right, b.left, b.right);
      } else {
        if (bcy >= acy - 4 && b.bottom >= a.bottom - 4) continue;
        primary = Math.max(0, a.top - b.bottom);
        if (a.top < b.bottom) primary = Math.max(8, acy - bcy);
        secondary = Math.abs(bcx - acx);
        ov = this.overlap(a.left, a.right, b.left, b.right);
      }
      const axis = (dir === "left" || dir === "right") ? Math.min(a.height, b.height) : Math.min(a.width, b.width);
      const ovRatio = axis ? ov / axis : 0;
      const score = primary + (ovRatio > 0.25 ? secondary * 0.15 : secondary * 1.35) + (ovRatio > 0.25 ? 0 : 80);
      if (score < bestScore) { bestScore = score; best = el; }
    }
    return best;
  },
  focus(el, opts) {
    if (!el) return;
    try { el.focus({ preventScroll: true }); } catch (e) { try { el.focus(); } catch (e2) {} }
    if (this.on) {
      const prev = document.querySelectorAll(".tv-focused");
      for (let i = 0; i < prev.length; i++) { if (prev[i] !== el) prev[i].classList.remove("tv-focused"); }
      el.classList.add("tv-focused");
    }
    const block = (opts && opts.block) || "nearest";
    // 2.1.2: opening a title pins the details page at the top so Resume/Play stay on screen
    if (block === "start") {
      const v = document.getElementById("view");
      if (v) v.scrollTop = 0;
    } else if (this.on && el.closest && (el.closest("#tv-rail") || el.closest("#tv-tabs") || el.closest("#tv-menu") || el.closest("#tv-top"))) {
      // Fixed TV chrome: never scroll the page to a rail icon or tab.
    } else {
      const r = el.getBoundingClientRect();
      const pad = 80;
      if (block === "center" || r.top < pad || r.bottom > window.innerHeight - pad || r.left < 20 || r.right > window.innerWidth - 20) {
        const target = (block === "center" && el.closest && (el.closest(".actions") || el.closest(".detail"))) || el;
        // 2.1.4: instant scroll on a TV so remote moves are not stacked behind smooth-scroll animations.
        const behavior = this.on ? "auto" : "smooth";
        target.scrollIntoView({ block: block === "center" ? "center" : "nearest", inline: "nearest", behavior: behavior });
      }
    }
    const strip = el.closest(".strip, .hs, .cast-strip");
    if (strip && typeof strip.scrollLeft === "number") {
      const sr = strip.getBoundingClientRect(), er = el.getBoundingClientRect();
      let leftPad = 16;
      const rail = document.getElementById("tv-rail");
      if (document.documentElement.classList.contains("tv-plex") && rail) {
        const art = el.querySelector && el.querySelector(".art");
        const box = art ? art.getBoundingClientRect() : er;
        const minLeft = rail.getBoundingClientRect().right + 8;
        if (box.left < minLeft) strip.scrollLeft += box.left - minLeft;
        else if (box.right > sr.right - 16) strip.scrollLeft += box.right - sr.right + 16;
      } else {
        if (er.left < sr.left + leftPad) strip.scrollLeft += er.left - sr.left - leftPad;
        else if (er.right > sr.right - 16) strip.scrollLeft += er.right - sr.right + 16;
      }
    }
  },
  playerOn() {
    const pl = $("#player");
    return !!(pl && !pl.classList.contains("hidden"));
  },
  // While the overlay is fading in, opacity is still 0 for a frame; treat ov-on as visible.
  playerVisibleChrome(el) {
    if (!el || !el.getBoundingClientRect) return false;
    if (el.disabled || el.getAttribute("aria-disabled") === "true") return false;
    if (el.closest && el.closest("[hidden]")) return false;
    let n = el;
    while (n && n !== document.documentElement) {
      if (n.classList && n.classList.contains("hidden")) return false;
      n = n.parentElement;
    }
    const st = window.getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden") return false;
    const pl = $("#player");
    const on = pl && pl.classList.contains("ov-on") && pl.contains(el);
    if (!on && st.opacity === "0") return false;
    const r = el.getBoundingClientRect();
    return r.width >= 2 && r.height >= 2;
  },
  playerControls() {
    const vis = (el) => this.playerVisibleChrome(el);
    const pop = $("#pl-pop");
    const menu = (pop && !pop.classList.contains("hidden")) ? [...pop.querySelectorAll("button")].filter(vis) : [];
    const top = [$("#pl-close")].filter(vis);
    const mid = [...document.querySelectorAll("#player .pl-big")].filter(vis);
    const seek = [$("#pl-seek")].filter(vis);
    const row = [...document.querySelectorAll("#pl-bar .pl-row .pl-cb")].filter(el => vis(el) && !el.classList.contains("hidden"));
    const vol = $("#pl-vol");
    if (vol && vis(vol) && window.getComputedStyle(vol).display !== "none") {
      const i = row.findIndex(el => el.id === "pl-mute");
      if (i >= 0) row.splice(i + 1, 0, vol); else row.push(vol);
    }
    const skipVis = (el) => el && !el.classList.contains("hidden") && this.visible(el);
    const skip = [$("#pl-skip-intro"), $("#pl-skip-credits")].filter(skipVis);
    const upn = [$("#pl-upnext-play"), $("#pl-upnext-cancel")].filter(skipVis);
    return { menu, top, mid, seek, row, skip, upn };
  },
  moveInPlayer(dir) {
    const z = this.playerControls();
    if (z.menu.length) {
      const items = z.menu;
      const cur = document.activeElement;
      const i = items.indexOf(cur);
      if (dir === "up" || dir === "down") {
        const n = items[(Math.max(i, 0) + (dir === "down" ? 1 : -1) + items.length) % items.length];
        if (n) this.focus(n);
        return true;
      }
      // Left / Right stay in the menu: walk speed chips sideways, otherwise stay put
      if (cur && cur.closest && cur.closest(".sp")) {
        const chips = [...cur.parentElement.querySelectorAll("button")].filter(el => items.includes(el));
        const j = chips.indexOf(cur) + (dir === "right" ? 1 : -1);
        if (j >= 0 && j < chips.length) this.focus(chips[j]);
      }
      return true;
    }
    const zones = [z.upn || [], z.skip || [], z.top, z.mid, z.seek, z.row].filter(a => a.length);
    const all = zones.flat();
    const cur = document.activeElement && all.includes(document.activeElement) ? document.activeElement : null;
    if (!cur) { this.focus(this.preferredStart(this.candidates()) || all[0]); return true; }
    const zi = zones.findIndex(a => a.includes(cur));
    if (dir === "left" || dir === "right") {
      if (z.seek.includes(cur)) {
        if (typeof skip === "function") skip(dir === "right" ? 10 : -10, dir);
        if (typeof OV !== "undefined") OV.show();
        this.focus(cur);
        return true;
      }
      const list = zones[zi] || [];
      const j = list.indexOf(cur) + (dir === "right" ? 1 : -1);
      if (j >= 0 && j < list.length) this.focus(list[j]);
      return true;   // do not fall through to the document skip handler
    }
    const nj = zi + (dir === "down" ? 1 : -1);
    if (nj < 0 || nj >= zones.length) return true;
    const next = zones[nj];
    const acx = cur.getBoundingClientRect().left + cur.getBoundingClientRect().width / 2;
    let best = next[0], bestD = Infinity;
    for (const el of next) {
      const b = el.getBoundingClientRect();
      const d = Math.abs((b.left + b.width / 2) - acx);
      if (d < bestD) { bestD = d; best = el; }
    }
    if (best) this.focus(best);
    return true;
  },
  preferredStart(items) {
    if (!items.length) return null;
    const cur = document.activeElement;
    if (cur && items.includes(cur) && this.isDetailView() && this.detailPrimaryAction()) {
      // After opening a title, never keep a Similar-movies card as the start focus.
    } else if (cur && items.includes(cur) && !this.isSearchChrome(cur)) {
      return cur;
    }
    const playerOn = $("#player") && !$("#player").classList.contains("hidden");
    if (playerOn) {
      const skip = items.find(el => el && (el.id === "pl-skip-intro" || el.id === "pl-skip-credits"));
      if (skip) return skip;
      const un = items.find(el => el && el.id === "pl-upnext-play");
      if (un) return un;
      return $("#pl-bplay") || $("#pl-pp") || items[0];
    }
    if (this.isDetailView()) {
      const act = this.detailPrimaryAction();
      if (act && items.includes(act)) return act;
    }
    const origin = this.originEl();
    if (origin && items.includes(origin)) return origin;
    const home = items.find((el) => el.matches && el.matches("#view .card, #view .lib-li"));
    if (home) return home;
    const lib = items.find((el) => el.matches && el.matches(".side nav a[data-nav^='lib'], #navlibs a"));
    const firstNav = items.find((el) => el.matches && el.matches(".side nav a, #tabbar a"));
    return home || lib || firstNav || items[0];
  },
  move(dir) {
    const items = this.candidates();
    if (!items.length) return false;
    const cur = document.activeElement && items.includes(document.activeElement) ? document.activeElement : null;
    if (!cur) { this.focus(this.preferredStart(items)); return true; }
    // 2.0.2: the account menu is its own zone (Up/Down through items; Back closes it)
    if (this.acctMenuOpen() && (cur.closest && (cur.closest("#acct-menu") || cur.id === "m-avatar"))) {
      const menu = this.acctMenuItems(items);
      if (cur.id === "m-avatar" && (dir === "down" || dir === "up") && menu.length) {
        this.focus(dir === "up" ? menu[menu.length - 1] : menu[0]);
        return true;
      }
      const next = this.nearest(cur, menu, dir);
      if (next) this.focus(next);
      return true;
    }
    // 2.0.2: Left/Right walk the header (search, sounds, status, account); Down leaves it
    if (cur.closest && cur.closest(".top") && !cur.closest("#view")) {
      const heads = this.headerItems(items);
      if (dir === "left" || dir === "right") {
        const next = this.nearest(cur, heads, dir);
        if (next) this.focus(next);
        return true;
      }
      if (dir === "down") {
        const content = items.filter((el) => !(el.closest && el.closest(".top")) && !this.isSearchChrome(el));
        const start = this.preferredStart(content) || content[0];
        if (start) this.focus(start);
        return true;
      }
      return true;
    }
    const atTop = !!(cur.closest && (cur.closest(".side") || cur.closest(".top")) || this.isSearchChrome(cur));
    let pool = items;
    if ((dir === "up" || dir === "down") && !atTop) {
      pool = items.filter((el) => !this.isSearchChrome(el));
    }
    // 2.0.2: Up from the first content row or Home in the sidebar reaches the header
    if (dir === "up" && this.isTopContentRow(cur, items)) {
      const heads = this.headerItems(items);
      const next = this.nearest(cur, heads, "up") || heads[heads.length - 1] || document.getElementById("m-avatar") || document.getElementById("search");
      if (next && this.visible(next)) { this.focus(next); return true; }
    }
    if (this.isDetailView() && cur.closest && cur.closest("#view")) {
      if (this.moveInDetail(dir, cur, pool)) return true;
    }
    const stripSel = ".strip, .hs, .cast-strip, .grid";
    // Stay inside a horizontal movie/library row first, so the remote cannot skip the posters
    const strip = cur.closest && cur.closest(stripSel);
    if (strip && (dir === "left" || dir === "right")) {
      const inStrip = pool.filter((el) => strip.contains(el));
      const next = this.nearest(cur, inStrip, dir);
      if (next) { this.focus(next); return true; }
    }
    // Right from the sidebar (Home / library list) should enter the first poster or library tile, not jump over it.
    if (dir === "right" && cur.closest && cur.closest(".side")) {
      const content = pool.filter((el) => el.closest("#view"));
      const preferred = content.filter((el) => el.matches && el.matches(".card, .lib-li, .person, .li[data-href], .btn"));
      const next = this.nearest(cur, preferred.length ? preferred : content, dir) || preferred[0];
      if (next) { this.focus(next); return true; }
    }
    if (dir === "down" && cur.closest && (cur.closest(".row-head") || cur.classList.contains("rh-a") || cur.classList.contains("see-all"))) {
      let row = cur.closest(".hrow") || cur.closest(".row-head");
      let st = row && (row.querySelector(stripSel) || (row.nextElementSibling && row.nextElementSibling.matches(stripSel) ? row.nextElementSibling : null) || (row.nextElementSibling && row.nextElementSibling.querySelector && row.nextElementSibling.querySelector(stripSel)));
      if (!st && row && row.parentElement) {
        const kids = [...row.parentElement.children];
        const i = kids.indexOf(row);
        st = kids.slice(i + 1).map((n) => (n.matches && n.matches(stripSel) ? n : n.querySelector && n.querySelector(stripSel))).find(Boolean);
      }
      if (st) {
        const cards = pool.filter((el) => st.contains(el));
        if (cards.length) { this.focus(cards[0]); return true; }
      }
    }
    const next = this.nearest(cur, pool, dir);
    if (next) { this.focus(next); return true; }
    return true;
  },
  activate(el) {
    if (!el) return false;
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT") { el.focus(); return true; }
    const href = (el.dataset && el.dataset.href) || el.getAttribute("href") || "";
    if (/#\/(item|show|album)\//.test(href)) this.rememberOrigin(el);
    if (el.classList && el.classList.contains("card") && el.dataset.href) { el.click(); return true; }
    el.click();
    return true;
  },
  back() {
    if (!this.on) return false;
    const d = document;
    const player = d.getElementById("player");
    if (player && !player.classList.contains("hidden")) {
      if (typeof BAR !== "undefined" && BAR.popOpen && BAR.popOpen()) {
        BAR.closePop();
        return true;
      }
      if (player.classList.contains("ov-on") && typeof OV !== "undefined" && OV.hide) { OV.hide(); return true; }
      const c = d.getElementById("pl-close"); if (c) c.click(); else if (typeof closePlayer === "function") closePlayer();
      return true;
    }
    if (typeof BAR !== "undefined" && BAR.popOpen && BAR.popOpen()) { BAR.closePop(); return true; }
    if (typeof abVolPop !== "undefined" && abVolPop) { if (typeof abSetVolPop === "function") abSetVolPop(false); return true; }
    const m = d.getElementById("modal");
    if (m && !m.classList.contains("hidden") && !m.dataset.locked) { m.dispatchEvent(new MouseEvent("mousedown", { bubbles: true })); return true; }
    const sd = d.querySelector(".side.open"); if (sd) { sd.classList.remove("open"); return true; }
    const mm = d.getElementById("more-menu"); if (mm && !mm.hidden) { mm.hidden = true; return true; }
    const am = d.getElementById("acct-menu");
    if (am && !am.classList.contains("hidden")) {
      const av = d.getElementById("m-avatar");
      if (av) av.click(); else am.classList.add("hidden");
      if (av) this.focus(av);
      return true;
    }
    if (typeof MLS !== "undefined" && MLS.el) { if (typeof mlClose === "function") mlClose(); return true; }
    const h = location.hash.replace(/^#\/?/, "");
    if (h && h !== "home" && h !== "") {
      if (h.startsWith("item/") || h.startsWith("show/") || h.startsWith("album/") || h.startsWith("person/")) {
        history.length > 1 ? history.back() : (location.hash = "#/home");
      } else if (h.startsWith("library/")) {
        location.hash = "#/home";
      } else if (h.startsWith("settings/") && h !== "settings") {
        location.hash = "#/settings";
      } else {
        location.hash = "#/home";
      }
      return true;
    }
    return false;
  },
  onKey(e) {
    if (!this.on || e.altKey || e.ctrlKey || e.metaKey) return;
    const playerOn = $("#player") && !$("#player").classList.contains("hidden");
    const key = e.key;
    const center = key === "Enter" || key === "Go" || key === "Select" || e.keyCode === 23;
    if (key === "Escape" || key === "BrowserBack" || key === "GoBack" || key === "Backspace" || e.keyCode === 4 || e.keyCode === 166) {
      if (this.typing(e) && (key === "Escape" || key === "Backspace")) return;
      if (this.back()) { e.preventDefault(); e.stopPropagation(); }
      return;
    }
    const arrow = key === "ArrowRight" || key === "ArrowLeft" || key === "ArrowUp" || key === "ArrowDown";
    // 2.0.2: arrow keys leave the search box so the remote can walk the header (typing letters still works)
    if (this.typing(e) && !center && !(arrow && this.isSearchChrome(e.target))) return;
    if (arrow) {
      const dir = key === "ArrowRight" ? "right" : key === "ArrowLeft" ? "left" : key === "ArrowDown" ? "down" : "up";
      if (playerOn) {
        const wasOn = $("#player").classList.contains("ov-on");
        if (typeof OV !== "undefined") OV.show();
        e.preventDefault(); e.stopPropagation();
        if (!wasOn) {
          if (dir === "left" && typeof skip === "function") skip(-10, "left");
          else if (dir === "right" && typeof skip === "function") skip(10, "right");
          this.focus(this.preferredStart(this.candidates()));
          return;
        }
        this.moveInPlayer(dir);
        return;
      }
      if (this.move(dir)) { e.preventDefault(); e.stopPropagation(); }
      return;
    }
    if (center) {
      if (this.typing(e)) return;
      if (playerOn) {
        const wasOn = $("#player").classList.contains("ov-on");
        const el0 = document.activeElement;
        const skipId = el0 && (el0.id === "pl-skip-intro" || el0.id === "pl-skip-credits" || el0.id === "pl-upnext-play" || el0.id === "pl-upnext-cancel");
        if (typeof OV !== "undefined" && !skipId) OV.show();
        e.preventDefault(); e.stopPropagation();
        if (skipId) { this.activate(el0); return; }
        if (!wasOn) {
          if (typeof togglePlay === "function") togglePlay();
          this.focus(this.preferredStart(this.candidates()));
          return;
        }
        const el = document.activeElement;
        const items = this.candidates();
        if (el && items.includes(el)) this.activate(el);
        else this.focus(this.preferredStart(items));
        return;
      }
      const el = document.activeElement;
      const items = this.candidates();
      if (el && items.includes(el)) {
        e.preventDefault(); e.stopPropagation();
        this.activate(el);
      } else if (items.length) {
        e.preventDefault(); e.stopPropagation();
        this.focus(this.preferredStart(items));
      }
    }
  },
  ensureFocusable() {
    $$("#view .card, #view .lib-li, #view .person, #view .li[data-href], #view .list .li, #view .tabs button, #navlibs a, #view .rh-a, #view .see-all, #view .actions .btn, #view .main-actions .btn").forEach((el) => {
      if (!el.hasAttribute("tabindex") && el.tagName !== "BUTTON" && el.tagName !== "SELECT" && el.tagName !== "INPUT" && el.tagName !== "A") el.tabIndex = 0;
      else if (!el.hasAttribute("tabindex") && (el.tagName === "A" || el.classList.contains("li") || el.classList.contains("card"))) el.tabIndex = 0;
    });
  },
  afterRoute() {
    if (!this.on) return;
    this.ensureFocusable();
    const typ = document.activeElement && this.typing({ target: document.activeElement });
    if (typ && !this.isSearchChrome(document.activeElement)) return;
    const items = this.candidates();
    if (!items.length) return;
    const playerOn = $("#player") && !$("#player").classList.contains("hidden");
    if (playerOn) { this.focus(this.preferredStart(items)); return; }
    if (this.isDetailView()) {
      const act = this.detailPrimaryAction();
      if (act && items.includes(act)) {
        this.focus(act, { block: "start" });
        return;
      }
    }
    const origin = this.originEl();
    if (origin) {
      this.focus(origin);
      this._origin = null;
      return;
    }
    if (document.activeElement && items.includes(document.activeElement) && this.visible(document.activeElement)
        && !this.isSearchChrome(document.activeElement)) {
      this.focus(document.activeElement);
      return;
    }
    this.focus(this.preferredStart(items));
  }
};
window.TV = TV;
window.__msTvBack = () => TV.back();
window.cardItem = cardItem;
window.cardShow = cardShow;
window.cardAlbum = cardAlbum;
window.api = api;
TV.prepare();

boot();
})();
