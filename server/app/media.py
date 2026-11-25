"""Filename parsing, ffprobe and thumbnail generation."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from . import config

VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts", ".m2ts", ".mts",
             ".mpg", ".mpeg", ".vob", ".3gp", ".ogv", ".divx", ".asf"}
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".wma", ".alac", ".aiff",
             ".aif", ".ape", ".wv", ".mka"}
SUB_EXT = {".srt", ".vtt", ".ass", ".ssa"}
IMAGE_NAMES_POSTER = ("poster", "folder", "cover", "movie", "default")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
SKIP_DIRS = {"@eadir", ".appledouble", "#recycle", "$recycle.bin", "system volume information", ".trash",
             "lost+found", "extras", "featurettes", "behind the scenes", "deleted scenes", "trailers"}

# release-name junk: only unambiguous technical tokens (words like "Web", "Remux", "Proper" can be real titles)
_JUNK = re.compile(
    r"[\[(]?\b(2160p|1080p|1080i|720p|576p|480p|4k|uhd|hdr10\+?|bluray|blu-ray|bdrip|brrip|"
    r"web-?dl|web-?rip|webrip|hdtv|dvdrip|x264|x265|h\.?264|h\.?265|hevc|xvid|divx|aac\d?(\.\d)?|"
    r"e?ac3|dts(-hd)?|truehd|ddp?\d\.\d|10bit|8bit)\b.*$", re.I)
_YEAR = re.compile(r"[\[(. _-]((?:19|20)\d{2})(?=[\])\s._-]|$)")
_SXE = [
    re.compile(r"^(?P<show>.*?)[ ._-]*[Ss](?P<s>\d{1,2})[ ._-]*[Ee](?P<e>\d{1,3})(?:[-Ee]+\d{1,3})*(?P<rest>.*)$"),
    re.compile(r"^(?P<show>.*?)[ ._-]+(?P<s>\d{1,2})x(?P<e>\d{2,3})(?P<rest>.*)$"),
    re.compile(r"^(?P<show>.*?)[ ._-]*Season[ ._-]*(?P<s>\d{1,2})[ ._-]*Episode[ ._-]*(?P<e>\d{1,3})(?P<rest>.*)$", re.I),
]
_SEASON_DIR = re.compile(r"^(?:season|series|s)[ ._-]*(\d{1,2})$", re.I)
_EP_ONLY = re.compile(r"^(?:e|ep|episode)?[ ._-]*(\d{1,3})\b(?P<rest>.*)$", re.I)
_TRACKNUM = re.compile(r"^(?:(?P<disc>\d)[-.])?(?P<track>\d{1,3})[ ._-]+(?P<rest>.+)$")


def clean(s: str) -> str:
    s = s.replace("_", " ")
    if " " not in s.strip() or s.count(".") > 2:
        s = s.replace(".", " ")
    s = re.sub(r"\s+", " ", s).strip(" -._")
    s = re.sub(r"[\[(]\s*[\])]", "", s)          # empty () []
    while s and s[-1] in ")]" and s.count(s[-1]) > s.count("(" if s[-1] == ")" else "["):
        s = s[:-1].rstrip(" -._")
    while s and s[0] in "([" and s.count(s[0]) > s.count(")" if s[0] == "(" else "]"):
        s = s[1:].lstrip(" -._")
    s = s.rstrip(" -._([")
    return s.strip()


# 1.3: edition words. Matched as whole words at the END of the title (after the year is cut off), repeatedly,
# so "Sin City EXTENDED and UNRATED" -> ("Sin City", "Extended, Unrated"). Plex-style "{edition-Foo}" too.
_EDITIONS = [
    (r"(?:the\s+)?ultimate\s+(?:edition|cut)", "Ultimate Edition"),
    (r"director'?s'?\s+cut|directors\s+cut|dir\s+cut", "Director's Cut"),
    (r"unrated\s+director'?s'?\s+cut", "Unrated Director's Cut"),
    (r"final\s+cut", "Final Cut"),
    (r"extended(?:\s+(?:edition|cut|version))?", "Extended"),
    (r"unrated(?:\s+(?:edition|cut|version))?", "Unrated"),
    (r"uncut(?:\s+(?:edition|version))?", "Uncut"),
    (r"(?:\d{1,2}(?:st|nd|rd|th)\s+)?anniversary(?:\s+edition)?", "Anniversary Edition"),
    (r"remastered|restored|4k\s+remaster(?:ed)?", "Remastered"),
    (r"theatrical(?:\s+(?:cut|version|edition))?", "Theatrical"),
    (r"imax(?:\s+(?:edition|version))?", "IMAX"),
    (r"special\s+edition", "Special Edition"),
    (r"collector'?s\s+edition", "Collector's Edition"),
    (r"criterion(?:\s+collection)?", "Criterion"),
    (r"open\s+matte", "Open Matte"),
    (r"redux", "Redux"),
    (r"alternate\s+(?:cut|ending)", "Alternate Cut"),
    (r"rogue\s+cut", "Rogue Cut"),
    (r"black\s+and\s+chrome|black\s*&\s*chrome", "Black & Chrome"),
]
_ED_TAIL = re.compile(r"(?:^|[\s._\-\[(,])(%s)[\s._\])]*$" % "|".join("(?:%s)" % p for p, _ in _EDITIONS), re.I)
_ED_UPPER_TAIL = re.compile(r"(?:^|\s)(DC|DDC|SE)\s*$")       # only in capitals: "Terminator 2 Judgment Day DC"
_ED_PLEX = re.compile(r"\{edition-([^}]+)\}", re.I)


def split_edition(title: str):
    """("Salt DIRECTORS CUT") -> ("Salt", "Director's Cut"). Never empties a title."""
    t = (title or "").strip()
    found = []
    m = _ED_PLEX.search(t)
    if m:
        found.append(m.group(1).strip())
        t = _ED_PLEX.sub("", t).strip()
    for _ in range(4):
        t2 = re.sub(r"[\s\-]+(?:and|&|\+)$", "", t, flags=re.I).strip(" -._,([")
        m = _ED_TAIL.search(t2)
        if m and m.start(1) > 0:
            rest = t2[:m.start(1)].strip(" -._,([")
            if re.search(r"(?:^|\s)(the|a|an)$", rest, re.I):          # "Blade Runner The Final Cut"
                if len(rest.split()) < 2:
                    break                                              # "The Final Cut" is a real title
                rest = rest.rsplit(None, 1)[0]
            if not rest:
                break
            word = m.group(1)
            label = next((lab for p, lab in _EDITIONS if re.fullmatch(p, word, re.I)), word.title())
            found.insert(0, label)
            t = rest
            continue
        m = _ED_UPPER_TAIL.search(t2)
        if m and m.start(1) > 0 and len(t2[:m.start(1)].split()) >= 3:
            found.insert(0, {"DC": "Director's Cut", "DDC": "Director's Cut", "SE": "Special Edition"}[m.group(1)])
            t = t2[:m.start(1)].strip(" -._,([")
            continue
        break
    if not t:
        return (title or "").strip(), None
    seen = []
    for f in found:
        if f not in seen:
            seen.append(f)
    return t, (", ".join(seen) or None)


def sort_key(title: str) -> str:
    t = (title or "").lower()
    for art in ("the ", "a ", "an "):
        if t.startswith(art):
            t = t[len(art):]
            break
    return t


def parse_movie(path: Path):
    stem = path.stem
    # "Movie (2010)/Movie (2010).mkv" or folder name better than "cd1"/"movie" style names
    if re.match(r"^(movie|cd\d|disc\d|part\d|video_ts)$", stem, re.I) and path.parent.name:
        stem = path.parent.name
    year = None
    # a year at the very start is part of the title ("1917.2019.mkv", "2001 A Space Odyssey (1968)")
    ms = [x for x in _YEAR.finditer(" " + stem + " ") if x.start() > 1]
    paren = [x for x in ms if x.group(0)[0] in "(["]
    m = paren[-1] if paren else (ms[-1] if ms else None)
    if m and m.start() > 1:
        # scene names put everything technical after the year: the title is what comes before it
        year = int(m.group(1))
        title = clean(stem[: m.start() - 1])
    else:
        first, _, rest = stem.partition(" " if " " in stem else ".")
        title = clean(first + " " + _JUNK.sub("", rest)) if rest else clean(stem)
    title = title or clean(stem)
    if not year:
        pm = _YEAR.search(" " + path.parent.name + " ")
        if pm:
            year = int(pm.group(1))
    file_title = title
    title, edition = split_edition(title)
    if not edition:   # "Movie (2010) {edition-Director's Cut}" / "Movie (2010) - Extended" after the year
        m2 = m and stem[m.end() - 1:]
        if m2:
            _, edition = split_edition("x " + _JUNK.sub("", clean(m2.replace("[", " ").replace("]", " "))))
    return {"kind": "movie", "title": title, "year": year, "edition": edition, "file_title": file_title}


def parse_episode(path: Path, lib_root: Path):
    stem = path.stem
    rel_parts = path.relative_to(lib_root).parts if lib_root in path.parents else (path.name,)
    show_from_dir = None
    season_from_dir = None
    if len(rel_parts) >= 2:
        show_from_dir = rel_parts[0]
        for part in rel_parts[1:-1]:
            m = _SEASON_DIR.match(part.strip())
            if m:
                season_from_dir = int(m.group(1))
            elif part.lower() in ("specials", "season 0"):
                season_from_dir = 0
    for rx in _SXE:
        m = rx.match(stem)
        if m:
            show = clean(_YEAR.sub(" ", " " + m.group("show") + " ")) if m.group("show") else ""
            show = clean(show_from_dir) if show_from_dir else (show or "Unknown show")
            rest = clean(_JUNK.sub("", m.group("rest") or ""))
            return {"kind": "episode", "show": _strip_year(show), "season": int(m.group("s")),
                    "episode": int(m.group("e")), "episode_title": rest or None,
                    "title": rest or "Episode %d" % int(m.group("e"))}
    if show_from_dir:
        m = _EP_ONLY.match(stem)
        ep = int(m.group(1)) if m else None
        rest = clean(_JUNK.sub("", m.group("rest"))) if m else clean(stem)
        return {"kind": "episode", "show": _strip_year(clean(show_from_dir)), "season": season_from_dir or 1,
                "episode": ep, "episode_title": rest or None, "title": rest or clean(stem)}
    return {"kind": "video", "title": clean(_JUNK.sub("", stem)) or stem}


def _strip_year(show):
    return re.sub(r"\s*[\[(]?(19|20)\d{2}[\])]?$", "", show).strip() or show


def parse_track(path: Path, lib_root: Path):
    rel = path.relative_to(lib_root).parts if lib_root in path.parents else (path.name,)
    artist = album = None
    if len(rel) >= 3:
        artist, album = rel[-3], rel[-2]
    elif len(rel) == 2:
        album = rel[-2]
    m = _TRACKNUM.match(path.stem)
    track = disc = None
    title = path.stem
    if m:
        track = int(m.group("track"))
        disc = int(m.group("disc")) if m.group("disc") else None
        title = m.group("rest")
    title = clean(title)
    if artist is None and " - " in title:
        a, t = title.split(" - ", 1)
        artist, title = a.strip(), t.strip()
    return {"kind": "track", "title": title, "artist": artist, "album": album, "album_artist": artist,
            "track": track, "disc": disc}


def ffprobe(path: str):
    try:
        out = subprocess.run(
            [config.FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, timeout=60, check=False)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout or b"{}")
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def summarize_probe(p):
    """Turn ffprobe JSON into item columns."""
    if not p:
        return {}
    fmt = p.get("format", {})
    streams = p.get("streams", [])
    res = {
        "container": fmt.get("format_name"),
        "duration": _f(fmt.get("duration")),
        "bitrate": _i(fmt.get("bit_rate")),
    }
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    if v:
        res.update(vcodec=v.get("codec_name"), width=v.get("width"), height=v.get("height"),
                   pix_fmt=v.get("pix_fmt"))
        if not res["duration"]:
            res["duration"] = _f(v.get("duration"))
        res["color_transfer"] = (v.get("color_transfer") or "").strip() or None
        rot = 0
        for sd in v.get("side_data_list") or []:
            if sd.get("rotation") not in (None, ""):
                try:
                    rot = int(round(float(sd["rotation"]))) % 360
                except (TypeError, ValueError):
                    pass
        tags_v = {k.lower(): val for k, val in (v.get("tags") or {}).items()}
        if not rot and tags_v.get("rotate"):
            try:
                rot = int(round(float(tags_v["rotate"]))) % 360
            except (TypeError, ValueError):
                pass
        res["rotation"] = rot
    auds, subs = [], []
    for s in streams:
        t = {k.lower(): val for k, val in (s.get("tags") or {}).items()}
        if s.get("codec_type") == "audio":
            auds.append({"index": s.get("index"), "codec": s.get("codec_name"), "channels": s.get("channels"),
                         "lang": t.get("language"), "title": t.get("title"),
                         "default": bool((s.get("disposition") or {}).get("default"))})
        elif s.get("codec_type") == "subtitle":
            subs.append({"index": s.get("index"), "codec": s.get("codec_name"), "lang": t.get("language"),
                         "title": t.get("title"),
                         "text": s.get("codec_name") in ("subrip", "ass", "ssa", "mov_text", "webvtt", "text")})
    if auds:
        res["acodec"] = auds[0]["codec"]
        if not res["duration"]:
            res["duration"] = _f(next((s.get("duration") for s in streams if s.get("codec_type") == "audio"), None))
    res["audio_streams"] = json.dumps(auds)
    res["subtitle_streams"] = json.dumps(subs)
    res["tags"] = tags
    res["has_cover"] = any((s.get("disposition") or {}).get("attached_pic") for s in streams)
    return res


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _i(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _num(x):
    if not x:
        return None
    m = re.match(r"\s*(\d+)", str(x))
    return int(m.group(1)) if m else None


def apply_audio_tags(info, tags):
    if not tags:
        return info
    if tags.get("title"):
        info["title"] = tags["title"]
    if tags.get("artist"):
        info["artist"] = tags["artist"]
    if tags.get("album_artist") or tags.get("albumartist"):
        info["album_artist"] = tags.get("album_artist") or tags.get("albumartist")
    elif tags.get("artist"):
        info["album_artist"] = tags["artist"]
    if tags.get("album"):
        info["album"] = tags["album"]
    if tags.get("track"):
        info["track"] = _num(tags["track"])
    if tags.get("disc"):
        info["disc"] = _num(tags["disc"])
    if tags.get("genre"):
        info["genre"] = tags["genre"]
    if tags.get("date") or tags.get("year"):
        y = _num(tags.get("date") or tags.get("year"))
        if y and 1000 < y < 3000:
            info["year"] = y
    return info


def thumb_name(path: str, suffix="") -> str:
    return hashlib.sha1((path + suffix).encode("utf-8", "surrogateescape")).hexdigest() + ".jpg"


def make_video_thumb(path: str, duration):
    """Grab a frame ~10% in (max 5 min), scaled to 480 wide."""
    out = config.THUMB_DIR / thumb_name(path)
    if out.exists() and out.stat().st_size > 0:
        return out.name
    at = 5.0
    if duration:
        at = min(max(duration * 0.1, 1.0), 300.0)
        if at >= duration:
            at = duration / 2
    # 1.2: decode a single keyframe only (-skip_frame nokey) -- ~10x less CPU than picking the "best" of 25
    # frames, which matters on big 4K/HEVC libraries over SMB. Fall back to a normal decode if that fails.
    base = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-threads", "2"]
    tail = ["-ss", "%.2f" % at, "-i", path, "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(out)]
    for cmd in (base + ["-skip_frame", "nokey"] + tail, base + tail):
        try:
            subprocess.run(cmd, capture_output=True, timeout=90, check=False)
        except (subprocess.TimeoutExpired, OSError):
            continue
        if out.exists() and out.stat().st_size > 0:
            return out.name
    out.unlink(missing_ok=True)
    return None


def make_cover_thumb(path: str):
    """Extract embedded album art."""
    out = config.THUMB_DIR / thumb_name(path, "#cover")
    if out.exists() and out.stat().st_size > 0:
        return out.name
    cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-an",
           "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=500:-2", "-q:v", "3", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.exists() and out.stat().st_size > 0:
        return out.name
    out.unlink(missing_ok=True)
    return None


def make_image_thumb(img_path: str):
    """Copy/scale a local poster.jpg/folder.jpg into the thumb cache."""
    try:
        st = os.stat(img_path)
    except OSError:
        return None
    out = config.THUMB_DIR / thumb_name(img_path, "#img%d" % int(st.st_mtime))
    if out.exists() and out.stat().st_size > 0:
        return out.name
    cmd = [config.FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", img_path,
           "-vf", "scale='min(600,iw)':-2", "-q:v", "3", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return out.name if out.exists() and out.stat().st_size > 0 else None


def find_local_image(media_path: Path, names=IMAGE_NAMES_POSTER, include_stem=True):
    d = media_path.parent
    try:
        entries = {e.lower(): e for e in os.listdir(d)}
    except OSError:
        return None
    cands = []
    if include_stem:
        for suf in ("-poster", "", ".poster", "-thumb", "-cover"):
            cands += [media_path.stem.lower() + suf + ext for ext in IMAGE_EXT]
    for n in names:
        cands += [n + ext for ext in IMAGE_EXT]
    for c in cands:
        if c in entries:
            return str(d / entries[c])
    return None


def find_external_subs(media_path: Path):
    d = media_path.parent
    stem = media_path.stem.lower()
    subs = []
    try:
        for e in sorted(os.listdir(d)):
            p = Path(e)
            if p.suffix.lower() in SUB_EXT and e.lower().startswith(stem):
                label = e[len(stem):-len(p.suffix)].strip(". _-") or "External"
                subs.append({"file": e, "label": label})
    except OSError:
        pass
    return subs
