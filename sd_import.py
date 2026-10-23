#!/usr/bin/env python3
"""CardDock: local, verified photo imports. Python 3.10+, standard library only."""
import argparse
import ctypes
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "0.1.0"
CHUNK = 4 * 1024 * 1024
FREE_MARGIN = 256 * 1024 * 1024
IMAGE_EXT = set(".nef .nrw .jpg .jpeg .heic .heif .hif .tif .tiff .png .dng .cr2 .cr3 .crw .arw .raf .orf .rw2 .pef .srw .gpr".split())
VIDEO_EXT = set(".mov .mp4 .m4v .avi .mts .m2ts .mpg .mpeg .3gp .mxf".split())
COMPANION_EXT = set(".xmp .aae .wav .thm .xml .srt".split())
TIFF_BASED = set(".nef .nrw .dng .cr2 .arw .pef .srw .tif .tiff .orf .rw2".split())
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT | COMPANION_EXT
RESULT = {"copied": 0, "duplicates": 0, "deleted": 0, "failed": 0}
GUI = False


def event(name, **data):
    if GUI:
        print("##" + name + " " + json.dumps(data), flush=True)


def say(message):
    print(message, flush=True)


def identity(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode):
        raise ValueError("Not a regular file: " + str(path))
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def digest(path):
    before = identity(path)
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if (st.st_dev, st.st_ino) != before[:2]:
            raise ValueError("File changed while opening: " + str(path))
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    if identity(path) != before:
        raise ValueError("File changed while reading: " + str(path))
    return h.hexdigest()


def _tiff_datetime(f, base):
    f.seek(base)
    hdr = f.read(8)
    if len(hdr) < 8:
        return None
    e = {b"II": "<", b"MM": ">"}.get(hdr[:2])
    if not e:
        return None
    ifd0 = struct.unpack(e + "I", hdr[4:8])[0]

    def ifd(off):
        f.seek(base + off)
        nb = f.read(2)
        if len(nb) < 2:
            return {}
        n = struct.unpack(e + "H", nb)[0]
        if n > 2000:
            return {}
        data = f.read(12 * n)
        out = {}
        for i in range(n):
            tag, typ, cnt, val = struct.unpack(e + "HHI4s", data[12 * i:12 * i + 12])
            out[tag] = (typ, cnt, val)
        return out

    def ascii_(entry):
        typ, cnt, val = entry
        if typ != 2 or cnt > 64:
            return None
        if cnt <= 4:
            raw = val[:cnt]
        else:
            f.seek(base + struct.unpack(e + "I", val)[0])
            raw = f.read(cnt)
        return raw.rstrip(b"\0 ").decode("ascii", "replace")

    t0 = ifd(ifd0)
    if 0x8769 in t0:
        tx = ifd(struct.unpack(e + "I", t0[0x8769][2])[0])
        if 0x9003 in tx:
            return ascii_(tx[0x9003])   # DateTimeOriginal
        if 0x9004 in tx:
            return ascii_(tx[0x9004])   # CreateDate
    if 0x0132 in t0:
        return ascii_(t0[0x0132])       # ModifyDate
    return None


def exif_capture(path, ext):
    """Return 'YYYY:MM:DD HH:MM:SS' from EXIF, or None if unavailable."""
    if ext not in TIFF_BASED and ext not in (".jpg", ".jpeg"):
        return None
    try:
        with open(str(path), "rb") as f:
            head = f.read(4)
            if head[:2] == b"\xff\xd8":                       # JPEG
                pos = 2
                for _ in range(64):
                    f.seek(pos)
                    m = f.read(4)
                    if len(m) < 4 or m[0] != 0xFF:
                        return None
                    marker, seglen = m[1], struct.unpack(">H", m[2:4])[0]
                    if marker == 0xE1 and f.read(6) == b"Exif\0\0":
                        return _tiff_datetime(f, pos + 10)
                    if marker in (0xDA, 0xD9):
                        return None
                    pos += 2 + seglen
                return None
            if head[:2] in (b"II", b"MM"):                   # TIFF-based RAW
                return _tiff_datetime(f, 0)
    except (OSError, struct.error):
        return None
    return None



def capture_date(path):
    value = exif_capture(path, path.suffix.lower())
    if value:
        try:
            return dt.datetime.strptime(value, "%Y:%m:%d %H:%M:%S").date(), True
        except ValueError:
            pass
    return dt.datetime.fromtimestamp(path.stat().st_mtime).date(), False


