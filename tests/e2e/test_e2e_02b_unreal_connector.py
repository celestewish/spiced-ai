"""E2E §2b -- Unreal Connector.

**Not in E2E_TEST_PLAN.md at all.** The plan scopes itself to six features
(Git, Godot, rules/trigger, billing, RBAC, extensibility-note) and never
mentions Unreal, but a complete Unreal connector exists on the same pending
local commits this plan is meant to gate (``c6ad822``, "Add Unreal
connector: detection, scans, UAT build, Automation tests") with full unit
coverage already (``tests/test_unreal*.py``) and structural parity with the
Godot connector this plan does cover. Added per the discovered-gap decision
in the final report -- mirrors §2's shape (detection, scan, docs) rather
than inventing a new structure, since that's the existing sibling connector
this one was built to match.

One real, documented limitation carried over from the source, not a gap in
this suite: Unreal's ``.uasset``/``.umap`` files are opaque binary, so the
scan only ever reads size/extension for them (see
``connectors.unreal_scan``'s module docstring) -- there is no scene-tree or
broken-reference equivalent to Godot's ``.tscn`` parsing to test here.
"""

from __future__ import annotations

from tests.e2e.conftest import make_unreal_fixture_project

from spiced.connectors.unreal import detect_unreal_project
from spiced.connectors.unreal_docs_scan import scan_headers
from spiced.connectors.unreal_scan import (
    find_loose_uncompressed_source_assets,
    find_oversized_binary_assets,
)


def test_detects_fixture_project_and_reads_metadata(tmp_path):
    project = make_unreal_fixture_project(tmp_path)

    result = detect_unreal_project(project)

    assert result.is_valid is True
    assert result.project_name == "FixtureGame"
    assert result.engine_association == "5.3"
    assert result.warnings == []


def test_rejects_folder_with_no_uproject_file(tmp_path):
    empty = tmp_path / "not-unreal"
    empty.mkdir()
    result = detect_unreal_project(empty)
    assert result.is_valid is False
    assert "uproject" in result.warnings[0]


def test_rejects_folder_with_more_than_one_uproject_file(tmp_path):
    project = make_unreal_fixture_project(tmp_path)
    (project / "Second.uproject").write_text("{}", encoding="utf-8")

    result = detect_unreal_project(project)

    assert result.is_valid is False
    assert "more than one" in result.warnings[0]


def test_oversized_binary_asset_is_flagged_by_size_only_not_parsed(tmp_path):
    project = make_unreal_fixture_project(tmp_path)
    big_uasset = project / "Content" / "Textures" / "Huge.uasset"
    big_uasset.parent.mkdir(parents=True)
    # Sparse write -- well over unreal_scan's 20MB .uasset threshold.
    with open(big_uasset, "wb") as f:
        f.seek(25 * 1024 * 1024 - 1)
        f.write(b"\0")

    findings = find_oversized_binary_assets(project)

    assert len(findings) == 1
    assert findings[0].kind == "uasset"
    assert findings[0].path == "Content/Textures/Huge.uasset"


def test_loose_uncompressed_source_asset_in_content_is_flagged(tmp_path):
    project = make_unreal_fixture_project(tmp_path)
    from PIL import Image

    loose_png = project / "Content" / "raw_source.png"
    Image.new("RGB", (32, 32), (10, 200, 10)).save(loose_png, format="PNG")

    # A 32x32 solid-color PNG is only a few dozen bytes -- nowhere near the
    # real 4MB default threshold. Override it low so the fixture doesn't
    # need a multi-megabyte image just to exercise the "flagged" branch.
    findings = find_loose_uncompressed_source_assets(project, texture_threshold=1)

    assert any(f.path == "Content/raw_source.png" for f in findings)


def test_header_scan_extracts_class_and_doc_comment(tmp_path):
    project = make_unreal_fixture_project(tmp_path)
    header = project / "Source" / "FixtureGame" / "FixturePawn.h"
    header.write_text(
        "#pragma once\n\n"
        "/** Controls the fixture pawn's movement. */\n"
        "class FIXTUREGAME_API AFixturePawn : public APawn\n"
        "{\n"
        "public:\n"
        "\t/** Moves the pawn forward by Amount. */\n"
        "\tvoid MoveForward(float Amount);\n"
        "};\n",
        encoding="utf-8",
    )

    result = scan_headers(project)

    pawn = next(c for c in result.classes if c.name == "AFixturePawn")
    assert pawn.doc_comment == "Controls the fixture pawn's movement."
    assert any(m.name == "MoveForward" for m in pawn.methods)


def test_header_scan_skips_unreadable_file_without_aborting(tmp_path):
    project = make_unreal_fixture_project(tmp_path)
    (project / "Source" / "FixtureGame" / "Broken.h").write_bytes(
        b"\xff\xfe\x00\x80 not real utf-8"
    )

    result = scan_headers(project)  # must not raise

    assert result.file_count >= 1  # the fixture's own Build.cs/headers still get counted
