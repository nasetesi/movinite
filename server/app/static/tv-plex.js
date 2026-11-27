/* TV-only Plex-inspired chrome (2.1). Does not change desktop or phone layouts. */
(function () {
  const ico = {
    search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
    home: '<svg viewBox="0 0 24 24"><path d="M4 11.5L12 5l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z"/></svg>',
    list: '<svg viewBox="0 0 24 24"><path d="M8 7h12M8 12h12M8 17h12"/><circle cx="4" cy="7" r="1.2" fill="currentColor" stroke="none"/><circle cx="4" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="4" cy="17" r="1.2" fill="currentColor" stroke="none"/></svg>',
    grid: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="7" height="7" rx="1.2"/><rect x="13" y="4" width="7" height="7" rx="1.2"/><rect x="4" y="13" width="7" height="7" rx="1.2"/><rect x="13" y="13" width="7" height="7" rx="1.2"/></svg>',
    film: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 10h18M3 14h18"/></svg>',
    tv: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M8 21h8M12 18v3"/></svg>',
    music: '<svg viewBox="0 0 24 24"><path d="M9 18V6l12-2v12"/><circle cx="7" cy="18" r="2.5"/><circle cx="19" cy="16" r="2.5"/></svg>',
    settings: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/><path d="M12 3.5v2.2M12 18.3V20.5M4.8 7.2l1.7 1.3M17.5 15.5l1.7 1.3M3.5 12h2.2M18.3 12H20.5M4.8 16.8l1.7-1.3M17.5 8.5l1.7-1.3"/></svg>',
    more: '<svg viewBox="0 0 24 24"><circle cx="6" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="18" cy="12" r="1.6" fill="currentColor" stroke="none"/></svg>'
  };

  function el(html) {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
  function initials(name) {
    const p = String(name || "A").trim().split(/\s+/);
    return ((p[0] && p[0][0]) || "A").toUpperCase();
  }
  function runtimeLabel(min) {
    min = parseInt(min, 10);
    if (!min) return "";
    const h = Math.floor(min / 60), m = min % 60;
    return h ? (m ? h + " hr " + m + " min" : h + " hr") : min + " min";
  }
  function isHome() {
    const h = (location.hash || "#/home").replace(/^#\/?/, "") || "home";
    return h === "home" || h === "";
  }
  function playerOn() {
    const p = document.getElementById("player");
    return !!(p && !p.classList.contains("hidden"));
  }
  function authOpen() {
    const a = document.getElementById("auth");
    return !!(a && !a.classList.contains("hidden"));
  }
  function libIcon(kind) {
    return kind === "tv" ? ico.tv : kind === "music" ? ico.music : ico.film;
  }

  const TVPlex = {
    items: {},
    tab: "foryou",
    tabsEnabled: false,
    menuOpen: false,
    acctOpen: false,
    returnEl: null,
    clockTimer: 0,
    heroId: "",
    previewTimer: 0,
    _pendingPreview: null,

    init() {
      if (!(window.TV && TV.on)) {
        setTimeout(() => this.init(), 400);
        return;
      }
      if (this._inited) return;
      this._inited = true;
      document.documentElement.classList.add("tv-plex");
      // 2.5.5: hide For You / Recently Added / Libraries for now (set true to bring them back).
      if (this.tabsEnabled === false) document.documentElement.classList.add("tv-tabs-off");
      else document.documentElement.classList.remove("tv-tabs-off");
      this.syncViewportVars();
      this.inject();
      this.hook();
      this.tickClock();
      this.clockTimer = setInterval(() => this.tickClock(), 15000);
      this.syncAuth();
      this.syncPage();
    },

    syncAuth() {
      const off = authOpen();
      document.documentElement.classList.toggle("tv-auth", off);
      if (off && this.menuOpen) this.closeMenu(true);
    },

    inject() {
      if (document.getElementById("tv-hero")) return;
      document.body.appendChild(el(`
        <div id="tv-hero" aria-hidden="true">
          <div class="tv-hero-img" id="tv-hero-a"></div>
          <div class="tv-hero-img-b" id="tv-hero-b"></div>
          <div class="tv-hero-g"></div>
          <div class="tv-hero-meta">
            <img class="tv-hero-logo" id="tv-hero-logo" alt="">
            <h1 class="tv-hero-title" id="tv-hero-title"></h1>
            <div class="tv-hero-facts" id="tv-hero-facts"></div>
            <p class="tv-hero-ov" id="tv-hero-ov"></p>
            <div class="tv-hero-cast" id="tv-hero-cast"></div>
          </div>
        </div>`));
      document.body.appendChild(el(`
        <div id="tv-top">
          <div id="tv-tabs" role="tablist" aria-label="Home sections">
            <button type="button" role="tab" data-tab="foryou" class="on" tabindex="0">For You</button>
            <button type="button" role="tab" data-tab="added" tabindex="0">Recently Added</button>
            <button type="button" role="tab" data-tab="libraries" tabindex="0">Libraries</button>
          </div>
          <div id="tv-clock"></div>
        </div>`));
      const who = (window.ME && (ME.username || ME.name)) || "Admin";
      document.body.appendChild(el(`
        <div id="tv-rail" aria-label="Menu">
          <button type="button" class="tv-rail-av" id="tv-rail-av" data-rail="menu" aria-label="Account">${esc(initials(who))}</button>
          <button type="button" data-rail="search" aria-label="Search">${ico.search}</button>
          <button type="button" data-rail="home" aria-label="Home">${ico.home}</button>
          <button type="button" data-rail="menu" aria-label="Libraries">${ico.grid}</button>
          <div class="tv-rail-spacer"></div>
        </div>`));
      document.body.appendChild(el(`<div id="tv-dim" aria-hidden="true"></div>`));
      document.body.appendChild(el(`<div id="tv-menu" role="menu" aria-label="Menu"></div>`));
      this.drawMenu();
      document.getElementById("tv-tabs").addEventListener("click", (e) => {
        const b = e.target.closest("button[data-tab]");
        if (b) this.setTab(b.getAttribute("data-tab"));
      });
      document.getElementById("tv-rail").addEventListener("click", (e) => {
        const b = e.target.closest("button[data-rail]");
        if (!b) return;
        const act = b.getAttribute("data-rail");
        if (act === "search") { this.closeMenu(); location.hash = "#/search"; return; }
        if (act === "home") { this.closeMenu(); location.hash = "#/home"; return; }
        this.openMenu(b);
      });
      document.getElementById("tv-dim").addEventListener("click", () => this.closeMenu());
      document.getElementById("tv-menu").addEventListener("click", (e) => this.onMenuClick(e));
    },

    drawMenu() {
      const who = (window.ME && (ME.username || ME.name)) || "admin";
      const libs = (this.libs && this.libs.length ? this.libs : (window.LIBS || [])).slice();
      const libRows = libs.map((L) => {
        const source = L.peer_name || L.source_name || (L.share && L.share.name) || "This server";
        const href = "#/library/" + L.id;
        const sub = esc(L.name) + " / " + esc(source);
        return `<a class="tv-mi" href="${href}" data-act="lib" data-id="${L.id}" tabindex="0">
          <span class="tv-mi-ico">${libIcon(L.kind)}</span>
          <span class="tv-mi-txt"><b>${esc(L.name)}</b><span>${sub}</span></span>
        </a>`;
      }).join("");
      document.getElementById("tv-menu").innerHTML = `
        <button type="button" class="tv-profile" data-act="profile" tabindex="0">
          <span class="tv-rail-av">${esc(initials(who))}</span>
          <span class="tv-mi-txt"><b>${esc(who)}</b></span>
          <span class="tv-chev">›</span>
        </button>
        <div id="tv-acct">
          <button type="button" data-act="account" tabindex="0">My account</button>
          <button type="button" data-act="signout" tabindex="0">Sign out</button>
        </div>
        <a class="tv-mi" href="#/mylist" data-act="lists" tabindex="0">
          <span class="tv-mi-ico">${ico.list}</span>
          <span class="tv-mi-txt"><b>My Lists</b></span>
        </a>
        <button type="button" data-act="search" tabindex="0">
          <span class="tv-mi-ico">${ico.search}</span>
          <span class="tv-mi-txt"><b>Search</b></span>
        </button>
        <button type="button" class="on" data-act="home" tabindex="0">
          <span class="tv-mi-ico">${ico.home}</span>
          <span class="tv-mi-txt"><b>Home</b></span>
        </button>
        <div class="tv-div">Libraries</div>
        ${libRows}
        <div class="tv-div">More</div>
        <button type="button" data-act="settings" tabindex="0">
          <span class="tv-mi-ico">${ico.settings}</span>
          <span class="tv-mi-txt"><b>Settings</b></span>
        </button>`;
    },

    hook() {
      const self = this;
      if (typeof api === "function" && !api._tvplex) {
        const orig = api;
        window.api = async function (url, opts) {
          const d = await orig(url, opts);
          if (typeof url === "string" && url.split("?")[0] === "/api/home") self.ingest(d);
          return d;
        };
        window.api._tvplex = true;
      }
      document.addEventListener("focusin", (e) => {
        if (self.menuOpen) return;
        const card = e.target && e.target.closest && e.target.closest("#view .card");
        if (card) {
          self.rememberContent(card);
          self.showHero(card);
        }
      });
      if (!this._resizeOn) {
        this._resizeOn = true;
        window.addEventListener("resize", () => {
          if (!isHome() || playerOn() || authOpen()) return;
          self.syncRowPitch();
          self.applyRowShift();
        });
      }
      const after = TV.afterRoute.bind(TV);
      TV.afterRoute = function () {
        // 2.1.2: apply tv-plex-off (and the tighter #view layout) BEFORE focusing
        // Resume/Play. In 2.1, afterRoute ran first while the home page still had
        // a large reserved top area, scrolled Play into the middle, then collapsing
        // that area jumped the page down and hid the button.
        if (authOpen()) { after(); self.syncAuth(); return; }
        self.syncPage();
        const detail = TV.isDetailView && TV.isDetailView();
        const v = document.getElementById("view");
        if (detail && v) v.scrollTop = 0;
        after();
        if (isHome() && !playerOn() && !authOpen()) {
          self.layoutRows();
          self.retagRows();
          requestAnimationFrame(() => self.layoutRows());
        }
        if (detail) {
          const pin = () => {
            if (v) v.scrollTop = 0;
            const act = TV.detailPrimaryAction && TV.detailPrimaryAction();
            if (act) {
              try { act.focus({ preventScroll: true }); } catch (e) {}
            }
          };
          pin();
          requestAnimationFrame(pin);
        }
      };
      if (!TV.focus._tvplexRow) {
        const focus = TV.focus.bind(TV);
        TV.focus = function (el, opts) {
          focus(el, opts);
          self.revealRow(el);
        };
        TV.focus._tvplexRow = true;
      }
      const onKey = TV.onKey.bind(TV);
      TV.onKey = function (e) {
        const t0 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
        if (authOpen()) { onKey(e); return; }
        if (!self.onKey(e)) onKey(e);
        if (isHome() && !playerOn() && !authOpen()) self.ensureFocus();
        const dt = ((typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now()) - t0;
        self._lastKeyMs = dt;
        const arr = window.__tvKeyMs || (window.__tvKeyMs = []);
        arr.push(dt);
        if (arr.length > 40) arr.splice(0, arr.length - 40);
      };
      const candidates = TV.candidates.bind(TV);
      TV.candidates = function () {
        if (self.menuOpen) return self.menuItems();
        if (authOpen()) return candidates();
        const now = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
        if (self._candCache && (now - self._candAt) < 80) return self._candCache;
        let list;
        if (isHome() && !playerOn()) {
          const extra = this.tabsEnabled
            ? [...document.querySelectorAll("#tv-tabs button, #tv-rail button")]
            : [...document.querySelectorAll("#tv-rail button")];
          const vh = window.innerHeight || 1080, vw = window.innerWidth || 1920;
          const cards = [];
          document.querySelectorAll("#view .card").forEach((el) => {
            const r = el.getBoundingClientRect();
            if (r.bottom < -240 || r.top > vh + 480 || r.width < 2 || r.height < 2) return;
            if (r.right < -480 || r.left > vw + 480) return;
            cards.push(el);
          });
          list = extra.concat(cards);
        } else {
          list = candidates().filter((el) => !(el.closest && el.closest(".side, .top, .tabbar")));
        }
        self._candCache = list;
        self._candAt = now;
        return list;
      };
    },

    ingest(d) {
      const add = (arr) => (arr || []).forEach((i) => { if (i && i.id) this.items[String(i.id)] = i; });
      add(d.continue);
      (d.libraries || []).forEach((L) => {
        add(L.items);
        (L.smart_rows || []).forEach((R) => add(R.items));
        (L.genre_rows || []).forEach((G) => add(G.items));
        add(L.albums);
      });
    },

    tickClock() {
      const n = document.getElementById("tv-clock");
      if (!n) return;
      n.textContent = new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    },

    syncPage() {
      this.syncAuth();
      if (authOpen()) return;
      const home = isHome() && !playerOn();
      document.documentElement.classList.toggle("tv-plex-off", !home);
      if (this.menuOpen && !home) this.closeMenu(true);
      this.retagRows();
      if (home) {
        this.ensureItems().then(() => {
        const cur = document.activeElement;
        if (cur && cur.closest && cur.closest("#view .card")) this.showHero(cur);
        else {
          const first = document.querySelector("#view .strip.cw .card, #view .card");
          if (first) this.showHero(first);
        }
        });
      }
    },

    retagRows() {
      if (!isHome()) return;
      document.querySelectorAll("#view .row-head").forEach((h) => {
        if (h.querySelector(".tv-lib-tag")) return;
        const sub = h.nextElementSibling && h.nextElementSibling.classList && h.nextElementSibling.classList.contains("row-sub")
          ? h.nextElementSibling.textContent : "";
        const extra = h.querySelector("h3 .d-only, h3 span.muted");
        let name = "";
        const m = (extra && extra.textContent || "").match(/in\s+(.+)$/);
        if (m) name = m[1].trim();
        if (!name && /Recently added in /i.test(h.textContent)) {
          name = h.textContent.replace(/Recently added in /i, "").trim();
        }
        // Continue Watching has no library tag
        if (/continue watching/i.test(h.textContent)) return;
        if (name) {
          const tag = document.createElement("span");
          tag.className = "tv-lib-tag";
          tag.textContent = name;
          const h3 = h.querySelector("h3");
          if (h3) h3.appendChild(tag);
        }
      });
    },

    async ensureItems() {
      if (this._loadingItems) return this._loadingItems;
      const needHome = !Object.keys(this.items).length;
      const needLibs = !(this.libs && this.libs.length);
      if (!needHome && !needLibs) return;
      this._loadingItems = Promise.all([
        needHome ? fetch("/api/home", { credentials: "same-origin" }).then((r) => r.json()).then((d) => this.ingest(d)) : null,
        needLibs ? fetch("/api/libraries", { credentials: "same-origin" }).then((r) => r.json()).then((d) => {
          const arr = Array.isArray(d) ? d : (d && (d.libraries || d.items));
          if (Array.isArray(arr) && arr.length) this.libs = arr;
        }) : null
      ]).finally(() => { this._loadingItems = null; });
      return this._loadingItems;
    },

    showHero(card) {
      if (!card) return;
      this._heroCard = card;
      if (this._heroTimer) {
        clearTimeout(this._heroTimer);
        this._heroTimer = 0;
      }
      const run = () => {
        this._heroTimer = 0;
        this._heroAt = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
        const c = this._heroCard;
        if (!c) return;
        const id = c.dataset.id || (c.dataset.href || "").split("/").pop();
        if (id && !this.items[String(id)]) {
          this.ensureItems().then(() => {
            if (this._heroCard === c) this.paintHero(c, id);
          });
          return;
        }
        this.paintHero(c, id);
        this.preloadNeighbors(c);
      };
      // Start the backdrop immediately on focus. Coalesce only tight key-repeat
      // (trailing) so a fast hold still lands on the last title.
      const now = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
      const since = now - (this._heroAt || 0);
      if (!this._heroAt || since >= 32) run();
      else this._heroTimer = setTimeout(run, 32);
    },

    preloadNeighbors(card) {
      const st = card && card.closest && card.closest(".strip, .hs");
      if (!st) return;
      const cards = [...st.querySelectorAll(".card")];
      const i = cards.indexOf(card);
      [cards[i - 2], cards[i - 1], cards[i + 1], cards[i + 2]].forEach((c) => {
        if (!c) return;
        const id = c.dataset.id || (c.dataset.href || "").split("/").pop();
        const it = this.items[String(id)] || {};
        const name = it.backdrop || it.poster;
        if (!name) return;
        const im = new Image();
        im.src = "/api/thumb/" + name;
      });
    },

    paintHero(card, id) {
      const it = this.items[String(id)] || {};
      const title = it.title || (card && card.querySelector(".t") && card.querySelector(".t").textContent) || "";
      const hero = document.getElementById("tv-hero");
      if (!hero) return;
      if (String(id || "") && String(this.heroId) === String(id)) return;
      const writeText = () => {
        const logo = document.getElementById("tv-hero-logo");
        const tEl = document.getElementById("tv-hero-title");
        if (it.logo) {
          hero.classList.remove("no-logo");
          logo.src = "/api/logo/" + it.logo;
          logo.alt = title;
          logo.hidden = false;
          tEl.textContent = title;
        } else {
          hero.classList.add("no-logo");
          logo.removeAttribute("src");
          tEl.textContent = title;
        }
        const bits = [];
        if (it.year) bits.push("<span>" + esc(it.year) + "</span>");
        const rt = runtimeLabel(it.runtime);
        if (rt) bits.push("<span class='dot'>·</span><span>" + esc(rt) + "</span>");
        const genres = (it.genres || []).slice(0, 3);
        if (genres.length) bits.push("<span class='dot'>·</span><span>" + genres.map(esc).join(", ") + "</span>");
        if (it.certification) bits.push("<span class='tv-cert'>" + esc(it.certification) + "</span>");
        if (it.rating) bits.push("<span class='tv-rate'><b>★</b> " + Number(it.rating).toFixed(1) + "</span>");
        document.getElementById("tv-hero-facts").innerHTML = bits.join("");
        document.getElementById("tv-hero-ov").textContent = it.overview || "";
        const cast = (it.cast || []).slice(0, 4);
        document.getElementById("tv-hero-cast").textContent = cast.length ? "Cast  " + cast.join(", ") : "";
      };
      if (this.heroId) {
        hero.classList.add("tv-hero-text-out");
        setTimeout(() => {
          writeText();
          requestAnimationFrame(() => hero.classList.remove("tv-hero-text-out"));
        }, 80);
      } else {
        writeText();
      }
      const bg = it.backdrop ? "/api/thumb/" + it.backdrop : (it.poster ? "/api/thumb/" + it.poster : "");
      const a = document.getElementById("tv-hero-a");
      const b = document.getElementById("tv-hero-b");
      if (bg) {
        const url = "url(\"" + bg + "\")";
        const apply = () => {
          if (this.heroId === String(id) && a.style.backgroundImage) {
            if (hero.classList.contains("swap")) {
              a.style.backgroundImage = b.style.backgroundImage;
              hero.classList.remove("swap");
            }
            b.style.backgroundImage = url;
            requestAnimationFrame(() => hero.classList.add("swap"));
          } else {
            a.style.backgroundImage = url;
            b.style.backgroundImage = "";
            hero.classList.remove("swap");
          }
          this.heroId = String(id || "");
        };
        const pre = new Image();
        pre.onload = apply;
        pre.onerror = apply;
        pre.src = bg;
      }
    },

    rowHeading(from) {
      // The heading lives before the .hrow wrapper; a row-sub or row-note may sit between them.
      let el = from && from.previousElementSibling;
      while (el && !(el.classList && el.classList.contains("row-head"))) {
        if (el.classList && el.classList.contains("hrow")) break;
        el = el.previousElementSibling;
      }
      return (el && el.classList && el.classList.contains("row-head")) ? el : null;
    },

    rowStep(card, dir) {
      // Next/previous home row, same poster index when possible. Geometric nearest can skip a
      // row when the focused poster is scaled up and overlaps the one below.
      const strip = card && card.closest && card.closest(".strip, .hs");
      if (!strip) return null;
      const wrap = (strip.closest && strip.closest(".hrow")) || strip;
      const strips = [...document.querySelectorAll("#view .hrow, #view > .strip, #view > .hs")].filter((n) => {
        if (n.matches && n.matches(".strip, .hs") && n.closest && n.closest(".hrow")) return false;
        return !!(n.querySelector && n.querySelector(".card"));
      });
      const i = strips.indexOf(wrap);
      if (i < 0) return null;
      const next = strips[i + dir];
      if (!next) return null;
      const cards = [...next.querySelectorAll(".card")];
      if (!cards.length) return null;
      const idx = [...strip.querySelectorAll(".card")].indexOf(card);
      return cards[Math.min(Math.max(0, idx), cards.length - 1)] || cards[0];
    },

    layoutRows() {
      // 2.5.4: wrap each heading+strip as a fixed-pitch row on a translated track.
      if (!isHome() || playerOn() || authOpen()) return;
      const view = document.getElementById("view");
      if (!view) return;
      let track = view.querySelector(":scope > .tv-rows-track");
      if (!track) {
        const kids = [...view.children];
        if (!kids.length) return;
        track = document.createElement("div");
        track.className = "tv-rows-track";
        const groups = [];
        let cur = [];
        kids.forEach((n) => {
          if (n.classList && n.classList.contains("row-head")) {
            if (cur.length) groups.push(cur);
            cur = [n];
          } else {
            cur.push(n);
          }
        });
        if (cur.length) groups.push(cur);
        groups.forEach((g) => {
          const row = document.createElement("div");
          row.className = "tv-home-row";
          g.forEach((n) => row.appendChild(n));
          track.appendChild(row);
        });
        view.appendChild(track);
      }
      this.syncRowPitch();
      this.applyRowShift();
    },

    layoutSize() {
      // 1.9.2 still lays the TV UI out at 1920×1080 and scales it to the WebView.
      // Size typography and posters against that layout, not the 960×540 CSS viewport,
      // so a real TV matches the 1080 previews (and is not half as big).
      const root = document.documentElement;
      if (root.classList.contains("tv-scaled")) {
        const w = parseFloat(root.style.getPropertyValue("--tv-layout-w")) || 1920;
        const h = parseFloat(root.style.getPropertyValue("--tv-layout-h")) || 1080;
        return { w: w, h: h };
      }
      return {
        w: root.clientWidth || window.innerWidth || 1920,
        h: root.clientHeight || window.innerHeight || 1080,
      };
    },

    syncViewportVars() {
      const root = document.documentElement;
      const size = this.layoutSize();
      const w = size.w, h = size.h;
      root.style.setProperty("--tv-screen-w", w + "px");
      root.style.setProperty("--tv-screen-h", h + "px");
      // ~8% of the 1080 layout (about 2× the 40px title that looked small on the TV).
      const title = Math.max(80, Math.round(h * 0.08));
      root.style.setProperty("--tv-title-size", title + "px");
      const safe = Math.max(32, Math.round(w * 0.04));
      const btn = h <= 700 ? 60 : 68;
      root.style.setProperty("--tv-safe-left", safe + "px");
      root.style.setProperty("--tv-rail-btn", btn + "px");
      root.style.setProperty("--tv-rail-w", (safe + btn + 16) + "px");
    },

    syncRowPitch() {
      this.syncViewportVars();
      const view = document.getElementById("view");
      const track = view && view.querySelector(":scope > .tv-rows-track");
      if (!view || !track) return;
      const h = this.layoutSize().h;
      // Posters are ~24% of the window. Leave room in the row for the label,
      // the 13% focus scale, and a ~15% peek of the next row.
      const posterH = Math.max(84, Math.round(h * 0.24));
      const posterW = Math.max(56, Math.round(posterH * 2 / 3));
      const scalePad = Math.ceil(posterH * 0.13) + 20;
      const headH = Math.max(48, Math.round(h * 0.045));
      const pitch = headH + scalePad + posterH + 10;
      const peek = Math.round(pitch * 0.15);
      const pane = pitch + peek;
      const heroPct = Math.max(50, Math.min(62, ((h - pane) / h) * 100));
      document.documentElement.style.setProperty("--tv-hero-share", heroPct.toFixed(2) + "%");
      document.documentElement.style.setProperty("--tv-focus-pad", scalePad + "px");
      const gap = posterW >= 130 ? 18 : 12;
      track.style.setProperty("--tv-card-w", posterW + "px");
      track.style.setProperty("--tv-card-gap", gap + "px");
      document.documentElement.style.setProperty("--tv-card-w", posterW + "px");
      document.documentElement.style.setProperty("--tv-card-gap", gap + "px");
      this._rowPitch = pitch;
      track.querySelectorAll(":scope > .tv-home-row").forEach((r) => { r.style.height = pitch + "px"; });
    },

    applyRowShift() {
      const view = document.getElementById("view");
      const track = view && view.querySelector(":scope > .tv-rows-track");
      if (!track || !this._rowPitch) return;
      const idx = Math.max(0, this._rowIndex || 0);
      this._rowIndex = idx;
      track.style.transform = "translateY(" + (-idx * this._rowPitch) + "px)";
      if (this.tabsEnabled) document.documentElement.classList.toggle("tv-tabs-hidden", idx > 0);
    },

    revealRow(el) {
      // 2.5.4: move the rows track so the focused row sits in the bottom slot.
      if (!isHome() || playerOn() || authOpen()) return;
      if (document.documentElement.classList.contains("tv-plex-off")) return;
      const view = document.getElementById("view");
      if (!view) return;
      if (!view.querySelector(":scope > .tv-rows-track")) this.layoutRows();
      const track = view.querySelector(":scope > .tv-rows-track");
      if (!track) return;
      if (!this._rowPitch) this.syncRowPitch();
      const card = el && el.closest && el.closest("#view .card");
      if (card) {
        const row = card.closest(".tv-home-row");
        const rows = [...track.querySelectorAll(":scope > .tv-home-row")];
        const idx = row ? rows.indexOf(row) : 0;
        if (idx >= 0) this._rowIndex = idx;
      }
      this.applyRowShift();
      if (view.scrollTop) view.scrollTop = 0;
    },

    setTab(name, opts) {
      this.tab = name;
      document.querySelectorAll("#tv-tabs button").forEach((b) => b.classList.toggle("on", b.getAttribute("data-tab") === name));
      if (!isHome()) { location.hash = "#/home"; return; }
      this.layoutRows();
      const keepFocus = !!(opts && opts.keepFocus);
      const heads = [...document.querySelectorAll("#view .row-head")];
      let target = null;
      if (name === "added") {
        target = heads.find((h) => /recently added/i.test(h.textContent));
      } else if (name === "libraries") {
        // Libraries is a selectable tab: jump to the first library row. The slide-out
        // still opens from a second Left on the rail, not from this tab.
        target = heads.find((h) => !/continue watching|recently added/i.test(h.textContent)) || heads[1] || heads[0];
      } else {
        target = heads[0];
      }
      if (target) {
        const homeRow = target.closest && target.closest(".tv-home-row");
        if (homeRow && homeRow.parentElement) {
          const rows = [...homeRow.parentElement.querySelectorAll(":scope > .tv-home-row")];
          const idx = rows.indexOf(homeRow);
          if (idx >= 0) this._rowIndex = idx;
          this.applyRowShift();
        }
        if (!keepFocus) {
          let strip = target.nextElementSibling;
          while (strip && !(strip.classList && (strip.classList.contains("hrow") || strip.classList.contains("strip") || strip.classList.contains("hs")))) {
            strip = strip.nextElementSibling;
          }
          const card = (strip && strip.querySelector && strip.querySelector(".card"))
            || document.querySelector("#view .card");
          if (card && window.TV) TV.focus(card);
        }
      }
    },

    menuItems() {
      const root = document.getElementById("tv-menu");
      if (!root) return [];
      const acct = document.getElementById("tv-acct");
      const open = acct && acct.classList.contains("open");
      return [...root.querySelectorAll("button, a.tv-mi")].filter((n) => {
        if (!open && acct && acct.contains(n) && n.dataset.act !== "profile") return false;
        return true;
      });
    },

    openMenu(from, focusAct) {
      this.returnEl = from || document.activeElement;
      this.menuOpen = true;
      this.acctOpen = false;
      const acct = document.getElementById("tv-acct");
      if (acct) acct.classList.remove("open");
      document.documentElement.classList.add("tv-menu-open");
      const finish = (keepAct) => {
        this.drawMenu();
        document.querySelectorAll("#tv-menu [data-act='home']").forEach((n) => n.classList.toggle("on", isHome()));
        let focus = document.querySelector("#tv-menu [data-act='home']");
        const want = keepAct || focusAct;
        if (want === "lib") focus = document.querySelector("#tv-menu [data-act='lib']") || focus;
        if (want === "profile") focus = document.querySelector("#tv-menu [data-act='profile']") || focus;
        if (want && want !== "lib" && want !== "profile") {
          const named = document.querySelector("#tv-menu [data-act='" + want + "']");
          if (named) focus = named;
        }
        if (window.TV && focus) TV.focus(focus);
        else if (focus) focus.focus();
      };
      // Paint immediately so Left feels instant; refresh library rows if they were not cached.
      finish();
      if (!(this.libs && this.libs.length)) {
        const stay = focusAct;
        this.ensureItems().then(() => {
          if (!this.menuOpen) return;
          const cur = document.activeElement;
          const keep = (cur && cur.getAttribute && cur.getAttribute("data-act")) || stay;
          finish(keep);
        });
      }
    },


    cancelPreview() {
      if (this.previewTimer) {
        clearTimeout(this.previewTimer);
        this.previewTimer = 0;
      }
      this._pendingPreview = null;
    },

    flushPreview() {
      const fn = this._pendingPreview;
      this.cancelPreview();
      if (fn) fn();
    },

    armPreview(el) {
      this.cancelPreview();
      if (!el) return;
      const tab = el.closest && el.closest("#tv-tabs button[data-tab]");
      if (tab) {
        const name = tab.getAttribute("data-tab");
        this._pendingPreview = () => { if (document.activeElement === tab) this.setTab(name, { keepFocus: true }); };
        this.previewTimer = setTimeout(() => { this.flushPreview(); }, 250);
        return;
      }
      const item = el.closest && el.closest("#tv-menu button, #tv-menu a.tv-mi");
      if (!item) return;
      const act = item.getAttribute("data-act");
      if (act === "signout") return;
      if (act === "profile") {
        if (!this.acctOpen) {
          this.acctOpen = true;
          const acct = document.getElementById("tv-acct");
          if (acct) acct.classList.add("open");
        }
        return;
      }
      this._pendingPreview = () => {
        if (document.activeElement !== item && !(item.contains && item.contains(document.activeElement))) return;
        item.click();
      };
      this.previewTimer = setTimeout(() => { this.flushPreview(); }, 250);
    },

    closeMenu(silent) {
      this.cancelPreview();
      if (!this.menuOpen && !document.documentElement.classList.contains("tv-menu-open")) return;
      this.menuOpen = false;
      this.acctOpen = false;
      const acct = document.getElementById("tv-acct");
      if (acct) acct.classList.remove("open");
      document.documentElement.classList.remove("tv-menu-open");
      if (silent) return;
      let back = this.returnEl && document.contains(this.returnEl) ? this.returnEl : null;
      if (back && back.closest && back.closest("#tv-rail") && !(window.TV && TV.visible(back))) {
        back = document.querySelector("#tv-rail button[data-rail='home']") || document.querySelector("#tv-rail button");
      }
      if (!back) {
        back = document.querySelector("#tv-rail button[data-rail='home']")
          || (this.contentEl && document.contains(this.contentEl) && this.contentEl)
          || document.querySelector("#view .card");
      }
      this.returnEl = null;
      if (back && window.TV) TV.focus(back);
      else if (back) back.focus();
    },

    onMenuClick(e) {
      const b = e.target.closest("button, a.tv-mi");
      if (!b) return;
      const act = b.getAttribute("data-act");
      if (act === "profile") {
        e.preventDefault();
        this.acctOpen = !this.acctOpen;
        document.getElementById("tv-acct").classList.toggle("open", this.acctOpen);
        if (this.acctOpen) {
          const first = document.querySelector("#tv-acct button");
          if (first && window.TV) TV.focus(first);
        }
        return;
      }
      if (act === "signout") {
        e.preventDefault();
        this.closeMenu(true);
        const lo = document.getElementById("logout") || document.getElementById("acct-logout");
        if (lo) lo.click();
        return;
      }
      if (act === "account") { this.closeMenu(true); location.hash = "#/settings/account"; return; }
      if (act === "settings") { e.preventDefault(); this.closeMenu(true); location.hash = "#/settings"; return; }
      if (act === "search") { e.preventDefault(); this.closeMenu(true); location.hash = "#/search"; return; }
      if (act === "home") { e.preventDefault(); this.closeMenu(true); location.hash = "#/home"; return; }
      if (act === "lists" || act === "lib") {
        // let the href navigate, then close
        this.closeMenu(true);
      }
    },

    firstInRow(card) {
      if (!card) return false;
      const st = card.closest(".strip, .hs, .cast-strip");
      if (st) {
        const cards = [...st.querySelectorAll(".card")];
        return cards[0] === card;
      }
      const row = card.parentElement;
      const cards = row ? [...row.querySelectorAll(":scope > .card")] : [];
      return !cards.length || cards[0] === card;
    },

    isTopContentRow(card) {
      if (!card) return false;
      const st = card.closest(".strip, .hs");
      if (st && st.classList.contains("cw")) return true;
      const first = document.querySelector("#view .strip, #view .hs");
      if (st && first && st === first) return true;
      const r = card.getBoundingClientRect();
      const heads = document.querySelectorAll("#view .row-head");
      if (heads[0]) {
        const strip = heads[0].parentElement && heads[0].parentElement.querySelector(".strip, .hs");
        if (strip && strip.contains(card)) return true;
      }
      // No other card sits clearly above this one (first visible row, including under the hero).
      const cards = document.querySelectorAll("#view .card");
      for (let i = 0; i < cards.length && i < 24; i++) {
        const c = cards[i];
        if (c === card) continue;
        const b = c.getBoundingClientRect();
        if (b.height >= 2 && b.bottom < r.top - 20) return false;
      }
      return true;
    },

    rememberContent(el) {
      if (el && el.classList && el.classList.contains("card") && el.closest && el.closest("#view")) {
        this.contentEl = el;
      }
    },

    railButtons() {
      return [...document.querySelectorAll("#tv-rail button")];
    },

    currentRailButton() {
      if (this.tab === "libraries") {
        return document.querySelector("#tv-rail button[aria-label='Libraries']")
          || document.querySelector("#tv-rail button[data-rail='menu']:not(.tv-rail-av)");
      }
      return document.querySelector("#tv-rail button[data-rail='home']") || this.railButtons()[2] || this.railButtons()[0];
    },

    focusRail(preferred) {
      const el = preferred || this.currentRailButton();
      if (!el) return null;
      if (window.TV) TV.focus(el);
      else el.focus();
      return el;
    },

    isTvChrome(el) {
      if (!el || !el.closest) return false;
      if (this.menuOpen) return !!el.closest("#tv-menu");
      if (el.closest("#tv-tabs") || el.closest("#tv-rail") || el.closest("#tv-menu")) return true;
      if (el.classList && el.classList.contains("card") && el.closest("#view")) return true;
      if (el.closest("#view") && el.matches && el.matches("button, a, [tabindex], .btn, .lib-li, .card")) return true;
      return false;
    },

    ensureFocus() {
      const cur = document.activeElement;
      if (this.isTvChrome(cur)) return cur;
      let fallback = null;
      if (this.menuOpen) fallback = (this.menuItems() || [])[0];
      if (!fallback && this.contentEl && document.contains(this.contentEl) && this.isTvChrome(this.contentEl)) {
        fallback = this.contentEl;
      }
      if (!fallback) {
        fallback = document.querySelector("#view .card")
          || document.querySelector("#tv-tabs button.on")
          || document.querySelector("#tv-rail button[data-rail='home']");
      }
      if (fallback) {
        if (window.TV) TV.focus(fallback);
        else fallback.focus();
      }
      return fallback;
    },

    onKey(e) {
      if (!(window.TV && TV.on)) return false;
      if (TV.typing && TV.typing(e)) return false;
      const key = e.key;
      if (playerOn()) return false;

      if (this.menuOpen) {
        if (key === "ArrowRight" || key === "Escape" || key === "Backspace" || key === "BrowserBack") {
          e.preventDefault(); e.stopPropagation();
          this.closeMenu();
          return true;
        }
        if (key === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); return true; }
        if (key === "ArrowUp" || key === "ArrowDown") {
          const items = this.menuItems();
          const cur = document.activeElement;
          const i = items.indexOf(cur);
          const n = key === "ArrowDown" ? items[Math.min(items.length - 1, i + 1)] : items[Math.max(0, i - 1)];
          if (n && window.TV) { e.preventDefault(); e.stopPropagation(); TV.focus(n); this.armPreview(n); }
          return true;
        }
        if (key === "Enter" || key === " " || key === "NumpadEnter") {
          const cur = document.activeElement;
          if (cur && (cur.closest && cur.closest("#tv-menu"))) {
            e.preventDefault(); e.stopPropagation();
            this.cancelPreview();
            cur.click();
            return true;
          }
        }
        return false;
      }

      if (!isHome()) {
        // Back still handled by core TV on details/player
        return false;
      }

      let cur = document.activeElement;
      if (!this.isTvChrome(cur)) cur = this.ensureFocus() || document.activeElement;
      const onCard = cur && cur.classList && cur.classList.contains("card");
      const onTab = cur && cur.closest && cur.closest("#tv-tabs");
      const onRail = cur && cur.closest && cur.closest("#tv-rail");
      if (onCard) this.rememberContent(cur);

      // Left on the first poster focuses the slim rail; the slide-out stays closed.
      if (key === "ArrowLeft" && onCard && this.firstInRow(cur)) {
        e.preventDefault(); e.stopPropagation();
        this.focusRail();
        return true;
      }
      // Left on the rail opens the slide-out. Mid-row Left is left to TV.move.
      if (key === "ArrowLeft" && onRail) {
        e.preventDefault(); e.stopPropagation();
        this.openMenu(cur);
        return true;
      }
      if (key === "ArrowRight" && onRail) {
        e.preventDefault(); e.stopPropagation();
        const back = (this.contentEl && document.contains(this.contentEl))
          ? this.contentEl : document.querySelector("#view .card");
        if (back && window.TV) TV.focus(back);
        else if (back) back.focus();
        return true;
      }
      if ((key === "ArrowUp" || key === "ArrowDown") && onRail) {
        e.preventDefault(); e.stopPropagation();
        const items = this.railButtons();
        const i = items.indexOf(cur);
        const n = key === "ArrowDown" ? items[Math.min(items.length - 1, Math.max(0, i) + 1)]
                                      : items[Math.max(0, i - 1)];
        if (n && n !== cur) this.focusRail(n);
        return true;
      }
      if ((key === "Enter" || key === " " || key === "NumpadEnter") && onRail) {
        e.preventDefault(); e.stopPropagation();
        this.cancelPreview();
        cur.click();
        return true;
      }
      // Left from the first tab goes to the rail; later tabs move Left/Right among themselves.
      if (key === "ArrowLeft" && onTab) {
        e.preventDefault(); e.stopPropagation();
        const tabs = [...document.querySelectorAll("#tv-tabs button")];
        const i = tabs.indexOf(cur);
        if (i <= 0) this.focusRail();
        else {
          if (window.TV) TV.focus(tabs[i - 1]);
          else tabs[i - 1].focus();
          this.armPreview(tabs[i - 1]);
        }
        return true;
      }
      if (key === "ArrowUp" && onTab) {
        e.preventDefault(); e.stopPropagation();
        return true;
      }
      if (key === "ArrowUp" && onCard && this.isTopContentRow(cur)) {
        if (!this.tabsEnabled || document.documentElement.classList.contains("tv-tabs-off")) {
          e.preventDefault(); e.stopPropagation();
          return true;
        }
        e.preventDefault(); e.stopPropagation();
        const tab = document.querySelector("#tv-tabs button.on") || document.querySelector("#tv-tabs button");
        if (tab) {
          if (window.TV) TV.focus(tab);
          else tab.focus();
          this.armPreview(tab);
        }
        return true;
      }
      if ((key === "ArrowDown" || key === "ArrowUp") && onCard && isHome() && !playerOn()
          && !document.documentElement.classList.contains("tv-plex-off")) {
        const n = this.rowStep(cur, key === "ArrowDown" ? 1 : -1);
        if (n) {
          e.preventDefault(); e.stopPropagation();
          if (window.TV) TV.focus(n);
          else n.focus();
          return true;
        }
      }
      if (key === "ArrowDown" && onTab) {
        e.preventDefault(); e.stopPropagation();
        this.flushPreview();
        const card = (this.contentEl && document.contains(this.contentEl) && this.contentEl)
          || document.querySelector("#view .strip.cw .card, #view .card");
        if (card && window.TV) TV.focus(card);
        else if (card) card.focus();
        return true;
      }
      if (key === "ArrowRight" && onTab) {
        const tabs = [...document.querySelectorAll("#tv-tabs button")];
        const i = tabs.indexOf(cur);
        const n = tabs[Math.min(tabs.length - 1, i + 1)];
        if (n && n !== cur) {
          e.preventDefault(); e.stopPropagation();
          if (window.TV) TV.focus(n);
          this.armPreview(n);
        } else {
          e.preventDefault(); e.stopPropagation();
        }
        return true;
      }
      if ((key === "Enter" || key === " ") && onTab) {
        e.preventDefault(); e.stopPropagation();
        this.cancelPreview();
        cur.click();
        return true;
      }
      return false;
    }
  };

  window.TVPlex = TVPlex;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(() => TVPlex.init(), 0));
  } else {
    setTimeout(() => TVPlex.init(), 0);
  }
})();
