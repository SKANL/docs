"""Versioned, renderer-neutral representation of a document template."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

TEMPLATE_IR_VERSION = "1.0"


def _deep_freeze(value: Any) -> Any:
    """Copy nested template data into immutable, deterministic containers."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    """Return a mutable serialization snapshot without exposing IR state."""
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted((_deep_thaw(item) for item in value), key=repr)
    return value


def _deep_copy_for_serialization(value: Any) -> Any:
    """Copy frozen containers while retaining declared tuple field types."""
    if isinstance(value, Mapping):
        return {key: _deep_copy_for_serialization(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_deep_copy_for_serialization(item) for item in value)
    if isinstance(value, frozenset):
        return {_deep_copy_for_serialization(item) for item in value}
    return value


def _copy_frozen_model(
    model: BaseModel,
    *,
    update: Mapping[str, Any] | None,
    deep: bool,
) -> Any:
    """Copy a frozen model without asking ``deepcopy`` to pickle proxies."""
    if deep:
        data = {
            key: _deep_freeze(_deep_copy_for_serialization(value))
            for key, value in model.__dict__.items()
        }
    else:
        data = dict(model.__dict__)

    fields_set = set(model.__pydantic_fields_set__)
    if update:
        data.update({key: _deep_freeze(value) for key, value in update.items()})
        fields_set.update(update)

    return type(model).model_construct(_fields_set=fields_set, **data)


class TemplateIR(BaseModel):
    """Stable intermediate representation for compiled templates.

    The ``legacy_config`` snapshot is intentional: permissive template
    extensions must survive compilation even when they are not part of the
    renderer-neutral vocabulary yet.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    CURRENT_VERSION: ClassVar[str] = TEMPLATE_IR_VERSION

    ir_version: str = TEMPLATE_IR_VERSION
    template_type: str
    title: str
    project_defaults: dict[str, Any] = Field(default_factory=dict)
    structure: tuple[dict[str, Any], ...] = ()
    sections: tuple[dict[str, Any], ...] = ()
    section_contracts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    context_schema: dict[str, Any] = Field(default_factory=dict)
    template_contract: dict[str, Any] | None = None
    legacy_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ir_version")
    @classmethod
    def supported_version(cls, value: str) -> str:
        if value != TEMPLATE_IR_VERSION:
            raise ValueError(f"Unsupported template IR version: {value!r}")
        return value

    @field_validator(
        "project_defaults",
        "structure",
        "sections",
        "section_contracts",
        "context_schema",
        "template_contract",
        "legacy_config",
        mode="after",
    )
    @classmethod
    def freeze_nested_data(cls, value: Any) -> Any:
        return _deep_freeze(value)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def model_dump(self, *, mode: str = "python", **kwargs: Any) -> dict[str, Any]:
        """Return a detached, JSON-native snapshot of the immutable IR."""
        snapshot = type(self).model_construct(
            _fields_set=set(self.__pydantic_fields_set__),
            **_deep_copy_for_serialization(self.__dict__),
        )
        return _deep_thaw(BaseModel.model_dump(snapshot, mode=mode, **kwargs))

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        return _copy_frozen_model(self, update=update, deep=deep)

    def model_dump_json(self, *, indent: int | None = None, **kwargs: Any) -> str:
        """Serialize a detached snapshot without exposing frozen containers."""
        value = self.model_dump(**kwargs)
        if indent is not None:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)
        from docs.domain.pipeline_kernel import deterministic_json

        return deterministic_json(value)

    def to_json(self) -> str:
        from docs.domain.pipeline_kernel import deterministic_json

        return deterministic_json(self.to_dict())
