from spiced.core.unity_log_parser import (
    CATEGORY_COMPILER,
    CATEGORY_EXCEPTION,
    parse_unity_log,
)

# The exact manual scenario from the Phase 1 spec.
NULL_REF_LOG = """NullReferenceException: Object reference not set to an instance of an object
HealthPickup.OnTriggerEnter2D (UnityEngine.Collider2D other) (at Assets/Scripts/HealthPickup.cs:24)
"""


def test_null_reference_exception():
    parsed = parse_unity_log(NULL_REF_LOG)
    assert parsed.has_errors
    primary = parsed.primary
    assert primary.category == CATEGORY_EXCEPTION
    assert primary.error_type == "NullReferenceException"
    assert primary.script == "HealthPickup.cs"
    assert primary.line == 24
    assert "Assets/Scripts/HealthPickup.cs" in (primary.file or "")


def test_missing_reference_exception():
    log = (
        "MissingReferenceException: The object of type 'Rigidbody2D' has been destroyed "
        "but you are still trying to access it.\n"
        "Player.Update () (at Assets/Scripts/Player.cs:42)\n"
    )
    parsed = parse_unity_log(log)
    assert parsed.primary.error_type == "MissingReferenceException"
    assert parsed.primary.script == "Player.cs"
    assert parsed.primary.line == 42


def test_compiler_error():
    log = "Assets/Scripts/Player.cs(12,20): error CS0103: The name 'speed' does not exist"
    parsed = parse_unity_log(log)
    primary = parsed.primary
    assert primary.category == CATEGORY_COMPILER
    assert primary.error_type == "CS0103"
    assert primary.script == "Player.cs"
    assert primary.line == 12


def test_repeated_errors_grouped():
    line = (
        "NullReferenceException: Object reference not set to an instance of an object\n"
        "Enemy.Update () (at Assets/Scripts/Enemy.cs:10)\n\n"
    )
    parsed = parse_unity_log(line * 3)
    assert len(parsed.errors) == 1
    assert parsed.errors[0].count == 3


def test_prefers_assets_frame_over_engine_frame():
    log = (
        "NullReferenceException: Object reference not set to an instance of an object\n"
        "UnityEngine.GameObject.Foo () (at /build/UnityEngine/Core.cs:99)\n"
        "Boss.Attack () (at Assets/Scripts/Boss.cs:7)\n\n"
    )
    parsed = parse_unity_log(log)
    assert parsed.primary.script == "Boss.cs"
    assert parsed.primary.line == 7


def test_no_errors_returns_empty():
    parsed = parse_unity_log("Everything compiled fine.\nAll good.")
    assert not parsed.has_errors
    assert parsed.primary is None


def test_excerpt_is_capped():
    huge = "NullReferenceException: boom\n" + ("frame line here\n" * 5000)
    parsed = parse_unity_log(huge)
    assert len(parsed.excerpt) <= 2100  # cap + truncation note
