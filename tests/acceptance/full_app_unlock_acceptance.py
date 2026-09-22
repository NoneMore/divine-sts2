#!/usr/bin/env python3
"""Verify a full-app sandbox materializes and reuses the progression-complete baseline."""

from __future__ import annotations

import json
from typing import Any

from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig, bridge_run


def main() -> int:
    config = FullAppClientConfig(worker_id=199, timeout_seconds=90.0)
    first = FullAppBridgeClient(config)
    try:
        first.launch(requested_character="IRONCLAD")
        first_hello = first.hello()
        if first_hello.get("status") != "ready":
            raise AssertionError(f"first launch was not ready: {first_hello!r}")
        first_fingerprint = first_hello.get("profile_fingerprint")
        if not isinstance(first_fingerprint, str) or len(first_fingerprint) != 64:
            raise AssertionError(f"first launch did not report a canonical profile fingerprint: {first_hello!r}")
    finally:
        first.close()

    client = FullAppBridgeClient(config)
    try:
        client.launch(requested_character="DEFECT")
        hello = client.hello()
        if hello.get("unlock_policy") != "all":
            raise AssertionError(f"unexpected hello unlock policy: {hello!r}")
        if hello.get("progression_policy") != "progression-complete-v1":
            raise AssertionError(f"unexpected progression policy: {hello!r}")
        if hello.get("profile_fingerprint") != first_fingerprint:
            raise AssertionError(f"profile provisioning was not idempotent: {first_hello!r} then {hello!r}")
        if not hello.get("game_build") or hello.get("pid") != client.process.pid or hello.get("bound_port") != client.bound_port:
            raise AssertionError(f"ready handshake lacks build/process provenance: {hello!r}")

        # This seed rolls Overgrowth. On an undiscovered profile the shipped game overrides that roll
        # with Underdocks, so observing Overgrowth proves Act discovery came from the baseline.
        started = client.start_run(seed="SCENAR10A01", character="DEFECT", ascension=2)
        if started.get("unlock_policy") != "all":
            raise AssertionError(f"unexpected start unlock policy: {started!r}")
        if started.get("profile_fingerprint") != first_fingerprint:
            raise AssertionError(f"start_run used a different profile baseline: {started!r}")

        observation: dict[str, Any] = started.get("observation") or {}
        if observation.get("character") != "DEFECT":
            raise AssertionError(f"requested character was not applied: {observation!r}")
        if bridge_run(observation).get("ascension") != 2:
            raise AssertionError(f"requested Ascension was not applied: {observation!r}")
        if bridge_run(observation).get("act_variant") != "OVERGROWTH":
            raise AssertionError(f"discovered Act did not follow the run seed: {observation!r}")

        history = client.history()
        if history.get("unlock_policy") != "all":
            raise AssertionError(f"unexpected history unlock policy: {history!r}")

        result = {
            "unlock_policy": started["unlock_policy"],
            "progression_policy": hello["progression_policy"],
            "profile_fingerprint": first_fingerprint,
            "character": observation["character"],
            "ascension": bridge_run(observation)["ascension"],
            "act_variant": bridge_run(observation)["act_variant"],
            "phase": observation.get("phase"),
        }
    finally:
        client.close()

    # Starting A2 writes A2 back as the shipped profile preference. That preference is not a
    # progression gate, so a third launch must still validate the same semantic fingerprint.
    third = FullAppBridgeClient(config)
    try:
        third.launch(requested_character="IRONCLAD")
        third_hello = third.hello()
        if third_hello.get("profile_fingerprint") != first_fingerprint:
            raise AssertionError(f"stored run preference changed the semantic fingerprint: {third_hello!r}")
    finally:
        third.close()

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
