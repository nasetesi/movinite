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
const lazyIO = ("IntersectionObserver" in window) ? new IntersectionObserver((ents) => ents.forEach(e => {
  if (e.isIntersecting) { e.target.style.backgroundImage = `url('${e.target.dataset.bg}')`; lazyIO.unobserve(e.target); }
}), { rootMargin: "800px 200px" }) : null;
new MutationObserver(() => $$("[data-bg]:not([data-lz])").forEach(el => {
  el.dataset.lz = "1";
  if (lazyIO) lazyIO.observe(el); else el.style.backgroundImage = `url('${el.dataset.bg}')`;
})).observe(document.body, { childList: true, subtree: true });
const KIND_ICON = { movies: "&#127916;", tv: "&#128250;", music: "&#127925;", other: "&#128193;" };

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
}
function showLogin() {
  stopAll();
  showAuth(`<form class="auth-box" id="loginf"><h1 class="auth-brand"><img class="auth-logo" src="/static/logo-full.png" alt="Movinite" width="300" height="155"></h1><div class="muted">Sign in to continue</div>
    <label>Username</label><input type="text" id="lu" autocomplete="username" autofocus>
    <label>Password</label><input type="password" id="lp" autocomplete="current-password">
    <button class="btn" type="submit">Sign in</button><div class="err" id="lerr"></div></form>`);
  $("#loginf").onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/login", { method: "POST", body: { username: $("#lu").value, password: $("#lp").value }, noAuthRedirect: true }); boot(); }
    catch (err) { $("#lerr").textContent = err.message; }
  };
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
function fmtGB(b, dp) { const g = GB(b || 0); return g >= 100 ? g.toFixed(0) : g.toFixed(dp == null ? 1 : dp); }
function fmtUptime(s) { const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60); return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`; }
function cpuPct(d) { return d.cpu == null ? "n/a" : Math.round(d.cpu) + "%"; }
function sysLevel(p, warn, bad) { return p >= bad ? "bad" : p >= warn ? "warn" : "ok"; }
function sysSpark(vals, w, h) {
  if (!vals.length) return "";
  const n = vals.length, step = n > 1 ? w / (n - 1) : w;
  const pts = vals.map((v, i) => `${(i * step).toFixed(1)},${(h - 1 - (Math.max(0, Math.min(100, v)) / 100) * (h - 2)).toFixed(1)}`).join(" ");
  return `<svg class="ss-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
}
function sysBar(p, lvl) { return `<span class="ss-bar ${lvl}"><i style="width:${Math.max(2, Math.min(100, p)).toFixed(0)}%"></i></span>`; }
function renderSysstat() {
  const d = SYS.d, box = $("#sysstat");
  if (!d) return;
  box.classList.remove("hidden");
  const memPct = d.mem.total ? 100 * d.mem.used / d.mem.total : 0;
  const cl = sysLevel(d.cpu, 60, 85), ml = sysLevel(memPct, 75, 90);
  const worst = [cl, ml].includes("bad") ? "bad" : [cl, ml].includes("warn") ? "warn" : "ok";
  const cpuHist = (d.history || []).map(x => x[1]);
  const hw = d.hw || {}, gpu = hw.streams > 0;
  $("#ss-pill").className = "ss-pill " + worst + (gpu ? " gpu" : "");
  $("#ss-pill").innerHTML = `<span class="ss-dot ${worst}"></span>${gpu ? `<span class="hw-badge ss-gpu" title="${hw.streams} stream${hw.streams > 1 ? "s" : ""} on the video card (${esc(hw.label || "")})">GPU</span>` : ""}
    <span class="ss-full"><span class="ss-k">CPU</span> <b class="${cl}">${cpuPct(d)}</b>${sysSpark(cpuHist, 44, 16).replace("ss-spark", "ss-spark " + cl)}
    <span class="ss-sep">&middot;</span><span class="ss-k">RAM</span> <b class="${ml}">${fmtGB(d.mem.used)}/${fmtGB(d.mem.total, 0)} GB</b>${sysBar(memPct, ml)}</span>`;
  $("#ss-pill").title = `Server status -- CPU ${cpuPct(d)}, RAM ${fmtGB(d.mem.used)} of ${fmtGB(d.mem.total)} GB${gpu ? ` -- ${hw.streams} on the GPU (${hw.label})` : ""}`;
  if (SYS.open) renderSysPanel();
  renderPlayerStat();
}
// 1.4.11: the same numbers, see-through, over the video (no extra requests: reuses the top-bar poll above)
function renderPlayerStat() {
  const el = document.getElementById("pl-ss"); if (!el) return;
  const d = SYS.d;
  if (!d || !ME || !ME.show_status || !P) { el.classList.add("hidden"); return; }
  const memPct = d.mem.total ? 100 * d.mem.used / d.mem.total : 0;
  el.innerHTML = `<span class="k">CPU</span> <b class="${sysLevel(d.cpu, 60, 85)}">${cpuPct(d)}</b><span class="sep">&middot;</span><span class="k">RAM</span> <b class="${sysLevel(memPct, 75, 90)}">${fmtGB(d.mem.used)}/${fmtGB(d.mem.total, 0)} GB</b>${d.hw && d.hw.streams ? `<span class="sep">&middot;</span><span class="hw-badge">GPU</span>` : ""}`;
  el.title = `Server CPU ${cpuPct(d)}, RAM ${fmtGB(d.mem.used)} of ${fmtGB(d.mem.total)} GB`;
  el.classList.remove("hidden");
}
function renderSysPanel() {
  const d = SYS.d; if (!d) return;
  const memPct = d.mem.total ? 100 * d.mem.used / d.mem.total : 0;
  const swPct = d.swap.total ? 100 * d.swap.used / d.swap.total : 0;
  const cl = sysLevel(d.cpu, 60, 85), ml = sysLevel(memPct, 75, 90);
  const row = (k, v, bar) => `<div class="ss-row"><span>${k}</span><b>${v}</b>${bar || ""}</div>`;
  const cores = (d.cores || []).map((c, i) => `<i class="${sysLevel(c, 60, 85)}" style="height:${Math.max(6, c).toFixed(0)}%" title="Core ${i}: ${Math.round(c)}%"></i>`).join("");
  const disks = (d.disks || []).map(x => { const p = 100 * x.used / x.total; return row(esc(x.name), `${fmtGB(x.free)} GB free of ${fmtGB(x.total, 0)}`, sysBar(p, sysLevel(p, 85, 95))); }).join("");
  $("#ss-panel").innerHTML = `<div class="ss-h"><b>Server status</b><span class="muted">up ${fmtUptime(d.uptime_s)}</span></div>
    ${row("CPU", `${cpuPct(d)} of ${d.ncpu} cores`, sysBar(d.cpu, cl))}
    <div class="ss-big">${sysSpark((d.history || []).map(x => x[1]), 268, 34).replace("ss-spark", "ss-spark " + cl)}</div>
    ${cores ? `<div class="ss-cores" title="Per core">${cores}</div>` : ""}
    ${row("Load average", d.load.map(x => x.toFixed(2)).join(" &nbsp;"))}
    ${row("Memory", `${fmtGB(d.mem.used)} / ${fmtGB(d.mem.total)} GB (${Math.round(memPct)}%)`, sysBar(memPct, ml))}
    ${row("Swap", d.swap.total ? `${fmtGB(d.swap.used)} / ${fmtGB(d.swap.total)} GB` : "none", d.swap.total ? sysBar(swPct, sysLevel(swPct, 50, 80)) : "")}
    <div class="ss-sub">Disks</div>${disks || `<div class="muted">-</div>`}
    <div class="ss-sub">Media server</div>
    ${row("Active streams", `${d.streams}${d.ffmpeg.count ? ` &middot; ${d.ffmpeg.count} ffmpeg (${fmtSize(d.ffmpeg.rss)})` : " &middot; no ffmpeg running"}`)}
    ${d.hw ? row("Transcoding", d.hw.streams ? `<span class="hw-badge">GPU</span> ${esc(d.hw.label)} &middot; ${d.hw.streams} stream${d.hw.streams > 1 ? "s" : ""}` : d.hw.method ? `${esc(d.hw.label)} ready${d.hw.name ? ` <span class="muted">(${esc(d.hw.name)})</span>` : ""}` : "CPU") : ""}
    ${row("App memory", fmtSize(d.app_rss))}
    <div class="ss-foot muted">Refreshes every 4 s${ME && ME.is_admin ? ` &middot; <a href="#/settings/system">Who can see this</a>` : ""}</div>`;
}
function setSysOpen(on, pinned) {
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

async function boot() {
  try {
    const st = await api("/api/setup-status", { noAuthRedirect: true });
    if (st.needs_setup) { showSetup(); return; }
    ME = await api("/api/me", { noAuthRedirect: true });
  } catch (e) { showLogin(); return; }
  $("#auth").classList.add("hidden"); $("#shell").classList.remove("hidden");
  $("#whoami").textContent = ME.username; $("#ver").textContent = "v" + ME.version;
  MOB.setup();
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

async function refreshLibs() {
  LIBS = await api("/api/libraries");
  $("#navlibs").innerHTML = LIBS.length ? LIBS.map(l => `<a href="#/library/${l.id}" data-nav="lib${l.id}">${KIND_ICON[l.kind] || ""} ${esc(l.name)}</a>`).join("")
    : `<div class="muted" style="padding:4px 10px;font-size:13px">No libraries yet</div>`;
}

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
    if (p === "settings") return "settings";
    return "";
  }
  function tab() { const t = tabFor(); $$("#tabbar a").forEach(a => { const on = a.dataset.tab === t; a.classList.toggle("on", on); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); }); }
  function sound() { const on = SFX.get().on; $("#acct-sound").textContent = "Interface sounds: " + (on ? "on" : "off"); }
  function open(v) {
    menu.classList.toggle("hidden", !v); av.setAttribute("aria-expanded", v ? "true" : "false");
    if (v) { sound(); const f = menu.querySelector("a,button"); if (f) f.focus({ preventScroll: true }); }
  }
  function setup() {
    const ini = (ME.username || "?").trim().charAt(0).toUpperCase() || "?";
    av.textContent = ini; $("#acct-ini").textContent = ini;
    $("#acct-name").textContent = ME.username; $("#acct-role").textContent = ME.is_admin ? "Administrator" : "User";
    $("#acct-ver").textContent = "Movinite v" + ME.version;
    $("#acct-settings").hidden = !ME.is_admin;
    $("#tab-set-l").textContent = ME.is_admin ? "Settings" : "Account";
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

async function route() {
  if (!ME) return;
  const h = location.hash.replace(/^#\/?/, "");
  const parts = h.split("/").map(decodeURIComponent);
  const v = $("#view");
  v.dataset.view = parts[0] || "home";   // 1.4.9: lets CSS style the settings pages for phones
  clearInterval(route._poll); route._live = null; route._token = (route._token || 0) + 1;
  try {
    switch (parts[0]) {
      case "library": setActive("lib" + parts[1]);
        if (parts[2] === "collections") await viewCollections(+parts[1]);
        else if (parts[2] === "smart") await viewSmart(+parts[1], parts[3]);
        else if (parts[2] === "collection") await viewLibrary(+parts[1], "", +parts[3]);
        else await viewLibrary(+parts[1], parts[2] || ""); break;
      case "item": setActive(""); await viewItem(+parts[1]); break;
      case "person": setActive(""); await viewPerson(+parts[1], +parts[2] || 0); break;
      case "show": setActive("lib" + parts[1]); await viewShow(+parts[1], parts[2]); break;
      case "album": setActive("lib" + parts[1]); await viewAlbum(+parts[1], parts[2], parts[3]); break;
      case "search": setActive(""); await viewSearch(parts.slice(1).join("/")); break;
      case "libraries": setActive(""); await viewLibraries(); break;
      case "mylist": setActive(""); await viewMyList(); break;
      case "settings": setActive("settings"); await viewSettings(parts[1] || "libraries"); break;
      default: setActive("home"); await viewHome();
    }
  } catch (e) {
    if (e.message !== "Not signed in") v.innerHTML = `<div class="empty">Error: ${esc(e.message)}</div>`;
  }
  v.scrollTop = route._keepScroll ? v.scrollTop : 0; route._keepScroll = false;
}

// ---------------------------------------------------------------- cards
function cardItem(i, opts) {
  opts = opts || {};
  const land = opts.landscape || i.kind === "episode" || i.kind === "video" || (!i.poster && i.media_type === "video" && i.kind !== "movie");
  const img = land ? (i.thumb || i.poster) : (i.poster || i.thumb);
  const pct = i.position && i.duration ? Math.min(100, 100 * i.position / i.duration) : 0;
  let t = i.title, s = (i.year || "") + (i.edition ? ` <span class="ed" title="${esc(i.edition)}">${esc(i.edition)}</span>` : "");
  if (i.kind === "episode") { t = opts.showName === false ? i.title : (i.show || i.title); s = epCode(i) + (opts.showName === false ? "" : " · " + esc(i.title)); }
  if (i.media_type === "audio") { s = i.artist || ""; }
  const cls = land ? "landscape" : (i.media_type === "audio" ? "square" : "");
  if (opts.resume && i.duration && i.position) { const left = Math.max(1, Math.round((i.duration - i.position) / 60)); s = `<span class="d-only">${(i.kind === "episode" ? epCode(i) + " · " : "") + left} min left</span><span class="m-only">${i.kind === "episode" ? epCode(i) : (i.year || left + " min left")}</span>`; }
  // 1.4.3: a poster always opens the details page; the small round button plays (resumes where you stopped)
  const resumeAt = i.position > 30 && !i.watched ? i.position : 0;
  const quick = i.media_type === "audio" ? `<div class="playov" data-play="${i.id}">&#9654;</div>`
    : `<button class="qplay" type="button" data-play="${i.id}" title="${resumeAt ? "Resume from " + fmtDur(resumeAt) : "Play"}" aria-label="${resumeAt ? "Resume" : "Play"} ${esc(t)}">&#9654;</button>`;
  // 1.4.7: info that fades in over the poster on hover / keyboard focus
  const hov = i.media_type === "audio" ? "" : `<div class="hov" aria-hidden="true"><b>${esc(t)}</b><span>${[i.year, i.rating ? "&#9733; " + (+i.rating).toFixed(1) : "", i.duration ? fmtLen(i.duration) : ""].filter(Boolean).join(" · ")}</span></div>`;
  return `<div class="card ${cls}${opts.resume ? " resume" : ""}" tabindex="0" data-href="#/item/${i.id}"${opts.resume ? ` title="${esc(t)} -- resume from ${fmtDur(i.position || 0)}"` : ""} data-id="${i.id}">
    <div class="art"${img ? ` data-bg="${thumbUrl(img)}"` : ""}>
      ${img ? "" : `<div class="ph">${i.media_type === "audio" ? "&#9835;" : "&#127902;"}</div>`}
      ${i.watched ? `<span class="badge">&#10003;</span>` : ""}
      ${i.needs_review ? `<span class="badge rv" title="Match needs review">?</span>` : ""}
      ${hov}
      ${pct ? `<div class="bar" style="width:${pct}%"></div>` : ""}
      ${quick}
    </div><div class="t" title="${esc(t)}">${esc(t)}</div><div class="s">${s}</div>${opts.reason && i.reason ? `<div class="why" title="${esc(i.reason)}">${esc(i.reason)}</div>` : ""}</div>`;
}
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
    b.title = S.on ? "Interface sounds on (click to mute)" : "Interface sounds off (click to turn on)";
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
    if (M.kind === "music") h += sec("View", `<div class="mls-chips">${chip("view", "", "Albums", st.view === "")}${chip("view", "tracks", "Tracks", st.view === "tracks")}</div>`);
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
  const nMovieLibs = d.libraries.filter(L => L.library.kind === "movies").length;
  for (const L of d.libraries) {
    const lib = L.library;
    if (L.smart_rows) {   // 1.4.1: Recommended, Recently released, Recently added, Top movies
      for (const R of L.smart_rows) {
        if (!R.items.length && R.key !== "added") continue;
        html += rowHead(esc(R.title), `#/library/${lib.id}/smart/${R.key}`, { sub: esc(lib.name), extra: nMovieLibs > 1 ? ` <span class="muted d-only" style="font-size:14px;font-weight:400">in ${esc(lib.name)}</span>` : "" });
        if (R.key === "recommended" && R.note) html += `<div class="help row-note">${esc(R.note)}</div>`;
        html += R.items.length ? `<div class="strip hs">${R.items.map(i => cardItem(i, { reason: R.key === "recommended" })).join("")}</div>` : `<div class="empty">Nothing here yet -- scanning may still be running.</div>`;
      }
    } else html += rowHead(`Recently added in ${esc(lib.name)}`, `#/library/${lib.id}`, { sub: nf(lib.item_count || 0) + " items" });
    if (L.smart_rows) { /* rows above */ }
    else if (L.albums) html += L.albums.length ? `<div class="strip hs">${L.albums.map(a => cardAlbum(lib.id, a)).join("")}</div>` : `<div class="empty">Nothing here yet</div>`;
    else if (lib.kind === "tv") html += L.items.length ? `<div class="strip hs wide">${L.items.map(i => cardItem(i, { landscape: true })).join("")}</div>` : `<div class="empty">Nothing here yet</div>`;
    else html += L.items.length ? `<div class="strip hs">${L.items.map(i => cardItem(i)).join("")}</div>` : `<div class="empty">Nothing here yet -- scanning may still be running.</div>`;
    for (const G of (L.genre_rows || [])) {   // 1.4: the library's biggest genres
      if (!G.items.length) continue;
      html += rowHead(esc(G.genre), `#/library/${lib.id}`, { attrs: ` data-genre="${esc(G.genre)}" data-lib="${lib.id}"`, extra: ` <span class="muted d-only" style="font-size:14px;font-weight:400">${nf(G.count)}</span>`, sub: `${esc(lib.name)} · ${nf(G.count)} movies` }) + `
        <div class="strip hs">${G.items.map(i => cardItem(i)).join("")}</div>`;
    }
  }
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
    return !collId && lib.kind !== "music" && (q || filt || (isMov && catActive(cat))) ? nf(n) + " of " + nf(d1.library.item_count) : nf(collId || lib.kind === "music" ? n : d1.library.item_count);
  };
  ML = { id, kind: lib.kind, sub, collId, sort: collId && sort === "poster" ? "title" : sort, defSort, filt, cat, d, lib };
  const mlMore = () => {   // admin "..." menu: the same Select / Scan buttons as the desktop toolbar
    const m = [];
    if (ME.is_admin && lib.kind === "movies") m.push([SEL.on ? "Done selecting" : "Select movies to tag", () => { const b = $("#libselect"); if (b) b.click(); }]);
    if (ME.is_admin) m.push([scanning ? "Scanning..." : "Scan library for new files", () => { const b = $("#libscan"); if (b) b.click(); }]);
    return m;
  };
  let html = mlHead({ id, name: lib.name, count: mlCount(d), search: "filter", q, filter: isMov || lib.kind === "music", badge: isMov ? mlBadge(collId ? null : cat, filt) : 0, sort: true, more: ME.is_admin })
    + `<div class="row-head lib-head"><h2>${KIND_ICON[lib.kind] || ""} ${esc(lib.name)} <span class="muted" style="font-size:14px;font-weight:400" id="lib-count">${nf(lib.item_count)} items</span></h2>
    <div class="tools"><input type="search" id="libfilter" placeholder="Filter..." value="${esc(q)}" style="width:180px">
    <select id="libsort" title="Sort">${lib.kind !== "music" ? `<option value="poster">${collId ? "Release order" : "Posters first"}</option>` : ""}<option value="title">${collId ? "Release order" : "Title (A-Z)"}</option><option value="added">Recently added</option>${lib.kind !== "music" ? `<option value="year">Year</option>` : ""}${lib.kind === "movies" ? `<option value="rating">TMDB score</option>` : ""}</select>
    ${lib.kind === "movies" ? `<select id="libfilt" title="Show"><option value="">All movies</option><option value="review">Needs review${lib.meta_counts && lib.meta_counts.review ? " (" + nf(lib.meta_counts.review) + ")" : ""}</option><option value="nomatch">No TMDB match${lib.meta_counts && lib.meta_counts.nomatch ? " (" + nf(lib.meta_counts.nomatch) + ")" : ""}</option><option value="edition">Special editions</option></select>` : ""}
    ${lib.kind === "music" ? `<select id="libview"><option value="">Albums</option><option value="tracks">Tracks</option></select>` : ""}
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
    $("#lib-count").textContent = nf(d2.library.item_count) + " items";
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
  return `<div class="list">${tracks.map((t, n) => `<div class="li" data-track="${n}">
    <div class="num">${t.track || n + 1}</div><div class="ttl"><div>${esc(t.title)}</div><div class="muted" style="font-size:12.5px">${esc(t.artist || "")}${showAlbum && t.album ? " · " + esc(t.album) : ""}</div></div>
    <div class="dur">${fmtDur(t.duration)}</div></div>`).join("")}</div>`;
}
function bindTrackList(tracks) {
  $$("[data-track]").forEach(el => el.onclick = () => playQueue(tracks, +el.dataset.track));
}

async function viewShow(libId, show) {
  const d = await api(`/api/show?library_id=${libId}&show=${enc(show)}`);
  const cur = +(sessionStorage.getItem("season:" + libId + show) || d.seasons[0].season);
  const season = d.seasons.find(s => s.season === cur) || d.seasons[0];
  const total = d.seasons.reduce((a, s) => a + s.episodes.length, 0);
  const tm = d.tmdb || {};
  let html = `<div class="hero"${heroStyle(tm.backdrop)}></div><div class="detail"><div class="poster" style="${d.poster ? `background-image:url('${thumbUrl(d.poster)}')` : ""}"></div><div class="info">
    <h1>${esc(tm.title || d.show)}</h1><div class="meta">${d.year ? `<span>${d.year}</span>` : ""}<span>${d.seasons.length} season${d.seasons.length > 1 ? "s" : ""}</span><span>${total} episodes</span></div>
    ${metaChips(tm)}${tm.overview ? `<p class="overview">${esc(tm.overview)}</p>` : ""}
    <div class="actions"><button class="btn" id="playnext">&#9654; ${d.next.position ? "Resume" : "Play"} ${epCode(d.next)}</button>
      ${ME.is_admin ? `<button class="btn ghost" id="fixmatch">Fix match</button>` : ""}
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
}

