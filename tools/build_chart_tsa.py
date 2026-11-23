import argparse
import json
from datetime import date, timedelta
from fractions import Fraction
from html import escape
from pathlib import Path


WEEKDAY_OFFSET = timedelta(days=364)
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
WEEKDAYS = "Mon Tue Wed Thu Fri Sat Sun".split()
CURRENT_COLOR = "var(--accent, #8fcbff)"
PRIOR_COLOR = "var(--amber-text, #ffd45c)"


def percent_change(current, prior):
    if prior == 0:
        return None
    return float(round(Fraction(100 * (current - prior), prior), 1))


def signed_percent(change):
    return "—" if change is None else f"{float(change):+.1f}%"


def millions(count):
    return f"{count / 1_000_000:.2f}M"


def short_date(day, weekday=False):
    prefix = f"{WEEKDAYS[day.weekday()]} " if weekday else ""
    return f"{prefix}{MONTHS[day.month - 1]} {day.day}"


def calendar_days(first, last):
    return (first + timedelta(days=offset) for offset in range((last - first).days + 1))


def build_model(days, *, latest_date=None, record_date=None, record_count=None):
    counts = {date.fromisoformat(key) if isinstance(key, str) else key: value
              for key, value in days.items()}
    latest = date.fromisoformat(latest_date) if latest_date else max(counts)
    first = latest - timedelta(days=59)
    last = max(latest, date(latest.year, 12, 1))
    november = date(latest.year, 11, 1)
    thanksgiving = november + timedelta(days=(3 - november.weekday()) % 7 + 21)
    if record_date is None:
        record_date = max((day for day in sorted(counts) if day.year < latest.year),
                          key=counts.__getitem__, default=None)
    else:
        record_date = date.fromisoformat(record_date)
    if record_count is None:
        record_count = counts.get(record_date)

    current = {day: counts[day] for day in calendar_days(first, latest) if day in counts}
    prior = {day: counts[day - WEEKDAY_OFFSET] for day in calendar_days(first, last)
             if day - WEEKDAY_OFFSET in counts}
    peak = max(current, key=current.__getitem__, default=None)
    week = [day for day in calendar_days(latest - timedelta(days=6), latest)
            if day in current and day in prior]
    change = percent_change(sum(current[day] for day in week), sum(prior[day] for day in week))
    day_change = percent_change(current[latest], prior[latest]) if latest in prior else None

    def average(series, offset):
        values = {}
        for day in series:
            window = [counts.get(key - offset)
                      for key in calendar_days(day - timedelta(days=6), day)]
            if None not in window:
                values[day] = sum(window) / 7
        return values

    aligned_record = record_date + WEEKDAY_OFFSET if record_date else None
    labels = {
        "latest_date": latest.isoformat(),
        "latest_count": current[latest],
        "yoy_pct_latest_day": day_change,
        "yoy_pct_7_day": f"{change:+.1f}" if change is not None else None,
        "peak_day": peak.isoformat() if peak else None,
        "peak_count": current.get(peak),
        "record_date": record_date.isoformat() if record_date else None,
        "record_count": record_count,
        "aligned_record_date": aligned_record.isoformat() if aligned_record else None,
        "thanksgiving_date": thanksgiving.isoformat(),
    }
    direction = "below" if change is not None and change < 0 else "above"
    if change is None:
        title = "Air travel ahead of the Thanksgiving rush"
    elif change == 0:
        title = "Air travel is running +0.0% vs last year as the Thanksgiving rush starts"
    else:
        title = f"Air travel is running {signed_percent(change)} {direction} last year as the Thanksgiving rush starts"
    return {
        "labels": labels, "title": title, "first": first, "last": last, "latest": latest,
        "thanksgiving": thanksgiving, "record": record_date, "aligned_record": aligned_record,
        "current": current, "prior": prior,
        "current-average": average(current, timedelta()), "prior-average": average(prior, WEEKDAY_OFFSET),
    }


def load_model(path):
    history = json.loads(path.read_text(encoding="utf-8"))
    return build_model(history["days"], latest_date=history["latest_date"],
                       record_date=history["record_date"], record_count=history["record_count"])