def volume_guard(path):
    # Do not turn a disconnected /Volumes destination into a local directory.
    path = path.absolute()
    if str(path).startswith("/Volumes/"):
        mount = Path("/Volumes") / path.parts[2]
        if not mount.is_mount():
            raise ValueError("Drive is disconnected. Reconnect it and choose the folder again.")


def paths(source, destination):
    source = Path(source).expanduser()
    destination = Path(destination).expanduser()
    volume_guard(source)
    volume_guard(destination)
    if source.is_symlink() or destination.is_symlink():
        raise ValueError("Choose real folders, not symbolic links.")
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if not source.is_dir() or source in (Path("/"), Path.home()):
        raise ValueError("Choose a card or a specific folder containing media.")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and destination must be separate, non-overlapping folders.")
    return source, destination


def scan(source, kind):
    found, skipped = [], 0
    allowed = IMAGE_EXT if kind == "photos" else VIDEO_EXT if kind == "videos" else IMAGE_EXT | VIDEO_EXT
    for root, dirs, files in os.walk(source, onerror=lambda e: (_ for _ in ()).throw(e)):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(root) / d).is_symlink() and d.lower() != "system volume information")
        main_stems = {Path(n).stem.casefold() for n in files if Path(n).suffix.lower() in allowed}
        for name in sorted(files):
            p = Path(root) / name
            if name.startswith(".") or p.is_symlink() or not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext in allowed or (ext in COMPANION_EXT and p.stem.casefold() in main_stems):
                found.append(p)
            else:
                skipped += 1
    return sorted(found), skipped


def target_folder(destination, date, layout, shoot):
    folder = destination / (date.strftime("%Y/%m/%d") if layout == "nested" else str(date))
    if shoot:
        folder = folder.with_name(folder.name + " " + shoot)
    return folder


def free_target(folder, name, reserved):
    p = folder / name
    i = 1
    # Casefold even on case-sensitive disks, so moving a library later stays safe.
    existing = {x.name.casefold() for x in folder.iterdir()} if folder.exists() else set()
    while str(p).casefold() in reserved or p.name.casefold() in existing or p.exists() or p.is_symlink():
        p = folder / (Path(name).stem + "_" + str(i) + Path(name).suffix)
        i += 1
    reserved.add(str(p).casefold())
    return p


def commit_exclusive(part, target):
    """Never replace an existing destination, even after planning races."""
    if sys.platform == "darwin":
        lib = ctypes.CDLL(None, use_errno=True)
        rename = lib.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        # RENAME_EXCL, declared by macOS sys/stdio.h.
        if rename(os.fsencode(part), os.fsencode(target), 0x4):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(target))
    else:
        os.link(part, target)
        part.unlink()


def verified_copy(source, target, expected, thorough=True):
    before = identity(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".carddock-", suffix=".partial", dir=target.parent)
    part = Path(name)
    try:
        h = hashlib.sha256()
        src_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "wb") as out, os.fdopen(src_fd, "rb") as inp:
            for chunk in iter(lambda: inp.read(CHUNK), b""):
                out.write(chunk)
                h.update(chunk)
            out.flush()
            os.fsync(out.fileno())
        if h.hexdigest() != expected or digest(part) != expected or identity(source) != before:
            raise ValueError("Verification failed; source was kept: " + source.name)
        if thorough and digest(source) != expected:
            raise ValueError("Source changed during verification: " + source.name)
        os.utime(part, ns=(source.stat().st_atime_ns, before[3]))
        commit_exclusive(part, target)
        # Flush the directory entry where the filesystem supports it.
        dfd = os.open(target.parent, os.O_RDONLY)
        try:
            try:
                os.fsync(dfd)
            except OSError as e:
                if e.errno not in (errno.EINVAL, errno.ENOTSUP):
                    raise
        finally:
            os.close(dfd)
    finally:
        # Only this invocation's uniquely named temporary file is owned by us.
        part.unlink(missing_ok=True)


def valid_destination(destination, relative):
    p = destination / relative
    if p.is_symlink() or not p.is_file() or destination not in p.resolve().parents:
        return None
    return p


