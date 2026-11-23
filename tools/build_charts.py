import argparse
import json
import re
from datetime import timedelta
from html import escape
from pathlib import Path

from build_chart_tsa import (
    calendar_days, load_model, millions, percent_change, render_svg, short_date, signed_percent,
)


ROOT = Path(__file__).resolve().parents[1]
SITE = "https://www.airtraveldesklive.com"
INDEX_URL = f"{SITE}/charts"
TSA_URL = f"{INDEX_URL}/tsa"

CHART_CSS = """\
body.page-charts { font-family: system-ui, sans-serif; }
.chart-main { max-width: 1080px; margin: 0 auto; padding: 1.5rem var(--gutter, 16px) 3rem; }
.chart-main h1 { max-width: 28ch; font: 750 clamp(1.9rem, 4.5vw, 3.6rem)/1.08 system-ui, sans-serif; margin: .35rem 0 .85rem; }
.chart-main h2 { font-family: inherit; }
.chart-crumb, .chart-kicker, .chart-source { font-size: .9rem; color: var(--text-muted, #a3afbd); }
.chart-kicker { margin: 2rem 0 0; font-weight: 700; color: var(--accent, #8fcbff); }
.chart-dek, .chart-reading { max-width: 68ch; }
.chart-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem; margin: 1.5rem 0; }
.chart-stats div { padding: .8rem; border: 1px solid var(--line, #2c3746); border-radius: var(--radius-sm, 8px); background: var(--surface, #0e1319); }
.chart-stats dt { color: var(--text-muted, #a3afbd); font-size: .875rem; }
.chart-stats dd { margin: .15rem 0 0; font-variant-numeric: tabular-nums; }
.chart-stats strong { display: block; font-size: clamp(1.05rem, 2.75vw, 1.65rem); }
.tsa-figure { margin: 1.5rem 0; padding: .85rem; background: var(--surface, #0e1319); border: 1px solid var(--line, #2c3746); border-radius: var(--radius, 14px); }
.tsa-figure svg { width: 100%; height: auto; display: block; }
.tsa-figure .chart-narrow { display: none; }
.chart-legend { display: flex; flex-wrap: wrap; gap: .45rem 1.35rem; margin: 0; padding: 0 .25rem .65rem; list-style: none; font-size: .875rem; }
.chart-legend li { display: flex; align-items: center; gap: .5rem; }
.chart-legend li::before { content: ""; width: 1.8rem; border-top: 3px solid var(--accent, #8fcbff); }
.chart-legend li + li::before { border-top: 3px dashed var(--amber-text, #ffd45c); }
.chart-note { margin: 0 .25rem .6rem; font-size: .875rem; color: var(--text-muted, #a3afbd); }
.chart-details { margin: 1.5rem 0; }
.chart-details summary { cursor: pointer; font-weight: 700; }
.chart-table-scroll { overflow-x: auto; }
.chart-details table { width: 100%; margin: .75rem 0; border-collapse: collapse; font-variant-numeric: tabular-nums; font-size: .875rem; }
.chart-details th, .chart-details td { padding: .45rem .35rem; border-bottom: 1px solid var(--line, #2c3746); text-align: right; }
.chart-details th:first-child { text-align: left; }
@media (max-width: 640px) {
  .tsa-figure { padding: .45rem; }
  .tsa-figure .chart-wide { display: none; }
  .tsa-figure .chart-narrow { display: block; }
  .chart-stats { grid-template-columns: 1fr 1fr; gap: .45rem; }
  .chart-stats div:first-child { grid-column: 1 / -1; }
  .chart-stats div { padding: .45rem; }
  .chart-stats dd { font-size: .82rem; overflow-wrap: anywhere; }
}
"""


def make_page(reference, title, description, url, crumbs, content, prefix, shared, chart_css):
    for asset in ("brand/", "theme.js", "watch.js"):  # root-relative assets in the reference page (it lives at the site root)
        reference = reference.replace(f'src="{asset}', f'src="{prefix}{asset}')
    head = reference.split("  <style>", 1)[0]
    head = re.sub(r"<title>.*?</title>", f"<title>{escape(title)} | Air Travel Desk</title>", head)
    replacements = {
        "description": description, "canonical": url, "og:title": title,
        "og:description": description, "og:url": url, "twitter:title": title,
        "twitter:description": description, "twitter:card": "summary",
    }
    for name, value in replacements.items():
        pattern = rf'((?:name|rel|property)="{name}" (?:content|href)=")[^"]*'
        head = re.sub(pattern, lambda match: match[1] + escape(value), head)
    head = re.sub(r'^.*(?:og:image|twitter:image).*\n', "", head, flags=re.MULTILINE)
    for asset in ("tokens.css", "style.css"):
        head = head.replace(f'href="{asset}"', f'href="{shared}{asset}"')
    head = head.replace('href="favicon.', f'href="{prefix}favicon.')
    header = reference.split('<body class="page-shows">\n', 1)[1].split("  </header>", 1)[0] + "  </header>"
    footer = reference.split('  <footer class="site-footer">', 1)[1].split("  </footer>", 1)[0]
    # Preserve the reference's outbound navigation without literal remote resource URLs.
    footer = '  <footer class="site-footer">' + footer.replace("https://", "&#104;ttps://") + "  </footer>"
    breadcrumb = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": position, "name": name, "item": address}
            for position, (name, address) in enumerate(crumbs, 1)
        ],
    }
    return f"""{head}  <link rel="stylesheet" href="{chart_css}">
  <script type="application/ld+json">{json.dumps(breadcrumb)}</script>
</head>
<body class="page-charts">
{header}
  <main id="main-content" class="chart-main">
{content}
  </main>
{footer}
</body>
</html>
"""


