"""Fetch the NOAA MRMS base reflectivity image into the out dir. Standard library only."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from desk.feeds import USER_AGENT

BBOX = [-125, 24, -66, 50]
RADAR_URL = (
    "https://opengeo.ncep.noaa.gov/geoserver/conus/conus_bref_qcd/ows?service=WMS"
    "&version=1.1.1&request=GetMap&layers=conus_bref_qcd&styles=&srs=EPSG:4326"
    "&bbox=-125,24,-66,50&width=1180&height=520&format=image/png&transparent=true"
)
MAX_AGE_SEC = 300.0
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "radar.png"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def is_fresh(out_dir: Path | str, now_ts: float, max_age: float = MAX_AGE_SEC) -> bool:
    """True when radar.png exists and radar.json says it was fetched less than max_age ago."""
    out = Path(out_dir)
    try:
        meta = json.loads((out / "radar.json").read_text(encoding="utf-8"))
        fetched = _parse_iso(meta["fetched_utc"])
    except (OSError, ValueError, KeyError):
        return False
    if not (out / "radar.png").is_file():
        return False
    return 0 <= (now_ts - fetched) < max_age


def fetch_bytes(url: str = RADAR_URL, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def maybe_fetch(
    out_dir: Path | str,
    now_ts: Optional[float] = None,
    replay: bool = False,
    fetcher: Optional[Callable[[], bytes]] = None,
    attempts: Optional[dict[str, float]] = None,
) -> str:
    """Refresh radar.png at most once per 5 minutes. Returns 'skip' or 'ok'; raises on error.

    attempts remembers the last try (also failed tries) so errors do not cause a retry storm.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = time.time() if now_ts is None else now_ts
    if is_fresh(out, now):
        return "skip"
    if attempts is not None:
        last = attempts.get("radar")
        if last is not None and 0 <= now - last < MAX_AGE_SEC:
            return "skip"
        attempts["radar"] = now
    if replay:
        data = FIXTURE.read_bytes()
    else:
        data = (fetcher or fetch_bytes)()
    if not data.startswith(b"\x89PNG"):
        raise ValueError("radar response is not a PNG")
    _atomic_write(out / "radar.png", data)
    meta: dict[str, Any] = {"fetched_utc": _iso(now), "bbox": BBOX}
    _atomic_write(out / "radar.json", json.dumps(meta).encode("utf-8"))
    return "ok"