def render_svg(model, layout):
    width, left, right, top, bottom, font, tick_stride = {
        "wide": (1000, 65, 965, 92, 492, 16, 1),
        "narrow": (420, 62, 396, 64, 492, 19, 2),
    }[layout]
    narrow = layout == "narrow"
    labels = model["labels"]
    first, last, latest = (model[key] for key in ("first", "last", "latest"))
    thanksgiving = model["thanksgiving"]
    record = model["aligned_record"]
    show_record = record is not None and first <= record <= last
    values = [value for key in ("current", "prior", "current-average", "prior-average")
              for value in model[key].values()]
    if show_record:
        values.append(labels["record_count"])
    span = max(values) - min(values)
    step = next(unit for magnitude in (1, 10, 100, 1000)
                for unit in (100_000 * magnitude, 200_000 * magnitude, 500_000 * magnitude)
                if unit >= span / 9)
    low = max(0, int((min(values) - step * .1) // step) * step)
    high = int((max(values) + step * .1) // step + 1) * step

    def x(day):
        return left + (day - first).days * (right - left) / (last - first).days

    def y(value):
        return bottom - (value - low) * (bottom - top) / (high - low)

    latest_short = f"{short_date(latest, True)}: {millions(labels['latest_count'])}"
    day_change = f"{signed_percent(labels['yoy_pct_latest_day'])} vs same weekday last year"
    avg_text = f"7-day avg {signed_percent(labels['yoy_pct_7_day'])}"
    record_text = ""
    if model["record"]:
        day = model["record"]
        record_text = f"Record: {millions(labels['record_count'])} on {short_date(day, True)}, {day.year}"
    description = (f"{model['title']}. {latest_short}, {day_change}. {avg_text}. "
                   f"{record_text}. Solid is this year. Dashed is the same weekday last year.")
    lines = [
        f'<svg xmlns="&#104;ttp://www.w3.org/2000/svg" class="chart-{layout}"'
        f' viewBox="0 0 {width} 560" width="{width}" height="560"'
        f' role="img" aria-labelledby="tsa-{layout}-title tsa-{layout}-desc">',
        f'<title id="tsa-{layout}-title">{escape(model["title"])}</title>',
        f'<desc id="tsa-{layout}-desc">{escape(description)}</desc>',
        f'<g font-family="inherit" font-size="{font}" fill="var(--text, #eef1f5)">',
    ]

    def text(column, row, content, attrs=""):
        lines.append(f'<text x="{column:.2f}" y="{row:.2f}" {attrs}>{escape(content)}</text>')

    shade_start = max(first, thanksgiving - timedelta(days=4))
    shade_end = min(last, thanksgiving + timedelta(days=3))
    if shade_start < shade_end:
        lines.append(f'<rect x="{x(shade_start):.2f}" y="{top}"'
                     f' width="{x(shade_end) - x(shade_start):.2f}" height="{bottom - top}"'
                     ' fill="var(--amber-soft, #ffd45c)" fill-opacity=".55"/>')
    for count in range(low, high + 1, step * tick_stride):
        row = y(count)
        lines.append(f'<path d="M {left} {row:.2f} H {right}" stroke="var(--line, #2c3746)"/>')
        text(left - 8, row, f"{count / 1_000_000:.1f}M",
             'class="y-tick" text-anchor="end" dominant-baseline="central"'
             ' fill="var(--text-muted, #a3afbd)"')
    tick_count = 3 if narrow else 7
    for index in range(tick_count):
        day = first + timedelta(days=round((last - first).days * index / (tick_count - 1)))
        text(x(day), bottom + 25, short_date(day),
             'class="x-tick" text-anchor="middle" fill="var(--text-muted, #a3afbd)"')
    if first <= thanksgiving <= last:
        column = x(thanksgiving)
        lines.append(f'<path d="M {column:.2f} {top} V {bottom}"'
                     f' stroke="{PRIOR_COLOR}" stroke-opacity=".55" stroke-dasharray="2 4"/>')
        text(min(column, right), 546, f"Thanksgiving · {short_date(thanksgiving, True)}",
             f'text-anchor="end" fill="{PRIOR_COLOR}"')
    for key in ("prior", "current", "prior-average", "current-average"):
        is_prior = key.startswith("prior")
        bold = key.endswith("average")
        color = PRIOR_COLOR if is_prior else CURRENT_COLOR
        previous = None
        points = []
        for day, count in model[key].items():
            command = "L" if previous and day - previous == timedelta(days=1) else "M"
            points.append(f"{command} {x(day):.2f} {y(count):.2f}")
            previous = day
        dash = (' stroke-dasharray="9 6"' if bold else ' stroke-dasharray="4 4"') if is_prior else ""
        lines.append(f'<path class="series-{key}" d="{" ".join(points)}" fill="none"'
                     f' stroke="{color}" stroke-width="{3.2 if bold else (1.1 if narrow else 1.3)}"'
                     f' stroke-opacity="{1 if bold else (.25 if narrow else .42)}" stroke-linejoin="round"{dash}/>')

    def marker(day, count, color, label_x, label_y, bend_y):
        column, row = x(day), y(count)
        lines.append(f'<path d="M {label_x:.2f} {label_y} L {column:.2f} {bend_y}'
                     f' V {row:.2f}" fill="none" stroke="{color}" stroke-opacity=".55"/>')
        lines.append(f'<circle cx="{column:.2f}" cy="{row:.2f}" r="4" fill="{color}"/>')

    if narrow:  # compact callout (the cards above the chart carry the percentages)
        marker(latest, labels["latest_count"], CURRENT_COLOR, x(latest), 50, top)
    else:
        marker(latest, labels["latest_count"], CURRENT_COLOR, x(latest), 66, top)
    if show_record:
        marker(record, labels["record_count"], PRIOR_COLOR, x(record),
               31 if narrow else 36, top)
    if latest in model["current-average"]:
        lines.append(f'<circle cx="{x(latest):.2f}" cy="{y(model["current-average"][latest]):.2f}"'
                     f' r="5" fill="{CURRENT_COLOR}"/>')
    if narrow:
        text(x(latest) - 8, 54, f"{latest_short.split(':')[0]} · {labels['latest_count'] / 1e6:.2f}M", 'text-anchor="end" font-weight="700"')
        if show_record:
            text(right, 24, record_text, f'text-anchor="end" fill="{PRIOR_COLOR}"')
    else:
        text(x(latest) - 10, 62, f"{latest_short}, {day_change}", 'text-anchor="end"')
        text(left, 65, avg_text, f'font-weight="700" fill="{CURRENT_COLOR}"')
        if show_record:
            text(right, 28, record_text, f'text-anchor="end" fill="{PRIOR_COLOR}"')
    lines.extend(("</g>", "</svg>"))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Build weekday-aligned TSA charts.")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    model = load_model(args.data)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for layout in ("wide", "narrow"):
        (args.out_dir / f"chart-tsa-{layout}.svg").write_text(render_svg(model, layout), encoding="utf-8")
    (args.out_dir / "chart-tsa-labels.json").write_text(
        json.dumps(model["labels"], indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
