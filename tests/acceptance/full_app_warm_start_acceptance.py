"""A reused shipped process must start a clean second run through its public RPC."""

from __future__ import annotations

import os

from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig


def worker(mode: str, index: int) -> FullAppBridgeClient:
    return FullAppBridgeClient(FullAppClientConfig(
        process_mode=mode, worker_id=os.getpid() * 10 + index, timeout_seconds=90
    ))


def initial_state(client: FullAppBridgeClient, seed: str, character: str) -> dict:
    started = client.start_run(seed=seed, character=character, ascension=0)
    history = client.history()
    assert history["actions"] == [], history
    assert history["state_hashes"] == [started["observation"]["state_hash"]], history
    assert started["observation"]["character"].endswith(character), started
    return started["observation"]


def main() -> None:
    reused = worker("reuse", 50)
    fresh = worker("fresh", 51)
    repeated_worker = worker("reuse", 52)
    repeated_fresh = worker("fresh", 53)
    try:
        reused.launch()
        pid = reused.hello()["pid"]
        first = initial_state(reused, "A1B2C3D4E5", "IRONCLAD")
        action = reused.call("legal_actions")[0]["action_id"]
        reused.step(action)
        ended = reused.end_run()
        assert ended["final_state"] == "idle", ended
        assert ended["reset_history_counts"] == {"actions": 1, "state_hashes": 2}, ended
        assert ended["driver_result"] in ("cancelled", "abandoned"), ended
        assert ended["stale_continuation_refusals"] >= 1, ended

        second = initial_state(reused, "B2C3D4E5F6", "SILENT")
        assert reused.hello()["pid"] == pid
        assert second["state_hash"] != first["state_hash"]
        fresh.launch()
        independent_second = initial_state(fresh, "B2C3D4E5F6", "SILENT")
        assert second == independent_second, (second, independent_second)

        repeated_worker.launch()
        initial_state(repeated_worker, "A1B2C3D4E5", "IRONCLAD")
        repeated_worker.end_run()
        repeated = initial_state(repeated_worker, "A1B2C3D4E5", "IRONCLAD")
        repeated_fresh.launch()
        independent_repeat = initial_state(repeated_fresh, "A1B2C3D4E5", "IRONCLAD")
        assert repeated == independent_repeat, (repeated, independent_repeat)
    finally:
        reused.close()
        fresh.close()
        repeated_worker.close()
        repeated_fresh.close()


if __name__ == "__main__":
    main()
