"""Project use-cases exposed to the UI."""

from __future__ import annotations

import uuid

from spiced.connectors.unity import UnityDetectionResult, detect_unity_project
from spiced.storage.projects import Project, ProjectRepository


class ProjectsService:
    def __init__(self, repo: ProjectRepository) -> None:
        self._repo = repo

    def create_project(
        self,
        name: str,
        engine: str = "Unity",
        path: str | None = None,
        description: str | None = None,
    ) -> Project:
        return self._repo.create(name=name, engine=engine, path=path, description=description)

    def list_projects(self) -> list[Project]:
        return self._repo.list_all()

    def get_project(self, project_id: int) -> Project:
        return self._repo.get(project_id)

    def attach_unity_folder(
        self, project_id: int, folder: str
    ) -> tuple[Project, UnityDetectionResult]:
        """Validate a Unity folder and store its path, status, and metadata.

        The result is stored whether or not the folder is valid, so the UI can
        show a friendly warning while still remembering the developer's choice.
        """
        detection = detect_unity_project(folder)
        project = self._repo.set_unity_folder(
            project_id,
            path=str(folder),
            validation_status=detection.validation_status,
            metadata=detection.metadata() or None,
        )
        return project, detection

    def set_unity_test_run_settings(
        self, project_id: int, enabled: bool, editor_path_override: str | None = None
    ) -> Project:
        """Opt a project in/out of Spiced launching its Unity Editor to run tests.

        Off by default. This is the one place Spiced executes an external
        engine process rather than just parsing text — everything else stays
        paste/import only.
        """
        return self._repo.set_unity_test_run_settings(project_id, enabled, editor_path_override)

    def set_build_pipeline_settings(
        self, project_id: int, enabled: bool, target_platform: str | None = None
    ) -> Project:
        """Opt a project in/out of Spiced writing/triggering its build script.

        Off by default, same opt-in shape as ``set_unity_test_run_settings``.
        Only when enabled does Spiced ever write a build script into the
        project or launch a headless build for it.
        """
        return self._repo.set_build_pipeline_settings(project_id, enabled, target_platform)

    def set_build_schedule(
        self, project_id: int, enabled: bool, schedule_time: str | None = None
    ) -> Project:
        """Set the in-app-only nightly build schedule ("HH:MM", 24h local time).

        Only ever checked by a QTimer while Spiced is running — never
        registers anything with the OS scheduler.
        """
        return self._repo.set_build_schedule(project_id, enabled, schedule_time)

    def set_precommit_review_settings(self, project_id: int, enabled: bool) -> Project:
        """Opt a project in/out of Spiced installing a .git/hooks/pre-commit script.

        Off by default, same opt-in shape as the other per-project toggles.
        This alone never touches the filesystem — see
        ``core.precommit_hook.install_hook`` for the actual install step,
        which the Projects screen calls separately once this is on.
        """
        return self._repo.set_precommit_review_settings(project_id, enabled)

    def set_design_doc_sync_settings(self, project_id: int, enabled: bool) -> Project:
        """Opt a project in/out of Design Doc Sync.

        Off by default, same opt-in shape as the other per-project toggles.
        """
        return self._repo.set_design_doc_sync_settings(project_id, enabled)

    def set_git_integration_settings(self, project_id: int, enabled: bool) -> Project:
        """Opt a project in/out of the Version Control connector.

        Off by default, same opt-in shape as the other per-project toggles.
        This alone never touches the filesystem — see
        ``core.git_integration`` for the gated read/write operations, which
        the Projects screen calls separately once this is on.
        """
        return self._repo.set_git_integration_settings(project_id, enabled)

    def set_loudness_normalize_target(
        self, project_id: int, target_lufs: float | None
    ) -> Project:
        """Set (or clear, with None) this project's EBU R128 loudness target
        (SPICED_IMPLEMENTATION_BIBLE.md, Feature 1). NULL falls back to
        ``automation.loudness_normalize.DEFAULT_TARGET_LUFS``.
        """
        return self._repo.set_loudness_normalize_target(project_id, target_lufs)

    def set_asset_qa_settings(
        self, project_id: int, naming_pattern: str | None, pivot_tolerance: float | None
    ) -> Project:
        """Set this project's Asset Technical QA Scan naming-convention regex
        and pivot-offset tolerance (SPICED_IMPLEMENTATION_BIBLE.md, Feature 3).
        NULL falls back to ``automation.asset_technical_qa``'s defaults.
        """
        return self._repo.set_asset_qa_settings(project_id, naming_pattern, pivot_tolerance)

    def set_palette_drift_threshold(self, project_id: int, threshold: float | None) -> Project:
        """Set (or clear, with None) this project's palette-drift Delta-E
        flag threshold (SPICED_IMPLEMENTATION_BIBLE.md, Feature 4). NULL
        falls back to ``automation.palette_drift.DEFAULT_DELTA_E_THRESHOLD``.
        """
        return self._repo.set_palette_drift_threshold(project_id, threshold)

    def set_mix_qa_silence_ms(self, project_id: int, silence_ms: float | None) -> Project:
        """Set (or clear, with None) this project's Mix Technical QA
        minimum-silent-region threshold in ms (SPICED_IMPLEMENTATION_BIBLE.md,
        Feature 5). NULL falls back to
        ``automation.mix_technical_qa.DEFAULT_SILENCE_MS``.
        """
        return self._repo.set_mix_qa_silence_ms(project_id, silence_ms)

    def set_shader_variant_threshold(self, project_id: int, threshold: int | None) -> Project:
        """Set (or clear, with None) this project's shader variant-count
        flag threshold (SPICED_IMPLEMENTATION_BIBLE.md, Feature 6). NULL
        falls back to
        ``automation.shader_variant_analysis.DEFAULT_VARIANT_THRESHOLD``.
        """
        return self._repo.set_shader_variant_threshold(project_id, threshold)

    def set_retarget_alias_prefixes(
        self, project_id: int, alias_prefixes: str | None
    ) -> Project:
        """Set (or clear, with None) this project's comma-separated retarget
        bone-name alias prefixes (SPICED_IMPLEMENTATION_BIBLE.md, Feature 7).
        NULL falls back to
        ``automation.state_machine_validation.DEFAULT_ALIAS_PREFIXES``.
        """
        return self._repo.set_retarget_alias_prefixes(project_id, alias_prefixes)

    def set_gpu_shader_profiling_settings(
        self, project_id: int, budget_ms: float | None, tier: str | None
    ) -> Project:
        """Set this project's GPU shader-profiling per-shader budget and
        default target hardware tier (SPICED_IMPLEMENTATION_BIBLE.md,
        Feature 9). NULL budget falls back to
        ``automation.gpu_shader_profiling.tier_budget_ms``.
        """
        return self._repo.set_gpu_shader_profiling_settings(project_id, budget_ms, tier)

    def ensure_project_uuid(self, project_id: int) -> str:
        """Return this project's stable cross-machine id, minting one on first use.

        Solo-Dev projects never call this — it only runs the first time a
        project is linked to a Small-Team Mode team, so purely local projects
        never gain a project_uuid.
        """
        project = self._repo.get(project_id)
        if project.project_uuid:
            return project.project_uuid
        new_uuid = str(uuid.uuid4())
        self._repo.set_project_uuid(project_id, new_uuid)
        return new_uuid
