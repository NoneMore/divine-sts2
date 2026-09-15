#!/usr/bin/env python3
"""Verify the full-app sandbox starts a content-complete run at requested settings."""

from __future__ import annotations

import json
from typing import Any

from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig


def main() -> int:
    client = FullAppBridgeClient(FullAppClientConfig(worker_id=99, timeout_seconds=90.0))
    try:
        client.launch(requested_character="DEFECT")
        hello = client.hello()
        if hello.get("unlock_policy") != "all":
            raise AssertionError(f"unexpected hello unlock policy: {hello!r}")

        started = client.start_run(seed="FULLUNLOCK", character="DEFECT", ascension=10)
        if started.get("unlock_policy") != "all":
            raise AssertionError(f"unexpected start unlock policy: {started!r}")

        observation: dict[str, Any] = started.get("observation") or {}
        if observation.get("character") != "DEFECT":
            raise AssertionError(f"requested character was not applied: {observation!r}")
        if observation.get("ascension") != 10:
            raise AssertionError(f"requested Ascension was not applied: {observation!r}")

        history = client.history()
        if history.get("unlock_policy") != "all":
            raise AssertionError(f"unexpected history unlock policy: {history!r}")

        print(json.dumps({
            "unlock_policy": started["unlock_policy"],
            "character": observation["character"],
            "ascension": observation["ascension"],
            "phase": observation.get("phase"),
        }, sort_keys=True))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
