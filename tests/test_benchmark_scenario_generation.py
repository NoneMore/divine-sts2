"""The benchmark CLI reports complete reference requests from fresh corpora."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_reference_benchmark_reports_both_scales(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "python"))
    from tools import benchmark_scenario_generation as benchmark

    monkeypatch.setattr(benchmark, "OUT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["benchmark_scenario_generation.py", "reference-check"])
    ticks = iter(range(0, 9 * 10, 10))
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(ticks))
    calls: list[tuple[Any, int, Path, int]] = []

    def corpus(request: Any, workers: int, output_dir: Path, *, compression: int) -> dict[str, int]:
        calls.append((request, workers, output_dir, compression))
        elements = len(request.characters) * len(request.ascensions) * len(request.seeds)
        failed = 1 if elements == 512 else 0
        return {"elements": elements, "succeeded": 3 * elements - failed, "failed": failed,
                "worker_replacements": failed}

    monkeypatch.setattr(benchmark, "generate_corpus", corpus)
    benchmark.main()

    assert [(r.characters, r.ascensions, r.seeds, workers, compression) for r, workers, _, compression in calls] == [
        (("IRONCLAD",), (0,), ("A1B2C3D4E5", "1", "2", "3"), workers, 3) for workers in (1, 2, 4)
    ] + [(("IRONCLAD", "DEFECT"), (0, 2), tuple(str(n) for n in range(1, 129)), 8, 3)]
    assert all(not path.exists() for _, _, path, _ in calls)

    report = json.loads((tmp_path / "results-reference-check.json").read_text(encoding="utf-8"))
    measurements = report["corpora"]
    assert [item["reference"] for item in measurements] == ["A", "A", "A", "B"]
    assert [item["elements_per_second"] for item in measurements] == [0.4, 0.4, 0.4, 51.2]
    assert [item["rows_per_second"] for item in measurements] == [1.2, 1.2, 1.2, 153.6]
    assert [item["success_ratio"] for item in measurements] == [1.0, 1.0, 1.0, 1535 / 1536]
    assert [item["worker_replacements"] for item in measurements] == [0, 0, 0, 1]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["elements_per_second"] for line in lines[:4]] == [0.4, 0.4, 0.4, 51.2]


def test_reference_benchmark_refuses_an_existing_corpus_before_measuring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "python"))
    from tools import benchmark_scenario_generation as benchmark

    monkeypatch.setattr(benchmark, "OUT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["benchmark_scenario_generation.py", "existing"])
    existing = tmp_path / "corpus-reference-B-8-existing-r1"
    existing.mkdir()
    (existing / "summary.json").write_text("existing corpus", encoding="utf-8")
    calls: list[Any] = []
    monkeypatch.setattr(benchmark, "generate_corpus", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(FileExistsError, match="fresh run ID"):
        benchmark.main()

    assert calls == []
    assert (existing / "summary.json").read_text(encoding="utf-8") == "existing corpus"
    assert not (tmp_path / "results-existing.json").exists()
