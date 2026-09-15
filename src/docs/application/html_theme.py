"""Deterministic CSS projection of the existing visual_theme and cover contracts."""
from __future__ import annotations

import math
import re
from typing import Any

from docs.domain.cover import CoverMode, CoverVariant, resolve_cover_spec


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _color(value: Any, default: str) -> str:
    raw = str(value or default).lstrip("#").upper()
    return "#" + (raw if re.fullmatch(r"[0-9A-F]{6}", raw) else default)


def _number(value: Any, default: float) -> str:
    number = float(value) if type(value) in {int, float} else default
    return f"{number if math.isfinite(number) and number >= 0 else default:g}"


def _font(value: Any) -> str:
    # CSS string escaping, including '<' to prevent a style end-tag injection.
    return '"' + "".join(f"\\{ord(char):x} " if char in '\\"<>' or ord(char) < 32 else char
                         for char in str(value or "Times New Roman")) + '"'


def visual_theme_css(config: dict[str, Any]) -> str:
    raw = _mapping(config.get("format")).get("visual_theme")
    cover = resolve_cover_spec(config)
    generated = cover is not None and cover.mode is CoverMode.GENERATED
    if not isinstance(raw, dict) and not generated:
        return ""
    theme = _mapping(raw)
    colors = _mapping(theme.get("colors"))
    typography = _mapping(theme.get("typography"))
    spacing = _mapping(theme.get("spacing"))
    navy = _color(colors.get("navy"), "000000")
    teal = _color(colors.get("teal"), "000000")
    css: list[str] = []
    if isinstance(raw, dict):
        css.append(f"body {{ color: {navy}; background: {_color(colors.get('soft_background'), 'FFFFFF')}; "
                   f"font-family: {_font(typography.get('body_font'))}; font-size: {_number(typography.get('body_size_pt'), 12)}pt; "
                   f"line-height: {_number(spacing.get('body_line_spacing'), 1.5)}; }}")
        css.append(f"p {{ margin-bottom: {_number(spacing.get('body_after_pt'), 18)}pt; }}")
        for level in (1, 2, 3):
            color = _color(colors.get(f"heading_{level}"), (teal if level == 3 else navy)[1:])
            css.append(f"h{level} {{ color: {color}; font-family: {_font(typography.get('heading_font'))}; "
                       f"font-size: {_number(typography.get(f'heading_{level}_size_pt'), 12)}pt; "
                       f"margin-top: {_number(spacing.get(f'heading_{level}_before_pt'), 0)}pt; "
                       f"margin-bottom: {_number(spacing.get(f'heading_{level}_after_pt'), 18)}pt; }}")
        css.append(f"a {{ color: {teal}; }}")
        caption_color = _mapping(theme.get("captions")).get("color", "navy")
        css.append(f"figcaption {{ color: {_color(colors.get(caption_color), navy[1:])}; }}")
    if generated:
        assert cover is not None
        variant = cover.variant
        accent = _color(cover.visual.get("accent", cover.visual.get("accent_color")),
                        teal[1:] if isinstance(raw, dict) else "0F766E")
        secondary = _color(cover.visual.get("secondary_accent", colors.get("warm_accent")), "D97706")
        background = _color(cover.page.get("background", colors.get("soft_background")), "F4F7FA")
        title_color = _color(cover.visual.get("title_color"), navy[1:] if isinstance(raw, dict) else "0B1F33")
        body_color = _color(cover.visual.get("body_color"), "334155")
        css.extend([
            (f".cover {{ box-sizing: border-box; display: flex; flex-direction: column; padding: 2rem; "
             f"min-height: 80vh; break-after: page; color: {body_color}; background: {background}; }}"),
            f".cover__title {{ color: {title_color}; overflow-wrap: anywhere; }}",
            f".cover__eyebrow, .cover__institution {{ color: {accent}; font-weight: bold; }}",
            ".cover__slot { max-width: 100%; overflow-wrap: anywhere; }",
        ])
        selector = f".cover--{variant.value}"
        layouts = {
            CoverVariant.ACADEMIC: f"text-align: left; border-top: 14pt solid {accent}; border-bottom: 4pt solid {secondary};",
            CoverVariant.INSTITUTIONAL: f"text-align: center; border-bottom: 16pt solid {accent}; justify-content: space-around;",
            CoverVariant.TECHNICAL: f"text-align: left; border-left: 12pt solid {accent}; justify-content: center;",
            CoverVariant.MINIMAL: "text-align: center; border: none; background: white; justify-content: center;",
            CoverVariant.VISUAL: f"text-align: center; border-top: 48pt solid {accent}; background: {background}; justify-content: center;",
        }
        if variant is CoverVariant.CUSTOM:
            alignment = str(cover.layout.get("alignment", "center")).lower()
            if alignment not in {"left", "center", "right"}:
                alignment = "center"
            layout = f"text-align: {alignment}; padding-top: {_number(cover.layout.get('top_space_pt'), 96)}pt;"
            css.append(f"{selector} .cover__title {{ font-size: {_number(cover.layout.get('title_size_pt'), 24)}pt; }}")
        else:
            layout = layouts[variant]
        css.append(f"{selector} {{ {layout} }}")
    return "\n".join(css)
