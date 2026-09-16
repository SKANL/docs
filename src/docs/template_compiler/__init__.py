"""Public Template Compiler and versioned Template IR API."""

from .compiler import (
    TemplateCompilationError,
    TemplateCompiler,
    compile_template,
    compile_template_json,
    legacy_template,
)
from .ir import TEMPLATE_IR_VERSION, TemplateIR
from .legacy import from_legacy_template, to_legacy_config, to_legacy_template
from .lowering import RendererLoweringMetadata

__all__ = [
    "TEMPLATE_IR_VERSION",
    "RendererLoweringMetadata",
    "TemplateCompilationError",
    "TemplateCompiler",
    "TemplateIR",
    "compile_template",
    "compile_template_json",
    "from_legacy_template",
    "legacy_template",
    "to_legacy_config",
    "to_legacy_template",
]
