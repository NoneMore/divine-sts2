"""Exercise the reusable shipped-game worker through its public RPC socket."""

from __future__ import annotations

import json
import os
import socket

from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig


def worker_for(worker_id: int) -> FullAppBridgeClient:
    return FullAppBridgeClient(FullAppClientConfig(
        process_mode="reuse", worker_id=os.getpid() * 10 + worker_id, timeout_seconds=90
    ))


def expect_rejected(worker: FullAppBridgeClient, method: str) -> None:
    try:
        if method == "start_run":
            worker.start_run()
        else:
            worker.call(method)
    except RuntimeError as error:
        assert "Bridge RPC error" in str(error), error
    else:
        raise AssertionError(f"{method} was accepted")


def main() -> None:
    worker = worker_for(40)
    try:
        worker.launch()
        hello = worker.hello()
        assert hello["process_mode"] == "reuse", hello
        assert hello["worker_state"] == "idle", hello
        try:
            worker.call("start_run", {"process_mode": "fresh"})
        except RuntimeError as error:
            assert "does not match" in str(error), error
        else:
            raise AssertionError("A mode-mismatched start_run was accepted")
        assert worker.hello()["worker_state"] == "idle"
        started = worker.start_run(seed="A1B2C3D4E5", character="IRONCLAD", ascension=0)
        assert started["observation"]["phase"]
        assert worker.hello()["worker_state"] == "running"
        ended = worker.end_run()
        assert ended["ended_generation"] == 1, ended
        assert ended["ending_phase"] == started["observation"]["phase"], ended
        assert ended["parked_wait_released"] is True, ended
        assert ended["stale_continuation_refusals"] >= 1, ended
        assert ended["driver_result"] in ("cancelled", "abandoned"), ended
        assert ended["reset_history_counts"] == {"actions": 0, "state_hashes": 1}, ended
        assert ended["final_state"] == "idle", ended
        assert ended["duration_ms"] >= 0, ended
        assert worker.hello()["worker_state"] == "idle"
        assert worker.process is not None and worker.process.poll() is None
        expect_rejected(worker, "step")
        expect_rejected(worker, "hello")  # Poisoned accepts only close.
    finally:
        worker.close()

    worker = worker_for(41)
    try:
        worker.launch()
        expect_rejected(worker, "end_run")
        expect_rejected(worker, "hello")
    finally:
        worker.close()

    worker = worker_for(42)
    try:
        worker.launch()
        worker.start_run()
        expect_rejected(worker, "start_run")
        expect_rejected(worker, "hello")
    finally:
        worker.close()

    worker = worker_for(43)
    try:
        worker.launch()
        worker.start_run()
        with socket.create_connection(("127.0.0.1", worker.bound_port), timeout=5):
            expect_rejected(worker, "hello")
    finally:
        worker.close()

    worker = worker_for(44)
    try:
        worker.launch()
        worker.start_run()
        assert worker.sock is not None and worker.file_reader is not None
        worker.sock.sendall(
            (json.dumps({"id": 100, "method": "end_run", "params": {}}) + "\n"
             + json.dumps({"id": 101, "method": "step", "params": {"action_id": "proceed"}}) + "\n")
            .encode("utf-8")
        )
        responses = [json.loads(worker.file_reader.readline()) for _ in range(2)]
        assert {response["id"] for response in responses} == {100, 101}, responses
        assert all(response["error"] for response in responses), responses
        expect_rejected(worker, "hello")
    finally:
        worker.close()

    worker = worker_for(45)
    try:
        worker.launch()
        started = worker.start_run()
        first_action = started["legal_actions"][0]["action_id"]
        advanced = worker.step(first_action)
        assert advanced["observation"]["phase"]
        ended = worker.end_run()
        assert ended["ending_phase"] == advanced["observation"]["phase"], ended
        assert ended["reset_history_counts"] == {"actions": 1, "state_hashes": 2}, ended
        assert ended["final_state"] == "idle", ended
    finally:
        worker.close()

    fresh = FullAppBridgeClient(FullAppClientConfig(
        worker_id=os.getpid() * 10 + 46, timeout_seconds=90
    ))
    try:
        fresh.launch()
        assert fresh.hello()["process_mode"] == "fresh"
        expect_rejected(fresh, "end_run")
        expect_rejected(fresh, "hello")
    finally:
        fresh.close()


if __name__ == "__main__":
    main()