async function viewAlbum(libId, artist, album) {
  const d = await api(`/api/album?library_id=${libId}&artist=${enc(artist)}&album=${enc(album)}`);
  $("#view").innerHTML = `<div class="detail"><div class="poster square" style="${d.poster ? `background-image:url('${thumbUrl(d.poster)}')` : ""}"></div><div class="info">
    <h1>${esc(d.album)}</h1><div class="meta"><span>${esc(d.artist)}</span>${d.year ? `<span>${d.year}</span>` : ""}<span>${d.tracks.length} tracks</span><span>${fmtLen(d.duration)}</span></div>
    <div class="actions"><button class="btn" id="playall">&#9654; Play album</button><button class="btn ghost" id="shuffle">&#8644; Shuffle</button></div>
    ${trackList(d.tracks, false)}</div></div>`;
  bindTrackList(d.tracks);
  $("#playall").onclick = () => playQueue(d.tracks, 0);
  $("#shuffle").onclick = () => { const t = d.tracks.slice(); for (let i = t.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [t[i], t[j]] = [t[j], t[i]]; } playQueue(t, 0); };
}

// 1.4.5: resolution name from width as well as height (a 1920x800 scope film is 1080p, not 720p)
function resName(w, h) { return w >= 3200 || h >= 2000 ? "4K" : w >= 1800 || h >= 1000 ? "1080p" : w >= 1200 || h >= 700 ? "720p" : h + "p"; }
// 1.4.5: the "..." menu on the details page (click / Enter opens; Esc, outside click or picking an item closes)
function bindMoreMenu() {
  const btn = $("#more"), menu = $("#more-menu"); if (!btn || !menu) return;
  const items = () => $$("#more-menu .mi");
  const open = (focusFirst) => { menu.hidden = false; btn.setAttribute("aria-expanded", "true"); if (focusFirst) (items()[0] || btn).focus(); };
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
  const pb = it.playback;
  const land = it.kind === "episode" || it.kind === "video";
  const img = land ? (it.thumb || it.poster) : (it.poster || it.thumb);
  let title = it.title, sub = [];
  if (it.kind === "episode") { title = it.title; sub.push(`<a href="#/show/${it.library_id}/${enc(it.show)}" style="color:var(--acc-text)">${esc(it.show_title || it.show)}</a>`, epCode(it)); if (it.air_date) sub.push(esc(it.air_date)); }
  if (it.media_type === "audio") { if (it.artist) sub.push(esc(it.artist)); if (it.album) sub.push(`<a style="color:var(--acc-text)" href="#/album/${it.library_id}/${enc(it.album_artist || it.artist || "Unknown artist")}/${enc(it.album)}">${esc(it.album)}</a>`); }
  if (it.year) sub.push(it.year);
  if (it.edition) sub.push(`<span class="ed">${esc(it.edition)}</span>`);
  if (it.duration) sub.push(fmtLen(it.duration));
  if (it.width) sub.push(resName(it.width, it.height));
  const playChip = pb.direct ? `<span class="chip ok">Direct play</span>` : pb.direct_maybe ? `<span class="chip warn">Direct play if your browser supports it, else ${pb.remux ? "remux" : "transcode"}</span>`
    : pb.remux ? `<span class="chip ok" title="The video is copied as-is; only the container${it.acodec && !["aac", "mp3"].includes(it.acodec) ? " and audio" : ""} are converted">Remux (no video re-encode)</span>` : `<span class="chip warn">Will transcode</span>`;
  const canMatch = ME.is_admin && (it.kind === "movie" || it.kind === "episode");
  const auds = pb.audio_streams.map(a => `${a.codec}${a.channels ? " " + a.channels + "ch" : ""}${a.lang ? " (" + a.lang + ")" : ""}`).join(", ");
  const isMovie = it.kind === "movie";
  if (isMovie && it.certification) sub.splice(it.year ? 1 : 0, 0, `<span class="chip cert" title="Age rating">${esc(it.certification)}</span>`);
  if (!it.duration && it.runtime) sub.splice(sub.length - (it.width ? 1 : 0), 0, fmtLen(it.runtime * 60));
  const chipsIt = Object.assign({}, it, { certification: isMovie ? null : it.certification });
  const plink = (p) => `<a href="#/person/${p.id}/${it.library_id}">${esc(p.name)}</a>`;
  const credLine = isMovie && (it.directors.length || it.writers.length) ? `<div class="credits-line">${it.directors.length ? `<span><span class="muted">Directed by</span> ${it.directors.map(plink).join(", ")}</span>` : ""}${it.writers.length ? `<span><span class="muted">Written by</span> ${it.writers.map(plink).join(", ")}</span>` : ""}</div>` : "";
  const castHtml = !isMovie ? "" : it.cast.length ? `<div class="cast-strip">${it.cast.map(p => `<a class="person" href="#/person/${p.id}/${it.library_id}" title="${esc(p.name)}${p.character ? " as " + esc(p.character) : ""}">
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
      ${pb.subtitles.length ? `<span>Subtitles</span><b>${esc(pb.subtitles.map(s => s.label).join(", "))}</b>` : ""}
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
    <div class="actions main-actions">
      ${it.position > 30 ? `<button class="btn big" id="resume">&#9654; Resume from ${fmtDur(it.position)}</button><button class="btn ghost big" id="play">Play from start</button>` : `<button class="btn big" id="play">&#9654; Play</button>`}
      <button class="btn ghost" id="watched">${it.watched ? "Mark unwatched" : "Mark watched"}</button>
      ${it.next ? `<a class="btn ghost" href="#/item/${it.next.id}">Next: ${epCode(it.next)} &rsaquo;</a>` : ""}
      ${moreMenu}
    </div>
    ${credLine}
    ${it.overview ? `<p class="overview">${esc(it.overview)}</p>` : (it.show_overview ? `<p class="overview muted">${esc(it.show_overview)}</p>` : "")}
    ${it.collection ? `<div class="coll-link">Part of <a href="#/library/${it.library_id}/collection/${it.collection.id}">${esc(it.collection.name || "a collection")} &rsaquo;</a></div>` : ""}
    ${isMovie && it.tags.length ? `<div class="tagrow">${it.tags.map(t => `<span class="chip tag"><a href="#/library/${it.library_id}" data-tagid="${t.id}">#${esc(t.name)}</a>${ME.is_admin ? `<button class="x" data-untag="${t.id}" title="Remove tag" aria-label="Remove tag ${esc(t.name)}">&times;</button>` : ""}</span>`).join("")}</div>` : ""}
    </div></div>
    ${isMovie ? `<section class="dsec"><div class="row-head"><h3>Cast</h3>${it.cast.length ? `<span class="muted">${it.cast.length} of the top-billed</span>` : ""}</div>${castHtml}</section>
    <section class="dsec"><div class="row-head"><h3>Similar movies</h3></div>${simHtml}</section>` : ""}
    ${it.tmdb ? TMDB_NOTE : ""}`;
  $("#play").onclick = () => { SFX.play(); playItem(id, 0); };
  bindMoreMenu();
  if ($("#fileinfo")) $("#fileinfo").onclick = fileInfoDlg;
  if ($("#fixmatch")) $("#fixmatch").onclick = () => {
    if (!it.tmdb_enabled) { toast("Add a TMDB API key in Settings -> Metadata first", true); return; }
    if (it.kind === "episode") fixMatchDialog("tv", it.show.replace(/\s*\((19|20)\d\d\)\s*$/, ""), null, (b) => api("/api/show/match", { method: "POST", body: { library_id: it.library_id, show: it.show, ...b } }));
    else fixMatchDialog("movie", it.file_title || it.title, it.year, (b) => api(`/api/items/${id}/match`, { method: "POST", body: b }));
  };
  if ($("#resume")) $("#resume").onclick = () => { SFX.play(); playItem(id, it.position); };
  if ($("#accept-cand")) $("#accept-cand").onclick = async () => { try { await api(`/api/items/${id}/match`, { method: "POST", body: { accept_candidate: true } }); toast("Match accepted"); route._keepScroll = true; route(); } catch (e) { toast(e.message, true); } };
  if ($("#confirm-match")) $("#confirm-match").onclick = async () => { try { await api(`/api/items/${id}/match`, { method: "POST", body: { tmdb_id: it.tmdb_id } }); toast("Match confirmed"); route._keepScroll = true; route(); } catch (e) { toast(e.message, true); } };
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
  if (d.episodes.length) html += `<h3>Episodes</h3><div class="grid wide">${d.episodes.map(i => cardItem(i, { landscape: true })).join("")}</div>`;
  if (d.albums.length) html += `<h3>Albums</h3><div class="grid">${d.albums.map(a => cardAlbum(a.library_id, a)).join("")}</div>`;
  if (d.tracks.length) html += `<h3>Tracks</h3>${trackList(d.tracks, true)}`;
  if (!d.items.length && !d.shows.length && !d.episodes.length && !d.albums.length && !d.tracks.length) html += `<div class="empty">Nothing found.</div>`;
  out.innerHTML = html;
  if (d.tracks.length) bindTrackList(d.tracks);
}

// 1.5.1: the Libraries tab -- every library, and for movie libraries their collections and categories
async function viewLibraries() {
  await refreshLibs();
  const sub = { movies: "Movies", tv: "TV shows", music: "Music", other: "Videos" };
  let html = `<h2 class="pg-h">Libraries</h2>`;
  if (!LIBS.length) html += `<div class="empty">No libraries yet.${ME.is_admin ? ` <a href="#/settings/libraries">Add one in Settings</a>` : ""}</div>`;
  else html += `<div class="lib-list">${LIBS.map(l => `<a class="lib-li" href="#/library/${l.id}"><span class="lib-ic" aria-hidden="true">${KIND_ICON[l.kind] || "&#127902;"}</span>
      <span class="lib-tx"><b>${esc(l.name)}</b><span class="muted">${sub[l.kind] || esc(l.kind)} · ${nf(l.item_count || 0)} items</span></span><span class="chev" aria-hidden="true">&rsaquo;</span></a>
      ${l.kind === "movies" ? `<div class="lib-subs"><a href="#/library/${l.id}/collections">Collections</a><a href="#/library/${l.id}/smart/recommended">Recommended</a><a href="#/library/${l.id}/smart/added">Recently added</a><a href="#/library/${l.id}/smart/top">Top movies</a></div>` : ""}`).join("")}</div>`;
  $("#view").innerHTML = html;
}

// 1.5.1: the My List tab -- your films in progress and the ones you watched last
async function viewMyList() {
  const d = await api("/api/mylist");
  let html = `<h2 class="pg-h">My List</h2>`;
  if (d.continue.length) html += rowHead("Continue watching", "", { sub: `${d.continue.length} in progress` }) + `<div class="strip hs cw">${d.continue.map(i => cardItem(i, { resume: true })).join("")}</div>`;
  if (d.watched.length) html += rowHead("Watched", "", { sub: "Most recent first" }) + `<div class="grid">${d.watched.map(i => cardItem(i)).join("")}</div>`;
  if (!d.continue.length && !d.watched.length) html += `<div class="empty">Nothing here yet. Films you start or finish show up here.</div>`;
  $("#view").innerHTML = html;
}

// ---------------------------------------------------------------- settings
async function viewSettings(tab) {
  // 1.4.9: non-admins only ever see My account, so don't offer a Libraries tab that just lands there
  const tabs = ME.is_admin ? [["libraries", "Libraries"], ["account", "My account"]] : [["account", "My account"]];
  if (ME.is_admin) tabs.splice(1, 0, ["scans", "Scan activity"], ["metadata", "Metadata"]), tabs.push(["users", "Users"], ["transcoding", "Transcoding"], ["system", "System"]);
  if (!ME.is_admin && tab !== "account") tab = "account";
  let html = `<h2>Settings</h2><div class="tabs set-tabs" role="tablist" aria-label="Settings sections">${tabs.map(([k, n]) => `<button role="tab" aria-selected="${k === tab}" class="${k === tab ? "on" : ""}" data-href="#/settings/${k}">${n}</button>`).join("")}</div>`;
  const v = $("#view");
  if (tab === "libraries") {
    await refreshLibs();
    html += `<div class="panel"><div class="row-head"><h3 style="margin:0">Libraries</h3>${ME.is_admin ? `<button class="btn" id="addlib">+ Add library</button>` : ""}</div>
      ${LIBS.length ? `<div class="tbl-wrap"><table class="lib-tbl"><tr><th>Name</th><th>Type</th><th>Source</th><th>Items</th><th>Last scan</th><th>Auto scan</th><th></th></tr>
      ${LIBS.map(l => {
        const sc = l.scan || {}; const busy = sc.state === "scanning" || sc.state === "queued";
        const src = l.share ? `<div class="src-share"><span class="src-kind">${l.share.kind.toUpperCase()}</span> <span class="path">${wbrPath(l.share.remote)}</span> ${l.share.mounted ? `<span class="chip ok pill">mounted &middot; ${l.share.mount_mode === "rw" ? "writable" : "read-only"}</span>` : `<span class="chip bad pill">not mounted</span>`}</div>${l.share.last_error ? `<div class="help" style="color:var(--bad)">${esc(l.share.last_error)}</div>` : ""}` : esc(l.path) + (l.online ? "" : ` <span class="chip bad">offline</span>`);
        return `<tr><td><a href="#/library/${l.id}"><b>${esc(l.name)}</b></a></td><td>${l.kind}</td><td class="src">${src}<div class="help path">${wbrPath(l.path)}</div></td><td>${l.item_count}</td>
        <td>${busy ? `scanning ${sc.done || 0}/${sc.total || "?"}<div class="prog"><div style="width:${sc.total ? 100 * sc.done / sc.total : 5}%"></div></div>` : ago(l.last_scan) + `<div class="help">${esc(l.last_scan_result || "")}</div>`}</td>
        <td>${intervalName(l.scan_interval_h)}${l.next_scan && !busy ? `<div class="help">next ${inTime(l.next_scan)}</div>` : ""}</td>
        <td>${ME.is_admin ? `<div class="row-actions"><button class="btn ghost small" data-scan="${l.id}">Scan</button><button class="btn ghost small" data-full="${l.id}" title="Re-probe every file and regenerate thumbnails">Full rescan</button>
          <span class="sep"></span>${l.share ? `<button class="btn ghost small" data-remount="${l.share.id}">Remount</button><button class="btn ghost small" data-editshare="${l.share.id}">Credentials</button>` : ""}
          ${l.kind === "movies" ? `<button class="btn ghost small" data-artwork="${l.id}" title="Save posters / fanart / .nfo into the movie folders">Artwork${l.art_write ? " &#10003;" : ""}</button>` : ""}
          <button class="btn ghost small" data-editlib="${l.id}">Edit</button><button class="btn danger small" data-dellib="${l.id}">Remove</button></div>` : ""}</td></tr>`; }).join("")}</table></div>` : `<div class="empty">No libraries yet.</div>`}</div>`;
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
    route._live = { every: 3000, fn: () => { if (!$(".modal:not(.hidden)")) { route._keepScroll = true; route(); } } };
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
    html += `<div class="panel" style="max-width:560px"><h3 style="margin-top:0">Change password</h3><div class="form">
      <label>Current password</label><input type="password" id="cp"><label>New password</label><input type="password" id="np" autocomplete="new-password">
      <label>Repeat</label><input type="password" id="np2" autocomplete="new-password"></div><div class="err" id="cperr"></div>
      <button class="btn" id="cpsave">Change password</button></div>`;
    const so = SFX.get();
    const swr = (id, on, title, hint) => `<label class="aw-row" for="${id}"><span class="sw"><input type="checkbox" id="${id}" ${on ? "checked" : ""}><i></i></span><span class="aw-txt"><b>${title}</b><span class="aw-hint">${hint}</span></span></label>`;
    html += `<div class="panel snd-panel" style="max-width:560px"><h3 style="margin-top:0">Sounds</h3>
      ${swr("snd-on", so.on, "Interface sounds", "Short sounds when you move over posters and open a movie. Never while a video is playing. Also switched with the speaker button in the top bar.")}
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
    $("#cpsave").onclick = async () => {
      if ($("#np").value !== $("#np2").value) { $("#cperr").textContent = "Passwords do not match"; return; }
      try { await api("/api/me/password", { method: "POST", body: { current_password: $("#cp").value, new_password: $("#np").value } }); toast("Password changed"); $("#cperr").textContent = ""; ["#cp", "#np", "#np2"].forEach(s => $(s).value = ""); }
      catch (e) { $("#cperr").textContent = e.message; }
    };
  } else if (tab === "users") {
    const users = await api("/api/users");
    html += `<div class="panel"><h3 style="margin-top:0">Users</h3><table><tr><th>Username</th><th>Role</th><th>Created</th><th></th></tr>
      ${users.map(x => `<tr><td>${esc(x.username)}</td><td>${x.is_admin ? "admin" : "viewer"}</td><td>${new Date(x.created_at * 1000).toLocaleDateString()}</td>
      <td><button class="btn ghost small" data-pw="${x.id}">Set password</button>${x.id !== ME.id ? `<button class="btn danger small" data-deluser="${x.id}">Delete</button>` : ""}</td></tr>`).join("")}</table>
      <h3>Add a user</h3><div class="form" style="max-width:560px"><label>Username</label><input type="text" id="nu"><label>Password</label><input type="password" id="nup" autocomplete="new-password">
      <label for="nua">Administrator</label><label class="chk"><input type="checkbox" id="nua"> <span class="help">can add libraries, shares and users</span></label></div><div class="err" id="nuerr"></div><button class="btn" id="nuadd">Add user</button></div>`;
    v.innerHTML = html;
    $("#nuadd").onclick = async () => { try { await api("/api/users", { method: "POST", body: { username: $("#nu").value, password: $("#nup").value, is_admin: $("#nua").checked } }); toast("User added"); route(); } catch (e) { $("#nuerr").textContent = e.message; } };
    $$("[data-deluser]").forEach(b => b.onclick = async () => { if (!confirm("Delete this user?")) return; try { await api("/api/users/" + b.dataset.deluser, { method: "DELETE" }); route(); } catch (e) { toast(e.message, true); } });
    $$("[data-pw]").forEach(b => b.onclick = async () => { const pw = prompt("New password (8+ characters). Other users must change it at next sign-in:"); if (!pw) return; try { await api(`/api/users/${b.dataset.pw}/password`, { method: "POST", body: { password: pw } }); toast("Password set"); } catch (e) { toast(e.message, true); } });
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
    $("#ss-all").onchange = async (e) => { try { await api("/api/settings", { method: "PUT", body: { status_all_users: e.target.checked } }); toast(e.target.checked ? "Server status is shown to everyone" : "Server status is shown to admins only"); } catch (err) { e.target.checked = !e.target.checked; toast(err.message, true); } };
    route._poll = setInterval(() => { route._keepScroll = true; route(); }, 5000);
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
        If the card fails on a video, that stream switches to the CPU by itself.</p>
      <div class="form hw-form">
        <label for="hw-mode">Hardware transcoding</label><select id="hw-mode">${["auto", "qsv", "vaapi", "nvenc", "off"].map(opt).join("")}</select>
        <label for="hw-dev">Video card</label><select id="hw-dev" ${usable.length ? "" : "disabled"}>${devOpts}</select>
        <label>In use now</label><div class="hw-now">${nowUse}</div>
      </div>
      <div class="help hw-modes">Auto picks the first method that passes a test: VAAPI, then Intel QSV, then NVIDIA NVENC. ${setBy}${userSet}</div>
      <div class="err" id="hw-err"></div>
      <div class="hw-acts"><button class="btn" id="hw-save">Save</button><button class="btn ghost" id="hw-scan">Scan for video cards again</button></div></div>
      <div class="panel"><div class="row-head"><h3 style="margin:0">Detected video cards</h3><span class="muted">${cards.length} found</span></div>
      ${cards.length ? `<div class="tbl-wrap"><table class="hw-tbl"><tr><th>Card</th><th>Device</th><th>Methods</th><th>Test</th></tr>${cardRows}</table></div>` : `<div class="empty">No video card found. Videos are converted on the CPU.</div>`}
      <div class="help" style="margin-top:8px">ffmpeg encoders: ${(det.encoders || []).map(e => esc(e)).join(", ") || "none"}</div></div>
      <div class="panel"><h3 style="margin-top:0">Streams right now</h3>${streams.length ? `<table><tr><th>Title</th><th>Quality</th><th>Encoder</th></tr>${streams.map(t => `<tr><td>${esc(t.title || "")}</td><td>${t.profile}</td><td>${encName(t)}</td></tr>`).join("")}</table>` : `<div class="muted">None</div>`}
      ${lf.at ? `<div class="help hw-last">Last fallback ${ago(lf.at)}: ${HW_LABEL[lf.method] || esc(lf.method)} (${lf.stage === "full" ? "GPU decode" : "GPU encode"}) &rarr; ${lf.stage === "full" ? "CPU decode + GPU encode" : "CPU"}<br><span class="path">${esc(lf.reason || "")}</span></div>` : ""}
      ${(st.held || []).map(h => `<div class="help" style="color:var(--warn)">${HW_LABEL[h.method]} is paused until ${new Date((h.since + 600) * 1000).toLocaleTimeString()} after it failed. Save or a passing test turns it back on now.</div>`).join("")}</div>`;
    $("#hw-save").onclick = async () => {
      $("#hw-err").textContent = "";
      try { st = await api("/api/hw", { method: "PUT", body: { mode: $("#hw-mode").value, device: $("#hw-dev").value } }); toast("Hardware transcoding: " + HW_LABEL[st.mode]); render(); }
      catch (e) { $("#hw-err").textContent = e.message; }
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
    <label>Type</label><div class="seg" id="al-kind"><button data-k="movies" class="on">Movies</button><button data-k="tv">TV shows</button><button data-k="music">Music</button><button data-k="other">Other videos</button></div>
    <label>Source</label><div class="seg" id="al-src"><button data-s="local" class="on">Folder on this server</button><button data-s="smb">SMB / Windows share</button><button data-s="nfs">NFS share</button></div>
    <div class="full" id="al-srcform"></div>
    <label>Automatic scan</label><select id="al-int">${intervalOpts(6)}</select>
  </div><div class="err" id="al-err"></div>
  <div class="modal-actions"><button class="btn ghost" id="al-cancel">Cancel</button><button class="btn" id="al-save">Add library</button></div>`, (box) => {
    let kind = "movies";
    $$("#al-kind button").forEach(b => b.onclick = () => { kind = b.dataset.k; $$("#al-kind button").forEach(x => x.classList.toggle("on", x === b)); if (!$("#al-name").value || $("#al-name").dataset.auto) { $("#al-name").value = b.textContent; $("#al-name").dataset.auto = "1"; } });
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
function artworkDialog(l) {
  const sh = l.share;
  const a = l.artwork || {};
  const busy = a.state === "running" || a.state === "queued";
  const row = (id, title, hint, on, extra = "") => `<label class="aw-row" for="${id}">
      <span class="sw"><input type="checkbox" id="${id}" ${on ? "checked" : ""} ${extra}><i></i></span>
      <span class="aw-txt"><b>${title}</b><span class="aw-hint">${hint}</span></span></label>`;
  modal(`<div class="aw">
    <div class="aw-head"><h2>Save artwork to movie folders</h2>
      <p class="aw-lead">Puts the TMDB poster (and, if you like, fanart and an info file) next to each matched movie so Kodi, Jellyfin and Plex can use it too. Video files are never changed.</p></div>
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
        ${row("aw-poster", "Poster", "Always included when artwork is saved.", true, "disabled")}
        ${row("aw-fan", "Fanart (backdrop)", "The wide background image, saved as fanart.jpg.", l.art_fanart)}
        ${row("aw-nfo", ".nfo info file", "Title, year, plot, genres and TMDB / IMDb ids for Kodi, Jellyfin and Plex.", l.art_nfo)}
        <div class="aw-row aw-static"><span class="aw-ico">&#128193;</span><span class="aw-txt"><b>Naming</b><span class="aw-hint">Chosen per movie, automatically:</span>
          <span class="aw-names"><span>Movie in its own folder</span><span class="aw-chips"><span class="aw-code">poster.jpg</span><span class="aw-code">fanart.jpg</span><span class="aw-code">movie.nfo</span></span>
          <span>Folder shared with other movies</span><span class="aw-chips"><span class="aw-code">&lt;file name&gt;-poster.jpg</span><span class="aw-code">&lt;file name&gt;.nfo</span></span></span></span></div>
        ${row("aw-on", "Save automatically for new matches", "Newly matched movies get their artwork without you doing anything.", l.art_write)}
        ${row("aw-ow", "Overwrite existing files", "Replace poster.jpg / fanart.jpg / .nfo that are already there. Off: existing files are never touched.", l.art_overwrite)}
      </section>
      <section class="aw-step">
        <div class="aw-step-h"><span class="aw-num">3</span><h3>Run</h3></div>
        <p class="aw-p" id="aw-why"></p>
        <div class="aw-run">
          <button class="btn ghost" id="aw-preview">Preview (dry run)</button>
          <button class="btn" id="aw-run">${busy ? "Saving artwork&hellip;" : "Write artwork for all matched movies"}</button>
          ${busy ? `<button class="btn danger" id="aw-stop">Stop</button>` : ""}
        </div>
        ${a.state === "error" ? `<div class="err">Last run: ${esc(a.error || "")}</div>` : ""}
        <div class="err" id="aw-err"></div><div id="aw-prev"></div>
      </section>
    </div>
    <div class="aw-foot"><span class="aw-dirty" id="aw-dirty"></span>
      <button class="btn ghost" id="aw-cancel">Close</button><button class="btn" id="aw-save" disabled>Save settings</button></div>
  </div>`, box => box.classList.add("modal-art"));

  const ids = ["aw-fan", "aw-nfo", "aw-on", "aw-ow"];
  const opts = () => ({ art_write: $("#aw-on").checked, art_fanart: $("#aw-fan").checked, art_nfo: $("#aw-nfo").checked, art_overwrite: $("#aw-ow").checked });
  let saved = JSON.stringify(opts());
  const dirty = () => JSON.stringify(opts()) !== saved;
  const writable = () => !sh || sh.mount_mode === "rw";
  const refresh = () => {
    if ($("#aw-mode")) $("#aw-mode").innerHTML = sh.mount_mode === "rw" ? `<span class="chip ok">Writable</span>` : sh.mount_mode === "ro" ? `<span class="chip warn">Read-only</span>` : `<span class="chip bad">Not mounted</span>`;
    const d = dirty();
    $("#aw-save").disabled = !d;
    $("#aw-dirty").textContent = d ? "Unsaved changes" : "";
    $("#aw-run").disabled = busy || d || !writable();
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
      const r = await api(`/api/libraries/${l.id}/artwork/preview?limit=400`);
      const root = (l.path || "").replace(/\/+$/, "") + "/";
      const rel = p => esc(p.startsWith(root) ? p.slice(root.length) : p);
      const s = r.summary; const todo = r.actions.filter(x => x.action !== "skip");
      const skips = r.actions.filter(x => x.action === "skip");
      $("#aw-prev").innerHTML = `<div class="aw-result">
        <div class="aw-sum"><span class="chip ok">${nf(s.create)} to create</span><span class="chip ${s.overwrite ? "warn" : ""}">${nf(s.overwrite)} to overwrite</span><span class="chip">${nf(s.skip)} skipped</span><span class="muted">${nf(r.items)} matched movies &middot; dry run, nothing written</span></div>
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
      if (!$("#aw-on").checked && !confirm("'Save automatically for new matches' is off, so new matches won't be written later. Write artwork for all matched movies once now?")) return;
      await api(`/api/libraries/${l.id}/artwork/write`, { method: "POST" });
      toast("Saving artwork -- progress is shown at the top"); pollActivity(); closeModal(); route._keepScroll = true; route();
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
function canDirect(it) {
  const pb = it.playback;
  if (pb.direct) {
    if (pb.mime === "video/x-matroska") return "try";   // most browsers play h264/aac mkv, but not all
    const t = video.canPlayType(pb.mime === "video/quicktime" ? "video/mp4" : pb.mime);
    return t ? "yes" : "try";
  }
  if (pb.direct_maybe) {
    if (it.vcodec === "hevc" && !video.canPlayType('video/mp4; codecs="hvc1.1.6.L120.90"')) return "no";
    if (it.acodec === "ac3" && !video.canPlayType('audio/mp4; codecs="ac-3"')) return "no";
    if (it.acodec === "eac3" && !video.canPlayType('audio/mp4; codecs="ec-3"')) return "no";
    return "try";
  }
  return "no";
}

async function playItem(id, startAt) {
  const it = await api("/api/items/" + id);
  if (it.media_type === "audio") { playQueue([it], 0); return; }
  if (startAt === undefined) startAt = it.position > 30 ? it.position : 0;
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
  q.innerHTML = `${dmode !== "no" ? `<option value="direct">Original (direct play)</option>` : ""}${pb.remux ? `<option value="remux">Original (remux, no re-encode)</option>` : ""}`
    + hi.map(m => `<option value="${m}">Transcode ${qualName(m)}</option>`).join("")
    + (pb.hires_off ? pb.hires_off.profiles.map(p => `<option value="" disabled data-note="${esc(pb.hires_off.note)}">${qualName(p)} &ndash; needs GPU transcoding</option>`).join("") : "")
    + pb.profiles.map(p => `<option value="${p}">Transcode ${p}</option>`).join("");
  // preference order: direct play -> remux (copy the video, convert container/audio) -> transcode
  let mode;
  const savedHi = hi.find(m => m.split(".")[0] === String(saved).split(".")[0]);
  if (pb.profiles.includes(saved)) mode = saved;
  else if (savedHi) mode = savedHi;
  else if (saved === "remux" && pb.remux) mode = "remux";
  else if (dmode !== "no") mode = "direct";
  else if (pb.remux) mode = "remux";
  else mode = pb.profiles[0];
  const a = $("#pl-audio");
  a.innerHTML = pb.audio_streams.map((s, i) => `<option value="${i}">${esc((s.title || s.lang || "Audio " + (i + 1)) + " · " + s.codec + (s.channels ? " " + s.channels + "ch" : ""))}</option>`).join("");
  a.classList.toggle("hidden", pb.audio_streams.length < 2);
  const sb = $("#pl-subs");
  sb.innerHTML = `<option value="">Subtitles off</option>` + pb.subtitles.map(s => `<option value="${s.key}">${esc(s.label)}</option>`).join("");
  sb.classList.toggle("hidden", !pb.subtitles.length);
  $("#pl-next").classList.toggle("hidden", !it.next);
  video.controls = false;          // 1.4.13: our own bar replaces the browser's controls
  BAR.closePop();
  $("#player").classList.remove("hidden");
  startStream(mode, P.start);
  BAR.sync(); BAR.draw(P.start); ROT.open();
  OV.show();     // 1.4.11: show the big buttons for a moment so they're discoverable
}

function setStatus(t) { $("#pl-status").textContent = t || ""; }
function modeLabel(m) { return (m === "direct" ? "Direct play" : m === "remux" ? "Remux (original video)" : `Transcoding ${qualName(m)}`) + (P && P.it.playback.hdr && m !== "direct" && m !== "remux" ? hdrNote() : ""); }
// 1.5.3: 2K / 4K names, HEVC support, HDR note
function qualName(m) { const [b, vc] = String(m).split("."); return (b === "2160p" ? "4K (2160p)" : b === "1440p" ? "2K (1440p)" : b) + (vc === "hevc" ? " HEVC" : ""); }
function hevcOK() {
  if (hevcOK.v !== undefined) return hevcOK.v;
  let ok = false;
  try {
    const c = 'video/mp4; codecs="hvc1.1.6.L153.B0"';
    if (window.Hls && Hls.isSupported()) ok = !!(window.MediaSource && MediaSource.isTypeSupported(c));
    else ok = !!document.createElement("video").canPlayType(c);
  } catch (e) { ok = false; }
  return (hevcOK.v = ok);
}
function hiresMode(p) { return hevcOK() ? p + ".hevc" : p; }
function hdrNote() { return " · " + P.it.playback.hdr + " without tone-mapping (colors may look flat)"; }

function startStream(mode, at) {
  if (!P) return;
  const it = P.it;
  teardownVideo(false);
  P.mode = mode;
  $("#pl-quality").value = mode;
  const subKey = $("#pl-subs").value;
  if (mode === "direct") {
    P.triedDirect = true;
    setStatus("Direct play");
    video.src = `/api/items/${it.id}/file`;
    video.addEventListener("loadedmetadata", function onMeta() {
      video.removeEventListener("loadedmetadata", onMeta);
      if (it.vcodec && video.videoWidth === 0) { fallback("browser cannot decode the video"); return; }
      if (at) video.currentTime = at;
    });
  } else {
    setStatus(modeLabel(mode));
    const url = `/api/items/${it.id}/hls/${mode}/index.m3u8?audio=${P.audio}${mode.endsWith(".hevc") ? "&start=" + Math.floor((at || 0) / 6) : ""}`;
    if (window.Hls && Hls.isSupported()) {
      hls = new Hls({ startPosition: at || 0, maxBufferLength: 30, maxMaxBufferLength: 120, fragLoadingTimeOut: 90000, fragLoadingMaxRetry: 4, manifestLoadingTimeOut: 30000, xhrSetup: (xhr) => { xhr.withCredentials = true; } });
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
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;  // Safari native HLS
      video.addEventListener("loadedmetadata", function onMeta() { video.removeEventListener("loadedmetadata", onMeta); if (at) video.currentTime = at; });
    } else { setStatus("This browser cannot play HLS"); return; }
  }
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
  const next = P.mode === "direct" && P.it.playback.remux && !P.triedRemux ? "remux" : P.it.playback.profiles[0];
  if (next === "remux") P.triedRemux = true;
  toast((next === "remux" ? "Switching to remux (" : "Switching to transcoding (") + reason + ")");
  startStream(next, at);
}
video.addEventListener("error", () => {
  if (P && P.mode === "direct") fallback("direct play failed");
  else if (P && P.mode === "remux" && !hls) fallback("remux failed");
  else if (P) setStatus("Playback error");
});

function addSubTrack(key) {
  $$("track", video).forEach(t => t.remove());
  if (!key) return;
  const tr = document.createElement("track");
  tr.kind = "subtitles"; tr.label = "Subtitles"; tr.default = true;
  tr.src = `/api/items/${P.it.id}/subs/${key}.vtt`;
  video.appendChild(tr);
  tr.addEventListener("load", () => { tr.track.mode = "showing"; });
  setTimeout(() => { if (tr.track) tr.track.mode = "showing"; }, 50);
}
$("#pl-subs").onchange = () => addSubTrack($("#pl-subs").value);
$("#pl-quality").onchange = () => {
  const m = $("#pl-quality").value; localStorage.setItem("quality", m === "direct" ? "auto" : m);
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
video.addEventListener("ended", () => { saveProgress(true); if (P && P.it.next) playItem(P.it.next.id, 0); });
video.addEventListener("waiting", () => { if (P && P.mode !== "direct") setStatus(`${modeLabel(P.mode)} · buffering...`); });
video.addEventListener("playing", () => { if (P) { P.played = true; setStatus(modeLabel(P.mode)); } setTimeout(() => setStatus(""), 4000); });

function teardownVideo(stopServer) {
  if (hls) { hls.destroy(); hls = null; }
  video.removeAttribute("src"); $$("track", video).forEach(t => t.remove()); video.load();
  if (stopServer && P) api(`/api/items/${P.it.id}/stop`, { method: "POST" }).catch(() => {});
}
function closePlayer() {
  if (!P) return;
  PIP.leave(); saveProgress(); teardownVideo(true); P = null; PIP.tell();
  OV.reset();
  $("#player").classList.add("hidden"); ROT.close();
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  route._keepScroll = true; route();
}
$("#pl-close").onclick = closePlayer;
$("#pl-next").onclick = () => { if (P && P.it.next) { saveProgress(); const n = P.it.next.id; teardownVideo(true); playItem(n, 0); } };
document.addEventListener("keydown", (e) => {
  if (!P || PIP.minimized() || e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;   // in PiP the page is free for browsing
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
  const isOn = () => pl.classList.contains("ov-on");
  const top = pl.querySelector(".pl-top");
  let overTop = false;
  // 1.4.12: keep everything up while a top-bar picker is open / focused or the mouse is over the top bar
  const bar = $("#pl-bar");
  // 1.4.12/1.4.13: keep everything up while a menu (Quality / Subtitles / Audio) is open, the seek bar is dragged,
  // or the mouse rests on the top or bottom bar
  const held = () => overTop || BAR.busy();
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
    const f = frac(e); tip.textContent = fmt(f * dur()); tip.style.left = (f * 100) + "%"; tip.classList.remove("hidden");
    if (drag) draw(f * dur());
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
    pop.innerHTML = "";
    const h = (t) => { const x = document.createElement("h4"); x.textContent = t; pop.appendChild(x); };
    if (kind === "q") {
      h("Quality");
      [...q.options].forEach(o => {
        if (o.disabled) { const b = item(o.textContent, false, () => toast(o.dataset.note || "Not available")); b.classList.add("off"); b.setAttribute("aria-disabled", "true"); b.title = o.dataset.note || ""; pop.appendChild(b); return; }
        pop.appendChild(item(o.textContent, o.value === q.value, () => { pick(q, o.value); closePop(); }));
      });
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
    if (first && !SFX.COARSE) first.focus({ preventScroll: true });
  }
  function closePop() {
    if (!popFor) return;
    popFor = null; pop.classList.add("hidden"); pop.innerHTML = "";
    $$(".pl-bar .pl-cb").forEach(b => b.setAttribute("aria-expanded", "false"));
    if (P && OV.isOn()) OV.arm();
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
  Q.list = list; Q.idx = idx; await loadTrack();
}
async function loadTrack() {
  const t0 = Q.list[Q.idx]; if (!t0) return;
  const t = t0.playback ? t0 : await api("/api/items/" + t0.id);
  Q.list[Q.idx] = t;
  if (Q.hls) { Q.hls.destroy(); Q.hls = null; }
  $("#audiobar").classList.remove("hidden");
  $("#ab-title").textContent = t.title; $("#ab-sub").textContent = [t.artist, t.album].filter(Boolean).join(" · ");
  $("#ab-art").src = t.poster ? thumbUrl(t.poster) : "/static/icon-192.png";
  const direct = t.playback.direct && audio.canPlayType(t.playback.mime) !== "";
  Q.mode = direct ? "direct" : "hls";
  if (direct) audio.src = `/api/items/${t.id}/file`;
  else {
    const url = `/api/items/${t.id}/hls/audio/index.m3u8`;
    if (window.Hls && Hls.isSupported()) { Q.hls = new Hls({ xhrSetup: (x) => { x.withCredentials = true; } }); Q.hls.loadSource(url); Q.hls.attachMedia(audio); }
    else audio.src = url;
  }
  audio.play().catch(() => {});
  $$(".li.playing").forEach(el => el.classList.remove("playing"));
  document.title = t.title + " · Movinite";
  if ("mediaSession" in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist || "", album: t.album || "", artwork: t.poster ? [{ src: thumbUrl(t.poster) }] : [] });
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
audio.addEventListener("play", () => $("#ab-play").innerHTML = "&#10074;&#10074;");
audio.addEventListener("pause", () => $("#ab-play").innerHTML = "&#9654;");
audio.addEventListener("timeupdate", () => {
  const d = isFinite(audio.duration) ? audio.duration : (Q.list[Q.idx] || {}).duration || 0;
  $("#ab-cur").textContent = fmtDur(audio.currentTime); $("#ab-dur").textContent = fmtDur(d);
  if (!$("#ab-range").dragging) $("#ab-range").value = d ? Math.round(1000 * audio.currentTime / d) : 0;
});
$("#ab-range").addEventListener("input", () => { $("#ab-range").dragging = true; });
$("#ab-range").addEventListener("change", () => {
  const d = isFinite(audio.duration) ? audio.duration : (Q.list[Q.idx] || {}).duration || 0;
  audio.currentTime = d * $("#ab-range").value / 1000; $("#ab-range").dragging = false;
});
$("#ab-play").onclick = () => audio.paused ? audio.play() : audio.pause();
$("#ab-next").onclick = nextTrack; $("#ab-prev").onclick = prevTrack;
$("#ab-vol").oninput = () => { audio.volume = $("#ab-vol").value / 100; };
$("#ab-close").onclick = stopAudio;
function stopAudio() {
  audio.pause(); if (Q.hls) { Q.hls.destroy(); Q.hls = null; }
  audio.removeAttribute("src"); audio.load(); Q = { list: [], idx: -1, hls: null, mode: null };
  $("#audiobar").classList.add("hidden"); document.title = "Movinite";
}
function stopAll() { if (P) { PIP.leave(); teardownVideo(true); P = null; OV.reset(); $("#player").classList.add("hidden"); } stopAudio(); }

boot();
})();
