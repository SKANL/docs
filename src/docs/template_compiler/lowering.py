"""Renderer-facing metadata lowered from a template fidelity contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from docs.domain.pipeline_kernel import deterministic_json

from .ir import _deep_copy_for_serialization, _deep_freeze, _deep_thaw


class RendererLoweringMetadata(BaseModel):
    """Data-shaped renderer hints; no renderer API is required to consume it."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    page_geometry: dict[str, Any] = Field(default_factory=dict)
    style_contract: dict[str, Any] = Field(default_factory=dict)
    components: tuple[dict[str, Any], ...] = ()
    editable_slots: tuple[dict[str, Any], ...] = ()
    required_assets: tuple[dict[str, Any], ...] = ()
    fidelity_checks: tuple[dict[str, Any], ...] = ()
    allowed_degradations: tuple[str, ...] = ()
    contract_declared: bool = False
    contract_hash: str | None = None

    @field_validator(
        "page_geometry",
        "style_contract",
        "components",
        "editable_slots",
        "required_assets",
        "fidelity_checks",
        "allowed_degradations",
        mode="after",
    )
    @classmethod
    def freeze_nested_data(cls, value: Any) -> Any:
        return _deep_freeze(value)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def model_dump(self, *, mode: str = "python", **kwargs: Any) -> dict[str, Any]:
        """Return a detached, JSON-native snapshot of the immutable metadata."""
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
        from .ir import _copy_frozen_model

        return _copy_frozen_model(self, update=update, deep=deep)

    def model_dump_json(self, *, indent: int | None = None, **kwargs: Any) -> str:
        """Serialize a detached snapshot without exposing frozen containers."""
        value = self.model_dump(**kwargs)
        if indent is not None:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)
        return deterministic_json(value)

    def to_json(self) -> str:
        return deterministic_json(self.to_dict())
