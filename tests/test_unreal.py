"""Tests for connectors.unreal.

``TPS_UPROJECT_TEXT`` is a trimmed, faithful reproduction of a real
``.uproject`` file (fetched from ``life-exe/UnrealTPSGame`` on GitHub
during development to verify field names/layout -- see the module's
docstring).
"""

from __future__ import annotations

from spiced.connectors.unreal import detect_unreal_project, find_uproject_file

TPS_UPROJECT_TEXT = """{
	"FileVersion": 3,
	"EngineAssociation": "5.0",
	"Category": "",
	"Description": "",
	"Modules": [
		{
			"Name": "TPS",
			"Type": "Runtime",
			"LoadingPhase": "Default",
			"AdditionalDependencies": [
				"Engine"
			]
		}
	]
}"""


def test_detect_unreal_project_false_for_missing_folder(tmp_path):
    result = detect_unreal_project(tmp_path / "does-not-exist")
    assert result.is_valid is False


def test_detect_unreal_project_false_without_uproject_file(tmp_path):
    result = detect_unreal_project(tmp_path)
    assert result.is_valid is False
    assert ".uproject" in result.warnings[0]


def test_detect_unreal_project_true_and_parses_fields(tmp_path):
    (tmp_path / "TPS.uproject").write_text(TPS_UPROJECT_TEXT, encoding="utf-8")

    result = detect_unreal_project(tmp_path)

    assert result.is_valid is True
    assert result.project_name == "TPS"
    assert result.engine_association == "5.0"
    assert result.warnings == []


def test_detect_unreal_project_metadata_dict(tmp_path):
    (tmp_path / "TPS.uproject").write_text(TPS_UPROJECT_TEXT, encoding="utf-8")

    result = detect_unreal_project(tmp_path)

    assert result.metadata() == {"engine_association": "5.0"}


def test_detect_unreal_project_invalid_for_malformed_json(tmp_path):
    (tmp_path / "TPS.uproject").write_text("{not valid json", encoding="utf-8")

    result = detect_unreal_project(tmp_path)

    assert result.is_valid is False
    assert "valid JSON" in result.warnings[0]


def test_detect_unreal_project_invalid_when_missing_file_version(tmp_path):
    (tmp_path / "TPS.uproject").write_text('{"EngineAssociation": "5.0"}', encoding="utf-8")

    result = detect_unreal_project(tmp_path)

    assert result.is_valid is False
    assert "FileVersion" in result.warnings[0]


def test_detect_unreal_project_invalid_when_multiple_uproject_files(tmp_path):
    (tmp_path / "TPS.uproject").write_text(TPS_UPROJECT_TEXT, encoding="utf-8")
    (tmp_path / "Other.uproject").write_text(TPS_UPROJECT_TEXT, encoding="utf-8")

    result = detect_unreal_project(tmp_path)

    assert result.is_valid is False
    assert "more than one" in result.warnings[0]


def test_find_uproject_file_none_when_missing(tmp_path):
    assert find_uproject_file(tmp_path) is None


def test_find_uproject_file_returns_the_single_match(tmp_path):
    uproject = tmp_path / "TPS.uproject"
    uproject.write_text(TPS_UPROJECT_TEXT, encoding="utf-8")

    assert find_uproject_file(tmp_path) == uproject


def test_find_uproject_file_none_when_multiple_matches(tmp_path):
    (tmp_path / "TPS.uproject").write_text(TPS_UPROJECT_TEXT, encoding="utf-8")
    (tmp_path / "Other.uproject").write_text(TPS_UPROJECT_TEXT, encoding="utf-8")

    assert find_uproject_file(tmp_path) is None
