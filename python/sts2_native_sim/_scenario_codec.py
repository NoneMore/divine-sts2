"""Internal encoding and row-summary rules for generated scenarios."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from ._scenario_model import (
    ANCIENT_CHOICE_KEY_ORDER,
    ERROR_KEY_ORDER,
    ERROR_RUN,
    FAILURE_RECORD,
    NESTED_CHOICE_KEY_ORDER,
    NODE_KEY_ORDER,
    RECIPE_KEY_ORDER,
    REWARD_CHOICE_KEY_ORDER,
    ROW_ESCAPE_NON_ASCII,
    ROW_KEY_ORDER,
    ROW_SEPARATORS,
    ROW_TYPES,
    SCENARIO_RECORD,
    STAGE_RECORD,
    RowFormatError,
    ScenarioGenerationError,
)
from .client import NativeSimError


def error_kind(error: BaseException) -> str:
    """The stable token a failure row names for one error.

    The kind is what a corpus can be counted by, so it is the error's own identity rather than
    its text: a run that did not reach its fight is :data:`ERROR_RUN` (the stage says where it
    stopped), a worker error contributes the worker's own code — ``worker_crashed``,
    ``protocol_desync`` — and anything else contributes its class name, ``key_error``. A message
    can name a path or a count that moves between builds; a kind cannot, which is what makes "the
    same element fails again with the same kind" a checkable claim about a re-run.
    """
    if isinstance(error, ScenarioGenerationError):
        return ERROR_RUN
    if isinstance(error, NativeSimError):
        return error.code
    return re.sub(r"(?<!^)(?=[A-Z])", "_", type(error).__name__).lower()


def summarize_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Count a batch's rows by type, so a corpus that lost elements says so.

    The counts are what makes a biased corpus visible: every row type this module declares is
    reported even at zero, so "nothing failed" is a stated fact rather than an absent key. A row
    of a type this summary does not know is refused instead of being counted as neither a success
    nor a failure, which would make the two counts stop adding up to the rows.
    """
    return _tally(_counts(rows))


def encode_row(row: dict[str, Any]) -> str:
    """One row as a corpus stores it: JSON on one line, in the declared key order.

    The bytes are the record's own: the row's structure is written in the order
    :data:`ROW_KEY_ORDER` and its siblings declare rather than in the order the dictionary happens
    to hold — so a row built by another call site, or by another version of one, is still the same
    line — and the encoding and separators are pinned rather than left to an encoder default.

    The two values the *worker* owns, the combat observation and the game build, are written as the
    capture reported them: their shape is the published canonical-state schema's, which is not a
    serialisation order, and their order is as fixed as their values are, because the byte guarantee
    is scoped to one game build.
    """
    return json.dumps(_row_in_declared_order(row), ensure_ascii=ROW_ESCAPE_NON_ASCII, separators=ROW_SEPARATORS) + "\n"


def _in_declared_order(record: dict[str, Any], order: Sequence[str], path: str) -> dict[str, Any]:
    """One document in its declared key order, refusing a key the declaration does not name.

    This is the one place the record's key order is applied: everything below it says which
    declaration governs which of the record's own documents, so a row's bytes follow from the
    declarations and from nothing about how the row was assembled.
    """
    undeclared = [key for key in record if key not in order]
    if undeclared:
        raise RowFormatError(f"{path} carries keys {sorted(undeclared)}, which {order} does not declare")
    return {key: record[key] for key in order if key in record}


def _row_in_declared_order(row: dict[str, Any]) -> dict[str, Any]:
    """One row's own keys, in the order the record format declares them, and nothing else.

    The row's *structure* is ordered here and its *values* are not touched, so what a capture
    reported is what a reader gets and only the record's own keys are this module's to place.
    """
    order = ROW_KEY_ORDER.get(row.get("record_type", ""))
    if order is None:
        raise RowFormatError(f"a row of type {row.get('record_type')!r} is not one this format declares")
    declared = _in_declared_order(row, order, "$")
    declared["recipe"] = _recipe_in_declared_order(row["recipe"])
    if "error" in row:
        declared["error"] = _in_declared_order(row["error"], ERROR_KEY_ORDER, "$.error")
    return declared


