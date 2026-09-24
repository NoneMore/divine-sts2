from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sts2_native_sim import full_app_client
from sts2_native_sim.full_app_client import FullAppClientConfig
from sts2_native_sim.reusable_full_app_worker import ReusableFullAppWorker, RunEntry

BRIDGE = r"""
import json
import os
import socket
from pathlib import Path

index = int(os.environ["TEST_LAUNCH_INDEX"])
mode = os.environ.get("TEST_FAILURE", "")
events = Path(os.environ["TEST_EVENTS"])
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen()
Path(os.environ["STS2_FULL_APP_BRIDGE_PORT_FILE"]).write_text(str(listener.getsockname()[1]))
connection, _ = listener.accept()
reader = connection.makefile("r")
writer = connection.makefile("w")
ordinal = 0

def record(event):
    with events.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"launch": index, "event": event}) + "\n")

while line := reader.readline():
    request = json.loads(line)
    method = request["method"]
    record(method)
    if method == "hello":
        result = {"status": "ready", "process_mode": "reuse", "pid": os.getpid(),
                  "profile_fingerprint": "drifted" if mode == "drift" and index > 1 else "canonical",
                  "game_build": {} if mode == "no_build" and index == 1 else {"pck_sha256": "test"}}
    elif method == "start_run":
        ordinal += 1
        result = {"started": True, "process_mode": "reuse", "pid": os.getpid(),
                  "process_entry_ordinal": ordinal,
                  "start_path": "direct" if mode == "wrong_start" and index == 1 else
                                ("menu" if ordinal == 1 else "direct"),
                  "observation": {"seed": request["params"]["seed"]}}
    elif method == "observe":
        if mode == "socket" and index == 1:
            connection.shutdown(socket.SHUT_RDWR)
            connection.close()
            break
        result = {"ordinal": ordinal}
    elif method == "end_run":
        if mode == "teardown" and index == 1:
            writer.write(json.dumps({"id": request["id"], "error": "teardown failed"}) + "\n")
            writer.flush()
            continue
        result = {"final_state": "idle", "driver_result": "abandoned",
                  "ended_generation": ordinal, "ending_phase": "ancient",
                  "parked_wait_released": True, "stale_continuation_refusals": 1,
                  "reset_history_counts": {"actions": 0, "state_hashes": 1}, "duration_ms": 1}
        if mode == "partial_teardown" and index == 1:
            result = {"final_state": "idle"}
    elif method == "close":
        result = {"closed": True}
    else:
        result = {}
    writer.write(json.dumps({"id": request["id"], "result": result}) + "\n")
    writer.flush()
    if method == "close" or (method == "end_run" and mode == "exit_after_end" and index == 1):
        break
"""


