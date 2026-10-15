"""Frontmatter models, one per note type.

These models know nothing about config or the filesystem: they check shape,
types and status enums only. Context-dependent checks (ID format against
configured prefixes, id == filename, author membership, links) live in the
lint rules. Unknown fields are allowed and preserved so projects can extend
schemas without forking the engine.
"""

from __future__ import annotations

import typing
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from labbrain.layout import NOTE_TYPES

FUTURE_AGENTS_HEADING = "For future agents"

# Frontmatter fields whose values are note IDs (scalars or lists).
ID_FIELDS: tuple[str, ...] = (
    "links",
    "evidence",
    "sources",
    "protocol",
    "dataset",
    "supersedes",
    "superseded_by",
    "consolidated_into",
    "split_of",
    "changes_from",
    "comparable_with",
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _null_lists_are_empty(cls, data: Any) -> Any:
        """Treat `key:` (YAML null) as an empty list for list-typed fields."""
        if isinstance(data, dict):
            for name, field in cls.model_fields.items():
                if data.get(name, ...) is None and typing.get_origin(field.annotation) is list:
                    data = {**data, name: []}
        return data


class Tracker(_Model):
    backend: str | None = None
    run_ids: list[str] = []
    url: str | None = None


class Code(_Model):
    repo: str | None = None
    # pydantic compiles patterns with the Rust regex engine: `\Z` is not supported there,
    # and `$` (no multiline flag) matches only at the very end, rejecting a trailing "\n".
    sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")
    dirty: bool | None = None

    @field_validator("sha", mode="before")
    @classmethod
    def _sha_as_text(cls, value: Any) -> Any:
        return str(value) if isinstance(value, int) and not isinstance(value, bool) else value


class Metric(_Model):
    name: str
    value: float
    split: str | None = None
    run_id: str | None = None
    as_of: date | None = None


class BaseNote(_Model):
    id: str
    type: str
    title: str
    created: date
    updated: date
    author: str
    status: str
    tags: list[str] = []
    links: list[str] = []


def _require_when(note: BaseNote, status: str, field: str) -> None:
    if note.status == status and not getattr(note, field, None):
        raise ValueError(f"{field} is required when status is {status}")


class ExperimentNote(BaseNote):
    type: Literal["experiment"]
    status: Literal["planned", "running", "done", "failed", "superseded"]
    hypothesis: str | None = None
    protocol: str | None = None
    tracker: Tracker | None = None
    code: Code | None = None
    config_hash: str | None = None
    dataset: str | None = None
    metrics: list[Metric] = []
    supersedes: str | None = None
    superseded_by: str | None = None

    @model_validator(mode="after")
    def _conditionals(self) -> ExperimentNote:
        _require_when(self, "done", "dataset")
        _require_when(self, "superseded", "superseded_by")
        return self


class ProtocolNote(BaseNote):
    type: Literal["protocol"]
    status: Literal["draft", "frozen", "retired"]
    version: int = Field(ge=1)
    changes_from: str | None = None
    comparable_with: list[str] = []


class ClaimNote(BaseNote):
    type: Literal["claim"]
    status: Literal["draft", "supported", "stale", "retracted"]
    statement: str | None = None
    value: float | list[float] | None = None
    value_format: str | None = None
    tolerance: float | None = Field(default=None, ge=0)
    evidence: list[str] = []
    protocol: str | None = None
    manuscript_locations: list[str] = []


class IdeaNote(BaseNote):
    type: Literal["idea"]
    status: Literal["open", "consolidated", "dropped"]
    consolidated_into: str | None = None

    @model_validator(mode="after")
    def _conditionals(self) -> IdeaNote:
        _require_when(self, "consolidated", "consolidated_into")
        return self


class ConceptNote(BaseNote):
    type: Literal["concept"]
    status: Literal["active", "stale"]
    sources: list[str]


class DecisionNote(BaseNote):
    type: Literal["decision"]
    status: Literal["proposed", "accepted", "superseded"]
    supersedes: str | None = None
    superseded_by: str | None = None

    @model_validator(mode="after")
    def _conditionals(self) -> DecisionNote:
        _require_when(self, "superseded", "superseded_by")
        return self


class LiteratureNote(BaseNote):
    type: Literal["literature"]
    status: Literal["active", "stale"]
    doi: str | None = None
    arxiv: str | None = None
    url: str | None = None
    year: int | None = Field(default=None, ge=1000, le=9999)
    venue: str | None = None
    relevance: Literal["high", "medium", "low"] | None = None


class HandoffNote(BaseNote):
    type: Literal["handoff"]
    status: Literal["final"]
    agent: str | None = None
    session_goal: str | None = None
    files_touched: list[str] = []


class DatasetNote(BaseNote):
    type: Literal["dataset"]
    status: Literal["active", "superseded"]
    location: str | None = None
    extracted: date | None = None
    split_of: str | None = None
    counts: dict[str, Any] | None = None
    protected: bool | None = None
    supersedes: str | None = None
    superseded_by: str | None = None

    @model_validator(mode="after")
    def _conditionals(self) -> DatasetNote:
        _require_when(self, "superseded", "superseded_by")
        return self


MODELS: dict[str, type[BaseNote]] = {
    "experiment": ExperimentNote,
    "protocol": ProtocolNote,
    "claim": ClaimNote,
    "idea": IdeaNote,
    "concept": ConceptNote,
    "decision": DecisionNote,
    "literature": LiteratureNote,
    "handoff": HandoffNote,
    "dataset": DatasetNote,
}

AnyNote = Annotated[
    Union[  # noqa: UP007 - discriminated unions read better spelled out
        ExperimentNote,
        ProtocolNote,
        ClaimNote,
        IdeaNote,
        ConceptNote,
        DecisionNote,
        LiteratureNote,
        HandoffNote,
        DatasetNote,
    ],
    Field(discriminator="type"),
]

REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "experiment": ("Hypothesis", "Setup", "Results", "Interpretation", "Next"),
    "protocol": ("Definition", "Changes from previous version", "Known caveats"),
    "claim": ("Evidence summary", "History"),
    "idea": (),
    "concept": ("Summary", "Evidence", "Open questions", "Related"),
    "decision": ("Context", "Decision", "Alternatives considered", "Consequences"),
    "literature": (
        "Summary",
        "Methods worth borrowing",
        "Results to compare against",
        "Style notes",
    ),
    "handoff": ("Done", "In progress", "Blockers", "Next step for whoever picks this up"),
    "dataset": ("Source", "Inclusion and exclusion", "Split definition", "Known issues"),
}

DEFAULT_STATUS: dict[str, str] = {
    "experiment": "planned",
    "protocol": "draft",
    "claim": "draft",
    "idea": "open",
    "concept": "active",
    "decision": "proposed",
    "literature": "active",
    "handoff": "final",
    "dataset": "active",
}

assert set(MODELS) == set(NOTE_TYPES)


def _format_error(error: Any) -> str:
    loc = ".".join(str(part) for part in error["loc"]) or "frontmatter"
    return f"{loc}: {error['msg'].removeprefix('Value error, ')}"


def validate_frontmatter(data: dict[str, Any]) -> tuple[BaseNote | None, list[str]]:
    """Validate a frontmatter dict. Error messages never contain input values."""
    note_type = data.get("type")
    model = MODELS.get(note_type) if isinstance(note_type, str) else None
    if model is None:
        return None, [f"type: must be one of {', '.join(NOTE_TYPES)}"]
    try:
        return model.model_validate(data), []
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        return None, [_format_error(e) for e in errors]


def json_schema(note_type: str | None = None) -> dict[str, Any]:
    if note_type is None:
        return TypeAdapter(AnyNote).json_schema()
    return MODELS[note_type].model_json_schema()
