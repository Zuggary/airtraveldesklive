import json, sys, tempfile, unittest, urllib.error
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import build_places  # noqa: E402
FX = ROOT / "tests" / "fixtures"
SFO = (37.621, -122.379)


class TestParse(unittest.TestCase):
    def setUp(self):
        self.out = build_places.parse_places((FX / "overpass-sample-synthetic.json").read_text(), *SFO)

    def test_hotels_sorted_by_distance_and_filtered(self):
        names = [h["name"] for h in self.out["hotels"]]
        self.assertEqual(names, ["Fixture Hotel One", "Fixture Motel Two"])  # dupe, nameless, far, hostel dropped
        kms = [h["km"] for h in self.out["hotels"]]
        self.assertEqual(kms, sorted(kms))
        self.assertLess(kms[0], 0.2)

    def test_websites_only_http_and_https(self):
        by = {h["name"]: h for h in self.out["hotels"] + self.out["cars"]}
        self.assertEqual(by["Fixture Hotel One"]["website"], "https://example.test/one")
        self.assertEqual(by["Fixture Motel Two"]["website"], "http://example.test/two")  # from contact:website
        self.assertNotIn("website", by["Fixture Rental A"])   # ftp
        self.assertNotIn("website", by["Fixture Rental B"])   # no scheme
        self.assertEqual(by["Fixture Rental C"]["website"], "https://example.test/c")

    def test_cars(self):
        self.assertEqual([c["name"] for c in self.out["cars"]], ["Fixture Rental C", "Fixture Rental A", "Fixture Rental B"])

    def test_limits(self):
        els = [{"type": "node", "id": i, "lat": SFO[0] + i * 0.001, "lon": SFO[1], "tags": {"tourism": "hotel", "name": f"H{i}"}} for i in range(1, 15)]
        els += [{"type": "node", "id": 100 + i, "lat": SFO[0] + i * 0.001, "lon": SFO[1], "tags": {"amenity": "car_rental", "name": f"C{i}"}} for i in range(1, 15)]
        out = build_places.parse_places({"elements": els}, *SFO)
        self.assertEqual(len(out["hotels"]), build_places.MAX_HOTELS)
        self.assertEqual(len(out["cars"]), build_places.MAX_CARS)
        self.assertEqual(out["hotels"][0]["name"], "H1")

    def test_query_shape(self):
        q = build_places.build_query(*SFO)
        self.assertIn("around:5000,37.621,-122.379", q)
        self.assertIn("car_rental", q)
        self.assertIn("hotel|motel", q)

    def test_haversine(self):
        self.assertAlmostEqual(build_places.haversine_km(0, 0, 0, 1), 111.19, places=1)


class TestUpdate(unittest.TestCase):
    def test_weekly_refresh_rule(self):
        calls = []
        def fake(q):
            calls.append(q)
            return (FX / "overpass-sample-synthetic.json").read_text()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            now = 1_800_000_000.0
            self.assertEqual(build_places.update(out, now=now, fetcher=fake, pause=0), "ok")
            self.assertEqual(len(calls), 30)
            data = json.loads((out / "places.json").read_text())
            self.assertEqual(len(data["airports"]), 30)
            self.assertIn("OpenStreetMap contributors", data["source"])
            self.assertEqual(build_places.update(out, now=now + 6 * 86400, fetcher=fake, pause=0), "skip")
            self.assertEqual(len(calls), 30)
            self.assertEqual(build_places.update(out, now=now + 8 * 86400, fetcher=fake, pause=0), "ok")
            self.assertEqual(len(calls), 60)

    def test_failure_keeps_old_airport_data(self):
        good = (FX / "overpass-sample-synthetic.json").read_text()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            build_places.update(out, now=1_800_000_000.0, fetcher=lambda q: good, pause=0)
            def flaky(q):
                if "37.621,-122.379" in q:
                    raise ValueError("boom")
                return good
            res = build_places.update(out, now=1_800_000_000.0 + 9 * 86400, fetcher=flaky, pause=0)
            self.assertEqual(res, "partial")
            data = json.loads((out / "places.json").read_text())
            self.assertEqual(len(data["airports"]["SFO"]["hotels"]), 2)

    def test_total_failure_writes_nothing(self):
        def bad(q):
            raise ValueError("down")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(build_places.update(Path(d), now=1.0, fetcher=bad, pause=0), "error")
            self.assertFalse((Path(d) / "places.json").exists())


class TestCommittedFile(unittest.TestCase):
    def test_committed_places_file_if_present(self):
        p = ROOT / "data" / "places.json"
        if not p.is_file():
            self.skipTest("no committed places.json")
        data = json.loads(p.read_text())
        self.assertEqual(len(data["airports"]), 30)
        for code, v in data["airports"].items():
            self.assertLessEqual(len(v["hotels"]), 8)
            self.assertLessEqual(len(v["cars"]), 6)
            for item in v["hotels"] + v["cars"]:
                self.assertTrue(item["name"])
                self.assertLessEqual(item["km"], 5.2)
                if "website" in item:
                    self.assertRegex(item["website"], r"^https?://")


if __name__ == "__main__":
    unittest.main()
