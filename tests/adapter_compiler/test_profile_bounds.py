from __future__ import annotations

import pytest

from reflow.adapter_compiler.profile import (
    MAX_PROFILE_COLUMN_NAME_CHARS,
    MAX_PROFILE_COLUMNS,
    MAX_PROFILE_SAMPLE_ROWS,
    profile_rows,
)


def test_profile_rows_enforces_model_facing_sample_bound() -> None:
    rows = tuple({"amount": index} for index in range(MAX_PROFILE_SAMPLE_ROWS + 1))
    assert len(profile_rows(rows, sample_limit=MAX_PROFILE_SAMPLE_ROWS).sample_rows) == (
        MAX_PROFILE_SAMPLE_ROWS
    )
    with pytest.raises(ValueError, match="sample limit"):
        profile_rows(rows, sample_limit=MAX_PROFILE_SAMPLE_ROWS + 1)
    with pytest.raises(TypeError, match="sample limit"):
        profile_rows(rows, sample_limit=True)


def test_profile_rows_rejects_unbounded_schema_width() -> None:
    row = {f"column_{index}": index for index in range(MAX_PROFILE_COLUMNS + 1)}
    with pytest.raises(ValueError, match="columns"):
        profile_rows((row,))


def test_profile_rows_rejects_unbounded_column_name() -> None:
    row = {"x" * (MAX_PROFILE_COLUMN_NAME_CHARS + 1): 1}
    with pytest.raises(ValueError, match="column name"):
        profile_rows((row,))
