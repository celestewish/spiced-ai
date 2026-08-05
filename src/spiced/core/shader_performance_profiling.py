"""Shader Performance Profiling (Phase J, section 8 part 2, Core tier).

Static heuristic scan of ``.shader``/``.shadergraph`` files under the
project's ``Assets/`` (reusing ``connectors.unity_scan.iter_assets``, the
same read-only file-walk every other recursive scan in this codebase uses).
Unity ``.shader`` files are plain HLSL/ShaderLab text, so this regex/text-
scans for complexity indicators rather than parsing a real shader AST:

- **Texture sampler count** -- ``sampler2D``/``sampler3D``/``samplerCUBE``/
  ``SAMPLER``/``Texture2D``/``Texture2DArray``/``TextureCube`` declarations.
- **Pass count** -- the number of ``Pass { ... }`` blocks (brace-matched, not
  just counting the literal string, so a ``Pass`` keyword appearing in a
  comment/string inside another block isn't double counted -- though this is
  still a text scan, not a real ShaderLab parser, so it can be fooled by
  unusual formatting).
- **Loop constructs** -- ``for``/``while`` anywhere in the file.
- **A rough instruction-count proxy** -- line count within the largest
  ``Pass`` block. This is explicitly a proxy, not a real GPU instruction
  count: line count correlates only loosely with actual compiled shader
  cost, which depends on the target platform, graphics API, driver shader
  compiler, and optimization passes -- none of which Spiced can see from a
  saved text file. **Spiced never compiles or profiles a shader on real
  hardware, or any hardware at all.**

**``.shadergraph`` scope decision**: Unity's Shader Graph asset format is
JSON, but this project could not locate or generate a real, Unity-authored
``.shadergraph`` file to verify its schema against (the same "verify against
a real sample, or say you didn't" discipline
``connectors.unity_controller_scan`` documents for ``.controller`` files).
Guessing at node-count-based complexity scoring from documentation alone
risked asserting a heuristic with no basis, so this module deliberately
scopes ``.shadergraph`` support down to *detection only*: the file is
confirmed present and (if it parses as JSON at all) noted as such, then
flagged for manual review -- no complexity score, no hardware-tier flag is
attempted for it. See ``ShaderGraphFinding``.

**Cross-Platform Test Simulation integration**: rather than inventing a new
hardware-tier framing, a shader whose ``.shader`` heuristic score crosses the
documented thresholds below is flagged as "likely too expensive" for the two
weakest tiers already defined in ``core.hardware_simulation.HARDWARE_TIERS``
(the two with the lowest ``fps_factor`` -- currently Low-end PC and Handheld)
-- the same tier names/framing the existing Performance screen already shows
the developer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from spiced.connectors.unity_scan import iter_assets
from spiced.core.hardware_simulation import HARDWARE_TIERS
from spiced.storage.projects import Project
from spiced.storage.shader_profiling_reports import (
    ShaderProfilingReport,
    ShaderProfilingReportRepository,
)

SHADER_PROFILING_CAVEAT = (
    "Rough, deterministic proxy only -- NOT a real GPU-instruction count or a profiling "
    "measurement. Spiced never compiles or runs your shaders on real hardware (or any "
    "hardware); it only counts texture samplers, Pass blocks, loop constructs, and lines of "
    "code inside the largest Pass block as a stand-in for cost. Two shaders with the same "
    "heuristic score can have wildly different real GPU cost depending on the target platform, "
    "graphics API, and driver shader compiler. Treat every flag as 'worth checking on real "
    "hardware,' never a verdict. .shadergraph (Shader Graph) files are detected but not deeply "
    "analyzed -- see the module docstring for why."
)

# Deliberately simple, documented thresholds -- see the module docstring for
# why these are a rough proxy, not a real cost estimate.
HIGH_SAMPLER_COUNT = 4
HIGH_PASS_COUNT = 3
HIGH_LOOP_COUNT = 1
HIGH_LINES_PER_PASS = 150

_SAMPLER_RE = re.compile(
    r"\b(?:sampler2D|sampler3D|samplerCUBE|SAMPLER\w*|Texture2DArray|Texture2D|TextureCube)\b"
)
_PASS_RE = re.compile(r"\bPass\s*\{")
_LOOP_RE = re.compile(r"\b(?:for|while)\s*\(")

# The two tiers a "likely_expensive" shader is flagged against -- the two
# weakest tiers already defined in core.hardware_simulation (lowest
# fps_factor), computed rather than hardcoded so this stays in sync if that
# module's tiers ever change.
FRAGILE_HARDWARE_TIERS: tuple[str, ...] = tuple(
    sorted(HARDWARE_TIERS, key=lambda tier: HARDWARE_TIERS[tier]["fps_factor"])[:2]
)


@dataclass(frozen=True)
class ShaderComplexity:
    path: str  # relative to the project root, forward-slashed
    sampler_count: int
    pass_count: int
    loop_count: int
    max_lines_in_pass: int
    likely_expensive: bool
    reasons: list[str] = field(default_factory=list)
    at_risk_tiers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ShaderGraphFinding:
    """A detected .shadergraph asset -- deliberately not deeply analyzed.

    See the module docstring's ".shadergraph scope decision" for why: this
    project could not verify Shader Graph's JSON schema against a real
    sample, so no complexity score is attempted.
    """

    path: str
    parses_as_json: bool
    note: str = "Shader Graph asset detected but not deeply analyzed -- flagged for manual review."


@dataclass(frozen=True)
class ShaderProfilingResult:
    shaders: list[ShaderComplexity] = field(default_factory=list)
    shader_graphs: list[ShaderGraphFinding] = field(default_factory=list)
    caveat: str = SHADER_PROFILING_CAVEAT

    @property
    def flagged_count(self) -> int:
        return sum(1 for s in self.shaders if s.likely_expensive)

    def as_summary_dict(self) -> dict:
        return {
            "shaders": [
                {
                    "path": s.path,
                    "sampler_count": s.sampler_count,
                    "pass_count": s.pass_count,
                    "loop_count": s.loop_count,
                    "max_lines_in_pass": s.max_lines_in_pass,
                    "likely_expensive": s.likely_expensive,
                    "reasons": s.reasons,
                    "at_risk_tiers": s.at_risk_tiers,
                }
                for s in self.shaders
            ],
            "shader_graphs": [
                {"path": g.path, "parses_as_json": g.parses_as_json, "note": g.note}
                for g in self.shader_graphs
            ],
            "flagged_count": self.flagged_count,
        }


def _pass_blocks(text: str) -> list[str]:
    """Brace-matched ``Pass { ... }`` blocks -- a rough splitter, not a real
    ShaderLab parser (see module docstring)."""
    blocks: list[str] = []
    for match in _PASS_RE.finditer(text):
        start = match.end() - 1  # index of the opening brace
        depth = 0
        i = start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(text[start : i + 1])
                    break
            i += 1
    return blocks


def analyze_shader_text(text: str, rel_path: str) -> ShaderComplexity:
    sampler_count = len(_SAMPLER_RE.findall(text))
    blocks = _pass_blocks(text)
    pass_count = len(blocks) if blocks else len(_PASS_RE.findall(text))
    loop_count = len(_LOOP_RE.findall(text))
    max_lines = max((len(b.splitlines()) for b in blocks), default=0)

    reasons: list[str] = []
    if sampler_count >= HIGH_SAMPLER_COUNT:
        reasons.append(f"{sampler_count} texture sampler declaration(s) (>= {HIGH_SAMPLER_COUNT})")
    if pass_count >= HIGH_PASS_COUNT:
        reasons.append(f"{pass_count} Pass block(s) (>= {HIGH_PASS_COUNT})")
    if loop_count >= HIGH_LOOP_COUNT:
        reasons.append(f"{loop_count} loop construct(s) (for/while)")
    if max_lines >= HIGH_LINES_PER_PASS:
        reasons.append(
            f"{max_lines} lines in its largest Pass block (>= {HIGH_LINES_PER_PASS}, a rough "
            "proxy only -- not a real instruction count)"
        )

    likely_expensive = bool(reasons)
    return ShaderComplexity(
        path=rel_path,
        sampler_count=sampler_count,
        pass_count=pass_count,
        loop_count=loop_count,
        max_lines_in_pass=max_lines,
        likely_expensive=likely_expensive,
        reasons=reasons,
        at_risk_tiers=list(FRAGILE_HARDWARE_TIERS) if likely_expensive else [],
    )


def _analyze_shader_graph(path: Path, rel_path: str) -> ShaderGraphFinding:
    parses = False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        json.loads(text)
        parses = True
    except (OSError, ValueError):
        parses = False
    return ShaderGraphFinding(path=rel_path, parses_as_json=parses)


def scan_shaders(project_path: str | Path) -> ShaderProfilingResult:
    """Read-only scan of every ``.shader``/``.shadergraph`` file under the
    project's ``Assets/`` folder. Returns an empty-findings result (never
    raises) if the project has no ``Assets/`` folder or no matching files."""
    root = Path(project_path)
    shaders: list[ShaderComplexity] = []
    shader_graphs: list[ShaderGraphFinding] = []
    for asset in iter_assets(root):
        suffix = asset.suffix.lower()
        rel = asset.relative_to(root).as_posix()
        if suffix == ".shader":
            try:
                text = asset.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            shaders.append(analyze_shader_text(text, rel))
        elif suffix == ".shadergraph":
            shader_graphs.append(_analyze_shader_graph(asset, rel))
    shaders.sort(key=lambda s: s.path)
    shader_graphs.sort(key=lambda g: g.path)
    return ShaderProfilingResult(shaders=shaders, shader_graphs=shader_graphs)


class NoUnityFolderError(RuntimeError):
    """Raised when the project has no connected folder to scan."""


class ShaderPerformanceProfilingService:
    def __init__(self, reports: ShaderProfilingReportRepository) -> None:
        self._reports = reports

    def scan(self, project: Project) -> tuple[ShaderProfilingResult, ShaderProfilingReport]:
        if not project.path:
            raise NoUnityFolderError(
                "Connect a Unity folder for this project first (Projects screen)."
            )
        result = scan_shaders(project.path)
        report = self._reports.create(project.id, result.as_summary_dict())
        return result, report

    def history(self, project_id: int, limit: int = 20) -> list[ShaderProfilingReport]:
        return self._reports.list_for_project(project_id, limit=limit)
