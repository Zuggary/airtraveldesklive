#!/usr/bin/env python3
"""Back up the history archive to a second place (no cloud, no public repo).

1. Local copy: ~/factory-scratch/an-archive-backup/ (env AN_ARCHIVE_BACKUP_DIR).
   - files/            the monthly YYYY-MM.jsonl files (always the newest copy)
   - rotated/          the previous copy of a month file that changed, kept for 7 days of changes
   - MANIFEST.sha256   sha256 + size of every file in files/ ; dated copies in manifests/ (last 30)
   Each file is copied to a temp name, hashed, compared with the source hash, then renamed.
2. Optional second copy to the GPD desktop by scp, only under C:\\fa\\archive\\ and only when reachable.
   Skipped silently when the machine does not answer.

Usage: python tools/archive_backup.py [--if-due] [--no-gpd]
       python tools/archive_backup.py verify
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_lib as lib  # noqa: E402

DEFAULT_BACKUP = Path.home() / "factory-scratch" / "an-archive-backup"
KEEP_ROTATED = 7
KEEP_MANIFESTS = 30
DUE_AFTER = (3, 40)  # local time; run the daily backup at or after this
GPD_KEY = str(Path.home() / ".ssh" / "factory_desktop_ed25519")
GPD_HOST = "zluca@192.168.1.171"
GPD_DIR = "C:/fa/archive"
GPD_DIR_WIN = "C:\\fa\\archive"
SSH_OPTS = ["-i", GPD_KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]


def backup_dir(path: Optional[os.PathLike] = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get("AN_ARCHIVE_BACKUP_DIR")
    return Path(env).expanduser() if env else DEFAULT_BACKUP


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(path: Path) -> dict:
    """name -> (sha256, size)"""
    out: dict = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("  ")
                if len(parts) == 3:
                    out[parts[2]] = (parts[0], int(parts[1]))
    except (OSError, ValueError):
        pass
    return out


def write_manifest(path: Path, entries: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for name in sorted(entries):
            sha, size = entries[name]
            fh.write(f"{sha}  {size}  {name}\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _copy_verified(src: Path, dst: Path) -> str:
    """Copy via temp name; hash source and the copy; rename only when equal. Returns the sha."""
    tmp = dst.with_name(dst.name + ".tmp")
    want = sha256_file(src)
    shutil.copyfile(src, tmp)
    got = sha256_file(tmp)
    if got != want:
        tmp.unlink()
        raise IOError(f"copy of {src.name} does not match its source")
    os.replace(tmp, dst)
    return want


def _prune(folder: Path, pattern: str, keep: int) -> None:
    items = sorted(folder.glob(pattern))
    for p in items[:-keep] if keep else items:
        try:
            p.unlink()
        except OSError:
            pass


def local_backup(source: Optional[os.PathLike] = None, dest: Optional[os.PathLike] = None,
                 today: Optional[str] = None) -> dict:
    src = lib.archive_dir(source)
    dst = backup_dir(dest)
    day = today or datetime.now().strftime("%Y-%m-%d")
    files_dir, rot_dir, man_dir = dst / "files", dst / "rotated", dst / "manifests"
    for d in (files_dir, rot_dir, man_dir):
        d.mkdir(parents=True, exist_ok=True)
    manifest_path = dst / "MANIFEST.sha256"
    old_manifest = read_manifest(manifest_path)
    entries: dict = {}
    copied = unchanged = 0
    with lib.archive_lock(src):
        sources = lib.month_files(src)
        for f in sources:
            sha = sha256_file(f)
            target = files_dir / f.name
            if target.exists() and sha256_file(target) == sha:
                entries[f.name] = (sha, f.stat().st_size)
                unchanged += 1
                continue
            if target.exists():
                shutil.copyfile(target, rot_dir / f"{f.stem}.{day}.jsonl")
            _copy_verified(f, target)
            entries[f.name] = (sha, f.stat().st_size)
            copied += 1
    for name, (sha, size) in old_manifest.items():  # month files that left the source stay in the backup
        if name not in entries and (files_dir / name).exists():
            entries[name] = (sha, size)
    write_manifest(manifest_path, entries)
    shutil.copyfile(manifest_path, man_dir / f"MANIFEST-{day}.sha256")
    # keep the last KEEP_ROTATED rotated copies per month file
    for stem in {p.name.split(".")[0] for p in rot_dir.glob("*.jsonl")}:
        _prune(rot_dir, f"{stem}.*.jsonl", KEEP_ROTATED)
    _prune(man_dir, "MANIFEST-*.sha256", KEEP_MANIFESTS)
    problems = verify(dst)
    (dst / "last-run.json").write_text(json.dumps({"day": day, "copied": copied, "unchanged": unchanged,
                                                   "problems": problems}), encoding="utf-8")
    return {"ok": not problems, "copied": copied, "unchanged": unchanged, "files": len(entries), "problems": problems,
            "dest": str(dst)}


def verify(dest: Optional[os.PathLike] = None) -> list:
    """Re-hash every file in files/ against MANIFEST.sha256. Returns a list of problem strings (empty = good)."""
    dst = backup_dir(dest)
    man = read_manifest(dst / "MANIFEST.sha256")
    problems = []
    if not man:
        return ["manifest missing or empty"]
    for name, (sha, size) in sorted(man.items()):
        p = dst / "files" / name
        if not p.exists():
            problems.append(f"{name}: missing")
        elif p.stat().st_size != size:
            problems.append(f"{name}: size {p.stat().st_size} != {size}")
        elif sha256_file(p) != sha:
            problems.append(f"{name}: sha256 mismatch")
    for p in (dst / "files").glob("*.jsonl"):
        if p.name not in man:
            problems.append(f"{p.name}: not in manifest")
    return problems


# ---------- optional GPD copy ----------

Runner = Callable[[list], "subprocess.CompletedProcess"]


def _run(cmd: list) -> "subprocess.CompletedProcess":
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def gpd_backup(dest: Optional[os.PathLike] = None, runner: Optional[Runner] = None) -> dict:
    """Copy files/ and the manifest to C:\\fa\\archive\\ on the GPD. Silent skip if unreachable. Touches nothing else."""
    run = runner or _run
    dst = backup_dir(dest)
    try:
        r = run(["ssh", *SSH_OPTS, GPD_HOST, f"mkdir {GPD_DIR_WIN}"])
        # mkdir may fail because the folder exists; reachability is judged by the exit code of a harmless echo
        r2 = run(["ssh", *SSH_OPTS, GPD_HOST, "echo ok"])
    except (OSError, subprocess.SubprocessError):
        return {"gpd": "skipped (not reachable)"}
    if r2.returncode != 0:
        return {"gpd": "skipped (not reachable)"}
    state_path = dst / "gpd-state.json"
    try:
        sent = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sent = {}
    man = read_manifest(dst / "MANIFEST.sha256")
    copied, failed = 0, []
    for name, (sha, _size) in sorted(man.items()):
        if sent.get(name) == sha:
            continue
        try:
            c = run(["scp", *SSH_OPTS, str(dst / "files" / name), f"{GPD_HOST}:{GPD_DIR}/{name}"])
        except (OSError, subprocess.SubprocessError):
            failed.append(name)
            continue
        if c.returncode != 0:
            failed.append(name)
            continue
        # verify remote hash with certutil (Windows); a parse miss counts as unverified, not as failure
        v = run(["ssh", *SSH_OPTS, GPD_HOST, f"certutil -hashfile {GPD_DIR_WIN}\\{name} SHA256"])
        text = (v.stdout or "").lower()
        if sha in text:
            sent[name] = sha
            copied += 1
        else:
            failed.append(f"{name} (unverified)" if v.returncode == 0 else name)
    try:
        run(["scp", *SSH_OPTS, str(dst / "MANIFEST.sha256"), f"{GPD_HOST}:{GPD_DIR}/MANIFEST.sha256"])
    except (OSError, subprocess.SubprocessError):
        pass
    state_path.write_text(json.dumps(sent), encoding="utf-8")
    return {"gpd": "ok" if not failed else "partial", "gpd_copied": copied, "gpd_failed": failed}


def is_due(dest: Optional[os.PathLike], now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    if (now.hour, now.minute) < DUE_AFTER:
        return False
    try:
        last = json.loads((backup_dir(dest) / "last-run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return last.get("day") != now.strftime("%Y-%m-%d") or bool(last.get("problems"))


def main(argv: list) -> int:
    if len(argv) > 1 and argv[1] == "verify":
        probs = verify()
        print(json.dumps({"ok": not probs, "problems": probs}))
        return 0 if not probs else 1
    if "--if-due" in argv and not is_due(None):
        print("archive_backup not due")
        return 0
    res = local_backup()
    if "--no-gpd" not in argv:
        res.update(gpd_backup())
    print(f"{datetime.now().strftime('%FT%T')} archive_backup {json.dumps(res, sort_keys=True)}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
