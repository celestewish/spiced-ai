"""Tests for core.audio_implementation_checklist: script/audio cross-reference,
matched and orphaned cases, built from small fake project trees."""

from __future__ import annotations

import pytest

from spiced.core.audio_implementation_checklist import (
    AudioImplementationChecklistService,
    NoUnityFolderError,
    scan_audio_implementation,
)
from spiced.storage.audio_checklist_reports import AudioChecklistReportRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bytes(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def test_matches_play_one_shot_reference_to_audio_file(tmp_path):
    _write(
        tmp_path / "Assets" / "Scripts" / "ExplosionFx.cs",
        "public class ExplosionFx {\n"
        "    public AudioClip explosionClip;\n"
        "    void Boom() { source.PlayOneShot(explosionClip); }\n"
        "}\n",
    )
    _write_bytes(tmp_path / "Assets" / "Audio" / "explosion.wav")

    scan = scan_audio_implementation(tmp_path)
    matched_vars = {r.variable_name for r in scan.matched_references}
    assert "explosionClip" in matched_vars
    assert scan.unreferenced_audio_files == []


def test_flags_unmatched_script_reference(tmp_path):
    _write(
        tmp_path / "Assets" / "Scripts" / "FootstepSfx.cs",
        "public class FootstepSfx {\n"
        "    public AudioClip footstepGrassClip;\n"
        "    void Play() { source.PlayOneShot(footstepGrassClip); }\n"
        "}\n",
    )
    # No matching audio file present anywhere.
    scan = scan_audio_implementation(tmp_path)
    unmatched_vars = {r.variable_name for r in scan.unmatched_references}
    assert "footstepGrassClip" in unmatched_vars


def test_flags_unreferenced_audio_file(tmp_path):
    _write(
        tmp_path / "Assets" / "Scripts" / "Player.cs",
        "public class Player {\n"
        "    void Jump() { }\n"
        "}\n",
    )
    _write_bytes(tmp_path / "Assets" / "Audio" / "orphaned_music.wav")

    scan = scan_audio_implementation(tmp_path)
    assert "Assets/Audio/orphaned_music.wav" in scan.unreferenced_audio_files


def test_matches_clip_assign_reference(tmp_path):
    _write(
        tmp_path / "Assets" / "Scripts" / "Music.cs",
        "public class Music {\n"
        "    public AudioClip themeClip;\n"
        "    void Setup() { source.clip = themeClip; }\n"
        "}\n",
    )
    _write_bytes(tmp_path / "Assets" / "Audio" / "theme.mp3")

    scan = scan_audio_implementation(tmp_path)
    matched_vars = {r.variable_name for r in scan.matched_references}
    assert "themeClip" in matched_vars


def test_counts_scripts_and_audio_files(tmp_path):
    _write(tmp_path / "Assets" / "Scripts" / "A.cs", "public class A {}\n")
    _write(tmp_path / "Assets" / "Scripts" / "B.cs", "public class B {}\n")
    _write_bytes(tmp_path / "Assets" / "Audio" / "one.wav")
    scan = scan_audio_implementation(tmp_path)
    assert scan.scripts_scanned == 2
    assert scan.audio_files_found == 1


def test_empty_project_returns_empty_scan(tmp_path):
    scan = scan_audio_implementation(tmp_path)
    assert scan.matched_references == []
    assert scan.unmatched_references == []
    assert scan.unreferenced_audio_files == []
    assert scan.scripts_scanned == 0


def test_service_scan_raises_without_project_path():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = AudioImplementationChecklistService(AudioChecklistReportRepository(db))
    with pytest.raises(NoUnityFolderError):
        service.scan(project)


def test_service_scan_saves_a_report(tmp_path):
    _write(
        tmp_path / "Assets" / "Scripts" / "ExplosionFx.cs",
        "public class ExplosionFx {\n"
        "    public AudioClip explosionClip;\n"
        "    void Boom() { source.PlayOneShot(explosionClip); }\n"
        "}\n",
    )
    _write_bytes(tmp_path / "Assets" / "Audio" / "explosion.wav")
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    project = projects.set_unity_folder(project.id, str(tmp_path), "valid")
    service = AudioImplementationChecklistService(AudioChecklistReportRepository(db))

    scan, report = service.scan(project)
    assert scan.scripts_scanned == 1
    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].id == report.id
