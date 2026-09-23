from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from sts2_native_sim import full_app_client
from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig


WORKER = r'''
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
Path(os.environ["STS2_TEST_CHILD_PID"]).write_text(str(child.pid), encoding="ascii")
mode = os.environ["STS2_TEST_MODE"]
if mode == "parent_exits":
    sys.exit(7)
elif mode == "no_port":
    time.sleep(120)
elif mode == "no_listener":
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    Path(os.environ["STS2_FULL_APP_BRIDGE_PORT_FILE"]).write_text(str(port), encoding="ascii")
    time.sleep(120)
else:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    Path(os.environ["STS2_FULL_APP_BRIDGE_PORT_FILE"]).write_text(
        str(listener.getsockname()[1]), encoding="ascii"
    )
    connection, _ = listener.accept()
    reader = connection.makefile("r")
    writer = connection.makefile("w")
    run_active = False
    while line := reader.readline():
        request = json.loads(line)
        if request["method"] == "start_run":
            run_active = True
        if request["method"] == "close":
            Path(os.environ["STS2_TEST_CLOSE_MARKER"]).write_text("close", encoding="ascii")
        if mode == "broken_handshake":
            connection.shutdown(socket.SHUT_RDWR)
            connection.close()
            time.sleep(120)
        elif mode == "failed_readiness":
            writer.write(json.dumps({"id": request["id"], "result": {"status": "failed"}}) + "\n")
            writer.flush()
        elif mode == "slow_close" and request["method"] == "close":
            time.sleep(120)
        elif mode == "active_run" and run_active and request["method"] == "close":
            time.sleep(120)
        else:
            writer.write(json.dumps({"id": request["id"], "result": {"status": "ready"}}) + "\n")
            writer.flush()
'''


@pytest.fixture
def controlled_client(
    fake_install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bridge_package = tmp_path / "bridge-package"
    protocol_package = tmp_path / "protocol-package"
    bridge_package.mkdir()
    protocol_package.mkdir()
    (bridge_package / "sts2-full-app-bridge.dll").write_bytes(b"bridge")
    (protocol_package / "Sts2.NativeSim.Protocol.dll").write_bytes(b"protocol")
    monkeypatch.setattr(full_app_client, "bridge_package_dir", lambda: bridge_package)
    monkeypatch.setattr(full_app_client, "protocol_package_dir", lambda: protocol_package)
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    child_pid_file = tmp_path / "child.pid"
    close_marker = tmp_path / "close-requested"
    original_popen = subprocess.Popen
    started: list[int] = []

    def spawn_worker(args, **kwargs):
        if not args or Path(args[0]).name != "SlayTheSpire2.exe":
            return original_popen(args, **kwargs)
        mode = os.environ["STS2_TEST_MODE"]
        kwargs["env"] = dict(
            kwargs["env"],
            STS2_TEST_MODE=mode,
            STS2_TEST_CHILD_PID=str(child_pid_file),
            STS2_TEST_CLOSE_MARKER=str(close_marker),
        )
        process = original_popen([sys.executable, str(script)], **kwargs)
        started.append(process.pid)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn_worker)
    client = FullAppBridgeClient(
        FullAppClientConfig(
            game_root=str(fake_install), sandbox_root=str(tmp_path / "sandboxes"), timeout_seconds=0.5
        )
    )
    yield client, started, child_pid_file, close_marker
    client.close()
    for pid in started + ([int(child_pid_file.read_text())] if child_pid_file.exists() else []):
        if psutil.pid_exists(pid):
            try:
                process = psutil.Process(pid)
                for child in process.children(recursive=True):
                    child.kill()
                process.kill()
            except psutil.NoSuchProcess:
                pass


def _wait_for_pid(path: Path) -> int:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if path.exists():
            return int(path.read_text(encoding="ascii"))
        time.sleep(0.01)
    pytest.fail("controlled worker did not start a child")


def _assert_tree_dead(parent_pid: int, child_pid: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and (psutil.pid_exists(parent_pid) or psutil.pid_exists(child_pid)):
        time.sleep(0.02)
    assert not psutil.pid_exists(parent_pid)
    assert not psutil.pid_exists(child_pid)


@pytest.mark.parametrize("mode, error", [
    ("parent_exits", RuntimeError),
    ("no_port", TimeoutError),
    ("no_listener", ConnectionError),
    ("broken_handshake", EOFError),
    ("failed_readiness", RuntimeError),
])
def test_partial_launch_ends_parent_and_descendant(
    controlled_client, monkeypatch: pytest.MonkeyPatch, mode: str, error: type[Exception]
) -> None:
    client, started, child_pid_file, _ = controlled_client
    monkeypatch.setenv("STS2_TEST_MODE", mode)

    with pytest.raises(error):
        client.launch()

    _assert_tree_dead(started[0], _wait_for_pid(child_pid_file))


@pytest.mark.parametrize("mode", ["ready", "slow_close", "active_run"])
def test_active_close_ends_parent_and_descendant_promptly(
    controlled_client, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    client, started, child_pid_file, close_marker = controlled_client
    monkeypatch.setenv("STS2_TEST_MODE", mode)
    client.launch()
    child_pid = _wait_for_pid(child_pid_file)
    if mode == "active_run":
        client.start_run()

    started_at = time.monotonic()
    client.close()

    assert time.monotonic() - started_at < 2
    _assert_tree_dead(started[0], child_pid)
    assert close_marker.read_text(encoding="ascii") == "close"


def test_launch_while_worker_is_active_keeps_its_process_owned(
    controlled_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, started, child_pid_file, _ = controlled_client
    monkeypatch.setenv("STS2_TEST_MODE", "ready")
    client.launch()
    child_pid = _wait_for_pid(child_pid_file)

    with pytest.raises(RuntimeError, match="already running"):
        client.launch()

    assert len(started) == 1
    client.close()
    _assert_tree_dead(started[0], child_pid)