def index_database(destination, preview):
    path = destination / ".carddock" / "imports.sqlite3"
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Import history cannot be a symbolic link.")
    if preview:
        if not path.exists():
            return None
        return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS imports (sha TEXT NOT NULL, size INTEGER NOT NULL, dest TEXT NOT NULL UNIQUE, imported TEXT NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS imports_content ON imports(sha, size)")
    db.commit()
    return db


def existing_match(db, destination, source, sha, folder):
    candidates = []
    names = re.compile(re.escape(source.stem) + r"(?:_\d+)?" + re.escape(source.suffix) + r"$", re.IGNORECASE)
    if db:
        for (relative,) in db.execute("SELECT dest FROM imports WHERE sha=? AND size=?", (sha, source.stat().st_size)):
            p = valid_destination(destination, relative)
            if p and names.fullmatch(p.name):
                candidates.append(p)
    if folder.is_dir():
        candidates += [p for p in folder.iterdir() if names.fullmatch(p.name) and not p.is_symlink() and p.is_file() and p.stat().st_size == source.stat().st_size]
    for p in dict.fromkeys(candidates):
        if digest(p) == sha:
            return p
    return None


def record(db, destination, target, sha):
    with db:
        db.execute("INSERT OR REPLACE INTO imports VALUES (?,?,?,?)", (sha, target.stat().st_size, str(target.relative_to(destination)), dt.datetime.now().isoformat()))


def confirm(kind, message, valid, **payload):
    if GUI:
        event("PROMPT", kind=kind, options=valid, **payload)
    else:
        say(message)
    try:
        answer = input().strip()
    except EOFError:
        return ""
    return answer if answer in valid else ""


def delete_verified(source, target, sha, original_identity):
    # Re-check BOTH copies immediately before each deletion, including this run.
    if identity(source) != original_identity:
        raise ValueError("Source changed since scanning; kept on card.")
    if digest(target) != sha or digest(source) != sha:
        raise ValueError("Copies no longer match; kept on card.")
    if identity(source) != original_identity:
        raise ValueError("Source changed during verification; kept on card.")
    if getattr(source.stat(), "st_flags", 0) & getattr(stat, "UF_IMMUTABLE", 0):
        raise ValueError("Camera-protected file was kept on card.")
    source.unlink()


def run(args):
    source, destination = paths(args.source, args.dest)
    shoot = args.shoot.strip()
    if len(shoot) > 60 or any(c in shoot for c in '/\\:') or any(ord(c) < 32 for c in shoot) or shoot in (".", ".."):
        raise ValueError("Shoot name must be at most 60 characters without slashes or control characters.")
    source_dev = source.stat().st_dev
    event("INFO", library=str(destination), version=VERSION, dry_run=args.dry_run)
    say("CardDock " + VERSION)
    say("From: " + str(source))
    say("To:   " + str(destination))
    lock = None
    db = None
    try:
        if not args.dry_run:
            destination.mkdir(parents=True, exist_ok=True)
            meta = destination / ".carddock"
            meta.mkdir(exist_ok=True)
            if meta.is_symlink():
                raise ValueError("Import metadata folder cannot be a symbolic link.")
            lock = os.fdopen(os.open(meta / "lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another import is using this destination. Wait for it to finish.")
        db = index_database(destination, args.dry_run)
        anchor = destination if destination.exists() else next(p for p in destination.parents if p.exists())
        dest_dev = anchor.stat().st_dev
        def check_drives():
            volume_guard(source)
            volume_guard(destination)
            if source.stat().st_dev != source_dev or anchor.stat().st_dev != dest_dev:
                raise ValueError("A drive changed or disconnected. Import stopped.")
        event("STATUS", text="Checking files and comparing originals…")
        media, skipped = scan(source, args.kind)
        say(f"Found {len(media)} supported files; {skipped} other files left alone.")
        plan, duplicates, reserved = [], [], set()
        fallback = 0
        for i, p in enumerate(media):
            check_drives()
            snap = identity(p)
            sha = digest(p)
            date, embedded = capture_date(p)
            fallback += not embedded
            folder = target_folder(destination, date, args.layout, shoot)
            # A symlinked date folder must never escape the chosen destination.
            if destination not in folder.resolve().parents:
                raise ValueError("Destination subfolder points outside the library.")
            match = existing_match(db, destination, p, sha, folder)
            if match:
                duplicates.append((p, match, sha, snap))
            else:
                plan.append((p, free_target(folder, p.name, reserved), sha, snap))
            event("PROGRESS", pct=round(100 * (i+1) / max(len(media),1), 1), text=f"Checked {i+1} of {len(media)} files")
        RESULT["duplicates"] = len(duplicates)
        say(f"Plan: {len(plan)} new, {len(duplicates)} verified duplicates.")
        if fallback:
            say(f"Date note: {fallback} files use their filesystem date because capture metadata was unavailable.")
        for p, t, _, _ in plan:
            say("  " + p.name + " → " + str(t.relative_to(destination)))
        if args.dry_run:
            RESULT["planned"] = len(plan)
            return f"Preview: {len(plan)} new files, {len(duplicates)} verified duplicates. No files changed."
        required = sum(s[3][2] for s in plan)
        if plan and shutil.disk_usage(destination).free < required + FREE_MARGIN:
            raise ValueError("Not enough destination space, including a 256 MB safety margin.")
        copied = []
        event("STATUS", text="Copying and verifying originals…")
        for i, (p, t, sha, snap) in enumerate(plan):
            check_drives()
            try:
                if identity(p) != snap:
                    raise ValueError("Source changed after scanning.")
                verified_copy(p, t, sha, args.verify == "thorough")
                record(db, destination, t, sha)
                copied.append((p, t, sha, snap))
                RESULT["copied"] += 1
                say("Verified: " + str(t.relative_to(destination)))
            except (OSError, ValueError) as e:
                RESULT["failed"] += 1
                say("FAILED " + p.name + ": " + str(e))
            event("PROGRESS", pct=round(100*(i+1)/max(len(plan),1),1), text=f"Processed {i+1} of {len(plan)} new files")
        eligible = copied + (duplicates if args.scope == "all" else [])
        if args.ask_delete and eligible and not RESULT["failed"]:
            choice = confirm("delete", f"Delete {len(eligible)} verified originals? Type 1 to continue, or 2 to keep.", ["1", "2"], files=len(eligible))
            if choice == "1" and confirm("confirm", "Type DELETE to confirm permanent removal:", ["DELETE"], files=len(eligible)) == "DELETE":
                event("STATUS", text="Rechecking both copies before each deletion…")
                for p, t, sha, snap in eligible:
                    check_drives()
                    try:
                        delete_verified(p,t,sha,snap)
                        RESULT["deleted"] += 1
                    except (OSError, ValueError) as e:
                        RESULT["failed"] += 1
                        say("Kept " + p.name + ": " + str(e))
        if args.eject and not RESULT["failed"]:
            if source.is_mount() and sys.platform == "darwin":
                if confirm("eject", "Eject the card? y/n", ["y", "n"]) == "y":
                    status = subprocess.run(["/usr/sbin/diskutil", "eject", str(source)], capture_output=True, text=True)
                    say(status.stdout.strip() or status.stderr.strip())
                    if status.returncode:
                        RESULT["failed"] += 1
            else:
                say("Eject skipped: the selected source is a folder, not a mounted drive.")
        return f"{RESULT['copied']} copied · {RESULT['duplicates']} duplicates · {RESULT['deleted']} deleted · {RESULT['failed']} need attention"
    finally:
        if db:
            db.close()
        if lock:
            lock.close()


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, help="card or media folder")
    ap.add_argument("--dest", required=True, help="destination library folder")
    ap.add_argument("--dry-run", action="store_true", help="read-only preview")
    ap.add_argument("--kind", choices=("all","photos","videos"), default="all")
    ap.add_argument("--layout", choices=("daily","nested"), default="daily")
    ap.add_argument("--shoot", default="")
    ap.add_argument("--verify", choices=("thorough","standard"), default="thorough")
    ap.add_argument("--ask-delete", action="store_true", help="offer verified deletion; default keeps originals")
    ap.add_argument("--scope", choices=("run","all"), default="run")
    ap.add_argument("--eject", action="store_true", help="offer to eject on completion")
    ap.add_argument("--gui", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=VERSION)
    return ap.parse_args()


def main():
    global GUI
    args = parse_args()
    GUI = args.gui
    try:
        headline = run(args)
        code = 1 if RESULT["failed"] else 0
    except KeyboardInterrupt:
        headline = f"Stopped. {RESULT['copied']} copies completed; {RESULT['deleted']} originals already deleted. Remaining originals kept."
        code = 130
    except (OSError, ValueError, sqlite3.Error) as e:
        headline = "Stopped: " + str(e)
        code = 1
    say(headline)
    event("DONE", **RESULT, headline=headline, rc=code)
    return code


if __name__ == "__main__":
    sys.exit(main())
