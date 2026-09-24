"""The certification RPC reads the same semantic profile from memory and persisted progress."""

from __future__ import annotations

import secrets

from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig


def main() -> None:
    worker = FullAppBridgeClient(FullAppClientConfig(
        worker_id=1_000_000_000_000 + secrets.randbelow(1_000_000_000_000),
        process_mode="reuse", timeout_seconds=90,
    ))
    try:
        worker.launch()
        baseline = worker.hello()["profile_fingerprint"]
        expected = {"in_memory": baseline, "persisted": baseline}
        assert worker.call("profile_snapshot") == expected
        worker.start_run("A1B2C3D4E5", "IRONCLAD", 0)
        worker.end_run()
        assert worker.call("profile_snapshot") == expected
    finally:
        worker.close()


if __name__ == "__main__":
    main()
