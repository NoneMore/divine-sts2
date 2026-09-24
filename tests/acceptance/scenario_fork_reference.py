"""Test-only native reference for the scenario generator's former fork RPC.

The old driver called ``fork()`` after entering and reading the Ancient offer, then
restored the returned handle for later choices. Reading the offer has no native side
effects, so this adapter makes that former RPC immediately after the entry step and
substitutes its handle in the step result. All other calls reach the real worker.
"""

from __future__ import annotations

from typing import Any

from sts2_native_sim.client import NativeWorker


class ForkAfterAncientWorker:
    def __init__(self, worker: NativeWorker) -> None:
        self._worker = worker
        self.build = worker.build

    def run_reset(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._worker.run_reset(state)

    def run_step(self, action_id: str) -> dict[str, Any]:
        result = self._worker.run_step(action_id)
        observation = result["observation"]
        if (observation["decision"]["kind"] == "event_choice"
                and (observation.get("event") or {}).get("model_id") == "NEOW"):
            result = {**result, "state_handle": self._worker.fork()}
        return result

    def restore(self, state_handle: str) -> dict[str, Any]:
        return self._worker.restore(state_handle)

    def alive(self) -> bool:
        return self._worker.alive()

    def close(self) -> None:
        self._worker.close()
