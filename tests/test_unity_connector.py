from pathlib import Path

from spiced.connectors.unity import detect_unity_project, read_manifest_dependencies


def _make_unity_project(root: Path, *, with_manifest=False, version=None) -> Path:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()
    if version:
        (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
            f"m_EditorVersion: {version}\n", encoding="utf-8"
        )
    if with_manifest:
        (root / "Packages").mkdir()
        (root / "Packages" / "manifest.json").write_text(
            '{"dependencies": {"com.unity.inputsystem": "1.7.0", "com.unity.ugui": "1.0.0"}}',
            encoding="utf-8",
        )
    return root


def test_valid_unity_folder(tmp_path):
    _make_unity_project(tmp_path, version="2022.3.10f1")
    result = detect_unity_project(tmp_path)
    assert result.is_valid
    assert result.validation_status == "valid"
    assert result.unity_version == "2022.3.10f1"
    assert result.warnings == []


def test_invalid_folder_missing_dirs(tmp_path):
    (tmp_path / "Assets").mkdir()  # ProjectSettings missing
    result = detect_unity_project(tmp_path)
    assert not result.is_valid
    assert result.validation_status == "invalid"
    assert any("ProjectSettings" in w for w in result.warnings)


def test_nonexistent_path(tmp_path):
    result = detect_unity_project(tmp_path / "does-not-exist")
    assert not result.is_valid
    assert result.warnings


def test_manifest_detection(tmp_path):
    _make_unity_project(tmp_path, with_manifest=True)
    result = detect_unity_project(tmp_path)
    assert result.is_valid
    assert result.manifest_path is not None
    assert result.metadata()["manifest_path"].endswith("manifest.json")

    deps = read_manifest_dependencies(result.manifest_path)
    assert "com.unity.inputsystem" in deps


def test_read_manifest_bad_json_returns_empty(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert read_manifest_dependencies(bad) == []
