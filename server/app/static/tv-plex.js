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
  function libIcon(kind) {
    return kind === "tv" ? ico.tv : kind === "music" ? ico.music : ico.film;
  }

  const TVPlex = {
    items: {},
    tab: "foryou",
    menuOpen: false,
    acctOpen: false,
    returnEl: null,
    clockTimer: 0,
    heroId: "",

    init() {
      if (!(window.TV && TV.on)) {
        setTimeout(() => this.init(), 400);
        return;
      }
      if (this._inited) return;
      this._inited = true;
      document.documentElement.classList.add("tv-plex");
      this.inject();
      this.hook();
      this.tickClock();
      this.clockTimer = setInterval(() => this.tickClock(), 15000);
      this.syncPage();
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
        if (card) self.showHero(card);
      });
      const after = TV.afterRoute.bind(TV);
      TV.afterRoute = function () {
        after();
        self.syncPage();
      };
      const onKey = TV.onKey.bind(TV);
      TV.onKey = function (e) {
        if (self.onKey(e)) return;
        onKey(e);
      };
      const candidates = TV.candidates.bind(TV);
      TV.candidates = function () {
        if (self.menuOpen) return self.menuItems();
        const base = candidates();
        if (isHome() && !playerOn()) {
          const extra = [];
          document.querySelectorAll("#tv-tabs button, #tv-rail button").forEach((n) => extra.push(n));
          return extra.concat(base.filter((el) => !(el.closest && el.closest(".side, .top, .tabbar"))));
        }
        return base;
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
      const id = card && (card.dataset.id || (card.dataset.href || "").split("/").pop());
      if (id && !this.items[String(id)]) {
        this.ensureItems().then(() => this.paintHero(card, id));
        return;
      }
      this.paintHero(card, id);
    },

    paintHero(card, id) {
      const it = this.items[String(id)] || {};
      const title = it.title || (card.querySelector(".t") && card.querySelector(".t").textContent) || "";
      const hero = document.getElementById("tv-hero");
      if (!hero) return;
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
    },

    setTab(name) {
      this.tab = name;
      document.querySelectorAll("#tv-tabs button").forEach((b) => b.classList.toggle("on", b.getAttribute("data-tab") === name));
      if (!isHome()) { location.hash = "#/home"; return; }
      const heads = [...document.querySelectorAll("#view .row-head")];
      let target = null;
      if (name === "added") {
        target = heads.find((h) => /recently added/i.test(h.textContent));
      } else if (name === "libraries") {
        this.openMenu(null, "lib");
        return;
      } else {
        target = heads[0];
      }
      if (target) {
        const row = target.parentElement;
        const card = (row && row.querySelector(".card")) || document.querySelector("#view .card");
        if (card && window.TV) TV.focus(card);
        target.scrollIntoView({ block: "center", behavior: "smooth" });
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
      const finish = () => {
        this.drawMenu();
        document.querySelectorAll("#tv-menu [data-act='home']").forEach((n) => n.classList.toggle("on", isHome()));
        let focus = document.querySelector("#tv-menu [data-act='home']");
        if (focusAct === "lib") focus = document.querySelector("#tv-menu [data-act='lib']") || focus;
        if (focusAct === "profile") focus = document.querySelector("#tv-menu [data-act='profile']") || focus;
        if (window.TV && focus) TV.focus(focus);
        else if (focus) focus.focus();
      };
      if (this.libs && this.libs.length) finish();
      else this.ensureItems().then(finish);
    },

    closeMenu(silent) {
      if (!this.menuOpen && !document.documentElement.classList.contains("tv-menu-open")) return;
      this.menuOpen = false;
      this.acctOpen = false;
      const acct = document.getElementById("tv-acct");
      if (acct) acct.classList.remove("open");
      document.documentElement.classList.remove("tv-menu-open");
      if (silent) return;
      const back = this.returnEl && document.contains(this.returnEl) ? this.returnEl
        : document.querySelector("#view .card");
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
      const st = card.closest(".strip");
      if (!st) return true;
      const cards = [...st.querySelectorAll(".card")];
      return cards[0] === card;
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
          if (n && window.TV) { e.preventDefault(); e.stopPropagation(); TV.focus(n); }
          return true;
        }
        if (key === "Enter" || key === " " || key === "NumpadEnter") {
          const cur = document.activeElement;
          if (cur && (cur.closest && cur.closest("#tv-menu"))) {
            e.preventDefault(); e.stopPropagation();
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

      const cur = document.activeElement;
      const onCard = cur && cur.classList && cur.classList.contains("card");
      const onTab = cur && cur.closest && cur.closest("#tv-tabs");
      const onRail = cur && cur.closest && cur.closest("#tv-rail");

      if ((key === "ArrowLeft" && onCard && this.firstInRow(cur)) ||
          (key === "ArrowLeft" && onTab && cur === document.querySelector("#tv-tabs button")) ||
          (key === "ArrowLeft" && onRail)) {
        e.preventDefault(); e.stopPropagation();
        this.openMenu(cur);
        return true;
      }
      if (key === "ArrowUp" && onCard) {
        const st = cur.closest(".strip");
        const firstStrip = document.querySelector("#view .strip");
        if (st && firstStrip && (st === firstStrip || st.classList.contains("cw"))) {
          e.preventDefault(); e.stopPropagation();
          const tab = document.querySelector("#tv-tabs button.on") || document.querySelector("#tv-tabs button");
          if (tab && window.TV) TV.focus(tab);
          return true;
        }
      }
      if (key === "ArrowDown" && onTab) {
        e.preventDefault(); e.stopPropagation();
        const card = document.querySelector("#view .strip.cw .card, #view .card");
        if (card && window.TV) TV.focus(card);
        return true;
      }
      if ((key === "ArrowLeft" || key === "ArrowRight") && onTab) {
        const tabs = [...document.querySelectorAll("#tv-tabs button")];
        const i = tabs.indexOf(cur);
        const n = key === "ArrowRight" ? tabs[Math.min(tabs.length - 1, i + 1)] : tabs[Math.max(0, i - 1)];
        if (n && n !== cur) {
          e.preventDefault(); e.stopPropagation();
          if (window.TV) TV.focus(n);
        }
        return true;
      }
      if ((key === "Enter" || key === " ") && onTab) {
        e.preventDefault(); e.stopPropagation();
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
