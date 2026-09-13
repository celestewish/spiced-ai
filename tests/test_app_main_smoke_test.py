"""spiced.app.main's --smoke-test flag (Connect-a-Project Setup
Simplification spec, Finding 3 fix 8).

Constructs the real app -- Services, MainWindow, every screen -- then exits
without ever calling .show()/.exec(). Meant to run against a *built*
installer in CI (.github/workflows/release.yml, packaging/README.md) to
catch a PyInstaller bundling gap before a user does; this test covers the
flag's own wiring against a source checkout, where that's fast and doesn't
need a real build.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from spiced.app import main as main_module  # noqa: E402
from spiced.ui.effects import motion  # noqa: E402


def test_smoke_test_flag_constructs_app_and_exits_zero(tmp_path, monkeypatch, capsys):
    # main() hard-codes Services() with no db_path -- redirect the default
    # so this test never touches the real user's ~/.spiced/spiced.db.
    monkeypatch.setattr(
        "spiced.storage.database.default_db_path", lambda: tmp_path / "spiced.db"
    )
    # _load_env() calls python-dotenv's load_dotenv(), which reads the repo
    # root's real .env (if present -- e.g. a developer's own OPENAI_API_KEY
    # or Team Mode SUPABASE_* config) and sets it directly into os.environ,
    # a process-wide, test-session-wide side effect nothing here reverts.
    # A real .env's Supabase config leaking in was enough to flip
    # test_backend_client_auth.py's "not configured" assertions when this
    # test ran earlier in the same pytest session. main() itself needs
    # this call for real usage; this test's job is exercising --smoke-test,
    # not env-loading, so it's a no-op here.
    monkeypatch.setattr("spiced.app.main._load_env", lambda: None)

    try:
        code = main_module.main(["spiced", "--smoke-test"])

        assert code == 0
        assert "Spiced smoke test OK" in capsys.readouterr().out
    finally:
        # MainWindow.__init__ registers this test's (now-closed) Services
        # instance as ui.effects.motion's global "active services" --
        # otherwise a later test's PillButton.set_loading() would hit a
        # closed-database error reading this instance's accessibility
        # settings. Not this test's own state to leave behind.
        motion.set_active_services(None)
