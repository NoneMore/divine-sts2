from __future__ import annotations

import hashlib
import os

from sts2_native_sim.pck_fingerprint import PckFingerprint


def test_pool_fingerprint_rejects_changed_file_even_when_size_is_unchanged(tmp_path):
    pck = tmp_path / "SlayTheSpire2.pck"
    pck.write_bytes(b"first")
    fingerprint = PckFingerprint.measure(pck)
    assert fingerprint.sha256 == hashlib.sha256(b"first").hexdigest().upper()
    assert fingerprint.is_current()

    replacement = tmp_path / "replacement.pck"
    replacement.write_bytes(b"later")
    stat = replacement.stat()
    os.utime(replacement, ns=(stat.st_atime_ns, fingerprint.mtime_ns))
    os.replace(replacement, pck)
    assert pck.stat().st_size == fingerprint.size
    assert pck.stat().st_mtime_ns == fingerprint.mtime_ns
    assert not fingerprint.is_current()
