"""Tests for build_asset_scan_prompt's multi-engine support.

The regression this guards against: ``_format_oversized_findings`` used to
unconditionally read ``finding.reason``, and the module imported Unity's own
``OversizedAssetFinding`` (which always has a ``reason``). Feeding it an
Unreal finding -- ``core.asset_scan.AssetScanService`` synthesizes a reason
for those, since ``connectors.unreal_scan.OversizedBinaryAssetFinding`` has
no ``reason`` field of its own -- would have raised ``AttributeError`` before
the fix. This test builds the exact real ``AssetFinding`` shape
``AssetScanService`` produces for Unreal and confirms the prompt still builds.
"""

from __future__ import annotations

from spiced.ai.prompt_templates import build_asset_scan_prompt
from spiced.core.asset_scan import AssetFinding


def test_build_asset_scan_prompt_does_not_raise_on_unreal_findings():
    finding = AssetFinding(
        path="Content/Textures/Huge.uasset",
        size_bytes=25 * 1024 * 1024,
        kind="uasset",
        reason="Unreal's packaged binary format can't be inspected further than size and "
        "extension without the Editor itself.",
    )

    prompt = build_asset_scan_prompt(
        [finding], [], orphan_caveat="no orphan-scan for Unreal", engine="Unreal"
    )

    assert "Huge.uasset" in prompt
    assert "indie Unreal developer" in prompt


def test_build_asset_scan_prompt_includes_broken_scene_references_for_godot():
    prompt = build_asset_scan_prompt(
        [],
        [],
        orphan_caveat="no orphan-scan for Godot",
        engine="Godot",
        broken_scene_references=["main.tscn -> res://missing.png"],
    )

    assert "main.tscn -> res://missing.png" in prompt
    assert "indie Godot developer" in prompt


def test_build_asset_scan_prompt_defaults_to_unity_wording():
    prompt = build_asset_scan_prompt([], [], orphan_caveat="")
    assert "indie Unity developer" in prompt


def test_build_asset_scan_prompt_handles_no_broken_scene_references_arg():
    """broken_scene_references is optional -- confirms the default (None)
    doesn't crash the formatter."""
    prompt = build_asset_scan_prompt([], [], orphan_caveat="")
    assert "None found by the local scan" in prompt
