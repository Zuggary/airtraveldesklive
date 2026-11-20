"""Check local URL references in the GitHub Pages publish directory."""

import argparse
from html.parser import HTMLParser
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote, urlsplit


OPTIONAL_DATA = {"/data/live.json", "/data/link-report.json", "/data/security-waits.json"}
JS_TOKEN = re.compile(
    r"""//[^\r\n]*|/\*[\s\S]*?\*/|"(?P<double>[^"\\]*(?:\\.[^"\\]*)*)"|'(?P<single>[^'\\]*(?:\\.[^'\\]*)*)'|`[^`\\]*(?:\\.[^`\\]*)*`"""
)
JS_PATH = re.compile(r"/(?:data|assets|help|airports|airlines|stories|fonts|brand)/[^\s\\]+")
CSS_URL = re.compile(
    r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*?))\s*\)|@import\s+(?:"([^"]*)"|'([^']*)')""",
    re.IGNORECASE,
)


def js_urls(script):
    for token in JS_TOKEN.finditer(script):
        target = token["double"] or token["single"]
        if target and JS_PATH.fullmatch(target):
            yield target


def css_urls(css):
    for match in CSS_URL.finditer(re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)):
        yield next(part for part in match.groups() if part is not None)


def srcset_urls(value):
    # A URL token can contain commas, notably in a data URI. A trailing
    # comma ends a candidate without a descriptor.
    while value := value.lstrip(" \t\r\n\f,"):
        candidate = re.match(r"\S+", value).group()
        yield candidate.rstrip(",")
        value = value[len(candidate):]
        if not candidate.endswith(","):
            _, _, value = value.partition(",")


class PageReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.stylesheets = []
        self.in_style = False
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = {key: value or "" for key, value in attrs}
        self.urls.extend(attrs[key] for key in ("href", "src") if key in attrs)
        self.urls.extend(srcset_urls(attrs.get("srcset", "")))
        self.urls.extend(srcset_urls(attrs.get("imagesrcset", "")))
        self.urls.extend(css_urls(attrs.get("style", "")))
        if tag == "link" and "stylesheet" in attrs.get("rel", "").lower().split():
            self.stylesheets.append(attrs.get("href", ""))
        if tag == "style":
            self.in_style = True
        if tag == "script":
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_style:
            self.urls.extend(css_urls(data))
        if self.in_script:
            self.urls.extend(js_urls(data))


def resolve(site, page, target):
    parts = urlsplit(target.strip())
    if parts.scheme or parts.netloc or not parts.path:
        return None
    path = unquote(parts.path)
    if not path.startswith("/"):
        path = posixpath.join("/", page.parent.relative_to(site).as_posix(), path)
    normalized = "/" + posixpath.normpath(path).lstrip("/")
    local = site / normalized.lstrip("/")
    candidates = (local / "index.html",) if path.endswith("/") else (
        local, local.with_suffix(local.suffix + ".html") if local != site else local,
        local / "index.html",
    )
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve().is_relative_to(site):
            return candidate
    if normalized not in OPTIONAL_DATA:
        return False
    return None


def broken_references(site):
    site = site.resolve()
    broken = set()
    checked_css = set()

    def check(page, target, stylesheet=False):
        local = resolve(site, page, target)
        if local is False:
            broken.add((page.relative_to(site).as_posix(), target))
        elif local is not None and (stylesheet or local.suffix.lower() == ".css"):
            if local not in checked_css:
                checked_css.add(local)
                for url in css_urls(local.read_text(encoding="utf-8")):
                    check(local, url)

    for page in sorted(site.rglob("*.html")):
        parser = PageReferences()
        parser.feed(page.read_text(encoding="utf-8"))
        parser.close()
        for target in parser.urls:
            check(page, target, target in parser.stylesheets)

    for script in sorted(site.rglob("*.js")):
        for target in js_urls(script.read_text(encoding="utf-8")):
            check(script, target)

    return sorted(broken)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, type=Path)
    args = parser.parse_args()
    if not args.site.is_dir():
        parser.error(f"site directory does not exist: {args.site}")
    broken = broken_references(args.site)
    for page, target in broken:
        print(f"{page} -> {target}")
    return int(bool(broken))


if __name__ == "__main__":
    raise SystemExit(main())
