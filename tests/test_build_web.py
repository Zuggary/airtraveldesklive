import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import build_web  # noqa: E402
FX = ROOT / "tests" / "fixtures"


class TestBuildWeb(unittest.TestCase):
    def test_first_and_change_runs(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            p1 = build_web.build(out, {}, (FX / "faa-1.xml").read_text(), (FX / "adsb-7700-synthetic.json").read_text(), {}, True)
            self.assertEqual(len(p1["board"]), 30)
            self.assertTrue(p1["last_lines"][0]["text"].startswith("Right now:"))
            prev = json.loads((out / "state.json").read_text())
            p2 = build_web.build(out, prev, (FX / "faa-2.xml").read_text(), '{"ac":[]}', {"JFK": ["Severe Thunderstorm Warning"]}, True)
            texts = [l["text"] for l in p2["last_lines"]]
            self.assertTrue(any("ground stop at J F K" in t for t in texts))
            self.assertTrue(any("Boston Logan has ended" in t for t in texts))
            jfk = [e for e in p2["events"] if e.get("airport") == "JFK"][0]
            self.assertEqual(jfk["status"], "CONFIRMED")
            self.assertLessEqual(len(p2["last_lines"]), build_web.MAX_LINES)
            for line in texts:
                self.assertTrue(line.endswith("per the FAA.") or line.endswith("Source: adsb.lol."), line)


if __name__ == "__main__":
    unittest.main()
