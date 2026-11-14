import sys, math
def banner(W, H, safe_w, safe_h):
    cx, cy = W/2, H/2
    s = safe_h/423  # scale against YouTube safe height
    arcs = []
    pts = [(0.18,0.62),(0.30,0.40),(0.45,0.66),(0.58,0.35),(0.72,0.60),(0.84,0.42)]
    for i,(a,b) in enumerate(zip(pts, pts[1:]+pts[:1])):
        x1,y1=a[0]*W,a[1]*H; x2,y2=b[0]*W,b[1]*H
        mx,my=(x1+x2)/2,(y1+y2)/2-H*0.12
        arcs.append(f'<path d="M{x1:.0f} {y1:.0f} Q{mx:.0f} {my:.0f} {x2:.0f} {y2:.0f}" stroke="#9fd3ff" stroke-opacity="0.10" stroke-width="{3*s:.1f}" fill="none" stroke-dasharray="{10*s:.0f} {12*s:.0f}"/>')
    dots = ''.join(f'<circle cx="{x*W:.0f}" cy="{y*H:.0f}" r="{7*s:.1f}" fill="{c}"/>' for (x,y),c in zip(pts,["#3ccf7c","#f2b33d","#3ccf7c","#e5484d","#3ccf7c","#f2b33d"]))
    rx = cx - safe_w/2 + safe_h*0.5
    r = safe_h*0.36
    radar = f'''<g transform="translate({rx:.0f} {cy:.0f})">
<circle r="{r:.0f}" fill="#10233a" stroke="#9fd3ff" stroke-opacity="0.35" stroke-width="{4*s:.1f}"/>
<circle r="{r*0.66:.0f}" fill="none" stroke="#9fd3ff" stroke-opacity="0.25" stroke-width="{3*s:.1f}"/>
<circle r="{r*0.33:.0f}" fill="none" stroke="#9fd3ff" stroke-opacity="0.25" stroke-width="{3*s:.1f}"/>
<path d="M0 0 L{r:.0f} 0 A{r:.0f} {r:.0f} 0 0 0 {r*0.707:.0f} {-r*0.707:.0f} Z" fill="#f2b33d" fill-opacity="0.45"/>
<g transform="rotate(45) scale({r/40:.2f})" fill="#eef3f7"><path d="M0 -34 C3 -34 4 -30 4 -26 L4 -8 L30 6 L30 12 L4 4 L4 20 L12 26 L12 31 L0 28 L-12 31 L-12 26 L-4 20 L-4 4 L-30 12 L-30 6 L-4 -8 L-4 -26 C-4 -30 -3 -34 0 -34 Z"/></g></g>'''
    tx = rx + r + safe_h*0.22
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b1520"/><stop offset="0.55" stop-color="#132a42"/><stop offset="1" stop-color="#0b1520"/></linearGradient></defs>
<rect width="{W}" height="{H}" fill="url(#g)"/>
{''.join(arcs)}{dots}{radar}
<text x="{tx:.0f}" y="{cy-safe_h*0.04:.0f}" font-family="-apple-system,Helvetica,Arial,sans-serif" font-weight="800" font-size="{safe_h*0.25:.0f}" fill="#eef3f7" letter-spacing="{safe_h*0.004:.1f}">AIR TRAVEL DESK</text>
<text x="{tx:.0f}" y="{cy+safe_h*0.13:.0f}" font-family="-apple-system,Helvetica,Arial,sans-serif" font-weight="600" font-size="{safe_h*0.085:.0f}" fill="#9fd3ff">Live US flight delays and ground stops, 24/7</text>
<text x="{tx:.0f}" y="{cy+safe_h*0.27:.0f}" font-family="-apple-system,Helvetica,Arial,sans-serif" font-weight="600" font-size="{safe_h*0.065:.0f}" fill="#f2b33d">FAA · NWS · TSA data  ·  airtraveldesklive.com</text>
</svg>'''
open('banner-youtube.svg','w').write(banner(2560,1440,1546,423))
open('banner-twitch.svg','w').write(banner(1200,480,1040,270))
