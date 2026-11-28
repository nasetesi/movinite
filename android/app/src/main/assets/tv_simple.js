/* 2.4.6: Android TV only — four rail entries (Home, Search, Libraries, Settings)
   and a native Settings screen. Does not run on phones. */
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
    "html.tv-plex a[href^='#/settings/'] { display: none !important; }"
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

  function simplifyMenu() {
    var menu = document.getElementById("tv-menu");
    if (!menu) return;
    // Libraries slide-out: keep only library rows (needed to open a library).
    Array.prototype.slice.call(menu.children).forEach(function (el) {
      var act = el.getAttribute && el.getAttribute("data-act");
      if (act === "lib" || (el.classList && el.classList.contains("tv-div"))) return;
      el.remove();
    });
  }

  function onRailClick(e) {
    var b = e.target && e.target.closest && e.target.closest("#tv-rail button[data-rail]");
    if (!b) return;
    var act = b.getAttribute("data-rail");
    if (act === "settings") {
      e.preventDefault(); e.stopPropagation();
      if (window.TVPlex && TVPlex.closeMenu) try { TVPlex.closeMenu(true); } catch (err) {}
      openNativeSettings();
      return;
    }
    if (act === "libraries") {
      e.preventDefault(); e.stopPropagation();
      if (window.TVPlex && TVPlex.closeMenu) try { TVPlex.closeMenu(true); } catch (err) {}
      location.hash = "#/libraries";
    }
  }

  function onHash() {
    var h = location.hash || "";
    if (h.indexOf("#/settings") === 0) {
      openNativeSettings();
      location.hash = "#/home";
      return;
    }
    if (/^#\/(downloads|activity|mylist|status|invites)(\/|$)/.test(h)) {
      location.hash = "#/home";
    }
  }

  document.addEventListener("click", onRailClick, true);
  window.addEventListener("hashchange", onHash);
  hideExtraRail();
  onHash();

  var mo = new MutationObserver(function () {
    hideExtraRail();
    simplifyMenu();
  });
  mo.observe(document.documentElement, { childList: true, subtree: true });

  // If TVPlex is already running, tidy the menu it just drew.
  if (window.TVPlex && TVPlex.drawMenu) {
    var orig = TVPlex.drawMenu.bind(TVPlex);
    TVPlex.drawMenu = function () {
      orig();
      simplifyMenu();
    };
    try { simplifyMenu(); } catch (e) {}
  }
})();
