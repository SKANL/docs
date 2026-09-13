"""Compatibility port for v2 transactional transforms.

Concrete implementations are resolved by the composition root at runtime;
the application package intentionally has no static infrastructure import.
"""

from typing import Any

__all__ = [  # noqa: F822
    "DEFAULT_COMMAND_TIMEOUT_SECONDS",
    "AtomicTransform",
    "SubprocessAdapter",
    "TransformCallable",
    "TransformResult",
    "TransformSpec",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    from importlib import import_module

    implementation = import_module("docs.infrastructure.transform.v2_atomic_transform")
    return getattr(implementation, name)