def count_text(count):
    return "—" if count is None else f"{count:,}"


def tsa_content(model):
    labels = model["labels"]
    latest = model["latest"]
    day_change = signed_percent(labels["yoy_pct_latest_day"])
    avg_change = signed_percent(labels["yoy_pct_7_day"])
    record = model["record"]
    record_text = f"{short_date(record, True)}, {record.year}"
    rows = []
    for day in reversed(list(calendar_days(latest - timedelta(days=13), latest))):
        current, prior = model["current"].get(day), model["prior"].get(day)
        change = percent_change(current, prior) if current is not None and prior is not None else None
        rows.append(
            f'        <tr><th scope="row"><time datetime="{day}">{short_date(day, True)}</time></th>'
            f'<td>{count_text(current)}</td><td>{count_text(prior)}</td><td>{signed_percent(change)}</td></tr>'
        )
    table = "\n".join(rows)
    return f"""    <nav class="chart-crumb" aria-label="Breadcrumb">
      <a href="/">Live board</a> / <a href="../">Charts</a> / <span aria-current="page">TSA throughput</span>
    </nav>
    <p class="chart-kicker">Thanksgiving tracker</p>
    <h1>{escape(model['title'])}</h1>
    <p class="chart-dek">Daily TSA checkpoint counts show how this year’s Thanksgiving travel is shaping up. Last year’s line continues through the holiday and the return rush.</p>
    <dl class="chart-stats">
      <div><dt>{short_date(latest, True)}</dt><dd><strong>{count_text(labels['latest_count'])}</strong>{day_change} vs last year</dd></div>
      <div><dt>7-day average change</dt><dd><strong>{avg_change}</strong>vs last year</dd></div>
      <div><dt>Last year’s record</dt><dd><strong>{millions(labels['record_count'])}</strong>{record_text}</dd></div>
    </dl>
    <figure class="tsa-figure">
      <ul class="chart-legend" aria-label="Legend"><li>This year</li><li>Same weekday last year</li></ul>
      <p class="chart-note"><strong>Passengers screened per day at TSA checkpoints.</strong> Last year’s dates are lined up by weekday, so the record sits on the matching Sunday of this year’s axis.</p>
{render_svg(model, "wide")}{render_svg(model, "narrow")}    </figure>
    <h2>How to read this</h2>
    <p class="chart-reading">The solid lines show this year. The dashed lines show the same weekdays last year. Daily counts normally dip on some weekdays. The thicker lines average the most recent seven days to smooth those dips.</p>
    <details class="chart-details">
      <summary>Show the numbers</summary>
      <div class="chart-table-scroll">
      <table aria-label="Daily checkpoint counts over the last 14 days">
        <thead><tr><th scope="col">Date</th><th scope="col">This year</th><th scope="col">Last year</th><th scope="col">Change</th></tr></thead>
        <tbody>
{table}
        </tbody>
      </table>
      </div>
    </details>
    <p class="chart-source">Source: TSA checkpoint travel numbers (public daily table), tsa.gov/travel/passenger-volumes. Last year is the same weekday, 364 days earlier. Updated {latest}.</p>"""


def main():
    parser = argparse.ArgumentParser(description="Build the static charts pages.")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path, default=ROOT / "charts")
    parser.add_argument("--sitemap-lines", action="store_true")
    args = parser.parse_args()
    if args.sitemap_lines:
        for url in (INDEX_URL, TSA_URL):
            print(f"<url><loc>{url}</loc></url>")
        return

    model = load_model(args.data / "tsa-history.json")
    ref_path = ROOT / "shows.html"
    reference = ref_path.read_text(encoding="utf-8").replace(' aria-current="page"', "")  # the reference page is /shows; charts pages have no current nav chip
    index_crumbs = [("Live board", SITE + "/"), ("Charts", INDEX_URL)]
    tsa_crumbs = index_crumbs + [("TSA throughput", TSA_URL)]
    description = model["title"] + ". Daily TSA checkpoint counts compared with the same weekdays last year."
    tsa = tsa_content(model)
    index = f"""    <nav class="chart-crumb" aria-label="Breadcrumb"><a href="/">Live board</a> / <span aria-current="page">Charts</span></nav>
    <h1>Charts</h1>
    <ul><li><a href="tsa/">TSA throughput</a><p>{escape(model['title'])}</p></li></ul>"""

    (args.out / "tsa").mkdir(parents=True, exist_ok=True)
    (args.out / "chart.css").write_text(CHART_CSS, encoding="utf-8")
    (args.out / "index.html").write_text(
        make_page(reference, "Charts", "Charts from Air Travel Desk. " + description, INDEX_URL,
                  index_crumbs, index, "../", "../", "chart.css"), encoding="utf-8")
    (args.out / "tsa" / "index.html").write_text(
        make_page(reference, model["title"], description, TSA_URL, tsa_crumbs, tsa, "../../", "../../", "../chart.css"),
        encoding="utf-8")


if __name__ == "__main__":
    main()
