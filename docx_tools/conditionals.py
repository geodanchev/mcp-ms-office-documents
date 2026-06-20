"""Conditional block resolution for DOCX templates (Phase 1: block-level).

A template author can wrap a range of body content between marker paragraphs so
that the range is kept or dropped depending on a boolean tool argument:

    {{#if flag}}        keep the inner content when ``flag`` is truthy
    ...
    {{/if}}

    {{^if flag}}        keep the inner content when ``flag`` is falsy
    ...
    {{/if}}

Markers are recognised only when a paragraph's entire (trimmed) text is exactly
one marker token. Because the marker text is read from the paragraph's combined
runs, a marker that Word has split across several runs is still detected.

Granularity is *block-level*: everything between the markers — paragraphs,
lists, page breaks and whole tables — is a sibling element in the document body,
so all of it is pruned together. Markers are evaluated against the document body
only; conditionals inside table cells, headers and footers are not handled yet.

Error handling is intentionally forgiving ("warn and keep content"): if the
markers in the body are not well balanced, a warning is logged, **all content is
preserved**, and only the recognisable marker paragraphs are stripped so the
literal ``{{#if}}`` text does not leak into the generated document.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

logger = logging.getLogger(__name__)

# Marker paragraphs: the whole trimmed paragraph text must be exactly one token.
_OPEN_IF = re.compile(r'^\{\{#if\s+([a-zA-Z_][a-zA-Z0-9_]*)\}\}$')
_OPEN_UNLESS = re.compile(r'^\{\{\^if\s+([a-zA-Z_][a-zA-Z0-9_]*)\}\}$')
_CLOSE_IF = re.compile(r'^\{\{/if\}\}$')


class _Marker:
    """A recognised conditional marker on a paragraph."""

    __slots__ = ("kind", "name", "negate")

    def __init__(self, kind: str, name: Optional[str] = None, negate: bool = False):
        self.kind = kind  # "open" or "close"
        self.name = name  # condition name (open markers only)
        self.negate = negate  # True for {{^if ...}}


def _parse_marker(text: str) -> Optional[_Marker]:
    """Return the marker a paragraph represents, or None if it is not a marker."""
    s = text.strip()
    if not s:
        return None
    m = _OPEN_IF.match(s)
    if m:
        return _Marker("open", m.group(1), negate=False)
    m = _OPEN_UNLESS.match(s)
    if m:
        return _Marker("open", m.group(1), negate=True)
    if _CLOSE_IF.match(s):
        return _Marker("close")
    return None


def _paragraph_text(p_elem) -> str:
    """Combined run text of a ``<w:p>`` element (handles run-split markers)."""
    return Paragraph(p_elem, None).text


def _evaluate(marker: _Marker, conditions: Dict[str, Any]) -> bool:
    """Whether the inner content of an open marker should be kept."""
    if marker.name not in conditions:
        logger.warning(
            "[dynamic-docx] Condition '%s' is not a known argument; "
            "treating as true (content kept).",
            marker.name,
        )
        value = True
    else:
        value = bool(conditions[marker.name])
    return (not value) if marker.negate else value


def resolve_conditionals(doc: DocxDocument, conditions: Dict[str, Any]) -> None:
    """Prune conditional blocks in the document body in place.

    Must run *before* placeholder substitution, because it deletes whole block
    elements (paragraphs and tables) and operates on the raw body element list.

    Args:
        doc: The Word document to process (mutated in place).
        conditions: Mapping of argument name -> value; truthiness decides keeps.
    """
    _resolve_block_container(doc._body._body, conditions)


def _resolve_block_container(container, conditions: Dict[str, Any]) -> None:
    """Resolve markers among the direct block children of ``container``."""
    p_tag = qn('w:p')
    children = list(container)

    # Pass 1: locate marker paragraphs and check that they are balanced.
    markers: Dict[int, _Marker] = {}
    depth = 0
    balanced = True
    for elem in children:
        if elem.tag != p_tag:
            continue
        marker = _parse_marker(_paragraph_text(elem))
        if marker is None:
            continue
        markers[id(elem)] = marker
        if marker.kind == "open":
            depth += 1
        else:  # close
            depth -= 1
            if depth < 0:
                balanced = False
                depth = 0  # recover so later counting stays sane
    if depth != 0:
        balanced = False

    if not markers:
        return

    if not balanced:
        logger.warning(
            "[dynamic-docx] Unbalanced {{#if}}/{{/if}} markers in template body; "
            "keeping all content and stripping %d marker paragraph(s).",
            len(markers),
        )
        for elem in children:
            if id(elem) in markers:
                container.remove(elem)
        return

    # Pass 2: prune. A frame on the stack holds whether its inner content is kept;
    # an element survives only when every enclosing frame keeps its content.
    stack = []
    for elem in children:
        marker = markers.get(id(elem))
        if marker is not None:
            if marker.kind == "open":
                stack.append(_evaluate(marker, conditions))
            elif stack:  # close
                stack.pop()
            container.remove(elem)  # marker paragraphs are always removed
            continue
        if stack and not all(stack):
            container.remove(elem)
