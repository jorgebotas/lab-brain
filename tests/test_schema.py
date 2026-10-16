from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from labbrain.layout import NOTE_TYPES
from labbrain.schema import (
    DEFAULT_STATUS,
    MODELS,
    REQUIRED_SECTIONS,
    ExperimentNote,
    json_schema,
    validate_frontmatter,
)

MINIMAL: dict[str, dict[str, Any]] = {"protocol": {"version": 1}, "concept": {"sources": []}}


def common(note_type: str, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "x",
        "type": note_type,
        "title": "T",
        "created": date(2026, 10, 13),
        "updated": date(2026, 10, 13),
        "author": "alice",
        "status": DEFAULT_STATUS[note_type],
    }
    data.update(MINIMAL.get(note_type, {}))
    data.update(extra)
    return data


@pytest.mark.parametrize("note_type", NOTE_TYPES)
def test_minimal_note_of_each_type_validates(note_type: str) -> None:
    model, errors = validate_frontmatter(common(note_type))
    assert errors == []
    assert model is not None


def test_registries_cover_every_type() -> None:
    assert set(MODELS) == set(REQUIRED_SECTIONS) == set(DEFAULT_STATUS) == set(NOTE_TYPES)


def test_unknown_type() -> None:
    model, errors = validate_frontmatter({"type": "memo"})
    assert model is None
    assert errors == ["type: must be one of " + ", ".join(NOTE_TYPES)]


def test_bad_status_message_does_not_echo_input() -> None:
    _, errors = validate_frontmatter(common("experiment", status="archived-123456789"))
    assert len(errors) == 1
    assert errors[0].startswith("status: Input should be")
    assert "archived-123456789" not in errors[0]


def test_done_experiment_requires_dataset_but_not_protocol() -> None:
    _, errors = validate_frontmatter(common("experiment", status="done", protocol="EVAL-v1"))
    assert errors == ["frontmatter: dataset is required when status is done"]
    _, errors = validate_frontmatter(common("experiment", status="done", dataset="DS-1"))
    assert errors == []  # protocol-missing is a lint rule, not a model error


@pytest.mark.parametrize("note_type", ["experiment", "decision", "dataset"])
def test_superseded_requires_superseded_by(note_type: str) -> None:
    _, errors = validate_frontmatter(common(note_type, status="superseded"))
    assert errors == ["frontmatter: superseded_by is required when status is superseded"]
    _, errors = validate_frontmatter(common(note_type, status="superseded", superseded_by="X"))
    assert errors == []


def test_consolidated_idea_requires_target() -> None:
    _, errors = validate_frontmatter(common("idea", status="consolidated"))
    assert errors == ["frontmatter: consolidated_into is required when status is consolidated"]


def test_concept_sources_key_required_but_may_be_empty() -> None:
    data = common("concept")
    del data["sources"]
    assert validate_frontmatter(data)[1] == ["sources: Field required"]
    assert validate_frontmatter(common("concept", sources=None))[1] == []


def test_unknown_fields_preserved() -> None:
    model, _ = validate_frontmatter(common("idea", project_field="kept"))
    assert model is not None
    assert model.model_extra == {"project_field": "kept"}


def test_nested_models_and_coercions() -> None:
    model, errors = validate_frontmatter(
        common(
            "experiment",
            code={"sha": 1234567, "dirty": False},
            tracker={"backend": "local", "run_ids": ["r1"]},
            metrics=[{"name": "auroc", "value": 0.81, "run_id": "r1", "as_of": "2026-10-13"}],
        )
    )
    assert errors == []
    assert isinstance(model, ExperimentNote)
    assert model.code is not None and model.code.sha == "1234567"
    assert model.metrics[0].as_of == date(2026, 10, 13)


def test_field_constraints() -> None:
    _, errors = validate_frontmatter(common("experiment", code={"sha": "not-hex"}))
    assert len(errors) == 1 and errors[0].startswith("code.sha:")
    _, errors = validate_frontmatter(common("claim", tolerance=-1))
    assert len(errors) == 1 and errors[0].startswith("tolerance:")
    _, errors = validate_frontmatter(common("protocol", version=0))
    assert len(errors) == 1 and errors[0].startswith("version:")


def test_null_list_fields_become_empty() -> None:
    model, errors = validate_frontmatter(common("experiment", tags=None, links=None, metrics=None))
    assert errors == []
    assert isinstance(model, ExperimentNote)
    assert model.tags == [] and model.metrics == []


def test_json_schema_export() -> None:
    assert json_schema("experiment")["title"] == "ExperimentNote"
    assert "oneOf" in json_schema()


def test_dict_key_never_rendered_in_loc() -> None:
    _, errors = validate_frontmatter(common("dataset", counts={998877665: [1]}))
    assert errors == ["counts.<key>: Input should be a valid string"]
    assert all("998877665" not in error for error in errors)


def test_union_type_tags_dropped_from_loc() -> None:
    _, errors = validate_frontmatter(common("claim", value="not-a-number"))
    assert errors
    assert all(error.split(": ", 1)[0] == "value" for error in errors)


def test_list_indices_and_nested_fields_kept_in_loc() -> None:
    _, errors = validate_frontmatter(
        common("experiment", tags=[1], metrics=[{"name": "auroc", "value": "x"}])
    )
    assert [error.split(": ", 1)[0] for error in errors] == ["tags.0", "metrics.0.value"]
