"""1.5.1: phone layout like the Plex app -- bottom tab bar, slim top bar with avatar/account menu, Plex-style rows,
the Libraries / Search / My List tabs and /api/mylist.  Static checks (+ live API checks when a test server runs)."""
import json, os, re, sys, urllib.request, http.cookiejar
HERE = os.path.dirname(os.path.abspath(__file__)); APP = os.path.join(HERE, "..", "app")
js = open(os.path.join(APP, "static", "app.js")).read(); css = open(os.path.join(APP, "static", "style.css")).read()
html = open(os.path.join(APP, "static", "index.html")).read(); srv = open(os.path.join(APP, "server.py")).read()
ver = open(os.path.join(APP, "version.py")).read()
fails = []
def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok: fails.append(msg)
m151 = css[css.index("1.5.1: phone layout"):]
check(tuple(int(x) for x in re.search(r'"([0-9.]+)"', ver).group(1).split(".")) >= (1, 5, 1), "version (1, 5, 1) or later (numeric; 1.6 > 1.5.5)")
check('viewport-fit=cover' in html, "viewport-fit=cover so the safe-area insets work")
# tab bar
tb = html[html.index('id="tabbar"'):html.index('</nav>', html.index('id="tabbar"'))]
tabs = re.findall(r'data-tab="([a-z]+)"', tb)
check(tabs == ["home", "libraries", "search", "mylist", "settings"], "tab bar: Home, Libraries, Search, My List, Settings (%s)" % tabs)
check(all(l in tb for l in [">Home<", ">Libraries<", ">Search<", ">My List<"]) and tb.count("<svg") == 5, "each tab has an icon and a label")
check('href="#/libraries"' in tb and 'href="#/mylist"' in tb and 'href="#/search"' in tb, "tabs link to the new pages")
check(".tabbar,.m-ico,.acct-w,.m-qw,.row-sub,.rh-a .chev,.m-only{display:none}" in m151, "phone-only parts hidden on wide screens (desktop unchanged)")
mq = m151[m151.index("@media (max-width:820px)"):]
check(re.search(r"\.tabbar\{display:grid;grid-template-columns:repeat\(5,1fr\);position:fixed;[^}]*bottom:0", mq) is not None, "tab bar fixed at the bottom on phones")
h = re.search(r"\.tabbar\{[^}]*height:calc\((\d+)px \+ env\(safe-area-inset-bottom\)\)", mq)
check(h is not None and 56 <= int(h.group(1)) <= 64, "tab bar 56-64 px + safe-area inset (%s)" % (h and h.group(1)))
check(".tabbar a.on{color:var(--acc-text)}" in mq, "active tab in Movinite purple")
check("html.pl-open .tabbar{display:none}" in mq and 'classList.add("pl-open")' in js and 'classList.remove("pl-open")' in js, "tab bar hidden while the player is open")
check("html.pl-open:has(#player.pip-min) .tabbar{display:grid}" in mq, "tab bar back while the player is minimised (PiP)")
check(".audiobar{bottom:calc(62px" in mq and ".pip-chip{bottom:calc(" in mq and ".toast{bottom:calc(" in mq, "audio bar, PiP chip and toasts sit above the tab bar")
check("#view{padding:8px 14px calc(92px + env(safe-area-inset-bottom))}" in mq, "page leaves room for the tab bar")
# top bar
check('id="m-search"' in html and '$("#m-search").onclick' in js, "top bar search icon opens the Search tab")
check("#menubtn" in mq and ".top #search" in mq and ".top .snd-btn" in mq and "display:none!important" in mq, "menu button, search field and speaker hidden on phones")
check('id="m-avatar"' in html and 'aria-haspopup="menu"' in html and 'role="menu"' in html, "avatar button with an account menu")
check(all(i in html for i in ['id="acct-account"', 'id="acct-settings"', 'id="acct-logout"', 'id="acct-sound"']) and ">My account<" in html and ">Sign out<" in html, "account menu: My account, Settings, Sign out (+ sounds)")
check('charAt(0).toUpperCase()' in js and 'av.textContent = ini' in js, "avatar shows the user's initial")
check('$("#logout").click()' in js and "SFX.toggle(); SFX.drawToggle(); sound();" in js, "sign out and sound toggle reuse the existing handlers")
check('e.key === "Escape"' in js[js.index("const MOB"):] and '!e.target.closest(".acct-w")' in js and 'addEventListener("hashchange", () => open(false))' in js, "account menu closes on Esc, outside tap and navigation")
check('ME.is_admin ? "Settings" : "Account"' in js, "non-admins get an Account tab")
# routes / pages
check('case "libraries": setActive(""); await viewLibraries();' in js and 'case "mylist": setActive(""); await viewMyList();' in js, "new routes #/libraries and #/mylist")
check('api("/api/mylist")' in js and "Continue watching" in js[js.index("async function viewMyList"):], "My List shows continue watching + watched")
check('@app.get("/api/mylist")' in srv and "p.watched=1" in srv[srv.index('@app.get("/api/mylist")'):] and "def _continue(u)" in srv and "cont = _continue(u)" in srv, "/api/mylist endpoint (shares the continue query with /api/home)")
check(srv.index('@app.get("/api/mylist")') < srv.index('@app.get("/api/search")'), "mylist route registered")
vs = js[js.index("async function viewSearch"):js.index("async function viewLibraries")]
check('id="m-q"' in vs and 'id="s-res"' in vs and "out.innerHTML = html" in vs, "Search tab: own search box, results render below it (keeps focus)")
check("if (!q) {" in vs and vs.index("if (!q) {") < vs.index('api("/api/search'), "empty search does not call the API")
check("for (const l of" in js or "LIBS.map(l =>" in js[js.index("async function viewLibraries"):], "Libraries tab lists every library")
check("/collections" in js[js.index("async function viewLibraries"):js.index("async function viewMyList")], "Libraries tab links categories / collections")
mt = js[js.index("function tabFor"):js.index("function tab()")]
check('"library"' in mt and '"show"' in mt and '"album"' in mt and 'return "libraries"' in mt, "library pages light the Libraries tab")
# rows
rh = js[js.index("function rowHead"):]
check('class="rh-a"' in rh and 'class="chev"' in rh and 'class="row-sub"' in rh and "see-all" in rh, "row header: title link with >, library underneath")
check(js.count("rowHead(") >= 6, "home rows use the new header (%d)" % js.count("rowHead("))
check(".rh-a{color:inherit;text-decoration:none;pointer-events:none}" in m151, "desktop row titles stay plain text")
check(re.search(r"\.row-head h3[^{]*\{font-size:2[0-2]px;font-weight:800", mq) is not None, "bold 20-22 px row titles on phones")
check(".see-all{display:none}" in mq and ".row-sub{display:block;color:var(--muted)" in mq, "phones: 'See all' replaced by the > and a gray subtitle")
check("grid-auto-columns:min(calc((100vw - 52px) / 2.3),190px)" in mq, "about 2.3 posters per row on phones")
check(".card .art{border-radius:8px}" in mq, "8 px rounded posters")
check("height:4px;border-radius:3px" in mq and ".card .art .badge:not(.rv){" in mq, "thin rounded progress bar and watched check")
check('<span class="m-only">' in js and '<span class="d-only">' in js, "resume cards: year on phones, minutes left on desktop")
# arrows
check("@media (max-width:599px){ .hnav{display:none!important} }" in css, "< > arrows hidden on phones under 600 px")
check(".hnav{width:34px;height:34px" in mq, "small, subtle arrows on tablets (600-820 px)")
check("safe-area-inset-top" in mq, "top bar respects the notch")
# Android app 1.5: native sign-in like the web page (if this copy ships the source)
A = os.environ.get("ANDROID_SRC", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "android"))
if os.path.isdir(A):
    R = os.path.join(A, "app", "src", "main", "res"); rd = lambda *p: open(os.path.join(*p)).read()
    g = rd(A, "app", "build.gradle"); lay = rd(R, "layout", "activity_login.xml"); la = rd(A, "app", "src", "main", "java", "org", "movinite", "app", "LoginActivity.java")
    ma = rd(A, "app", "src", "main", "java", "org", "movinite", "app", "MainActivity.java")
    check(re.search(r"versionCode (\d+)", g) and int(re.search(r"versionCode (\d+)", g).group(1)) >= 6 and 'VERSION = "%s"' % re.search(r"versionName '([^']+)'", g).group(1) in rd(A, "app", "src", "main", "java", "org", "movinite", "app", "BuildConfigInfo.java"), "app 1.5+ (code 6+), versions in step")
    check('android:src="@drawable/logo_full"' in lay and os.path.exists(os.path.join(R, "drawable-nodpi", "logo_full.png")) and 'android:maxWidth="300dp"' in lay, "app sign-in: the full logo with MOVINITE, 300 dp like the web")
    from PIL import Image
    check(Image.open(os.path.join(R, "drawable-nodpi", "logo_full.png")).width >= 1000, "app sign-in logo sharp at 3.5x")
    check('android:text="@string/app_name" android:textColor="@color/text" android:textSize="26sp"' not in lay, "no separate 'Movinite' text under the logo (the wordmark is in the logo)")
    check(lay.index('@+id/logo') > lay.index('@+id/card') and lay.index('@+id/subtitle') > lay.index('@+id/logo') and lay.index('@+id/username') > lay.index('@+id/subtitle'), "logo + 'Sign in to continue' inside the card, above the fields (web order)")
    bg = rd(R, "drawable", "login_bg.xml"); card = rd(R, "drawable", "auth_card.xml"); inp = rd(R, "drawable", "auth_input.xml"); btn = rd(R, "drawable", "auth_btn.xml")
    check("#07050C" in bg and 'android:type="radial"' in bg and 'android:centerY="0.18"' in bg, "app: web backdrop (purple glow at 18% on #07050c)")
    check("#D1120E1A" in card and "#389637FA" in card and "14dp" in card, "app: web card (rgba(18,14,26,.82), purple border, 14 corners)")
    check('state_focused="true"' in inp and "@color/acc" in inp and "8dp" in inp, "app: fields get a purple border when focused, 8 corners")
    check("@color/acc_fill" in btn and "8dp" in btn and '@drawable/auth_btn' in lay, "app: full-width #8424EA Sign in button")
    check("@+id/gear" in lay and "openSettings()" in la and "setOnLongClickListener" in la, "app: gear (Server settings) kept")
    check("Math.round(380 * dp)" in la, "app: card at most 380 dp wide (tablets / landscape), like the web")
    check("acct-menu" in ma and "m-avatar" in ma, "app: Back closes the phone account menu")
    check("SCREEN_ORIENTATION_FULL_SENSOR" in ma and "enterPictureInPictureMode" in ma, "app: rotation + PiP untouched")
