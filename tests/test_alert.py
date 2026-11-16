"""Breaking-news block: alert.js is wired into the pages and the deploy allowlist, reads only its own data file, writes text only, and the
data file in the repo is well formed (and, while active, not expired by the time it is built)."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


class Alert(unittest.TestCase):
    def test_script_is_text_only_and_reads_only_its_data_file(self):
        js = (ROOT / "alert.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("document.write", js)
        self.assertNotIn("localStorage", js)
        self.assertNotIn("document.cookie", js)
        self.assertEqual(re.findall(r'fetch\("([^"?]+)', js), ["/data/alert.json"])

    def test_wired_into_home_and_stuck_once(self):
        for page in ("index.html", "stuck.html"):
            self.assertEqual((ROOT / page).read_text(encoding="utf-8").count('<script src="/alert.js" defer></script>'), 1, page)

    def test_deploy_allowlist_ships_both_files(self):
        yml = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        self.assertRegex(yml, r"for file in [^;]*\balert\.js\b")
        self.assertRegex(yml, r"for f in [^;]*\balert\.json\b")

    def test_data_file_is_well_formed(self):
        d = json.loads((ROOT / "data" / "alert.json").read_text(encoding="utf-8"))
        self.assertIn(d["level"], ("warning", "watch"))
        self.assertTrue(0 < len(d["headline"]) <= 160)
        for s in d.get("sources", []):
            self.assertTrue(s["url"].startswith("https://"), s)
        self.assertLessEqual(len(d.get("points", [])), 5)

    @unittest.skipUnless(NODE, "node not installed")
    def test_node_checks_pass(self):
        r = subprocess.run([NODE, str(ROOT / "tests" / "node" / "test_alert.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
