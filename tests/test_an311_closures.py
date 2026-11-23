"""AN311 (23 Nov 2026): the GA-only airport restriction is not a closure event; every other closure (incl. CLSD TO ALL ACFT, CLSD EXC ...) is."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from desk import feeds  # noqa: E402


def xml(cases):
    items = "".join("<Airport><ARPT>%s</ARPT><Reason>%s</Reason><Start>Nov 20 at 10:00 UTC.</Start><Reopen>Nov 23 at 23:00 UTC.</Reopen></Airport>" % c for c in cases)
    return "<AIRPORT_STATUS_INFORMATION><Airport_Closure_List>%s</Airport_Closure_List></AIRPORT_STATUS_INFORMATION>" % items


class GaOnlyClosure(unittest.TestCase):
    def test_ga_only_skipped_real_kept(self):
        cases = [
            ("LAS", "!LAS 10/160 LAS AD AP CLSD TO NON SKED TRANSIENT GA ACFT EXC 24HR PPR 702-261-7775 2610281926-2701272300"),
            ("LAX", "!LAX 05/277 LAX AD AP CLSD TO NON SKED TRANSIENT GA ACFT EXC 24HR PPR CTC ATLANTIC AVIATION 310-258-9884"),
            ("SAN", "!SAN 10/004 SAN AD AP CLSD TO NON SKED TRANSIENT GA ACFT EXC PPR 619-298-7704 2610011633-2701010800"),
            ("BOS", "!BOS 11/200 BOS AD AP CLSD"), ("ORD", "AD AP CLSD TO ALL ACFT"), ("DEN", "AD AP CLSD EXC EMERGENCY ACFT"),
            ("SEA", "AD CLSD EXC PPR"), ("PHX", "AIRPORT CLOSED EXC PPR"), ("MSP", "AD AP CLSD TO ALL ACFT EXC TRANSIENT GA PPR"),
            ("SNA", "!SNA 11/101 SNA AD AP CLSD DLY 0730-1415"),
        ]
        kept = [e["airport"] for e in feeds.parse_faa(xml(cases)) if e["kind"] == "closure"]
        self.assertEqual(kept, ["BOS", "ORD", "DEN", "SEA", "PHX", "MSP", "SNA"])

    def test_the_real_faa_feed_of_23_nov_5_05_am(self):
        raw = (Path(__file__).resolve().parent / "fixtures" / "faa-nas-2026-11-23-1305Z.xml").read_text(encoding="utf-8")
        self.assertEqual([e for e in feeds.parse_faa(raw) if e["kind"] == "closure"], [])


if __name__ == "__main__":
    unittest.main()
