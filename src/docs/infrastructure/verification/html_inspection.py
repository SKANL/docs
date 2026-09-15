"""Static HTML evidence only: no CSS cascade, JavaScript, network or WCAG claim."""
from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlsplit

from PIL import Image

from docs.domain.artifacts import RenderProfile, VerificationFinding

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class Element:
    tag: str
    attrs: dict[str, str]
    ancestors: tuple[Element, ...]
    text: list[str] = field(default_factory=list)

    @property
    def styles(self) -> dict[str, str]:
        return {key.strip().lower(): value.strip().lower() for item in self.attrs.get("style", "").split(";")
                if ":" in item for key, value in [item.split(":", 1)]}

    @property
    def hidden(self) -> bool:
        return any(node.tag in {"head", "script", "style", "template"} or "hidden" in node.attrs or node.attrs.get("aria-hidden") == "true"
                   or node.styles.get("display") == "none" or node.styles.get("visibility") == "hidden"
                   for node in (*self.ancestors, self))


class HtmlInspection(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self.stack: list[Element] = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Element(tag, {k: v or "" for k, v in attrs}, tuple(self.stack))
        self.elements.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if not any(n.tag in {"script", "style", "template", "head"} or n.hidden for n in self.stack):
            for node in self.stack:
                node.text.append(data)

    def accessibility(self) -> list[VerificationFinding]:
        findings: list[VerificationFinding] = []

        def missing(code: str, message: str) -> None:
            findings.append(VerificationFinding(f"accessibility.html.{code}", message, dimension="accessibility"))

        roots = [n for n in self.elements if n.tag == "html"]
        if not roots or not roots[0].attrs.get("lang", "").strip():
            missing("lang", "HTML must declare its document language on the html element.")
        visible = [n for n in self.elements if not n.hidden]
        headings = [n for n in visible if re.fullmatch(r"h[1-6]", n.tag)]
        if not any(n.tag == "h1" and "".join(n.text).strip() for n in headings):
            missing("h1", "HTML needs a nonempty, visible h1.")
        previous = 0
        for node in headings:
            level = int(node.tag[1])
            if level > previous + 1 or not "".join(node.text).strip():
                missing("heading_order", f"Empty or skipped heading level: {node.tag} after h{previous}.")
            previous = level
        for tag, role in (("main", "main"), ("header", "banner")):
            if not any(n.tag == tag or n.attrs.get("role") == role for n in visible):
                missing(tag, f"HTML needs a visible {tag} landmark ({tag} or role={role}).")
        for node in visible:
            if node.tag == "img" and "alt" not in node.attrs:
                missing("alt", "Image is missing alt text; use alt=\"\" for a decorative image.")
        return findings

    def visual(self, path: Path, profile: RenderProfile) -> list[VerificationFinding]:
        findings: list[VerificationFinding] = []
        bodies = [n for n in self.elements if n.tag == "body"]
        images = [n for n in self.elements if n.tag == "img" and not n.hidden]
        graphics = any(n.tag in {"svg", "canvas", "video", "object", "iframe"} and not n.hidden for n in self.elements)
        if not any("".join(n.text).strip() for n in bodies) and not images and not graphics:
            findings.append(VerificationFinding("render.page.blank", "HTML body has no static visible content.",
                                                "warning" if profile.allow_blank_pages else "error"))
        for node in images:
            findings.extend(_image_findings(node, path))
        for node in self.elements:
            if node.hidden:
                continue
            for parent in reversed(node.ancestors):
                for axis in ("width", "height"):
                    size = _pixels(node.styles.get(axis, node.attrs.get(axis, "")))
                    limit = _pixels(parent.styles.get(axis, ""))
                    if size is not None and limit is not None and size > limit:
                        clipped = parent.styles.get(f"overflow-{'x' if axis == 'width' else 'y'}",
                                                    parent.styles.get("overflow")) in {"hidden", "clip"}
                        findings.append(VerificationFinding(
                            "render.content.clipping" if clipped else "render.content.overflow",
                            f"Declared {node.tag} {axis} {size:g}px exceeds ancestor {limit:g}px; browser confirmation required.",
                            "warning", evidence={"axis": axis, "size_px": size, "limit_px": limit},
                        ))
        findings.append(VerificationFinding(
            "render.layout.unavailable",
            "Browser renderer unavailable: computed layout, CSS cascade, clipping and screenshots are unverified; static checks only.",
            "warning",
        ))
        return findings


def _pixels(value: str) -> float | None:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(px)?", value)
    return float(match[1]) if match else None


def _image_findings(node: Element, path: Path) -> list[VerificationFinding]:
    source = node.attrs.get("src", "")
    try:
        if not source:
            raise ValueError("missing src")
        if source.startswith("data:"):
            header, data = source.split(",", 1)
            content = base64.b64decode(data, validate=True) if header.endswith(";base64") else unquote_to_bytes(data)
        else:
            url = urlsplit(source)
            candidate = (path.parent / unquote(url.path)).resolve()
            if url.scheme or url.netloc or not candidate.is_relative_to(path.parent.resolve()):
                return [VerificationFinding("render.image.unverified", "External image not read by static QA.", "warning")]
            content = candidate.read_bytes()
        if source.startswith("data:image/svg+xml") or source.lower().endswith(".svg"):
            from defusedxml.ElementTree import fromstring

            if fromstring(content).tag.split("}")[-1] != "svg":
                raise ValueError("not an SVG root")
            return [VerificationFinding("render.image.unverified", "SVG XML parsed; raster appearance requires a browser.", "warning")]
        with Image.open(io.BytesIO(content)) as image:
            image.load()
    except Exception as exc:
        # One bad image must not hide the remaining image/layout findings.
        return [VerificationFinding("render.image.invalid", f"Invalid HTML image: {exc}")]
    return []