@pytest.fixture
def controlled_worker(fake_install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bridge_package = tmp_path / "bridge-package"
    protocol_package = tmp_path / "protocol-package"
    bridge_package.mkdir()
    protocol_package.mkdir()
    (bridge_package / "sts2-full-app-bridge.dll").write_bytes(b"bridge")
    (protocol_package / "Sts2.NativeSim.Protocol.dll").write_bytes(b"protocol")
    monkeypatch.setattr(full_app_client, "bridge_package_dir", lambda: bridge_package)
    monkeypatch.setattr(full_app_client, "protocol_package_dir", lambda: protocol_package)
    script = tmp_path / "bridge.py"
    script.write_text(BRIDGE, encoding="utf-8")
    events = tmp_path / "events.jsonl"
    original_popen = subprocess.Popen
    launches = []

    def spawn(args, **kwargs):
        if Path(args[0]).name != "SlayTheSpire2.exe":
            return original_popen(args, **kwargs)
        launch_index = len(launches) + 1
        kwargs["env"] = dict(
            kwargs["env"],
            TEST_LAUNCH_INDEX=str(launch_index),
            TEST_FAILURE=os.environ.get("TEST_FAILURE", ""),
            TEST_EVENTS=str(events),
        )
        process = original_popen([getattr(sys, "_base_executable", sys.executable), str(script)], **kwargs)
        launches.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    config = FullAppClientConfig(
        game_root=str(fake_install), sandbox_root=str(tmp_path / "sandboxes"), timeout_seconds=0.5, process_mode="reuse"
    )
    workers = []

    def create(**kwargs):
        worker = ReusableFullAppWorker(config, **kwargs)
        workers.append(worker)
        return worker

    yield create, launches, events
    for worker in workers:
        worker.close()
    for process in launches:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


def test_healthy_worker_recycles_only_for_entry_after_default_cap(controlled_worker):
    create, launches, _ = controlled_worker
    worker = create()

    results = [worker.run_entry(RunEntry(seed=f"SEED{i}"), lambda client, started: started) for i in range(17)]

    assert all(result.succeeded for result in results), [result.error for result in results]
    assert len(launches) == 2
    assert [result.process_entry_ordinal for result in results] == list(range(1, 17)) + [1]
    assert [result.start_path for result in results] == ["menu"] + ["direct"] * 15 + ["menu"]
    assert [result.replacement_count for result in results] == [0] * 16 + [1]
    assert [result.pck_fingerprint_bytes for result in results] == [3] + [0] * 15 + [3]
    assert [result.pck_fingerprint_count for result in results] == [1] + [0] * 15 + [1]
    assert all(result.pid == launches[0].pid for result in results[:16])
    assert results[16].pid == launches[1].pid
    assert results[0].startup_seconds > 0 and results[1].startup_seconds == 0
    assert all(result.close_seconds == 0 for result in results[:15])
    assert results[15].close_seconds > 0
    assert all(result.entry_seconds >= 0 and result.teardown_seconds >= 0 for result in results)
    assert all(result.teardown and result.teardown["final_state"] == "idle" for result in results)
    assert launches[0].poll() is not None


def test_socket_loss_poisoning_records_failure_once_and_next_entry_replaces(controlled_worker, monkeypatch):
    create, launches, events = controlled_worker
    monkeypatch.setenv("TEST_FAILURE", "socket")
    worker = create()

    failed = worker.run_entry(RunEntry("FIRST"), lambda client, started: client.observe())
    continued = worker.run_entry(RunEntry("SECOND"), lambda client, started: client.observe())

    assert not failed.succeeded
    assert failed.error and "EOFError" in failed.error
    assert continued.succeeded
    assert continued.value == {"ordinal": 1}
    assert continued.replacement_count == 1
    assert continued.start_path == "menu"
    assert len(launches) == 2
    assert launches[0].poll() is not None
    traffic = [json.loads(line) for line in events.read_text().splitlines()]
    assert [event["event"] for event in traffic if event["event"] == "start_run"] == ["start_run", "start_run"]


def test_teardown_failure_poisoning_does_not_retry_failed_entry(controlled_worker, monkeypatch):
    create, launches, events = controlled_worker
    monkeypatch.setenv("TEST_FAILURE", "teardown")
    worker = create()

    failed = worker.run_entry(RunEntry("FIRST"), lambda client, started: started["observation"])
    continued = worker.run_entry(RunEntry("SECOND"), lambda client, started: started["observation"])

    assert not failed.succeeded
    assert failed.value is None
    assert failed.error and "teardown failed" in failed.error
    assert continued.succeeded and continued.value == {"seed": "SECOND"}
    assert continued.replacement_count == 1
    assert len(launches) == 2
    assert launches[0].poll() is not None
    traffic = [json.loads(line) for line in events.read_text().splitlines()]
    assert [(event["launch"], event["event"]) for event in traffic if event["event"] == "start_run"] == [
        (1, "start_run"),
        (2, "start_run"),
    ]


def test_driver_failure_discards_process_before_later_entry(controlled_worker):
    create, launches, _ = controlled_worker
    worker = create()

    def fail(client, started):
        raise ValueError("driver rejected the decision")

    failed = worker.run_entry(RunEntry("FIRST"), fail)
    continued = worker.run_entry(RunEntry("SECOND"), lambda client, started: started["observation"])

    assert not failed.succeeded and failed.error == "ValueError: driver rejected the decision"
    assert failed.teardown is None
    assert continued.succeeded and continued.start_path == "menu"
    assert len(launches) == 2


def test_replacement_revalidates_sandbox_before_starting_next_entry(controlled_worker, monkeypatch):
    create, launches, events = controlled_worker
    monkeypatch.setenv("TEST_FAILURE", "drift")
    worker = create(max_entries=1)

    first = worker.run_entry(RunEntry("FIRST"), lambda client, started: started)
    second = worker.run_entry(RunEntry("SECOND"), lambda client, started: started)

    assert first.succeeded
    assert not second.succeeded and second.error == "RuntimeError: Replacement sandbox profile fingerprint changed"
    assert second.replacement_count == 1
    assert len(launches) == 2 and launches[1].poll() is not None
    traffic = [json.loads(line) for line in events.read_text().splitlines()]
    assert [(event["launch"], event["event"]) for event in traffic if event["event"] == "start_run"] == [
        (1, "start_run")
    ]


def test_illegal_start_response_poisoning_replaces_for_later_entry(controlled_worker, monkeypatch):
    create, launches, _ = controlled_worker
    monkeypatch.setenv("TEST_FAILURE", "wrong_start")
    worker = create()

    failed = worker.run_entry(RunEntry("FIRST"), lambda client, started: started)
    continued = worker.run_entry(RunEntry("SECOND"), lambda client, started: started)

    assert not failed.succeeded and failed.error and "Illegal start_run response" in failed.error
    assert continued.succeeded and continued.start_path == "menu"
    assert len(launches) == 2 and launches[0].poll() is not None


def test_idle_process_exit_replaced_before_next_entry_starts(controlled_worker, monkeypatch):
    create, launches, _ = controlled_worker
    monkeypatch.setenv("TEST_FAILURE", "exit_after_end")
    worker = create()

    first = worker.run_entry(RunEntry("FIRST"), lambda client, started: started)
    launches[0].wait(timeout=2)
    second = worker.run_entry(RunEntry("SECOND"), lambda client, started: started)

    assert first.succeeded and second.succeeded
    assert second.replacement_count == 1 and second.start_path == "menu"
    assert len(launches) == 2


def test_one_lane_serializes_overlapping_callers(controlled_worker):
    create, launches, events = controlled_worker
    worker = create()
    entered = threading.Event()
    release = threading.Event()

    def hold(client, started):
        entered.set()
        assert release.wait(timeout=3)
        return started

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(worker.run_entry, RunEntry("FIRST"), hold)
        assert entered.wait(timeout=3)
        second_future = pool.submit(worker.run_entry, RunEntry("SECOND"), lambda client, started: started)
        traffic = [json.loads(line) for line in events.read_text().splitlines()]
        assert [event["event"] for event in traffic].count("start_run") == 1
        release.set()
        first, second = first_future.result(timeout=3), second_future.result(timeout=3)

    assert first.succeeded and second.succeeded
    assert (first.process_entry_ordinal, second.process_entry_ordinal) == (1, 2)
    assert len(launches) == 1


def test_missing_build_fingerprint_poisoning_does_not_claim_pck_work(controlled_worker, monkeypatch):
    create, launches, _ = controlled_worker
    monkeypatch.setenv("TEST_FAILURE", "no_build")
    worker = create()

    failed = worker.run_entry(RunEntry("FIRST"), lambda client, started: started)
    continued = worker.run_entry(RunEntry("SECOND"), lambda client, started: started)

    assert not failed.succeeded and failed.error and "build fingerprint" in failed.error
    assert failed.pck_fingerprint_count == 0
    assert continued.succeeded and continued.pck_fingerprint_count == 1
    assert len(launches) == 2


def test_incomplete_teardown_evidence_poisoning_replaces_for_later_entry(controlled_worker, monkeypatch):
    create, launches, _ = controlled_worker
    monkeypatch.setenv("TEST_FAILURE", "partial_teardown")
    worker = create()

    failed = worker.run_entry(RunEntry("FIRST"), lambda client, started: started)
    continued = worker.run_entry(RunEntry("SECOND"), lambda client, started: started)

    assert not failed.succeeded and failed.error and "Illegal end_run response" in failed.error
    assert continued.succeeded and continued.replacement_count == 1
    assert len(launches) == 2 and launches[0].poll() is not None


def test_close_during_launch_cannot_leave_a_process_behind(controlled_worker, monkeypatch):
    create, launches, _ = controlled_worker
    worker = create()
    spawn_entered = threading.Event()
    allow_spawn = threading.Event()
    original_spawn = subprocess.Popen

    def delayed_spawn(args, **kwargs):
        if Path(args[0]).name == "SlayTheSpire2.exe":
            spawn_entered.set()
            assert allow_spawn.wait(timeout=3)
        return original_spawn(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", delayed_spawn)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker.run_entry, RunEntry("FIRST"), lambda client, started: started)
        assert spawn_entered.wait(timeout=3)
        worker.close()
        allow_spawn.set()
        result = future.result(timeout=3)

    assert not result.succeeded
    assert len(launches) == 1 and launches[0].poll() is not None
