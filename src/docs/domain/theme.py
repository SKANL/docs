"""Pure document visual-theme model and resolution from workspace config."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ThemeColors:
    navy: str = "000000"
    teal: str = "000000"
    warm_accent: str = "000000"
    soft_background: str = "FFFFFF"
    heading_1: str = "000000"
    heading_2: str = "000000"
    heading_3: str = "000000"


@dataclass(frozen=True)
class ThemeTypography:
    body_font: str = "Times New Roman"
    body_size_pt: float = 12
    heading_font: str = "Times New Roman"
    heading_1_size_pt: float = 12
    heading_2_size_pt: float = 12
    heading_3_size_pt: float = 12


@dataclass(frozen=True)
class ThemeSpacing:
    body_line_spacing: float = 1.5
    body_after_pt: float = 18
    heading_1_before_pt: float = 0
    heading_1_after_pt: float = 18
    heading_2_before_pt: float = 0
    heading_2_after_pt: float = 18
    heading_3_before_pt: float = 0
    heading_3_after_pt: float = 18


@dataclass(frozen=True)
class ThemeHeader:
    title: str = ""
    accent_color: str = "navy"


@dataclass(frozen=True)
class ThemeFooter:
    font_size_pt: float = 12
    color: str = "navy"


@dataclass(frozen=True)
class ThemeCaptions:
    color: str = "navy"


@dataclass(frozen=True)
class VisualTheme:
    colors: ThemeColors = ThemeColors()
    typography: ThemeTypography = ThemeTypography()
    spacing: ThemeSpacing = ThemeSpacing()
    header: ThemeHeader = ThemeHeader()
    footer: ThemeFooter = ThemeFooter()
    captions: ThemeCaptions = ThemeCaptions()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _hex_color(value: Any, default: str) -> str:
    candidate = str(value or default).lstrip("#").upper()
    return candidate if re.fullmatch(r"[0-9A-F]{6}", candidate) else default


def _number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def resolve_visual_theme(config: dict[str, Any]) -> VisualTheme:
    """Resolve the optional document visual theme while retaining current defaults."""
    raw = _mapping(_mapping(config.get("format")).get("visual_theme"))
    colors = _mapping(raw.get("colors"))
    typography = _mapping(raw.get("typography"))
    spacing = _mapping(raw.get("spacing"))
    header = _mapping(raw.get("header"))
    footer = _mapping(raw.get("footer"))
    captions = _mapping(raw.get("captions"))
    defaults = ThemeColors()
    navy = _hex_color(colors.get("navy"), defaults.navy)
    teal = _hex_color(colors.get("teal"), defaults.teal)
    return VisualTheme(
        colors=ThemeColors(
            navy=navy,
            teal=teal,
            warm_accent=_hex_color(colors.get("warm_accent"), defaults.warm_accent),
            soft_background=_hex_color(colors.get("soft_background"), defaults.soft_background),
            heading_1=_hex_color(colors.get("heading_1"), navy),
            heading_2=_hex_color(colors.get("heading_2"), navy),
            heading_3=_hex_color(colors.get("heading_3"), teal),
        ),
        typography=ThemeTypography(
            body_font=str(typography.get("body_font") or ThemeTypography.body_font),
            body_size_pt=_number(typography.get("body_size_pt"), ThemeTypography.body_size_pt),
            heading_font=str(typography.get("heading_font") or ThemeTypography.heading_font),
            heading_1_size_pt=_number(typography.get("heading_1_size_pt"), ThemeTypography.heading_1_size_pt),
            heading_2_size_pt=_number(typography.get("heading_2_size_pt"), ThemeTypography.heading_2_size_pt),
            heading_3_size_pt=_number(typography.get("heading_3_size_pt"), ThemeTypography.heading_3_size_pt),
        ),
        spacing=ThemeSpacing(**{field: _number(spacing.get(field), getattr(ThemeSpacing(), field)) for field in ThemeSpacing.__dataclass_fields__}),
        header=ThemeHeader(title=str(header.get("title") or ""), accent_color=str(header.get("accent_color") or "navy")),
        footer=ThemeFooter(font_size_pt=_number(footer.get("font_size_pt"), ThemeFooter.font_size_pt), color=str(footer.get("color") or "navy")),
        captions=ThemeCaptions(color=str(captions.get("color") or "navy")),
    )


def has_visual_theme(config: dict[str, Any]) -> bool:
    return isinstance(_mapping(config.get("format")).get("visual_theme"), dict)


def resolve_theme_color(theme: VisualTheme, name: str) -> str:
    return getattr(theme.colors, name, theme.colors.navy)
