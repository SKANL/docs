# src/docs/domain/svg_normalize.py
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as safe_fromstring

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_CSS_URL_RE = re.compile(r"url\s*\(\s*([\"']?)#([\w:.-]+)\1\s*\)", re.IGNORECASE)
_CSS_ID_RE = re.compile(r"(?<![\w.-])#([\w:.-]+)(?![\w.-])")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse(text: str) -> ET.Element:
    try:
        return safe_fromstring(text)
    except DefusedXmlException as exc:
        raise ValueError("Unsafe SVG XML: DTD and entity declarations are not allowed") from exc
    except ET.ParseError as exc:
        raise ValueError(f"Invalid SVG XML: {exc}") from exc


def _serialize(root: ET.Element) -> str:
    ET.register_namespace("", _SVG_NS)
    ET.register_namespace("xlink", _XLINK_NS)
    return ET.tostring(root, encoding="unicode", short_empty_elements=True)


def _rewrite_css_references(css: str, mapping: dict[str, str]) -> str:
    """Rewrite SVG references in CSS while leaving comments and strings intact."""
    if not mapping:
        return css

    rewritten: list[str] = []
    position = 0
    while position < len(css):
        if css.startswith("/*", position):
            end = css.find("*/", position + 2)
            end = len(css) if end == -1 else end + 2
            rewritten.append(css[position:end])
            position = end
            continue
        if css[position] in {"'", '\"'}:
            quote = css[position]
            end = position + 1
            while end < len(css):
                if css[end] == "\\":
                    end += 2
                elif css[end] == quote:
                    end += 1
                    break
                else:
                    end += 1
            rewritten.append(css[position:end])
            position = end
            continue

        url_match = _CSS_URL_RE.match(css, position)
        if url_match:
            old = url_match.group(2)
            rewritten.append(
                css[position:url_match.start(2)]
                + mapping.get(old, old)
                + css[url_match.end(2):url_match.end()]
            )
            position = url_match.end()
            continue

        id_match = _CSS_ID_RE.match(css, position)
        if id_match and _is_css_selector_reference(css, position):
            old = id_match.group(1)
            rewritten.append(css[position:id_match.start(1)] + mapping.get(old, old))
            position = id_match.end(1)
            continue

        rewritten.append(css[position])
        position += 1
    return "".join(rewritten)


def _is_css_selector_reference(css: str, position: int) -> bool:
    """Distinguish a selector ID from a color or other declaration value."""
    cursor = position
    while cursor < len(css):
        if css.startswith("/*", cursor):
            end = css.find("*/", cursor + 2)
            cursor = len(css) if end == -1 else end + 2
            continue
        if css[cursor] in {"'", '\"'}:
            quote = css[cursor]
            cursor += 1
            while cursor < len(css):
                if css[cursor] == "\\":
                    cursor += 2
                elif css[cursor] == quote:
                    cursor += 1
                    break
                else:
                    cursor += 1
            continue
        if css[cursor] in "{};":
            return css[cursor] == "{"
        cursor += 1
    return False


def ensure_accessibility_metadata(
    text: str, name: str, description: str, *, decorative: bool = False
) -> str:
    """Replace SVG accessibility semantics using the XML tree, not tag regexes."""
    if not name and not description and not decorative:
        return text
    root = _parse(text)
    if _local_name(root.tag).lower() != "svg":
        return text
    for child in list(root):
        if _local_name(child.tag).lower() in {"title", "desc"}:
            root.remove(child)
    if decorative:
        for attr in list(root.attrib):
            if _local_name(attr).lower() in {"aria-labelledby", "aria-describedby", "role", "hidden"}:
                del root.attrib[attr]
        root.set("role", "presentation")
        root.set("aria-hidden", "true")
    else:
        root.set("aria-labelledby", "visual-title visual-desc")
        namespace = root.tag.split("}", 1)[0][1:] if root.tag.startswith("{") else ""
        title_tag = f"{{{namespace}}}title" if namespace else "title"
        desc_tag = f"{{{namespace}}}desc" if namespace else "desc"
        title = ET.Element(title_tag, {"id": "visual-title"})
        title.text = name
        desc = ET.Element(desc_tag, {"id": "visual-desc"})
        desc.text = description
        root.insert(0, desc)
        root.insert(0, title)
    return _serialize(root)


def normalize_svg(text: str) -> str:
    """Normalize valid SVG XML and rewrite IDs by first appearance."""
    root = _parse(text)
    ids: list[str] = []
    seen: set[str] = set()
    for element in root.iter():
        value = element.get("id")
        if value is not None and value not in seen:
            seen.add(value)
            ids.append(value)
    mapping = {old: f"n{i}" for i, old in enumerate(ids)}
    for element in root.iter():
        for attr, original_value in list(element.attrib.items()):
            value = original_value
            if attr == "id" and value in mapping:
                element.set(attr, mapping[value])
                continue
            if attr in {"aria-labelledby", "aria-describedby"}:
                element.set(attr, " ".join(mapping.get(token, token) for token in value.split()))
                continue
            for old in sorted(mapping, key=len, reverse=True):
                value = value.replace(f"url(#{old})", f"url(#{mapping[old]})")
                value = re.sub(rf"(?<![\w.-])#{re.escape(old)}(?![\w.-])", f"#{mapping[old]}", value)
                if value == old:
                    value = mapping[old]
            element.set(attr, value)
        if _local_name(element.tag).lower() == "style" and element.text:
            element.text = _rewrite_css_references(element.text, mapping)
    for parent in root.iter():
        for child in list(parent):
            if _local_name(child.tag).lower() == "metadata":
                parent.remove(child)
    return _serialize(root)
