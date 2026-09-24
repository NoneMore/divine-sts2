from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

from .full_app_sandbox import SandboxLayout, share_install
from .paths import find_game_root, find_sandbox_root
from .process_tree import OwnedProcessTree


def _package_dir(project_name: str) -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / project_name
        / "bin"
        / "Release"
        / "net9.0"
        / "package"
    )


def bridge_package_dir() -> Path:
    """Where the built full-app bridge mod package lives."""
    return _package_dir("Sts2.NativeSim.FullAppBridge")


def protocol_package_dir() -> Path:
    """Where the built shared protocol mod package lives."""
    return _package_dir("Sts2.NativeSim.Protocol")


def bridge_run(observation: dict[str, Any]) -> dict[str, Any]:
    """The run block of a full-app bridge observation, or an empty block when it carries none.

    The bridge reports where the run is as one block — its seed, Ascension and gold, the Act it is in
    and how far into it, the run's total floor and its named RNG counters — the way the simulator's
    own observation reports it, so a reader reaches every one of those through one name rather than a
    flat field per quantity. A bridge older than that block, or an observation taken with no run to
    describe, yields an empty block and so a caller's own default; the acceptance script is the reader
    that fails loudly instead, because a wrong shape is what it exists to catch.

    `run["act_index"]` is the run's own zero-based act index — one-based act numbers are the caller's
    to derive, and `run["total_floor"]` is the map points travelled, which is the counter the Ancient
    room advances.
    """
    return _bridge_block(observation, "run")


def bridge_inventory(observation: dict[str, Any]) -> dict[str, Any]:
    """The inventory block of a full-app bridge observation: relics in order, potions by slot.

    A relic is an object with its model id, the counter it shows and its own saved state; a potion is
    an entry per slot with `null` where the slot is empty, so a slot index is never renumbered away.
    An observation that carries no inventory yields an empty block, as the run block does.
    """
    return _bridge_block(observation, "inventory")


def bridge_potion_count(observation: dict[str, Any]) -> int:
    """How many of the run's potion slots hold a potion.

    The belt is one entry per slot with `null` where the slot is empty, so the potions a run holds are
    the entries that are not null and not the entries there are: a three-slot belt reads as length 3
    whether it is full or empty, which is the trap a slot-preserving list sets for a reader of `len`.
    """
    return sum(1 for potion in bridge_inventory(observation).get("potions", []) if potion)


def _bridge_block(observation: dict[str, Any], member: str) -> dict[str, Any]:
    """One object-valued block of a bridge observation, or an empty block when it is absent."""
    block = observation.get(member)
    return block if isinstance(block, dict) else {}


@dataclass
class FullAppClientConfig:
    game_root: str = field(default_factory=lambda: str(find_game_root()))
    sandbox_root: str = ""
    worker_id: int = 0
    port: int = 0
    timeout_seconds: float = 60.0
    process_mode: str = "fresh"

    def __post_init__(self) -> None:
        if self.process_mode not in ("fresh", "reuse"):
            raise ValueError("process_mode must be 'fresh' or 'reuse'")
        if not self.sandbox_root:
            # A sandbox hard-links the install, so it defaults to the volume of
            # the game root this config names rather than a second discovery.
            self.sandbox_root = str(find_sandbox_root(game_root=self.game_root))


