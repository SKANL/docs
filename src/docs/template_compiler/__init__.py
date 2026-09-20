"""Public Template Compiler and versioned Template IR API."""

from .compiler import (
    TemplateCompilationError,
    TemplateCompiler,
    compile_template,
    compile_template_json,
    source_template,
)
from .ir import TEMPLATE_IR_VERSION, TemplateIR
from .lowering import RendererLoweringMetadata
from .source_adapter import (
    from_source_template,
    to_source_config,
    to_source_template,
)

__all__ = [
    "TEMPLATE_IR_VERSION",
    "RendererLoweringMetadata",
    "TemplateCompilationError",
    "TemplateCompiler",
    "TemplateIR",
    "compile_template",
    "compile_template_json",
    "from_source_template",
    "source_template",
    "to_source_config",
    "to_source_template",
]