def _recipe_in_declared_order(recipe: dict[str, Any]) -> dict[str, Any]:
    """One row's recipe in declared order, with the nested records it carries in theirs."""
    declared = _in_declared_order(recipe, RECIPE_KEY_ORDER, "$.recipe")
    if "ancient_options" in recipe:
        declared["ancient_options"] = [
            _in_declared_order(option, ANCIENT_CHOICE_KEY_ORDER, f"$.recipe.ancient_options[{index}]")
            for index, option in enumerate(recipe["ancient_options"])
        ]
    if "ancient_choice" in recipe:
        declared["ancient_choice"] = _in_declared_order(
            recipe["ancient_choice"], ANCIENT_CHOICE_KEY_ORDER, "$.recipe.ancient_choice"
        )
    if "nested_choices" in recipe:
        declared["nested_choices"] = [
            _nested_choice_in_declared_order(nested, f"$.recipe.nested_choices[{index}]")
            for index, nested in enumerate(recipe["nested_choices"])
        ]
    if "node" in recipe:
        declared["node"] = _in_declared_order(recipe["node"], NODE_KEY_ORDER, "$.recipe.node")
    return declared


def _nested_choice_in_declared_order(nested: dict[str, Any], path: str) -> dict[str, Any]:
    """One nested choice in declared order, with the identity a reward pick carries in its own.

    A nested choice is a record of a record: its own fields are declared, and the reward identity
    inside it is declared too, because a record assembled in another order must still be the same
    bytes. The identity is optional — a prompt that selects option ids, and a skip, carry none.
    """
    declared = _in_declared_order(nested, NESTED_CHOICE_KEY_ORDER, path)
    if "selected_reward" in nested:
        declared["selected_reward"] = _in_declared_order(
            nested["selected_reward"], REWARD_CHOICE_KEY_ORDER, f"{path}.selected_reward"
        )
    return declared


def _refuse_floats(value: Any, path: str = "$") -> None:
    """Refuse a record that carries a floating-point quantity, naming where it is.

    Every quantity a record carries is an integer or a string, so that a corpus cannot drift with a
    float's formatting: `1.0` and `1` are one number and two byte strings, and which of them a build
    prints is not something a diff can tell from a real change. The published schema cannot catch
    one — `1.0` *is* an integer to JSON Schema's `integer` type — so the record refuses it itself,
    and a capture that reports a fractional quantity is an element that could not be recorded rather
    than a corpus written twice differently.
    """
    if isinstance(value, float):
        raise ScenarioGenerationError(STAGE_RECORD, f"{path} is {value!r}, a floating-point quantity")
    if isinstance(value, dict):
        for key, child in value.items():
            _refuse_floats(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _refuse_floats(child, f"{path}[{index}]")


def _counts(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    """How many rows of each declared type `rows` holds, refusing a type nothing declares."""
    counts = _empty_counts()
    for row in rows:
        _add(counts, row["record_type"])
    return counts


def _tally(counts: dict[str, int]) -> dict[str, Any]:
    """The counts a batch reports: by row type, then the two totals that follow from them."""
    return {
        "rows": dict(counts),
        "succeeded": counts[SCENARIO_RECORD],
        "failed": counts[FAILURE_RECORD],
        "total": sum(counts.values()),
    }


def _empty_counts() -> dict[str, int]:
    return {record_type: 0 for record_type in ROW_TYPES}


def _add(counts: dict[str, int], record_type: str) -> None:
    if record_type not in counts:
        raise ValueError(f"unknown row type {record_type!r}")
    counts[record_type] += 1
