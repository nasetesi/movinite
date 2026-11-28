/* 2.4.8: Android TV only — four rail entries, native Settings and Libraries,
   no slide-out menu, details title wrap, and a dismissable play-error banner.
   Does not run on phones. */
(function () {
  if (window.__msTvSimple) return;
  window.__msTvSimple = 1;
  try {
    if (!(window.MSAndroid && MSAndroid.isTv && MSAndroid.isTv())) return;
  } catch (e) { return; }

  var style = document.createElement("style");
  style.setAttribute("data-ms-tv-simple", "1");
  style.textContent = [
    "html.tv-plex #tv-rail button[data-rail='lists'],",
    "html.tv-plex #tv-rail button[data-rail='profile'],",
    "html.tv-plex #tv-rail #tv-rail-av,",
    "html.tv-plex #tv-tabs,",
    "html.tv-plex .side,",
    "html.tv-plex .tabbar,",
    "html.tv-plex .top:not(#tv-top),",
    "html.tv-plex #activity,",
    "html.tv-plex a[href='#/downloads'],",
    "html.tv-plex a[href='#/mylist'],",
    "html.tv-plex a[href='#/activity'],",
    "html.tv-plex a[href='#/settings'],",
    "html.tv-plex a[href^='#/settings/'] { display: none !important; }",
    /* Slide-out drawer is disabled on TV. */
    "html.tv-plex #tv-menu,",
    "html.tv-plex #tv-dim,",
    "html.tv-plex.tv-menu-open #tv-menu,",
    "html.tv-plex.tv-menu-open #tv-dim { display: none !important; visibility: hidden !important; pointer-events: none !important; }",
    /* Details title: show up to 2 full lines; don't clip the start of a long name. */
    "html.tv-mode.tv-plex.tv-plex-off .detail h1 {",
    "  max-width: none !important;",
    "  width: 100% !important;",
    "  white-space: normal !important;",
    "  overflow: hidden !important;",
    "  display: -webkit-box !important;",
    "  -webkit-box-orient: vertical !important;",
    "  -webkit-line-clamp: 2 !important;",
    "  word-break: break-word !important;",
    "  overflow-wrap: break-word !important;",
    "  line-height: 1.15 !important;",
    "  font-size: clamp(28px, 4.6vw, var(--tv-title-size, 48px)) !important;",
    "}",
    "html.tv-mode.tv-plex.tv-plex-off .detail .info { overflow: visible !important; }",
    /* Default toast must not cover the synopsis; errors use the banner below. */
    "html.tv-mode .toast { bottom: auto !important; top: 24px !important; left: auto !important; right: 48px !important; transform: none !important; max-width: 36vw; }",
    "#ms-tv-err {",
    "  display: flex; align-items: center; gap: 16px;",
    "  margin: 12px 0 8px; padding: 14px 18px;",
    "  background: #1F232C; border: 1px solid #E5534B; border-radius: 12px;",
    "  color: #ffb4ae; font-size: 18px; line-height: 1.35; max-width: 900px;",
    "}",
    "#ms-tv-err[hidden] { display: none !important; }",
    "#ms-tv-err .ms-tv-err-msg { flex: 1 1 auto; min-width: 0; }",
    "#ms-tv-err .ms-tv-err-x {",
    "  flex: none; min-height: 48px; padding: 8px 16px; border-radius: 10px;",
    "  border: 3px solid transparent; background: transparent; color: #fff;",
    "  font-size: 16px; font-weight: 700; cursor: pointer;",
    "}",
    "#ms-tv-err .ms-tv-err-x:focus, #ms-tv-err .ms-tv-err-x:focus-visible {",
    "  outline: none; border-color: #fff; background: #8424EA;",
    "}"
  ].join("");
  (document.head || document.documentElement).appendChild(style);

  function hideExtraRail() {
    var rail = document.getElementById("tv-rail");
    if (!rail) return;
    rail.querySelectorAll("button[data-rail='lists'], button[data-rail='profile'], #tv-rail-av").forEach(function (b) {
      b.remove();
    });
  }

  function openNativeSettings() {
    try { if (window.MSAndroid && MSAndroid.openTvSettings) MSAndroid.openTvSettings(); } catch (e) {}
  }
  function openNativeLibraries() {
    try { if (window.MSAndroid && MSAndroid.openTvLibraries) MSAndroid.openTvLibraries(); } catch (e) {}
  }

  function closeSlideOut() {
    try {
      if (window.TVPlex && TVPlex.closeMenu) TVPlex.closeMenu(true);
    } catch (e) {}
    document.documentElement.classList.remove("tv-menu-open");
  }

  function disableSlideOut() {
    closeSlideOut();
    if (window.TVPlex) {
      TVPlex.openMenu = function () { closeSlideOut(); };
    }
    var menu = document.getElementById("tv-menu");
    if (menu) { menu.hidden = true; menu.setAttribute("aria-hidden", "true"); }
  }

  function onRailClick(e) {
    var b = e.target && e.target.closest && e.target.closest("#tv-rail button[data-rail]");
    if (!b) return;
    var act = b.getAttribute("data-rail");
    if (act === "settings") {
      e.preventDefault(); e.stopPropagation();
      closeSlideOut();
      openNativeSettings();
      return;
    }
    if (act === "libraries") {
      e.preventDefault(); e.stopPropagation();
      closeSlideOut();
      openNativeLibraries();
      return;
    }
    if (act === "lists" || act === "profile" || act === "menu") {
      e.preventDefault(); e.stopPropagation();
      closeSlideOut();
    }
  }

  function onHash() {
    var h = location.hash || "";
    if (h.indexOf("#/settings") === 0) {
      openNativeSettings();
      location.hash = "#/home";
      return;
    }
    if (h === "#/libraries" || h.indexOf("#/libraries/") === 0) {
      openNativeLibraries();
      location.hash = "#/home";
      return;
    }
    if (/^#\/(downloads|activity|mylist|status|invites)(\/|$)/.test(h)) {
      location.hash = "#/home";
    }
  }

  /* Back from Search (and any stray Libraries hash) goes to Home.
     Back from Home is left to the app so it can exit. */
  window.__msTvBack = function () {
    try {
      closeSlideOut();
      var h = location.hash || "";
      if (h.indexOf("#/search") === 0 || h.indexOf("#/libraries") === 0) {
        location.hash = "#/home";
        return true;
      }
    } catch (e) {}
    return false;
  };

  function hideBanner() {
    var b = document.getElementById("ms-tv-err");
    if (b) b.hidden = true;
  }

  function showErrorBanner(msg) {
    var actions = document.querySelector(".detail .actions, .detail .main-actions");
    if (!actions) return false;
    var box = document.getElementById("ms-tv-err");
    if (!box) {
      box = document.createElement("div");
      box.id = "ms-tv-err";
      box.setAttribute("role", "alert");
      box.innerHTML = '<div class="ms-tv-err-msg"></div><button type="button" class="ms-tv-err-x">Dismiss</button>';
      box.querySelector(".ms-tv-err-x").addEventListener("click", function (ev) {
        ev.preventDefault();
        hideBanner();
      });
    }
    box.querySelector(".ms-tv-err-msg").textContent = msg || "Playback failed.";
    box.hidden = false;
    if (box.parentNode !== actions.parentNode || box.previousElementSibling !== actions) {
      actions.parentNode.insertBefore(box, actions.nextSibling);
    }
    var toast = document.getElementById("toast");
    if (toast) toast.classList.add("hidden");
    return true;
  }

  function hookToast() {
    if (typeof window.toast !== "function" || window.toast.__msTv) return;
    var orig = window.toast;
    var wrapped = function (msg, bad) {
      if (bad && document.querySelector(".detail .actions, .detail .main-actions")) {
        if (showErrorBanner(msg)) return;
      }
      return orig(msg, bad);
    };
    wrapped.__msTv = 1;
    wrapped._t = orig._t;
    window.toast = wrapped;
  }

  document.addEventListener("click", onRailClick, true);
  document.addEventListener("keydown", function (e) {
    var key = e.key || "";
    /* Do not use keyCode 82 here — that is the letter R in the DOM, not
       Android KEYCODE_MENU (swallowed in MainActivity.dispatchKeyEvent). */
    if (key === "ContextMenu" || key === "Menu" || key === "Help") {
      closeSlideOut();
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    if (key === "ArrowLeft") {
      var cur = document.activeElement;
      if (cur && cur.closest && cur.closest("#tv-rail")) {
        closeSlideOut();
        e.preventDefault();
        e.stopPropagation();
      }
    }
  }, true);
  window.addEventListener("hashchange", onHash);
  hideExtraRail();
  disableSlideOut();
  hookToast();
  onHash();

  var mo = new MutationObserver(function () {
    hideExtraRail();
    disableSlideOut();
    hookToast();
    if (!document.querySelector(".detail")) hideBanner();
  });
  mo.observe(document.documentElement, { childList: true, subtree: true });

  if (window.TVPlex) {
    disableSlideOut();
    if (TVPlex.drawMenu) {
      var origDraw = TVPlex.drawMenu.bind(TVPlex);
      TVPlex.drawMenu = function () { origDraw(); disableSlideOut(); };
    }
  }
})();
