from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.check_site import broken_references


ROOT = Path(__file__).resolve().parents[1]


class CheckSiteTests(unittest.TestCase):
    def test_fixture_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            files = {
                "index.html": """
                    <a href="/stuck?reason=late#help">Help</a>
                    <a href="/help/">Help index</a>
                    <a href="#top">Top</a>
                    <a href="mailto:example@example.invalid">Email</a>
                    <a href="tel:5550100">Call</a>
                    <a href="//example.invalid/no-file">External</a>
                    <link rel="stylesheet" href="/assets/site.css">
                    <link rel="manifest" href="/assets/manifest.json">
                    <script src="/assets/site.js"></script>
                    <style>p { background: url('/assets/picture.webp'); }</style>
                    <picture>
                      <source srcset="data:image/png;base64,AAAA 1x, /assets/picture.webp 2x">
                      <img src="/assets/picture.webp"
                           style="background: url(/assets/picture.webp)">
                    </picture>
                    <a href="/data/live.json">Optional feed</a>
                """,
                "stuck.html": '<a href="/">Home</a>',
                "help/index.html": '<a href="../stuck">Help</a>',
                "assets/site.css": """
                    @import "nested.css";
                    p { background: url(picture.webp?cache=1); }
                """,
                "assets/nested.css": "",
                "assets/site.js": """
                    fetch('/data/demo.json');
                    const picture = "/assets/picture.webp";
                    // '/data/obsolete.json'
                """,
                "assets/manifest.json": "{}",
                "assets/picture.webp": "",
                "data/demo.json": "{}",
            }
            for name, content in files.items():
                path = site / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            command = [sys.executable, str(ROOT / "tools/check_site.py"), "--site", directory]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, "")

            additions = {
                "help/index.html": '<a href="../missing#help">Missing</a>',
                "index.html": '<img srcset="/assets/picture.webp 1x, /assets/missing.webp 2x">',
                "assets/nested.css": 'p { background: url("missing.png"); }',
                "assets/site.js": """fetch("/data/missing.json?cache=1");""",
            }
            for name, content in additions.items():
                with (site / name).open("a", encoding="utf-8") as stream:
                    stream.write(content)

            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [
                "assets/nested.css -> missing.png",
                "assets/site.js -> /data/missing.json?cache=1",
                "help/index.html -> ../missing#help",
                "index.html -> /assets/missing.webp",
            ])

    def test_existing_publish_tree(self):
        site = ROOT / "_site"
        if not site.is_dir():
            self.skipTest("_site is absent")
        self.assertEqual(broken_references(site), [])
