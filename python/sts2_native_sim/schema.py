"""The published canonical-state schema, and checking an observation against it.

`schemas/canonical-state.schema.json` is the published shape of a canonical observation —
the object a native capture puts under `observation`, and the object the Python seam
projects from. It is the only description of that shape that lives outside the C#
capture sites, so it is worth *validating* an observation against it rather than merely
parsing the file: a capture that no longer matches, or a schema that no longer describes
what the environment emits, is then a failure instead of a document nobody reads.

The schema is hand-written and is expected to move with the environment: the observation
schema version it pins and `ProtocolConstants.ObservationSchemaVersion` are the same
number, and `tests/test_observation_schema.py` validates recorded captures against it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import jsonschema  # type: ignore[import-untyped]  # jsonschema ships no type information

from .paths import REPOSITORY_ROOT

CANONICAL_STATE_SCHEMA_PATH = REPOSITORY_ROOT / "schemas" / "canonical-state.schema.json"


class ObservationSchemaViolation(ValueError):
    """A canonical observation does not match the published canonical-state schema."""


@lru_cache(maxsize=1)
def canonical_state_schema() -> dict[str, Any]:
    """The published canonical-state schema, parsed once per process."""
    return json.loads(CANONICAL_STATE_SCHEMA_PATH.read_text(encoding="utf-8"))


def observation_schema_version() -> int:
    """The observation schema version the published schema pins."""
    return int(canonical_state_schema()["properties"]["schema_version"]["const"])


def validate_observation(observation: Any) -> None:
    """Validate one canonical observation against the published schema.

    Raises :class:`ObservationSchemaViolation` naming the JSON path that differed, because a
    schema failure is only useful when it says which field drifted. The dialect is the one
    the schema declares — JSON Schema draft 2020-12.
    """
    validator = jsonschema.Draft202012Validator(canonical_state_schema())
    error = jsonschema.exceptions.best_match(validator.iter_errors(observation))
    if error is None:
        return
    path = "$" + "".join(
        f"[{step}]" if isinstance(step, int) else f".{step}" for step in error.absolute_path
    )
    raise ObservationSchemaViolation(f"{path}: {error.message}")
