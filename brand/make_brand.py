#!/usr/bin/env python3
"""Build the channel art from the site's own look (DESIGN.md): night airfield aerial (assets/art/airports, USGS NAIP rendering),
site ring mark, Barlow Condensed capitals, signage status colours. Output: avatar-800.png, avatar-400.jpg, banner-youtube.jpg
(2560x1440, text inside the 1546x423 safe area), banner-twitch.jpg (1200x480), offline-1920.jpg. Usage: python3 brand/make_brand.py"""
import base64, pathlib, sys
from playwright.sync_api import sync_playwright
ROOT = pathlib.Path(__file__).resolve().parent.parent
F = (ROOT / "fonts").as_uri()
LOGO = (ROOT / "brand/logo.svg").read_text().replace('<rect width="200" height="200" rx="44" fill="#0B1730"/>', '')
LOGO_BIG = LOGO.replace("translate(148.8 41.8) rotate(130) scale(.95)", "translate(142 50) rotate(130) scale(1.55)")
INK, ACCENT, GREEN, AMBER, RED = "#0b0f14", "#7cc4ff", "#3ddc84", "#ffc233", "#ff5a5f"
BASE = (ROOT / "assets/art/airports/ap-DEN-night.webp").as_uri()
CSS = f"""
@font-face {{ font-family: Barlow; font-weight: 700; src: url({F}/barlow-condensed-700.woff2); }}
@font-face {{ font-family: Barlow; font-weight: 600; src: url({F}/barlow-condensed-600.woff2); }}
@font-face {{ font-family: PS; src: url({F}/public-sans-latin-wght-normal.woff2); font-weight: 100 900; }}
* {{ box-sizing: border-box; margin: 0; }} body {{ background: {INK}; color: #f4f1ea; overflow: hidden; }}
.bg {{ position: absolute; inset: 0; background: url({BASE}) center/cover; filter: saturate(1.15) brightness(1.25) contrast(1.05); }}
.shade {{ position: absolute; inset: 0; background: linear-gradient(90deg, rgba(11,15,20,.5) 0%, rgba(11,15,20,.85) 30%, rgba(11,15,20,.85) 70%, rgba(11,15,20,.5) 100%); }}
.mark svg {{ width: 100%; height: 100%; display: block; }}
.name {{ font: 700 1em/.9 Barlow; letter-spacing: .02em; text-transform: uppercase; }}
.tag {{ font: 600 1em/1.2 Barlow; letter-spacing: .12em; text-transform: uppercase; color: {ACCENT}; }}
.chips {{ display: flex; gap: .7em; font: 700 1em/1 Barlow; letter-spacing: .1em; text-transform: uppercase; }}
.chip {{ display: flex; align-items: center; gap: .5em; padding: .45em .8em .4em; border: 2px solid rgba(244,241,234,.28); border-radius: 999px; background: rgba(11,15,20,.6); }}
.chip i {{ width: .8em; height: .8em; border-radius: 50%; display: block; }}
"""
def chips(fs):
    return (f'<div class="chips" style="font-size:{fs}px"><span class="chip"><i style="background:{GREEN}"></i>Clear</span>'
            f'<span class="chip"><i style="background:{AMBER}"></i>Delay</span><span class="chip"><i style="background:{RED}"></i>Ground stop</span></div>')
def banner(w, h, cx, cy, sw, sh, k):
    # text block centred on (cx, cy) inside a safe area sw x sh; k scales everything
    return f"""<html><style>{CSS}</style><body style="width:{w}px;height:{h}px;position:relative"><div class="bg"></div><div class="shade"></div>
<div style="position:absolute;left:{cx-sw/2}px;top:{cy-sh/2}px;width:{sw}px;height:{sh}px;display:flex;align-items:center;justify-content:center;gap:{44*k}px">
 <div style="display:flex;flex-direction:column;align-items:center;text-align:center;gap:{22*k}px">
  <div class="name" style="font-size:{104*k}px;white-space:nowrap">Air Travel Desk</div>
  <div class="tag" style="font-size:{30*k}px;white-space:nowrap">Live US airport delays and ground stops, 24/7</div>
  {chips(32*k)}
 </div></div></body></html>"""
def icon(s):
    return f"""<html><style>{CSS}</style><body style="width:{s}px;height:{s}px;position:relative;background:{INK}">

<div class="mark" style="position:absolute;left:{s*.12}px;top:{s*.12}px;width:{s*.76}px;height:{s*.76}px;filter:drop-shadow(0 0 {s*.03}px rgba(124,196,255,.5))">{LOGO_BIG}</div></body></html>"""
def offline():
    return f"""<html><style>{CSS}</style><body style="width:1920px;height:1080px;position:relative"><div class="bg"></div><div class="shade" style="background:rgba(11,15,20,.72)"></div>
<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px;text-align:center">
 <div class="mark" style="width:190px;height:190px">{LOGO}</div>
 <div class="name" style="font-size:150px">Air Travel Desk</div>
 <div class="tag" style="font-size:44px">The desk is offline. Back shortly.</div>
 <div style="font:500 34px/1.4 PS,sans-serif;color:#cfd6dd">Live delays any time at airtraveldesklive.com</div>{chips(30)}</div></body></html>"""
with sync_playwright() as p:
    b = p.chromium.launch()
    def shot(html, w, h, out, fmt):
        tmp = ROOT / "brand" / "_tmp.html"; tmp.write_text(html)
        pg = b.new_page(viewport={"width": w, "height": h}); pg.goto(tmp.as_uri()); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(800)
        kw = {"type": "jpeg", "quality": 90} if fmt == "jpg" else {}
        pg.screenshot(path=str(ROOT / "brand" / out), **kw); pg.close(); tmp.unlink()
    shot(banner(2560, 1440, 1280, 720, 1546, 423, 1.45), 2560, 1440, "banner-youtube.jpg", "jpg")
    shot(banner(1200, 480, 600, 240, 1000, 330, .75), 1200, 480, "banner-twitch.jpg", "jpg")
    shot(icon(800), 800, 800, "avatar-800.png", "png")
    shot(icon(400), 400, 400, "avatar-400.jpg", "jpg")
    shot(offline(), 1920, 1080, "offline-1920.jpg", "jpg")
    b.close()
print("ok")