# live API (optional)
B = os.environ.get("MS_URL", "http://127.0.0.1:8150")
try:
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(urllib.request.Request(B + "/api/login", json.dumps({"username": "admin", "password": "TestPass14!"}).encode(), {"Content-Type": "application/json"}), timeout=5)
    d = json.load(op.open(B + "/api/mylist", timeout=5))
    check(isinstance(d.get("continue"), list) and isinstance(d.get("watched"), list), "live: /api/mylist returns continue + watched (%d/%d)" % (len(d["continue"]), len(d["watched"])))
    check(all(i.get("media_type", "video") == "video" for i in d["watched"]) and all("progress" in i or "position" in i or "watched" in i for i in d["watched"]), "live: watched items carry progress")
    hm = json.load(op.open(B + "/api/home", timeout=5))
    check([i["id"] for i in hm["continue"]] == [i["id"] for i in d["continue"]], "live: same continue list as the home page")
    try: urllib.request.urlopen(B + "/api/mylist", timeout=5); check(False, "live: /api/mylist needs sign-in")
    except urllib.error.HTTPError as e: check(e.code == 401, "live: /api/mylist needs sign-in (%d)" % e.code)
except (urllib.error.URLError, ConnectionError, OSError) as e:
    print("skip live checks (%s)" % e)
print("\nmobile151: %d failure(s)" % len(fails)); sys.exit(1 if fails else 0)
