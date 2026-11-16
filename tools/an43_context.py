"""AN43: static, data-driven context for an airport page, from data/an43/bts-profile.json.

Every sentence comes from this airport's own 12 months of BTS numbers, so no two pages read alike.
render_context() returns HTML lines for one visible <section>; it needs no script.
"""
from __future__ import annotations

from html import escape
from typing import Any

PARTS = (("early morning (5 to 9 am)", range(5, 9)), ("late morning and midday (9 am to 2 pm)", range(9, 14)),
         ("afternoon (2 to 6 pm)", range(14, 18)), ("evening (6 pm to midnight)", range(18, 24)))
CAUSE_EXPLAIN = {
    "airline": "something the airline controls, such as crew, cleaning, fuelling, baggage or a mechanical check",
    "late incoming aircraft": "the plane arriving late from its previous flight, so the delay rolls forward through the day",
    "air traffic system": "the national air traffic system: heavy traffic, non-extreme weather that slows the flow, runway work or an FAA program",
    "extreme weather": "weather bad enough to stop or hold flights, such as thunderstorms, snow, ice or a hurricane",
    "security": "security events, such as a terminal evacuation or a long screening line",
}
CAUSE_NAME = {"airline": "the airline itself", "late incoming aircraft": "a late incoming aircraft",
              "air traffic system": "the air traffic system", "extreme weather": "extreme weather", "security": "security"}
MONTH_FULL = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April", "May": "May", "Jun": "June",
              "Jul": "July", "Aug": "August", "Sep": "September", "Oct": "October", "Nov": "November", "Dec": "December"}


# Summer thunderstorms are rare on the Pacific coast, Hawaii and Alaska; hard freezes are rare in these warm places.
NO_TSTORM_STATES = {"CA", "OR", "WA", "HI", "AK"}
WARM_WINTER_STATES = {"FL", "HI", "PR", "AZ"}
WARM_WINTER_CODES = {"LAX", "SAN", "SNA", "LGB", "BUR", "ONT", "SJC", "SFO", "OAK", "SMF", "PSP", "HOU", "IAH", "SAT", "AUS", "MSY", "LAS"}


def _state(city: str) -> str:
    return city.rsplit(",", 1)[-1].strip().upper() if "," in city else ""


def _pct(v: Any) -> str:
    return f"{v:.0f}%" if isinstance(v, (int, float)) else "n/a"


def _num(n: int) -> str:
    return f"{n:,}"


def _part_stats(by_hour: dict[str, dict]) -> list[tuple[str, float, int]]:
    out = []
    for label, hours in PARTS:
        fl = ot = 0.0
        for h in hours:
            e = by_hour.get(f"{h:02d}")
            if e and e.get("ontime") is not None:
                done = e["flights"] * (1 - (e.get("cancel") or 0) / 100)
                fl += done; ot += done * e["ontime"] / 100
        if fl >= 200:
            out.append((label, ot / fl * 100, int(fl)))
    return out


def _compare(v: float, nat: float, what: str) -> str:
    d = round(v) - round(nat)          # from the shown, rounded numbers, so the words match the figures
    if d == 0:
        return f"about the same as the national figure of {nat:.0f}%"
    return f"{abs(d):.0f} point{'s' if abs(d) != 1 else ''} {'better' if d > 0 else 'worse'} than the national figure of {nat:.0f}% for {what}"


