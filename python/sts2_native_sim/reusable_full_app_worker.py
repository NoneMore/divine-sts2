"""One serial lane for explicit full-app run lifecycles."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Self, TypeVar

from .full_app_client import FullAppBridgeClient, FullAppClientConfig

T = TypeVar("T")


@dataclass(frozen=True)
class RunEntry:
    seed: str
    character: str = "IRONCLAD"
    ascension: int = 0


@dataclass(frozen=True)
class WorkerEntryResult(Generic[T]):
    succeeded: bool
    value: T | None
    error: str | None
    pid: int | None
    process_entry_ordinal: int | None
    start_path: str | None
    process_mode: str
    startup_seconds: float
    entry_seconds: float
    teardown_seconds: float
    replacement_count: int
    pck_fingerprint_bytes: int
    pck_fingerprint_count: int
    teardown: dict[str, Any] | None


class ReusableFullAppWorker:
    """Execute entries sequentially, discarding a process after any uncertain lifecycle result.

    A failed entry is returned once. Only a subsequent call may launch a replacement in the
    same sandbox. The driver receives the active client and the bridge's start response;
    it must finish at a stable decision boundary so the worker can call ``end_run``.
    """

    def __init__(self, config: FullAppClientConfig, *, max_entries: int = 16,
                 capture_profile: bool = False) -> None:
        if config.process_mode != "reuse":
            raise ValueError("Reusable worker requires reuse process mode")
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.config = config
        self.max_entries = max_entries
        self.capture_profile = capture_profile
        self.profile_at_readiness: dict[str, str] | None = None
        self.game_build: dict[str, Any] | None = None
        self.lifecycle_protocol_revision: str | None = None
        self.progression_policy_revision: str | None = None
        self._client: FullAppBridgeClient | None = None
        self._ordinal = 0
        self._last_generation = 0
        self._launches = 0
        self._profile_fingerprint: str | None = None
        self.profile_baseline: str | None = None
        self._lock = threading.Lock()
        self._closed = False

    def run_entry(
        self,
        entry: RunEntry,
        drive: Callable[[FullAppBridgeClient, dict[str, Any]], T],
        *, after_teardown: Callable[[FullAppBridgeClient], None] | None = None,
    ) -> WorkerEntryResult[T]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Reusable worker is closed")
            startup_seconds = 0.0
            entry_seconds = 0.0
            teardown_seconds = 0.0
            pck_bytes = 0
            pck_count = 0
            pid: int | None = None
            ordinal: int | None = None
            start_path: str | None = None
            teardown: dict[str, Any] | None = None
            value: T | None = None
            launched_at: float | None = None
            active_client: FullAppBridgeClient | None = None

            def result(succeeded: bool, value: T | None, error: str | None) -> WorkerEntryResult[T]:
                return WorkerEntryResult(
                    succeeded=succeeded,
                    value=value,
                    error=error,
                    pid=pid,
                    process_entry_ordinal=ordinal,
                    start_path=start_path,
                    process_mode="reuse",
                    startup_seconds=startup_seconds,
                    entry_seconds=entry_seconds,
                    teardown_seconds=teardown_seconds,
                    replacement_count=max(0, self._launches - 1),
                    pck_fingerprint_bytes=pck_bytes,
                    pck_fingerprint_count=pck_count,
                    teardown=teardown,
                )

            try:
                if self._client is not None and (
                    self._client.process is None or self._client.process.poll() is not None
                ):
                    self._discard()
                if self._client is None:
                    launched_at = time.monotonic()
                    self._launches += 1
                    active_client = FullAppBridgeClient(self.config)
                    self._client = active_client
                    active_client.launch(requested_character=entry.character)
                    if self._closed:
                        raise RuntimeError("Reusable worker closed during launch")
                    hello = active_client.hello()
                    if hello.get("status") != "ready" or hello.get("process_mode") != "reuse":
                        raise RuntimeError(f"Illegal worker handshake: {hello!r}")
                    build = hello.get("game_build")
                    if (
                        not isinstance(build, dict)
                        or not isinstance(build.get("pck_sha256"), str)
                        or not build["pck_sha256"]
                    ):
                        raise RuntimeError("Worker did not report a build fingerprint")
                    fingerprint = hello.get("profile_fingerprint")
                    if not isinstance(fingerprint, str) or not fingerprint:
                        raise RuntimeError("Worker did not report a profile fingerprint")
                    if self._profile_fingerprint is not None and fingerprint != self._profile_fingerprint:
                        raise RuntimeError("Replacement sandbox profile fingerprint changed")
                    self._profile_fingerprint = fingerprint
                    self.profile_baseline = fingerprint
                    self.game_build = build
                    self.lifecycle_protocol_revision = hello.get("lifecycle_protocol_revision")
                    self.progression_policy_revision = hello.get("progression_policy")
                    if self.capture_profile:
                        self.profile_at_readiness = active_client.call("profile_snapshot")
                    pid = hello.get("pid")
                    if not isinstance(pid, int) or active_client.process is None or pid != active_client.process.pid:
                        raise RuntimeError(
                            f"Worker reported an unexpected PID: {pid!r}, owned {getattr(active_client.process, 'pid', None)!r}"
                        )
                    pck_bytes = (Path(self.config.game_root) / "SlayTheSpire2.pck").stat().st_size
                    pck_count = 1
                    startup_seconds = time.monotonic() - launched_at
                else:
                    active_client = self._client
                    pid = active_client.process.pid if active_client.process is not None else None
                client = active_client
                if self._closed:
                    raise RuntimeError("Reusable worker closed during entry")
                if client.process is None or client.process.poll() is not None:
                    raise RuntimeError("Full-app process exited before entry")
                ordinal = self._ordinal + 1
                expected_path = "menu" if ordinal == 1 else "direct"
                entered_at = time.monotonic()
                try:
                    started = client.start_run(entry.seed, entry.character, entry.ascension)
                    if (
                        not isinstance(started, dict)
                        or started.get("started") is not True
                        or started.get("process_mode") != "reuse"
                        or started.get("pid") != pid
                        or started.get("process_entry_ordinal") != ordinal
                        or started.get("start_path") != expected_path
                    ):
                        raise RuntimeError(f"Illegal start_run response: {started!r}")
                    start_path = expected_path
                    self._ordinal = ordinal
                    value = drive(client, started)
                finally:
                    entry_seconds = time.monotonic() - entered_at
                ended_at = time.monotonic()
                try:
                    teardown = client.end_run()
                    if not self._valid_teardown(teardown):
                        raise RuntimeError(f"Illegal end_run response: {teardown!r}")
                    self._last_generation = teardown["ended_generation"]
                finally:
                    teardown_seconds = time.monotonic() - ended_at
                if self._closed:
                    raise RuntimeError("Reusable worker closed during entry")
                if after_teardown is not None:
                    after_teardown(client)
                completed = result(True, value, None)
                if self._ordinal >= self.max_entries:
                    self._discard()
                return completed
            except Exception as exc:  # noqa: BLE001 - any driver or lifecycle exception poisons this process
                if launched_at is not None and startup_seconds == 0:
                    startup_seconds = time.monotonic() - launched_at
                if active_client is not None and self._client is not active_client:
                    active_client.close()
                self._discard()
                return result(False, None, f"{type(exc).__name__}: {exc}")

    def _discard(self) -> None:
        client, self._client = self._client, None
        self._ordinal = 0
        self._last_generation = 0
        if client is not None:
            client.close()

    def _valid_teardown(self, teardown: Any) -> bool:
        if not isinstance(teardown, dict):
            return False
        history = teardown.get("reset_history_counts")
        return (
            teardown.get("final_state") == "idle"
            and type(teardown.get("ended_generation")) is int
            and teardown["ended_generation"] > self._last_generation
            and isinstance(teardown.get("ending_phase"), str)
            and bool(teardown["ending_phase"])
            and teardown.get("parked_wait_released") is True
            and type(teardown.get("stale_continuation_refusals")) is int
            and teardown["stale_continuation_refusals"] >= 0
            and teardown.get("driver_result") in ("abandoned", "cancelled")
            and isinstance(history, dict)
            and all(type(history.get(key)) is int and history[key] >= 0 for key in ("actions", "state_hashes"))
            and type(teardown.get("duration_ms")) is int
            and teardown["duration_ms"] >= 0
        )

    def close(self) -> None:
        self._closed = True
        self._discard()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
