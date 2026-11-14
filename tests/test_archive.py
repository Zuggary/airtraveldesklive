"""Tests for the history archive: tools/archive_{lib,hourly,backfill,backup}.py. No network, no real archive."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import archive_backfill as bf  # noqa: E402
import archive_backup as bk  # noqa: E402
import archive_hourly as hourly  # noqa: E402
import archive_lib as lib  # noqa: E402

RUN = datetime(2026, 11, 14, 10, 12, 0, tzinfo=timezone.utc)


def files_fixture(updated="2026-11-14T10:05:00Z", obs="2026-11-14T09:52:00Z", wx_fetched="2026-11-14T10:05:00Z"):
    return {
        "airports": {"updated_utc": updated, "airports": {
            "ATL": {"code": "ATL", "level": "clear", "reason": "", "events": [],
                    "wx": {"cat": "VFR", "obs_utc": obs, "wind_kt": 9.0}},
            "LGA": {"code": "LGA", "level": "stop", "reason": "thunderstorms; low ceilings", "events": [
                {"kind": "ground_stop", "reason": "thunderstorms", "avg": ""},
                {"kind": "delay", "reason": "low ceilings", "avg": "1 hour and 15 minutes"}]},
            "SFO": {"code": "SFO", "level": "delay", "reason": "low ceilings", "events": [
                {"kind": "ground_delay", "reason": "low ceilings", "avg": "45 minutes"}]},
            "SNA": {"code": "SNA", "level": "stop", "reason": "closed", "events": [{"kind": "closure"}]},
        }},
        "state": {"updated_utc": updated, "board": [
            {"code": "ATL", "level": "green", "status": "green", "avg_min": None},
            {"code": "SFO", "level": "amber", "status": "amber", "avg_min": 45}]},
        "wx": {"fetched_utc": wx_fetched, "hubs": {
            "ATL": {"cat": "VFR", "obs_utc": obs, "wind_kt": 9.0, "gust_kt": None, "vis_sm": 10.0, "ceiling_ft": None, "temp_f": 55},
            "LGA": {"cat": "IFR", "obs_utc": obs, "wind_kt": 20.0, "gust_kt": 30.0, "vis_sm": 2.0, "ceiling_ft": 400}}},
        "tsa": {"fetched_utc": "2026-11-14T09:45:06Z", "latest_date": "2026-11-12", "latest_count": 2484345},
    }


def fake_fetcher(files):
    def f(name):
        v = files.get(name)
        if v is None:
            return None
        return json.loads(json.dumps(v))
    return f


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.arch = self.tmp / "arch"
        self.addCleanup(self._tmp.cleanup)

    def go(self, files=None, now=RUN):
        return hourly.run(self.arch, fetcher=fake_fetcher(files or files_fixture()), now=now, pause=0)

    def row(self, hour, code):
        return lib.read_month(lib.month_file(self.arch, hour[:7])).get(f"{hour}|{code}")


class TestRows(Base):
    def test_row_building(self):
        rows = {r["airport"]: r for r in hourly.build_rows(files_fixture(), RUN)}
        self.assertEqual(set(rows), {"ATL", "LGA", "SFO", "SNA", "NATIONAL"})
        atl = rows["ATL"]
        self.assertEqual((atl["k"], atl["hour_utc"], atl["cat"], atl["temp_f"]), ("2026-11-14T10:00Z|ATL", "2026-11-14T10:00Z", "VFR", 55))
        self.assertEqual(atl["faa_updated_utc"], "2026-11-14T10:05:00Z")
        self.assertEqual(atl["wx_obs_utc"], "2026-11-14T09:52:00Z")
        self.assertEqual(atl["run_utc"], "2026-11-14T10:12:00Z")
        self.assertEqual(atl["source"], "live")
        self.assertNotIn("stale", atl)
        lga = rows["LGA"]
        self.assertTrue(lga["ground_stop"] and lga["delay"] and not lga["closure"])
        self.assertEqual((lga["delay_min"], lga["reason"], lga["vis_sm"], lga["ceiling_ft"], lga["gust_kt"]), (75, "thunderstorms; low ceilings", 2.0, 400, 30.0))
        sfo = rows["SFO"]
        self.assertTrue(sfo["ground_delay"] and not sfo["ground_stop"])
        self.assertEqual((sfo["delay_min"], sfo["faa_status"]), (45, "amber"))
        self.assertTrue(rows["SNA"]["closure"])

    def test_national_row(self):
        nat = [r for r in hourly.build_rows(files_fixture(), RUN) if r["type"] == "national"][0]
        self.assertEqual((nat["n_airports"], nat["n_ground_stop"], nat["n_ground_delay"], nat["n_delay"], nat["n_closure"]), (4, 1, 1, 1, 1))
        self.assertEqual((nat["tsa_count"], nat["tsa_date"]), (2484345, "2026-11-12"))

    def test_tsa_dropped_when_not_fresh(self):
        f = files_fixture()
        f["tsa"]["fetched_utc"] = "2026-11-10T09:45:06Z"
        nat = [r for r in hourly.build_rows(f, RUN) if r["type"] == "national"][0]
        self.assertNotIn("tsa_count", nat)
        f["tsa"] = None
        nat = [r for r in hourly.build_rows(f, RUN) if r["type"] == "national"][0]
        self.assertNotIn("tsa_count", nat)

    def test_stale_marking(self):
        f = files_fixture(updated="2026-11-14T09:20:00Z")  # 52 minutes old
        rows = hourly.build_rows(f, RUN)
        self.assertTrue(all(r.get("stale") is True for r in rows))
        self.assertIn("faa", rows[0]["stale_why"])
        edge = hourly.build_rows(files_fixture(updated="2026-11-14T09:42:00Z"), RUN)  # exactly 30 minutes: fresh
        self.assertFalse(any(r.get("stale") for r in edge))

    def test_stale_wx_marks_airport_rows(self):
        rows = hourly.build_rows(files_fixture(wx_fetched="2026-11-14T08:00:00Z"), RUN)
        self.assertTrue(all(r.get("stale") for r in rows if r["type"] == "airport"))
        self.assertIn("wx", rows[0]["stale_why"])

    def test_fetch_failure_writes_nothing(self):
        def boom(name):
            raise OSError("down")
        res = hourly.run(self.arch, fetcher=boom, now=RUN, pause=0)
        self.assertFalse(res["ok"])
        self.assertEqual(lib.month_files(self.arch), [])

    def test_missing_tsa_is_not_fatal(self):
        f = files_fixture()
        f["tsa"] = None
        res = self.go(f)
        self.assertTrue(res["ok"])
        self.assertEqual(res["added"], 5)

    def test_only_own_site_urls(self):
        self.assertTrue(hourly.BASE.startswith("https://www.airtraveldesklive.com/"))
        self.assertIn("airtraveldesklive", hourly.USER_AGENT)


class TestUpsert(Base):
    def test_update_only_when_newer(self):
        self.go(files_fixture(updated="2026-11-14T10:05:00Z"))
        before = self.row("2026-11-14T10:00Z", "LGA")
        res = self.go(files_fixture(updated="2026-11-14T10:05:00Z"), now=RUN.replace(minute=40))
        self.assertEqual((res["added"], res["updated"]), (0, 0))   # same data, same hour: kept
        self.assertEqual(self.row("2026-11-14T10:00Z", "LGA"), before)
        newer = files_fixture(updated="2026-11-14T10:35:00Z", obs="2026-11-14T10:20:00Z", wx_fetched="2026-11-14T10:35:00Z")
        res = self.go(newer, now=RUN.replace(minute=41))
        self.assertEqual(res["updated"], 5)
        self.assertEqual(self.row("2026-11-14T10:00Z", "LGA")["faa_updated_utc"], "2026-11-14T10:35:00Z")
        older = files_fixture(updated="2026-11-14T10:01:00Z", obs="2026-11-14T09:40:00Z", wx_fetched="2026-11-14T10:01:00Z")
        res = self.go(older, now=RUN.replace(minute=50))
        self.assertEqual(res["updated"], 0)
        self.assertEqual(self.row("2026-11-14T10:00Z", "LGA")["faa_updated_utc"], "2026-11-14T10:35:00Z")

    def test_flag_seen_earlier_in_hour_is_kept(self):
        self.go()                                                    # LGA ground stop at 10:12
        clear = files_fixture(updated="2026-11-14T10:35:00Z", obs="2026-11-14T10:20:00Z", wx_fetched="2026-11-14T10:35:00Z")
        clear["airports"]["airports"]["LGA"].update(level="clear", reason="", events=[])
        self.go(clear, now=RUN.replace(minute=41))
        lga = self.row("2026-11-14T10:00Z", "LGA")
        self.assertEqual(lga["faa_updated_utc"], "2026-11-14T10:35:00Z")   # newest data
        self.assertTrue(lga["ground_stop"] and lga["delay"])               # flags seen earlier in the hour stay on
        self.assertEqual(lga["flags_from_earlier"], ["delay", "ground_stop"])
        self.assertEqual(lga["faa_level"], "clear")
        self.assertEqual(lga["reason"], "thunderstorms; low ceilings")

    def test_stale_row_never_replaces_fresh(self):
        self.go()
        stale = files_fixture(updated="2026-11-14T09:00:00Z", obs="2026-11-14T08:50:00Z", wx_fetched="2026-11-14T09:00:00Z")
        self.go(stale, now=RUN.replace(minute=50))
        self.assertNotIn("stale", self.row("2026-11-14T10:00Z", "ATL"))

    def test_monthly_rollover(self):
        self.go(now=datetime(2026, 11, 30, 23, 12, tzinfo=timezone.utc))
        self.go(files_fixture(updated="2026-12-01T00:05:00Z", obs="2026-12-01T00:00:00Z", wx_fetched="2026-12-01T00:05:00Z"),
                now=datetime(2026, 12, 1, 0, 12, tzinfo=timezone.utc))
        self.assertEqual([p.name for p in lib.month_files(self.arch)], ["2026-11.jsonl", "2026-12.jsonl"])
        self.assertIsNotNone(self.row("2026-11-30T23:00Z", "ATL"))
        self.assertIsNotNone(self.row("2026-12-01T00:00Z", "ATL"))
        self.assertEqual(len(lib.read_month(self.arch / "2026-11.jsonl")), 5)

    def test_file_is_plain_jsonl_utc(self):
        self.go()
        for line in (self.arch / "2026-11.jsonl").read_text().splitlines():
            r = json.loads(line)
            self.assertTrue(r["hour_utc"].endswith("Z"))

    def test_atomic_write_interrupted_keeps_old_file(self):
        self.go()
        path = self.arch / "2026-11.jsonl"
        old = path.read_bytes()
        newer = files_fixture(updated="2026-11-14T10:35:00Z", obs="2026-11-14T10:20:00Z", wx_fetched="2026-11-14T10:35:00Z")
        with mock.patch("archive_lib.os.replace", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                self.go(newer, now=RUN.replace(minute=41))
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual([p.name for p in self.arch.iterdir() if p.name.endswith(".tmp")], [])

    def test_atomic_write_fails_midway(self):
        path = self.arch / "2026-11.jsonl"
        lib.write_month_atomic(path, {"a": {"k": "a", "x": 1}})
        old = path.read_bytes()

        class Bad:
            def __getitem__(self, k):
                raise RuntimeError("boom")
        rows = {"b": {"k": "b"}, "c": object()}   # object() is not JSON serializable
        with self.assertRaises(TypeError):
            lib.write_month_atomic(path, rows)
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual([p for p in self.arch.iterdir() if p.name.endswith(".tmp")], [])


def desk_fixture(root: Path):
    h = root / "hist"
    h.mkdir()

    def w(name, rows):
        (h / name).write_text("".join(json.dumps(r) + "\n" for r in rows))
    w("board.jsonl", [
        {"hour_utc": "2026-11-14T09:00Z", "code": "ATL", "level": "green", "avg_min": None, "t_utc": "2026-11-14T09:37:16Z"},
        {"hour_utc": "2026-11-14T22:00Z", "code": "LGA", "level": "red", "avg_min": None, "t_utc": "2026-11-14T22:00:04Z"},
        {"hour_utc": "2026-11-14T22:00Z", "code": "LGA", "level": "red", "avg_min": None, "t_utc": "2026-11-14T22:30:04Z"},
        {"hour_utc": "2026-11-14T10:00Z", "code": "ATL", "level": "green", "avg_min": None, "t_utc": "2026-11-14T10:37:16Z"}])
    w("wx.jsonl", [
        {"hour_utc": "2026-11-14T09:00Z", "code": "ATL", "wind_kt": 9.0, "gust_kt": None, "cat": "VFR", "obs_utc": "2026-11-14T08:52:00Z", "t_utc": "2026-11-14T09:37:16Z", "temp_f": 50, "vis_sm": 10.0},
        {"hour_utc": "2026-11-14T22:00Z", "code": "LGA", "wind_kt": 25.0, "gust_kt": 35.0, "cat": "IFR", "obs_utc": "2026-11-14T21:51:00Z", "t_utc": "2026-11-14T22:00:04Z"}])
    w("faa-hourly.jsonl", [
        {"t_utc": "2026-11-14T22:00:30Z", "hour_utc": "2026-11-14T22:00Z", "ground_stop": 1, "ground_delay": 0, "delay": 0, "closure": 0, "airports": ["LGA"]},
        {"t_utc": "2026-11-14T05:00:29Z", "hour_utc": "2026-11-14T05:00Z", "ground_stop": 0, "ground_delay": 1, "delay": 1, "closure": 0, "airports": ["SAN", "SFO"]},
        {"t_utc": "2026-11-14T06:00:29Z", "hour_utc": "2026-11-14T06:00Z", "ground_stop": 0, "ground_delay": 0, "delay": 0, "closure": 0, "airports": []}])
    w("tsa.jsonl", [{"date": "2026-11-12", "count": 2484345, "t_utc": "2026-11-14T09:37:16Z"}])
    return h


class TestBackfill(Base):
    def test_backfill_rows_and_counts(self):
        h = desk_fixture(self.tmp)
        res = bf.run(h, self.arch)
        self.assertTrue(res["ok"])
        lga = self.row("2026-11-14T22:00Z", "LGA")
        self.assertEqual(lga["source"], "desk-log")
        self.assertTrue(lga["ground_stop"])
        self.assertEqual((lga["faa_level"], lga["cat"], lga["gust_kt"], lga["wx_obs_utc"]), ("stop", "IFR", 35.0, "2026-11-14T21:51:00Z"))
        self.assertEqual(lga["faa_updated_utc"], "2026-11-14T22:30:04Z")      # latest duplicate wins
        self.assertEqual(self.row("2026-11-14T09:00Z", "ATL")["temp_f"], 50)
        sfo = self.row("2026-11-14T05:00Z", "SFO")
        self.assertEqual(sfo["faa_event_kind"], "unknown")                    # two kinds that hour: not guessed
        self.assertNotIn("ground_stop", sfo)
        nat = self.row("2026-11-14T22:00Z", "NATIONAL")
        self.assertEqual((nat["n_ground_stop"], nat["source"]), (1, "desk-log"))
        self.assertEqual(nat["tsa_count"], 2484345)
        self.assertEqual(res["airports"], 4)   # ATL, LGA, SAN, SFO
        self.assertEqual(res["hours"], 5)      # 05, 06, 09, 10, 22
        self.assertEqual(bf.run(h, self.arch)["added"], 0)    # idempotent

    def test_backfill_skips_live_hours(self):
        h = desk_fixture(self.tmp)
        live = hourly.build_rows(files_fixture(updated="2026-11-14T09:05:00Z", obs="2026-11-14T08:52:00Z", wx_fetched="2026-11-14T09:05:00Z"),
                                 datetime(2026, 11, 14, 9, 12, tzinfo=timezone.utc))
        lib.upsert_rows(live, self.arch)
        res = bf.run(h, self.arch)
        atl = self.row("2026-11-14T09:00Z", "ATL")
        self.assertEqual(atl["source"], "live")
        self.assertGreaterEqual(res["kept"], 1)

    def test_missing_history_is_empty(self):
        res = bf.run(self.tmp / "nope", self.arch)
        self.assertEqual(res["rows_built"], 0)


class TestLoader(Base):
    def setUp(self):
        super().setUp()
        rows = []
        def add(hour, code, cat, **kw):
            r = {"k": f"{hour}|{code}", "type": "airport", "hour_utc": hour, "airport": code, "cat": cat,
                 "ground_stop": False, "ground_delay": False, "delay": False, "closure": False, "source": "live"}
            r.update(kw)
            rows.append(r)
        add("2026-10-31T23:00Z", "ATL", "VFR")
        add("2026-11-01T00:00Z", "ATL", "VFR")
        add("2026-11-01T01:00Z", "ATL", "IFR", ground_delay=True)
        add("2026-11-01T02:00Z", "ATL", "IFR", ground_stop=True)
        add("2026-11-01T05:00Z", "ATL", "VFR", delay=True, stale=True)   # stale: excluded from shares
        add("2026-11-01T00:00Z", "LGA", "MVFR")
        add("2026-12-01T00:00Z", "ATL", "VFR")
        rows.append({"k": "2026-11-01T00:00Z|NATIONAL", "type": "national", "hour_utc": "2026-11-01T00:00Z", "airport": "NATIONAL", "n_airports": 2})
        lib.upsert_rows(rows, self.arch)

    def test_iter_rows_ranges_and_filters(self):
        got = [(r["hour_utc"], r["airport"]) for r in lib.iter_rows("2026-11-01T00:00Z", "2026-11-01T02:00Z", directory=self.arch)]
        self.assertEqual(got, [("2026-11-01T00:00Z", "ATL"), ("2026-11-01T00:00Z", "LGA"), ("2026-11-01T01:00Z", "ATL")])
        self.assertEqual(len(list(lib.iter_rows("2026-11", "2026-12", directory=self.arch))), 5)
        self.assertEqual(len(list(lib.iter_rows(airports=["lga"], directory=self.arch))), 1)
        self.assertEqual(len(list(lib.iter_rows(kind="national", directory=self.arch))), 1)
        self.assertEqual(len(list(lib.iter_rows(kind="all", directory=self.arch))), 8)
        self.assertEqual(len(list(lib.iter_rows(datetime(2026, 11, 1, tzinfo=timezone.utc).date(), None, directory=self.arch))), 6)

    def test_hour_counts(self):
        c = lib.hour_counts(self.arch)
        self.assertEqual(c["2026-11-01T00:00Z"], 2)
        self.assertEqual(c["2026-11-01T01:00Z"], 1)
        self.assertEqual(len(c), 6)

    def test_delay_share_with_period(self):
        s = lib.delay_share("ATL", "2026-11", self.arch)
        self.assertEqual(s["archived_hours"], 3)
        self.assertEqual((s["hours_with_ground_stop"], s["hours_with_ground_delay"], s["hours_with_any_flag"]), (1, 1, 2))
        self.assertEqual(s["stale_rows_excluded"], 1)
        self.assertAlmostEqual(s["share_any_flag"], 0.6667, places=4)
        self.assertEqual(s["period"], {"first_hour_utc": "2026-11-01T00:00Z", "last_hour_utc": "2026-11-01T02:00Z"})
        both = lib.delay_share("ATL", ("2026-11", "2026-12"), self.arch)
        self.assertEqual(both["archived_hours"], 4)
        self.assertEqual(both["period"]["last_hour_utc"], "2026-12-01T00:00Z")
        none = lib.delay_share("ZZZ", "2026-11", self.arch)
        self.assertEqual((none["archived_hours"], none["share_any_flag"], none["period"]), (0, None, None))

    def test_category_by_month_counts_not_predictions(self):
        c = lib.category_by_month("ATL", self.arch)
        self.assertEqual(set(c), {"10", "11", "12"})
        self.assertEqual(c["11"]["counts"], {"IFR": 2, "VFR": 1})
        self.assertEqual(c["11"]["most_common"], "IFR")
        self.assertEqual(c["11"]["period"]["first_hour_utc"], "2026-11-01T00:00Z")
        self.assertEqual(lib.past_facts("ATL", "2026-11", self.arch)["delay"]["archived_hours"], 3)

    def test_stats_with_gaps(self):
        s = lib.archive_stats(self.arch)
        self.assertEqual((s["rows"], s["airport_rows"], s["national_rows"], s["airports"]), (8, 7, 1, 2))
        self.assertEqual((s["first_hour"], s["last_hour"]), ("2026-10-31T23:00Z", "2026-12-01T00:00Z"))
        self.assertEqual(s["hours_with_data"], 6)
        total_hours = 30 * 24 + 2          # Oct 31 23:00 to Dec 1 00:00, inclusive
        self.assertEqual(s["hours_with_gaps"], (total_hours) - 6)
        self.assertEqual(s["stale_rows"], 1)

    def test_stats_empty_archive(self):
        s = lib.archive_stats(self.tmp / "none")
        self.assertEqual((s["rows"], s["first_hour"], s["hours_with_gaps"]), (0, None, 0))

    def test_env_dir(self):
        with mock.patch.dict(os.environ, {"AN_ARCHIVE_DIR": str(self.arch)}):
            self.assertEqual(lib.archive_stats()["rows"], 8)


class TestBackup(Base):
    def setUp(self):
        super().setUp()
        self.dst = self.tmp / "bak"
        lib.write_month_atomic(self.arch / "2026-10.jsonl", {"a": {"k": "a", "hour_utc": "2026-10-01T00:00Z"}})
        lib.write_month_atomic(self.arch / "2026-11.jsonl", {"b": {"k": "b", "hour_utc": "2026-11-01T00:00Z"}})

    def test_backup_manifest_verify(self):
        res = bk.local_backup(self.arch, self.dst, today="2026-11-14")
        self.assertTrue(res["ok"])
        self.assertEqual((res["copied"], res["unchanged"]), (2, 0))
        man = bk.read_manifest(self.dst / "MANIFEST.sha256")
        self.assertEqual(set(man), {"2026-10.jsonl", "2026-11.jsonl"})
        self.assertEqual(man["2026-11.jsonl"][0], bk.sha256_file(self.arch / "2026-11.jsonl"))
        self.assertEqual(bk.verify(self.dst), [])
        self.assertTrue((self.dst / "manifests" / "MANIFEST-2026-11-14.sha256").exists())
        res2 = bk.local_backup(self.arch, self.dst, today="2026-11-14")
        self.assertEqual((res2["copied"], res2["unchanged"]), (0, 2))

    def test_changed_file_rotates_old_copy(self):
        bk.local_backup(self.arch, self.dst, today="2026-11-14")
        old = (self.dst / "files" / "2026-11.jsonl").read_bytes()
        lib.write_month_atomic(self.arch / "2026-11.jsonl", {"b": {"k": "b"}, "c": {"k": "c"}})
        res = bk.local_backup(self.arch, self.dst, today="2026-11-15")
        self.assertEqual(res["copied"], 1)
        self.assertEqual((self.dst / "rotated" / "2026-11.2026-11-15.jsonl").read_bytes(), old)
        self.assertEqual(bk.verify(self.dst), [])

    def test_rotation_limits(self):
        for i in range(10):
            lib.write_month_atomic(self.arch / "2026-11.jsonl", {"n": {"k": "n", "i": i}})
            bk.local_backup(self.arch, self.dst, today=f"2026-11-{10 + i:02d}")
        self.assertLessEqual(len(list((self.dst / "rotated").glob("2026-11.*.jsonl"))), bk.KEEP_ROTATED)

    def test_corruption_detected(self):
        bk.local_backup(self.arch, self.dst, today="2026-11-14")
        p = self.dst / "files" / "2026-11.jsonl"
        p.write_bytes(p.read_bytes().replace(b"b", b"X", 1))
        probs = bk.verify(self.dst)
        self.assertTrue(any("2026-11.jsonl" in x and "sha256" in x for x in probs), probs)
        (self.dst / "files" / "2026-10.jsonl").unlink()
        self.assertTrue(any("missing" in x for x in bk.verify(self.dst)))
        (self.dst / "files" / "2026-12.jsonl").write_text("{}\n")
        self.assertTrue(any("not in manifest" in x for x in bk.verify(self.dst)))

    def test_bad_copy_is_refused(self):
        real = bk.shutil.copyfile
        def corrupt(src, dst, *a, **k):
            real(src, dst)
            with open(dst, "ab") as fh:
                fh.write(b"junk")
            return dst
        with mock.patch("archive_backup.shutil.copyfile", side_effect=corrupt):
            with self.assertRaises(IOError):
                bk.local_backup(self.arch, self.dst, today="2026-11-14")
        self.assertFalse((self.dst / "files" / "2026-10.jsonl").exists())

    def test_due_logic(self):
        self.assertFalse(bk.is_due(self.dst, datetime(2026, 11, 14, 3, 30)))
        self.assertTrue(bk.is_due(self.dst, datetime(2026, 11, 14, 3, 40)))   # no last-run yet
        bk.local_backup(self.arch, self.dst, today="2026-11-14")
        self.assertFalse(bk.is_due(self.dst, datetime(2026, 11, 14, 9, 0)))
        self.assertTrue(bk.is_due(self.dst, datetime(2026, 11, 15, 3, 41)))

    def test_gpd_skipped_when_unreachable(self):
        bk.local_backup(self.arch, self.dst, today="2026-11-14")
        calls = []
        def runner(cmd):
            calls.append(cmd)
            return mock.Mock(returncode=255, stdout="", stderr="timeout")
        self.assertEqual(bk.gpd_backup(self.dst, runner)["gpd"], "skipped (not reachable)")
        self.assertFalse(any(c[0] == "scp" for c in calls))

    def test_gpd_oserror_skipped(self):
        def runner(cmd):
            raise OSError("no ssh")
        self.assertEqual(bk.gpd_backup(self.dst, runner)["gpd"], "skipped (not reachable)")

    def test_gpd_copy_only_under_fa_archive(self):
        bk.local_backup(self.arch, self.dst, today="2026-11-14")
        calls = []
        def runner(cmd):
            calls.append(cmd)
            if cmd[0] == "ssh" and "certutil" in cmd[-1]:
                name = cmd[-1].split("\\")[-1].split()[0]
                return mock.Mock(returncode=0, stdout=bk.sha256_file(self.dst / "files" / name), stderr="")
            return mock.Mock(returncode=0, stdout="ok", stderr="")
        res = bk.gpd_backup(self.dst, runner)
        self.assertEqual((res["gpd"], res["gpd_copied"]), ("ok", 2))
        for c in calls:
            remote = [a for a in c if "C:" in a or "C:/" in a]
            for a in remote:
                self.assertTrue("C:/fa/archive" in a or "C:\\fa\\archive" in a, a)
        again = bk.gpd_backup(self.dst, runner)
        self.assertEqual(again["gpd_copied"], 0)    # nothing changed since the last send


if __name__ == "__main__":
    unittest.main()
