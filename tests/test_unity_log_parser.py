from spiced.core.unity_log_parser import (
    CATEGORY_COMPILER,
    CATEGORY_EXCEPTION,
    LEADING_CONTEXT_LINES,
    leading_context,
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


# --- first_error_line_index / leading_context (Unity Alpha Readiness Spec,
# Priority 3b) --------------------------------------------------------------


def test_first_error_line_index_is_none_without_errors():
    parsed = parse_unity_log("Everything compiled fine.\nAll good.")
    assert parsed.first_error_line_index is None


def test_first_error_line_index_points_at_the_exception_header():
    log = (
        "Loading scene DungeonLevel1\n"
        "Player spawned at (0, 1, 0)\n"
        "NullReferenceException: Object reference not set to an instance of an object\n"
        "HealthPickup.OnTriggerEnter2D () (at Assets/Scripts/HealthPickup.cs:24)\n"
    )
    parsed = parse_unity_log(log)
    assert parsed.first_error_line_index == 2  # 0-indexed: the exception header line


def test_first_error_line_index_points_at_the_compiler_error_line():
    log = (
        "Compiling...\n"
        "Assets/Scripts/Player.cs(12,20): error CS0103: The name 'speed' does not exist\n"
    )
    parsed = parse_unity_log(log)
    assert parsed.first_error_line_index == 1


def test_first_error_line_index_is_the_first_of_several_errors():
    log = (
        "line 0\n"
        "NullReferenceException: boom\n"  # line 1 -- first error
        "Foo.Bar () (at Assets/Scripts/Foo.cs:1)\n\n"
        "MissingReferenceException: also boom\n"  # a second, later error
        "Baz.Qux () (at Assets/Scripts/Baz.cs:2)\n\n"
    )
    parsed = parse_unity_log(log)
    assert parsed.first_error_line_index == 1


def test_leading_context_returns_preceding_nonblank_lines_verbatim():
    text = (
        "Loading scene DungeonLevel1\n\nPlayer spawned at (0, 1, 0)\n"
        "NullReferenceException: boom\n"
    )
    # The error header is line index 3.
    assert leading_context(text, 3) == [
        "Loading scene DungeonLevel1",
        "Player spawned at (0, 1, 0)",
    ]


def test_leading_context_is_capped_at_leading_context_lines():
    lines = [f"log line {i}" for i in range(20)]
    text = "\n".join(lines) + "\nNullReferenceException: boom\n"
    context = leading_context(text, 20)  # error header is line index 20
    assert len(context) == LEADING_CONTEXT_LINES
    assert context == lines[20 - LEADING_CONTEXT_LINES : 20]


def test_leading_context_clamps_at_the_start_of_the_file():
    text = "line a\nline b\nNullReferenceException: boom\n"
    assert leading_context(text, 2) == ["line a", "line b"]


def test_leading_context_at_index_zero_is_empty():
    text = "NullReferenceException: boom\n"
    assert leading_context(text, 0) == []
