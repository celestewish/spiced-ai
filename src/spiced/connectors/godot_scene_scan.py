"""Read-only parsing of Godot scene (``.tscn``) files (Market-Viability
Roadmap, Phase 2) -- the Godot counterpart to ``connectors.
unity_controller_scan``.

Same philosophy: Godot's ``.tscn`` format is a simple, line-oriented text
format (``[section_type key="value" ...]`` headers, each followed by its
own ``key = value`` body lines until the next header), and a full parser
isn't needed -- targeted regex extraction of the handful of fields this
module cares about (node tree structure, signal connections, and external
resource references) is sufficient.

**Format verification.** Grounded against two real ``.tscn`` files fetched
from the official ``godotengine/godot-demo-projects`` repo (``2d/
dodge_the_creeps/main.tscn`` and ``player.tscn``), not assumed from
documentation. That confirmed: the ``[gd_scene format=3 ...]`` header line;
that ``[ext_resource type="..." uid="..." path="res://..." id="..."]``
declares every external file a scene depends on, addressed by ``path=``
directly (no separate GUID-lookup layer the way Unity's ``.meta`` system
needs -- this is what makes broken-reference detection here simpler than
Unity's); that a ``[node ...]`` block omits ``type=`` when the node is an
instanced sub-scene (``instance=ExtResource(...)``) rather than a plain
engine node type; and the ``[connection signal="..." from="..." to="..."
method="..."]`` line shape for signal wiring.

**What is NOT independently verified**: no sample containing an
``AnimationTree``/``AnimationNodeStateMachine`` sub-resource was available
in the fetched project (it uses ``AnimatedSprite2D``/``SpriteFrames``
instead, which has no state-machine structure) -- this module deliberately
does not attempt to parse Godot's animation state machines. That is real,
tracked follow-up scope, not silently skipped: see the module-level
``__all__`` and this docstring as the record of the gap.

Every function here only reads files; nothing is ever modified or deleted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from spiced.connectors.godot_scan import iter_resources

__all__ = [
    "ParsedExtResource",
    "ParsedNode",
    "ParsedConnection",
    "ParsedScene",
    "BrokenSceneReference",
    "parse_scene_text",
    "scan_scenes",
    "scan_broken_references",
]

_HEADER_RE = re.compile(r"^\[(\w+)((?:\s+\w+=(?:\"(?:[^\"\\]|\\.)*\"|[^\s\]]+))*)\s*\]\s*$")
_ATTR_RE = re.compile(r'(\w+)=(?:"((?:[^"\\]|\\.)*)"|([^\s\]]+))')


def _parse_attrs(attr_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(attr_text):
        key = m.group(1)
        attrs[key] = m.group(2) if m.group(2) is not None else m.group(3)
    return attrs


@dataclass(frozen=True)
class ParsedExtResource:
    id: str
    type: str | None
    path: str | None  # "res://..." — None for a non-file external resource


@dataclass(frozen=True)
class ParsedNode:
    name: str
    type: str | None  # None when the node is an instanced sub-scene
    parent: str | None  # "." for a direct child of the scene root


@dataclass(frozen=True)
class ParsedConnection:
    signal: str
    from_node: str
    to_node: str
    method: str


@dataclass(frozen=True)
class ParsedScene:
    path: str  # relative to the project root, forward-slashed
    ext_resources: list[ParsedExtResource] = field(default_factory=list)
    nodes: list[ParsedNode] = field(default_factory=list)
    connections: list[ParsedConnection] = field(default_factory=list)


def parse_scene_text(text: str, rel_path: str) -> ParsedScene:
    ext_resources: list[ParsedExtResource] = []
    nodes: list[ParsedNode] = []
    connections: list[ParsedConnection] = []

    for line in text.splitlines():
        header_match = _HEADER_RE.match(line)
        if not header_match:
            continue
        section_type, attr_text = header_match.group(1), header_match.group(2)
        attrs = _parse_attrs(attr_text)

        if section_type == "ext_resource":
            ext_resources.append(
                ParsedExtResource(
                    id=attrs.get("id", ""), type=attrs.get("type"), path=attrs.get("path")
                )
            )
        elif section_type == "node":
            nodes.append(
                ParsedNode(
                    name=attrs.get("name", ""), type=attrs.get("type"), parent=attrs.get("parent")
                )
            )
        elif section_type == "connection":
            connections.append(
                ParsedConnection(
                    signal=attrs.get("signal", ""),
                    from_node=attrs.get("from", ""),
                    to_node=attrs.get("to", ""),
                    method=attrs.get("method", ""),
                )
            )
        # sub_resource / gd_scene headers carry no information this module's
        # consumers need yet.

    return ParsedScene(
        path=rel_path, ext_resources=ext_resources, nodes=nodes, connections=connections
    )


def scan_scenes(project_path: str | Path) -> list[ParsedScene]:
    """Parse every ``.tscn`` file in the project. Returns ``[]`` (never
    raises) if a file can't be read -- unreadable files are silently
    skipped, same discipline as every other Godot connector scan."""
    root = Path(project_path)
    results: list[ParsedScene] = []
    for asset in iter_resources(root):
        if asset.suffix.lower() != ".tscn":
            continue
        try:
            text = asset.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = asset.relative_to(root).as_posix()
        results.append(parse_scene_text(text, rel))
    return results


@dataclass(frozen=True)
class BrokenSceneReference:
    scene_path: str
    missing_resource_path: str


def scan_broken_references(project_path: str | Path) -> list[BrokenSceneReference]:
    """Cross-reference every scene's ``ext_resource path="res://..."``
    entries against files that actually exist on disk.

    Simpler than Unity's GUID-based broken-reference scan (see this
    module's docstring): Godot's ``.tscn`` addresses external resources by
    path directly, so no separate GUID-to-file lookup table is needed.
    """
    root = Path(project_path)
    broken: list[BrokenSceneReference] = []
    for scene in scan_scenes(project_path):
        for ext_resource in scene.ext_resources:
            if ext_resource.path is None or not ext_resource.path.startswith("res://"):
                continue
            resource_path = root / ext_resource.path[len("res://") :]
            if not resource_path.is_file():
                broken.append(
                    BrokenSceneReference(
                        scene_path=scene.path, missing_resource_path=ext_resource.path
                    )
                )
    broken.sort(key=lambda b: (b.scene_path, b.missing_resource_path))
    return broken
