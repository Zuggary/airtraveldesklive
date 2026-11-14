"""Check the airport guide links with HTTP HEAD and write a report (AN23 phase 1, item 2).

This is a report, not a gate: the build never fails because of it. Some airport sites block
scripts, so a failed check does not prove a link is broken. The report goes to data/link-report.json,
which is a build artifact and is not committed.

Polite by design: one HEAD request per URL, one URL at a time, a pause between requests to the
same host, a short timeout, a cap on the number of URLs, and a User-Agent that names the site.

Usage: python tools/check_links.py [--guide data/airport-guide.json] [--out data/link-report.json]
                                    [--min-age-hours 24] [--limit 600]
Stdlib only. Tests use a fake opener; they make no network calls.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "AirTravelDeskLinkCheck/1.0 (+https://www.airtraveldesklive.com/about.html)"
TIMEOUT_S = 10
HOST_PAUSE_S = 1.5

Opener = Callable[[urllib.request.Request, float], Any]


def collect_links(guide: dict[str, Any]) -> list[dict[str, str]]:
    """Every http(s) guide link as {code, label, url}, in file order."""
    out: list[dict[str, str]] = []
    for code, entry in (guide.get("airports") or {}).items():
        for item in (entry or {}).get("links") or []:
            url = str((item or {}).get("url") or "").strip()
            parts = urllib.parse.urlsplit(url)
            if parts.scheme in ("http", "https") and parts.netloc:
                out.append({"code": code, "label": str(item.get("label") or ""), "url": url})
    return out


def default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 (http/https only, checked by collect_links)


def check_url(url: str, opener: Opener = default_opener, timeout: float = TIMEOUT_S, method: str = "HEAD") -> dict[str, Any]:
    """One request (HEAD by default; GET reads only the response headers). Returns {status, ok, error}. Never raises."""
    request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    try:
        resp = opener(request, timeout)
        status = int(getattr(resp, "status", None) or resp.getcode())
        close = getattr(resp, "close", None)
        if callable(close):
            close()
        return {"status": status, "ok": 200 <= status < 400, "error": ""}
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:  # a redirect this opener did not follow (for example 308): the site answered
            return {"status": exc.code, "ok": True, "error": ""}
        return {"status": exc.code, "ok": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # timeout, DNS, TLS, anything else
        return {"status": None, "ok": False, "error": type(exc).__name__}


def run_checks(
    links: list[dict[str, str]],
    opener: Opener = default_opener,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    limit: int = 600,
    host_pause: float = HOST_PAUSE_S,
    method: str = "HEAD",
) -> list[dict[str, Any]]:
    """Check each distinct URL once, pausing between requests to the same host."""
    results: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    last_hit: dict[str, float] = {}
    for link in links:
        url = link["url"]
        if url not in seen:
            if len(seen) >= limit:
                continue
            host = urllib.parse.urlsplit(url).netloc.lower()
            wait = host_pause - (clock() - last_hit[host]) if host in last_hit else 0
            if wait > 0:
                sleep(wait)
            seen[url] = check_url(url, opener, method=method)
            last_hit[host] = clock()
        results.append({**link, **seen[url]})
    return results


def build_report(results: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    return {
        "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "HTTP HEAD, one request per URL",
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "note": "A failed check can mean the site blocks scripts. It does not prove the link is broken.",
        "results": results,
    }


def report_is_fresh(path: Path, min_age_hours: float, now: datetime | None = None) -> bool:
    """True when a report exists and is newer than min_age_hours."""
    if min_age_hours <= 0 or not path.is_file():
        return False
    try:
        checked = json.loads(path.read_text(encoding="utf-8")).get("checked_utc", "")
        when = datetime.strptime(checked, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (OSError, ValueError, AttributeError):
        return False
    return (now or datetime.now(timezone.utc)) - when < timedelta(hours=min_age_hours)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HEAD-check the airport guide links and write a report.")
    ap.add_argument("--guide", default=str(ROOT / "data" / "airport-guide.json"))
    ap.add_argument("--links", default=None, help="Airport website links for the other 70 airports (default: airports-links.json next to the guide file)")
    ap.add_argument("--out", default=str(ROOT / "data" / "link-report.json"))
    ap.add_argument("--min-age-hours", type=float, default=0, help="Skip when the report is newer than this")
    ap.add_argument("--limit", type=int, default=600)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if report_is_fresh(out, args.min_age_hours):
        print(f"check_links: {out} is newer than {args.min_age_hours} hours; skipped")
        return 0
    try:
        guide = json.loads(Path(args.guide).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"check_links: cannot read the guide file ({exc}); no report written")
        return 0
    links = collect_links(guide)
    try:
        extra = json.loads((Path(args.links) if args.links else Path(args.guide).with_name("airports-links.json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        extra = {}
    links += collect_links({"airports": {c: {"links": [{"label": "Airport website", "url": (e or {}).get("home_link")}]}
                                         for c, e in (extra.get("airports") or {}).items()}})
    report = build_report(run_checks(links, limit=args.limit))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"check_links: {report['ok']} ok, {report['failed']} failed of {report['total']}; wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