class FullAppBridgeClient:
    def __init__(self, config: FullAppClientConfig) -> None:
        self.config = config
        self.sandbox_root = Path(config.sandbox_root).expanduser().resolve()
        self.sandbox_dir = self.sandbox_root / f"worker_{config.worker_id}"
        self.sandbox_layout: Optional[SandboxLayout] = None
        self.process: Optional[subprocess.Popen[bytes]] = None
        self._owned_process: Optional[OwnedProcessTree] = None
        self.sock: Optional[socket.socket] = None
        self.file_reader: Optional[TextIO] = None
        self.file_writer: Optional[TextIO] = None
        self.request_id = 0
        self.bound_port = 0
        self.launch_timings: dict[str, float] = {}
        self.last_close_seconds = 0.0
        self.ready_hello: dict[str, Any] = {}
        self.processes_started = 0

    def prepare_sandbox(self, requested_character: str = "IRONCLAD") -> SandboxLayout:
        game_root = Path(self.config.game_root).resolve()
        if not game_root.exists():
            raise FileNotFoundError(f"Game root not found at {game_root}")

        # Hard links and junctions, never copies: the sandbox root has to sit on
        # the install's own volume, and a link failure says so.
        share = share_install(game_root, self.sandbox_dir)

        for required in ("SlayTheSpire2.exe", "SlayTheSpire2.pck"):
            if not (self.sandbox_dir / required).is_file():
                raise FileNotFoundError(f"Sandbox preparation did not produce {required}: {self.sandbox_dir}")

        # The game loads one assembly per mod manifest. Protocol is therefore a small internal
        # dependency mod rather than a loose DLL beside the bridge, and the manifest dependency
        # makes the game load its types before scanning the bridge assembly.
        packages = (
            ("Sts2.NativeSim.Protocol", protocol_package_dir(), "Sts2.NativeSim.Protocol.dll"),
            ("sts2-full-app-bridge", bridge_package_dir(), "sts2-full-app-bridge.dll"),
        )
        for mod_id, mod_package, assembly_name in packages:
            dll_src = mod_package / assembly_name
            if not dll_src.exists():
                raise FileNotFoundError(f"Mod DLL not found at {dll_src}. Build the solution first.")
            mod_dir = self.sandbox_dir / "mods" / mod_id
            mod_dir.mkdir(parents=True, exist_ok=True)
            for pkg_file in mod_package.glob("*"):
                if pkg_file.is_file():
                    dest_file = mod_dir / pkg_file.name
                    try:
                        shutil.copy2(pkg_file, dest_file)
                    except Exception:
                        if not dest_file.exists():
                            raise

        # Set up isolated userdata. Progress is deliberately preserved: the bridge provisions a
        # missing baseline through shipped-game APIs and validates an existing one fail-closed.
        userdata_dir = self.sandbox_dir / "userdata"
        saves_dir = userdata_dir / "SlayTheSpire2" / "default" / "1" / "modded" / "profile1" / "saves"
        if saves_dir.exists():
            # A full-app entry always starts a new run. Active run saves are run-scoped state, not
            # part of the persistent progression baseline, and would send AutoSlay through its
            # abandon/continue UI on the next process launch.
            for run_save_name in ("current_run.save", "current_run_mp.save"):
                for run_save in saves_dir.glob(f"{run_save_name}*"):
                    run_save.unlink()
        settings_dir = userdata_dir / "SlayTheSpire2" / "default" / "1"
        settings_dir.mkdir(parents=True, exist_ok=True)

        real_appdata = os.environ.get("APPDATA", "")
        source_settings = Path(real_appdata) / "SlayTheSpire2" / "default" / "1" / "settings.save"
        settings_data = {}
        if source_settings.exists():
            try:
                with open(source_settings, "r", encoding="utf-8") as f:
                    settings_data = json.load(f)
            except Exception:
                pass

        settings_data["mod_settings"] = {"mods_enabled": True, "mod_list": []}
        settings_data["fullscreen"] = False
        settings_data["skip_intro_logo"] = True
        settings_data["volume_master"] = 0
        settings_data["volume_bgm"] = 0
        settings_data["volume_sfx"] = 0
        settings_data["volume_ambience"] = 0

        with open(settings_dir / "settings.save", "w", encoding="utf-8") as f:
            json.dump(settings_data, f, indent=2)

        self.sandbox_layout = SandboxLayout(
            game_root=game_root,
            sandbox_root=self.sandbox_root,
            worker_dir=self.sandbox_dir,
            share=share,
        )
        return self.sandbox_layout

    def launch(self, requested_character: str = "IRONCLAD") -> None:
        if self._owned_process is not None:
            raise RuntimeError("Full-app worker is already running")
        launched_at = time.monotonic()
        try:
            self.prepare_sandbox(requested_character=requested_character)
        finally:
            self.launch_timings = {"sandbox_seconds": time.monotonic() - launched_at}

        port_file = self.sandbox_dir / "userdata" / "bridge_port.txt"
        if port_file.exists():
            port_file.unlink()

        exe_path = self.sandbox_dir / "SlayTheSpire2.exe"
        log_path = self.sandbox_dir / "full_app.log"

        env = os.environ.copy()
        env["APPDATA"] = str(self.sandbox_dir / "userdata")
        env["LOCALAPPDATA"] = str(self.sandbox_dir / "local_userdata")
        env["STS2_FULL_APP_BRIDGE_PORT"] = str(self.config.port)
        env["STS2_FULL_APP_BRIDGE_PORT_FILE"] = str(port_file)
        env["STS2_FULL_APP_BRIDGE_PROCESS_MODE"] = self.config.process_mode
        env["STS2_FORCE_CHARACTER"] = requested_character

        args = [
            str(exe_path),
            "--headless",
            "--force-steam=off",
            f"--log-file={log_path}",
        ]

        try:
            self._owned_process = OwnedProcessTree.spawn(
                args,
                cwd=str(self.sandbox_dir),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.processes_started += 1
            self.process = self._owned_process.process
            self._complete_launch(port_file)
            self.launch_timings["process_ready_seconds"] = time.monotonic() - launched_at - self.launch_timings["sandbox_seconds"]
        except BaseException:
            self.launch_timings["process_ready_seconds"] = time.monotonic() - launched_at - self.launch_timings["sandbox_seconds"]
            self._cleanup(send_close=False)
            raise

    def _complete_launch(self, port_file: Path) -> None:
        process = self.process
        assert process is not None

        # Wait for port file to appear and bind
        start_time = time.time()
        bound_port = 0
        while time.time() - start_time < 30.0:
            if port_file.exists():
                try:
                    text = port_file.read_text(encoding="utf-8").strip()
                    if text:
                        bound_port = int(text)
                        break
                except Exception:
                    pass
            if process.poll() is not None:
                raise RuntimeError(f"Process terminated prematurely with code {process.returncode}")
            time.sleep(0.05)

        if bound_port == 0:
            raise TimeoutError(f"Worker {self.config.worker_id} timed out waiting for bridge port initialization")

        self.bound_port = bound_port

        # Connect TCP socket
        connected = False
        start_connect = time.time()
        while time.time() - start_connect < 15.0:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(self.config.timeout_seconds)
                self.sock.connect(("127.0.0.1", self.bound_port))
                self.file_reader = self.sock.makefile("r", encoding="utf-8-sig")
                self.file_writer = self.sock.makefile("w", encoding="utf-8")
                connected = True
                break
            except Exception:
                if self.sock is not None:
                    self.sock.close()
                    self.sock = None
                time.sleep(0.05)

        if not connected:
            raise ConnectionError(f"Failed to connect to bridge socket on port {self.bound_port}")

        readiness_started = time.time()
        while time.time() - readiness_started < self.config.timeout_seconds:
            hello = self.hello()
            if hello.get("process_mode") != self.config.process_mode:
                raise RuntimeError(
                    f"Full-app process mode mismatch: requested {self.config.process_mode}, "
                    f"worker reported {hello.get('process_mode')!r}"
                )
            status = hello.get("status")
            if status == "ready":
                self.ready_hello = hello
                return
            if status == "failed":
                raise RuntimeError(f"Full-app progression baseline failed: {hello.get('error', 'unknown failure')}")
            time.sleep(0.05)
        raise TimeoutError(f"Worker {self.config.worker_id} timed out waiting for progression baseline readiness")

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if self.sock is None or self.file_writer is None or self.file_reader is None:
            raise RuntimeError("Client is not connected")

        self.request_id += 1
        payload = {
            "id": self.request_id,
            "method": method,
            "params": params or {},
        }

        msg = json.dumps(payload) + "\n"
        self.file_writer.write(msg)
        self.file_writer.flush()

        response_line = self.file_reader.readline()
        if not response_line:
            raise EOFError("Remote socket closed connection")

        response = json.loads(response_line)
        if response.get("error"):
            raise RuntimeError(f"Bridge RPC error on {method}: {response['error']}")

        return response.get("result")

    def hello(self) -> Dict[str, Any]:
        return self.call("hello")

    def start_run(self, seed: str = "A1B2C3D4E5", character: str = "IRONCLAD", ascension: int = 0) -> Dict[str, Any]:
        return self.call("start_run", {
            "seed": seed, "character": character, "ascension": ascension,
            "process_mode": self.config.process_mode,
        })

    def end_run(self) -> Dict[str, Any]:
        return self.call("end_run")

    def observe(self) -> Dict[str, Any]:
        return self.call("observe")

    def legal_actions(self) -> List[Dict[str, Any]]:
        return self.call("legal_actions")

    def step(self, action_id: str) -> Dict[str, Any]:
        return self.call("step", {"action_id": action_id})

    def history(self) -> Dict[str, Any]:
        return self.call("history")

    def close(self) -> None:
        started = time.monotonic()
        try:
            self._cleanup(send_close=True)
        finally:
            self.last_close_seconds = time.monotonic() - started

    def _cleanup(self, *, send_close: bool) -> None:
        try:
            if send_close and self.sock is not None:
                self.sock.settimeout(min(self.config.timeout_seconds, 0.5))
                self.call("close")
        except Exception:
            pass

        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        try:
            if self.file_writer is not None:
                self.file_writer.close()
        except Exception:
            pass

        try:
            if self.file_reader is not None:
                self.file_reader.close()
        except Exception:
            pass

        try:
            if self.sock is not None:
                self.sock.close()
        except Exception:
            pass

        self.sock = None
        self.file_reader = None
        self.file_writer = None

        if self._owned_process is not None:
            try:
                self._owned_process.close()
            finally:
                self._owned_process = None
                self.process = None
        self.bound_port = 0
