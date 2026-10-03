"""Private dataset identity. Fingerprints stay outside published metadata."""
import ctypes
import os
import hashlib
import json
import shutil
import tempfile
from pathlib import Path


def event_key(row):
    return row.get('event_id') or f"{row['org']}/{row['repo']}@{row['sha']}"


def fingerprint(rows, scope):
    payload={'scope':scope,'events':sorted(rows,key=event_key)}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def content_digest(doc):
    return hashlib.sha256(json.dumps(doc,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _exchange(left, right):
    """Linux atomic directory exchange; fail closed when unavailable."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise OSError('Atomic snapshot exchange requires Linux renameat2')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(left), -100, os.fsencode(right), 2) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def replace_generation(staged, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        # One syscall exposes either complete generation, with no missing-path
        # window even when a process is interrupted. Old output now is staged.
        _exchange(staged, destination)
        shutil.rmtree(staged)
    else:
        staged.rename(destination)


def write_snapshot(destination, files):
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged=Path(tempfile.mkdtemp(prefix='snapshot-',dir=destination.parent))
    try:
        for name,doc in files.items():
            (staged/name).write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
        replace_generation(staged,destination)
    finally:
        if staged.exists():shutil.rmtree(staged)