def render_context(code: str, short: str, prof: dict[str, Any] | None, city: str = "") -> list[str]:
    if not prof or code not in prof.get("airports", {}):
        return []
    a = prof["airports"][code]; nat = prof["nation"]; period = escape(prof["period"])
    dep, arr = a["departures"], a.get("arrivals") or {}
    if not dep.get("flights") or dep.get("ontime") is None:
        return []
    S = escape(short); C = escape(code)
    st = _state(city)
    tstorms = st not in NO_TSTORM_STATES
    freezes = st not in WARM_WINTER_STATES and code not in WARM_WINTER_CODES
    L: list[str] = []
    p = L.append
    p('      <section class="airport-section an43-context" aria-labelledby="usual-heading">')
    p(f'        <h2 id="usual-heading">How flights at {C} usually run</h2>')
    p(f'        <p class="small">From {_num(dep["flights"])} scheduled departures, {period}, in the U.S. DOT Bureau of Transportation Statistics on-time file. '
      'Only the larger U.S. airlines report, so some regional and foreign flights are not in these numbers.</p>')

    # 1. The headline numbers
    ot = dep["ontime"]; nd = nat["departures"]
    late_share = 100 - ot
    s1 = (f"Over those twelve months, {ot:.0f}% of departures from {S} left the gate on time, which the government defines as less than "
          f"15 minutes late. That is {_compare(ot, nd['ontime'], 'all reporting airports')}. ")
    if dep.get("late_avg_min"):
        s1 += (f"Roughly one flight in {max(2, round(100 / late_share)) if late_share else 'many'} left late, and when a flight did leave late, "
               f"it averaged {dep['late_avg_min']:.0f} minutes behind schedule. ")
    c = dep.get("cancel")
    if c is not None:
        rel = "lower than" if c < nd["cancel"] - 0.2 else ("higher than" if c > nd["cancel"] + 0.2 else "close to")
        s1 += f"{c:.1f}% of scheduled departures were cancelled, {rel} the national rate of {nd['cancel']:.1f}%."
    p(f"        <p>{s1}</p>")
    if dep.get("taxi_out_min"):
        t = dep["taxi_out_min"]; tn = nd.get("taxi_out_min") or t
        word = "a longer wait than" if t > tn + 2 else ("a shorter wait than" if t < tn - 2 else "close to")
        p(f"        <p>After pushing back, planes here took an average of {t:.0f} minutes to taxi out and take off, {word} the national average of {tn:.0f} minutes. "
          "That time is already inside the schedule, so a long taxi is normal here and not, by itself, a delay.</p>" if t > tn + 2 else
          f"        <p>After pushing back, planes here took an average of {t:.0f} minutes to taxi out and take off, {word} the national average of {tn:.0f} minutes.</p>")

    # 2. Time of day
    parts = _part_stats(a.get("by_hour_block") or {})
    if len(parts) >= 3:
        best = max(parts, key=lambda x: x[1]); worst = min(parts, key=lambda x: x[1])
        p(f'        <h3>Best and worst time of day to leave {C}</h3>')
        gap = best[1] - worst[1]
        if gap >= 8:
            txt = (f"The clock matters a lot here. Flights scheduled to leave in the {best[0]} were on time {best[1]:.0f}% of the time, "
                   f"against {worst[1]:.0f}% in the {worst[0]}, a gap of {gap:.0f} points. ")
        else:
            txt = (f"The time of day matters less here than at many airports: the best slot, the {best[0]}, ran {best[1]:.0f}% on time "
                   f"and the worst, the {worst[0]}, {worst[1]:.0f}%. ")
        if best[0].startswith("early"):
            txt += ("Early flights do best because the aircraft is usually already at the gate from the night before, so there is no late inbound "
                    "plane to wait for. If you can choose, the first departures of the day are the safest bet for a tight connection.")
        else:
            txt += "Unusually, the first flights of the day are not the most reliable here, so the time of day is a weaker guide than the airline and the season."
        p(f"        <p>{txt}</p>")
        p('        <table class="an43-table"><caption>On-time departures by scheduled departure time (local)</caption>')
        p('          <thead><tr><th scope="col">Leaving in the</th><th scope="col">On time</th><th scope="col">Flights</th></tr></thead><tbody>')
        for lab, v, n in parts:
            p(f'          <tr><th scope="row">{escape(lab)}</th><td>{v:.0f}%</td><td>{_num(n)}</td></tr>')
        p("          </tbody></table>")

    # 3. Season
    bm = {k: v for k, v in (a.get("by_month") or {}).items() if v.get("ontime") is not None and v.get("flights", 0) >= 100}
    if len(bm) >= 9:
        hi = max(bm.items(), key=lambda kv: kv[1]["ontime"]); lo = min(bm.items(), key=lambda kv: kv[1]["ontime"])
        hc = max(bm.items(), key=lambda kv: kv[1].get("cancel") or 0)
        p(f'        <h3>Best and worst months at {C}</h3>')
        txt = (f"In the period covered, {MONTH_FULL[hi[0]]} was the most reliable month at {S}, with {hi[1]['ontime']:.0f}% of departures on time, "
               f"and {MONTH_FULL[lo[0]]} the least, at {lo[1]['ontime']:.0f}%. ")
        if (hc[1].get("cancel") or 0) >= 2:
            cause = "a storm, a freeze or one airline's systems outage" if freezes else "a storm system or one airline's systems outage, here or at a connecting hub"
            txt += (f"Cancellations peaked in {MONTH_FULL[hc[0]]}, when {hc[1]['cancel']:.1f}% of departures were cancelled. "
                    f"A single event, such as {cause}, can drive a month's number, so treat this as one year's pattern, not a forecast. ")
            if hc[0] == hi[0]:
                txt += (f"{MONTH_FULL[hi[0]]} topping both lists is not a contradiction: when airlines cancel flights early, "
                        "the flights that do go tend to leave on time. ")
        else:
            txt += "Cancellations stayed low all year, never reaching 2% of departures in any month. "
        summer = [bm[m]["ontime"] for m in ("Jun", "Jul", "Aug") if m in bm]
        winter = [bm[m]["ontime"] for m in ("Dec", "Jan", "Feb") if m in bm]
        if summer and winter:
            sv, wv = sum(summer) / len(summer), sum(winter) / len(winter)
            if sv < wv - 3:
                why = ("afternoon thunderstorms and peak crowds" if tstorms else
                       "peak summer crowds and thunderstorms at the hubs these flights connect to, plus morning low cloud on this coast")
                txt += f"Summer was harder than winter here ({sv:.0f}% against {wv:.0f}%), the usual sign of {why}."
            elif wv < sv - 3:
                why = ("snow, ice and de-icing, here or at the airports these flights connect to" if freezes else
                       "winter storms at the hubs these flights connect to, since hard freezes are rare here")
                txt += f"Winter was harder than summer here ({wv:.0f}% against {sv:.0f}%), which points to {why}."
            else:
                txt += f"Summer and winter ran close ({sv:.0f}% and {wv:.0f}%), so no one season stands out."
        p(f"        <p>{txt}</p>")

    # 4. Causes
    cs = arr.get("cause_share") or {}
    if cs:
        order = sorted(cs.items(), key=lambda kv: -kv[1])
        top, second = order[0], order[1]
        p(f'        <h3>Why flights into {C} run late</h3>')
        txt = (f"When a flight arrived at {S} late, the airlines reported the cause of each delay minute. The largest share, {top[1]:.0f}%, came from "
               f"{CAUSE_EXPLAIN[top[0]]}. Next came {CAUSE_NAME[second[0]]}, at {second[1]:.0f}%, meaning {CAUSE_EXPLAIN[second[0]]}. ")
        w = cs.get("extreme weather", 0); n = cs.get("air traffic system", 0)
        rest = [k for k, _ in order[2:] if k in ("extreme weather", "air traffic system")]
        if rest:
            txt += " and ".join(f"{CAUSE_NAME[k][0].upper() + CAUSE_NAME[k][1:]} accounted for {cs[k]:.0f}%" if i == 0 else f"{CAUSE_NAME[k]} for {cs[k]:.0f}%" for i, k in enumerate(rest)) + ". "
        if top[0] in ("airline", "late incoming aircraft"):
            txt += ("Because most delay here starts with the airline or a late plane, the airline's own app is usually the first place a new departure time shows up, "
                    "often before the airport boards update.")
        else:
            txt += ("Because so much delay here comes from the air traffic system, the FAA status at the top of this page is a good early warning: "
                    "a ground delay program for this airport usually means a later departure even before your airline says so.")
        p(f"        <p>{txt}</p>")

    # 5. Cancellation reasons
    cr = dep.get("cancel_reasons") or {}
    tot = sum(cr.values())
    if tot >= 30:
        parts_txt = ", ".join(f"{k} {v / tot * 100:.0f}%" for k, v in cr.items() if v / tot >= 0.02)
        p(f"        <p>Of the {_num(tot)} cancelled departures, the reasons the airlines gave split as follows: {escape(parts_txt)}. "
          "Whatever the reason, U.S. DOT rules say that if the airline cancels and you choose not to travel or rebook, you are owed your money back to the original form of payment, not just a credit. "
          'See <a class="tap" href="../stuck.html">what you are owed when you are stuck</a>.</p>')

    # 6. Airlines
    cars = [x for x in (a.get("carriers") or []) if x.get("flights", 0) >= max(500, 0.05 * dep["flights"]) and x.get("ontime") is not None]
    if len(cars) >= 2:
        b = max(cars, key=lambda x: x["ontime"]); wv = min(cars, key=lambda x: x["ontime"])
        p(f'        <h3>Airlines at {C}</h3>')
        p(f"        <p>{escape(cars[0]['name'])} ran the most reported departures from {S}. Among the larger operators here, {escape(b['name'])} had the best on-time rate "
          f"({b['ontime']:.0f}%) and {escape(wv['name'])} the lowest ({wv['ontime']:.0f}%). Regional brands such as American Eagle or United Express "
          "are listed under the company that flies them (for example SkyWest or Republic).</p>")
        p('        <table class="an43-table"><caption>Departures by operating airline</caption>')
        p('          <thead><tr><th scope="col">Airline</th><th scope="col">Departures</th><th scope="col">On time</th><th scope="col">Cancelled</th></tr></thead><tbody>')
        for x in cars:
            p(f'          <tr><th scope="row">{escape(x["name"])}</th><td>{_num(x["flights"])}</td><td>{_pct(x["ontime"])}</td><td>{x["cancel"]:.1f}%</td></tr>')
        p("          </tbody></table>")

    # 7. Routes
    ds = [x for x in (a.get("top_destinations") or []) if x.get("ontime") is not None][:5]
    if len(ds) >= 3:
        w = min(ds, key=lambda x: x["ontime"]); bst = max(ds, key=lambda x: x["ontime"])
        names = ", ".join(f'<a class="tap" href="{escape(x["code"])}.html">{escape(x["code"])}</a>' for x in ds[:5])
        p(f"        <p>The busiest routes from {C} go to {names}. Of those five, flights to {escape(bst['code'])} were the most punctual ({bst['ontime']:.0f}% on time) "
          f"and flights to {escape(w['code'])} the least ({w['ontime']:.0f}%). A late route usually reflects trouble at the other end, so check that airport's page too.</p>")
    p(f'        <p class="small">Source: <a class="tap" href="https://www.transtats.bts.gov/" rel="noopener">BTS TranStats</a>, Reporting Carrier On-Time Performance, {period}. '
      "Departure figures count flights leaving this airport; delay causes count late arrivals into it.</p>")
    p("      </section>")
    return L
