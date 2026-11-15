"""Build static airline pages (airlines/<id>.html and airlines/index.html) and update sitemap.xml (AN23 phase 2).

Reads data/dot-commitments.json (U.S. DOT Airline Cancellation and Delay Dashboard, transcribed by lane 1)
and data/airline-pages.json (the re-read date and the plan link check). Stdlib only; no network requests.

Wording rules come from specs/AN9: "has committed to", never "must cover"; "possibly owed";
the pages cover only delays and cancellations the airline causes; the refund rule (14 CFR 260.6) stands apart.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools import build_airport_pages as bap
except ImportError:  # run as a script: tools/ is on the path
    import build_airport_pages as bap  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SITE_URL = bap.SITE_URL
SITEMAP_BEGIN = "<!-- airlines:begin -->"
SITEMAP_END = "<!-- airlines:end -->"

DASHBOARD_URL = "https://www.transportation.gov/airconsumer/airline-cancellation-delay-dashboard"
ORDER = ["rebook_same", "rebook_other", "meal", "hotel", "transport", "cash", "voucher", "miles"]

# The same sentence as stuck.js (REFUND_QUOTE and PLAIN_READING), already reviewed.
REFUND_SENTENCE = "Refunds are a separate rule, 14 CFR 260.6, and it applies whatever the cause of the delay or cancellation."
PLAIN_READING = "This is our plain reading, not legal advice."
REFUND_ELIGIBLE = "What you may be eligible for depends on your flight and whether you choose not to travel."

# Short names for the one-sentence summary on each page. The table uses the labels in the data file.
SHORT = {
    "rebook_same": "rebooking on the same airline at no additional cost",
    "rebook_other": "rebooking on a partner or other airline at no additional cost",
    "meal": "a meal or meal voucher for a wait of 3 hours or more",
    "hotel": "a hotel for an overnight delay or cancellation",
    "transport": "ground transport to and from the hotel",
    "cash": "cash compensation for a wait of 3 hours or more",
    "voucher": "a credit or travel voucher for a wait of 3 hours or more",
    "miles": "frequent flyer miles for a wait of 3 hours or more",
}

FOOTER_NOTE = "Built from the U.S. DOT airline dashboard. Not affiliated with any airline or government agency."


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _header() -> str:
    return bap._render_header(current="airlines", airports_href="../airports/index.html")


def _footer() -> str:
    return bap._render_footer(airports_href="../airports/index.html", airlines_href="index.html", note=FOOTER_NOTE)


def _breadcrumb(items: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": url}
            for i, (name, url) in enumerate(items, 1)
        ],
    }


def _listed(airline: dict[str, Any]) -> bool:
    return isinstance(airline.get("commitments"), dict)


def _counts(airline: dict[str, Any]) -> tuple[int, int]:
    """(committed, total) over the 8 commitments; (0, 0) for an airline with no dashboard column."""
    com = airline.get("commitments")
    if not isinstance(com, dict):
        return 0, 0
    keys = [k for k in ORDER if k in com]
    return sum(1 for k in keys if com[k] is True), len(keys)


def plan_link_for(airline: dict[str, Any], plan_info: dict[str, Any]) -> tuple[str, str]:
    """(url, status). The url is '' when the link is missing, unchecked or dead."""
    url = bap._safe_http_url(airline.get("plan_link"))
    entry = (plan_info.get("airlines") or {}).get(str(airline.get("id")))
    status = str((entry or {}).get("status") or "unchecked")
    if status in ("ok", "blocked") and url:
        return url, status
    return "", status


def _source_line(updated: str, read: str) -> str:
    return (
        "Source: U.S. DOT Airline Cancellation and Delay Dashboard, "
        f"last updated {bap._esc(updated)}, read {bap._esc(read)}."
    )


def _plan_label(airline: dict[str, Any]) -> str:
    name = str(airline.get("name") or "")
    kind = "customer service plan" if _listed(airline) else "contract of carriage"
    return f"{name} {kind}"


def _table(airline: dict[str, Any], labels: dict[str, Any]) -> list[str]:
    name = str(airline["name"])
    com = airline["commitments"]
    rows: list[str] = []
    for key in ORDER:
        if key not in com:
            continue
        yes = com[key] is True
        badge = (
            '<span class="badge badge--yes">Yes</span>' if yes else '<span class="badge badge--no">No</span>'
        )
        rows.append(
            f'            <tr><th scope="row">{bap._esc(labels.get(key) or key)}</th>'
            f"<td>{badge}</td><td>{badge}</td></tr>"
        )
    return [
        '        <table class="commit-table">',
        f'          <caption class="sr-only">What {bap._esc(name)} has committed to, for cancellations and for delays</caption>',
        "          <thead>",
        '            <tr><th scope="col">Commitment</th><th scope="col">Cancellation</th><th scope="col">Delay</th></tr>',
        "          </thead>",
        "          <tbody>",
        *rows,
        "          </tbody>",
        "        </table>",
    ]


def render_airline_page(
    airline: dict[str, Any],
    *,
    airlines: list[dict[str, Any]],
    labels: dict[str, Any],
    updated: str,
    read: str,
    plan_info: dict[str, Any],
    build_date: str,
) -> str:
    aid = str(airline["id"])
    name = str(airline["name"])
    listed = _listed(airline)
    n_yes, n_all = _counts(airline)
    title = f"{name}: what you may be owed for a delay or cancellation"
    if listed:
        description = (
            f"What {name} has committed to when it causes a delay or cancellation: {n_yes} of {n_all} items "
            f"on the U.S. DOT dashboard. Plain-language help, not legal advice."
        )
    else:
        description = (
            f"{name} is not listed on the U.S. DOT delay and cancellation dashboard. "
            "What the dashboard covers and where refunds fit. Plain-language help, not legal advice."
        )
    canonical = f"{SITE_URL}/airlines/{aid}.html"
    breadcrumb = _breadcrumb([
        ("Air Travel Desk", f"{SITE_URL}/"),
        ("Airline commitments", f"{SITE_URL}/airlines/index.html"),
        (name, canonical),
    ])

    commit_section: list[str]
    if listed:
        yes_items = [SHORT[k] for k in ORDER if airline["commitments"].get(k) is True]
        no_items = [SHORT[k] for k in ORDER if k in airline["commitments"] and airline["commitments"][k] is not True]
        summary = f"On the DOT dashboard, {name} has committed to {n_yes} of the {n_all} items: {_join(yes_items)}."
        if no_items:
            summary += f" It has not committed to {_join(no_items)}."
        commit_section = [
            '      <section class="airport-section" aria-labelledby="commit-heading">',
            f'        <h2 id="commit-heading">What {bap._esc(name)} has committed to</h2>',
            f"        <p>{bap._esc(summary)}</p>",
            *_table(airline, labels),
            '        <p class="small">The DOT dashboard has one table for cancellations and one for delays. For every airline they show the same answers, so the two columns above match.</p>',
            '        <p class="small">Yes means the airline has committed to it in its customer service plan. No means it has not made that commitment on the dashboard. An airline may still help in some cases at its own discretion.</p>',
            "      </section>",
        ]
    else:
        commit_section = [
            '      <section class="airport-section" aria-labelledby="commit-heading">',
            f'        <h2 id="commit-heading">{bap._esc(name)} is not listed on the DOT dashboard</h2>',
            f"        <p>The dashboard tables have no column for {bap._esc(name)}, so this page shows no Yes or No answers. "
            f"Without a dashboard entry we cannot say what {bap._esc(name)} has committed to.</p>",
            f"        <p class=\"small\">In place of a customer service plan, the dashboard lists a contract of carriage for {bap._esc(name)}. "
            "The contract of carriage is the airline's own legal terms; read it for what the airline says it will do.</p>",
            "      </section>",
        ]

    if listed:
        purpose = (
            f"Purpose: show what {name} has committed to when it causes a delay or a cancellation, "
            "as the U.S. Department of Transportation lists it. This is plain-language help, not legal advice."
        )
        owed = (
            f"If you paid for something {name} has committed to, such as a meal, a hotel or ground transport, "
            "that cost is possibly owed back to you. Keep your receipts and ask the airline. "
            "Your airline decides every claim, voucher or reimbursement."
        )
        source_for = "the source of the table on this page"
    else:
        purpose = (
            f"Purpose: explain what the U.S. Department of Transportation dashboard does and does not show for {name}. "
            "This is plain-language help, not legal advice."
        )
        owed = (
            "If you paid for a meal, a hotel or ground transport, ask the airline whether its own terms cover it. "
            "Any cost the airline covers is possibly owed back to you. Keep your receipts. "
            "Your airline decides every claim, voucher or reimbursement."
        )
        source_for = "the source for this page"

    plan_url, plan_status = plan_link_for(airline, plan_info)
    plan_checked = str(plan_info.get("checked") or "")
    sources: list[str] = [
        f'          <li><a class="tap" href="{bap._esc(DASHBOARD_URL)}" target="_blank" rel="noopener noreferrer">'
        f"U.S. DOT Airline Cancellation and Delay Dashboard</a> ({source_for})</li>",
    ]
    if plan_url:
        sources.append(
            f'          <li><a class="tap" href="{bap._esc(plan_url)}" target="_blank" rel="noopener noreferrer">'
            f"{bap._esc(_plan_label(airline))}</a> (the airline's own page; this site takes no wording from it)</li>"
        )
    else:
        when = f" when we last checked ({bap._esc(plan_checked)})" if plan_checked else ""
        sources.append(
            f"          <li>{bap._esc(_plan_label(airline))}: the address on the dashboard did not open{when}, "
            "so it is not linked here. Use the dashboard link above.</li>"
        )

    others = [a for a in airlines if str(a["id"]) != aid]
    other_links = " &middot; ".join(
        f'<a class="tap" href="{bap._esc(str(a["id"]))}.html">{bap._esc(str(a["name"]))}</a>' for a in others
    )

    parts = [
        bap._render_head(title=title, description=description, canonical=canonical, breadcrumb=breadcrumb),
        "<body>",
        _header(),
        '    <main id="main-content" class="airport-main">',
        f'      <h1 class="airport-page-title">{bap._esc(name)} delay and cancellation commitments</h1>',
        f'      <p class="airport-purpose">{bap._esc(purpose)}</p>',
        *commit_section,
        '      <section class="airport-section" aria-labelledby="covers-heading">',
        '        <h2 id="covers-heading">What this covers</h2>',
        (
            "        <p>The dashboard's commitments cover only delays and cancellations the airline causes. Its examples are "
            "maintenance or crew problems, cabin cleaning, baggage loading and fueling. The dashboard does not say what an "
            "airline gives when the cause is weather or air traffic control.</p>"
        ),
        f"        <p>{bap._esc(owed)}</p>",
        "      </section>",
        '      <section class="airport-section" aria-labelledby="refund-heading">',
        '        <h2 id="refund-heading">Refunds for cancelled flights are a different rule</h2>',
        f'        <p class="refund-line">{bap._esc(REFUND_SENTENCE)}</p>',
        f'        <p class="small">{bap._esc(PLAIN_READING)} {bap._esc(REFUND_ELIGIBLE)}</p>',
        "      </section>",
        '      <section class="airport-section" aria-labelledby="stuck-heading">',
        '        <h2 id="stuck-heading">If you are stuck now</h2>',
        '        <div class="stuck-note">',
        (
            '          <p>The <a class="tap" href="../stuck.html">I\'m stuck at the airport guide</a> walks through what to do, '
            "what to say at the counter and an email draft. It is plain-language help, not legal advice.</p>"
        ),
        (
            '          <p><a class="tap" href="../stuck.html#ask-first">Ask before you pay</a>: what to say to an agent about a meal or '
            "hotel, and what to ask for in writing.</p>"
        ),
        "        </div>",
        "      </section>",
        '      <section class="airport-section" aria-labelledby="sources-heading">',
        '        <h2 id="sources-heading">Where this page\'s data comes from</h2>',
        f'        <p class="last-checked">{_source_line(updated, read)}</p>',
        '        <ul class="airport-sources">',
        *sources,
        "        </ul>",
        (
            f'        <p class="small">The dashboard says it was last updated {bap._esc(updated)}. Airlines can change their plans after that, '
            "so check the airline's own plan for the current version.</p>"
        ),
        f'        <p class="small">Page built {bap._esc(build_date)}.</p>',
        "      </section>",
        '      <section class="airport-section" aria-labelledby="others-heading">',
        '        <h2 id="others-heading">Other airlines</h2>',
        f'        <p class="small">{other_links} &middot; <a class="tap" href="index.html">All airlines</a></p>',
        "      </section>",
        "    </main>",
        _footer(),
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


def render_index_page(
    airlines: list[dict[str, Any]],
    *,
    updated: str,
    read: str,
    build_date: str,
) -> str:
    n = len(airlines)
    listed = [a for a in airlines if _listed(a)]
    title = "Airline delay and cancellation commitments: what US airlines have committed to"
    description = (
        f"What {len(listed)} US airlines have committed to when they cause a delay or cancellation, from the U.S. DOT "
        "dashboard, with a page for each airline. Plain-language help, not legal advice."
    )
    canonical = f"{SITE_URL}/airlines/index.html"
    breadcrumb = _breadcrumb([
        ("Air Travel Desk", f"{SITE_URL}/"),
        ("Airline commitments", canonical),
    ])

    cards: list[str] = []
    for a in airlines:
        aid = str(a["id"])
        name = str(a["name"])
        yes, total = _counts(a)
        if _listed(a):
            line = f"Has committed to {yes} of {total} items on the DOT dashboard."
        else:
            line = "Not listed on the DOT dashboard."
        cards.append('          <li class="airport-index-card">')
        cards.append(f'            <a class="tap airport-index-link" href="{bap._esc(aid)}.html">{bap._esc(name)}</a>')
        cards.append(f'            <p class="airport-index-meta">{bap._esc(line)}</p>')
        cards.append("          </li>")

    parts = [
        bap._render_head(title=title, description=description, canonical=canonical, breadcrumb=breadcrumb),
        "<body>",
        _header(),
        '    <main id="main-content" class="airport-main">',
        '      <h1 class="airport-page-title">Airline delay and cancellation commitments</h1>',
        (
            f'      <p class="airport-purpose">Purpose: show what {len(listed)} US airlines have committed to when they cause a delay '
            f"or a cancellation, as the U.S. Department of Transportation lists it. {n - len(listed)} more "
            f"{'airline has' if n - len(listed) == 1 else 'airlines have'} a page but no table column on the dashboard. "
            "This is plain-language help, not legal advice.</p>"
        ),
        '      <section class="airport-section" aria-labelledby="airlines-heading">',
        f'        <h2 id="airlines-heading">{n} airlines</h2>',
        '        <ul class="airport-index-list">',
        *cards,
        "        </ul>",
        "      </section>",
        '      <section class="airport-section" aria-labelledby="read-heading">',
        '        <h2 id="read-heading">How to read these pages</h2>',
        '        <ul class="airport-sources">',
        "          <li>\"Has committed to\" means the airline listed it in its own customer service plan. It is not a promise from this site.</li>",
        "          <li>The commitments cover only delays and cancellations the airline causes, not weather or air traffic control.</li>",
        f"          <li>{bap._esc(REFUND_SENTENCE)}</li>",
        "          <li>Where this site says money is possibly owed, your airline decides every claim. This is not legal advice.</li>",
        "        </ul>",
        '        <p class="small">Stuck at an airport now? Use the <a class="tap" href="../stuck.html">I\'m stuck at the airport guide</a>. '
        'Before you pay for a meal or hotel, read <a class="tap" href="../stuck.html#ask-first">Ask before you pay</a>.</p>',
        "      </section>",
        '      <section class="airport-section" aria-labelledby="sources-heading">',
        '        <h2 id="sources-heading">Where this page\'s data comes from</h2>',
        f'        <p class="last-checked">{_source_line(updated, read)}</p>',
        '        <ul class="airport-sources">',
        (
            f'          <li><a class="tap" href="{bap._esc(DASHBOARD_URL)}" target="_blank" rel="noopener noreferrer">'
            "U.S. DOT Airline Cancellation and Delay Dashboard</a></li>"
        ),
        "        </ul>",
        f'        <p class="small">Page built {bap._esc(build_date)}.</p>',
        "      </section>",
        "    </main>",
        _footer(),
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


def render_sitemap_block(ids: list[str], build_date: str) -> str:
    urls = [f"{SITE_URL}/airlines/index.html"] + [f"{SITE_URL}/airlines/{i}.html" for i in ids]
    lines = [f"  {SITEMAP_BEGIN}"]
    for url in urls:
        lines.append(f"  <url><loc>{bap._esc(url)}</loc><lastmod>{bap._esc(build_date)}</lastmod></url>")
    lines.append(f"  {SITEMAP_END}")
    return "\n".join(lines)


def update_sitemap(sitemap_path: Path, ids: list[str], build_date: str) -> None:
    bap.update_sitemap_block(sitemap_path, render_sitemap_block(ids, build_date), SITEMAP_BEGIN, SITEMAP_END)


def build_pages(
    *,
    data_dir: Path,
    out_dir: Path,
    sitemap_path: Path | None = None,
    build_date: str | None = None,
) -> list[Path]:
    """Write one page per airline in dot-commitments.json plus index.html; optionally update the sitemap."""
    date_str = build_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dot = bap._load_json(data_dir / "dot-commitments.json")
    extra = bap._load_json(data_dir / "airline-pages.json")
    airlines = [a for a in (dot.get("airlines") or []) if isinstance(a, dict) and a.get("id") and a.get("name")]
    if not airlines:
        raise ValueError(f"No airlines found in {data_dir / 'dot-commitments.json'}")
    labels = dot.get("commitment_labels") or {}
    updated = str(dot.get("source_last_updated") or "unknown")
    reread = extra.get("dot_reread") or {}
    read = str(reread.get("date") or dot.get("read_by_lane_1") or "unknown")
    plan_info = extra.get("plan_links") or {}

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for airline in airlines:
        dest = out_dir / f"{airline['id']}.html"
        dest.write_text(
            render_airline_page(
                airline, airlines=airlines, labels=labels, updated=updated, read=read,
                plan_info=plan_info, build_date=date_str,
            ),
            encoding="utf-8",
        )
        written.append(dest)
    index_dest = out_dir / "index.html"
    index_dest.write_text(
        render_index_page(airlines, updated=updated, read=read, build_date=date_str), encoding="utf-8"
    )
    written.append(index_dest)

    if sitemap_path is not None:
        update_sitemap(sitemap_path, [str(a["id"]) for a in airlines], date_str)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build static airline pages and update sitemap.xml.")
    ap.add_argument("--data", default=str(ROOT / "data"), help="Directory containing data/*.json")
    ap.add_argument("--out", default=None, help="Output directory for airline HTML pages (default: airlines/)")
    ap.add_argument("--sitemap", default=None, help="Path to sitemap.xml (default: sitemap.xml when --out is default)")
    ap.add_argument("--date", default=None, help="Override UTC build date (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    out_dir = Path(args.out) if args.out is not None else ROOT / "airlines"
    if args.sitemap is not None:
        sitemap_path: Path | None = Path(args.sitemap) if args.sitemap else None
    elif args.out is None:
        sitemap_path = ROOT / "sitemap.xml"
    else:
        sitemap_path = None

    written = build_pages(data_dir=Path(args.data), out_dir=out_dir, sitemap_path=sitemap_path, build_date=args.date)
    print(f"build_airline_pages: wrote {len(written)} files to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
