from spiced.core.code_health_analyzer import LONG_FUNCTION_LINES, analyze_code_health

SMALL_SCRIPT = """using UnityEngine;

public class Player : MonoBehaviour
{
    void Start()
    {
        int x = 1;
    }
}
"""


def _long_function(name: str, lines: int) -> str:
    body = "\n".join(f"        int v{i} = {i};" for i in range(lines))
    return f"    public void {name}()\n    {{\n{body}\n    }}\n"


def test_finds_functions_and_line_count():
    metrics = analyze_code_health(SMALL_SCRIPT)
    assert metrics.line_count == len(SMALL_SCRIPT.splitlines())
    assert metrics.function_count == 1
    assert metrics.functions[0].name == "Start"


def test_long_function_is_flagged():
    script = "public class C {\n" + _long_function("Big", LONG_FUNCTION_LINES + 5) + "}\n"
    metrics = analyze_code_health(script)
    assert metrics.longest_functions
    assert metrics.longest_functions[0].name == "Big"
    assert metrics.longest_functions[0].length >= LONG_FUNCTION_LINES


def test_short_function_is_not_flagged_as_long():
    metrics = analyze_code_health(SMALL_SCRIPT)
    assert metrics.longest_functions == []


def test_branch_keywords_are_counted():
    script = """public void Foo() {
    if (a) { }
    else if (b) { }
    for (int i = 0; i < 10; i++) { }
    while (true) { }
    if (a && b) { }
    if (a || b) { }
}
"""
    metrics = analyze_code_health(script)
    assert metrics.branch_count > 0


def test_todo_markers_are_counted():
    script = "// TODO: fix this\n// FIXME: and this\nint x = 1;\n"
    metrics = analyze_code_health(script)
    assert metrics.todo_count == 2


def test_duplicate_blocks_detected():
    block = "int a = 1;\nint b = 2;\nint c = 3;\nint d = 4;\n"
    script = block + "unrelated();\n" + block
    metrics = analyze_code_health(script)
    assert metrics.duplicate_blocks > 0


def test_no_duplicate_blocks_in_unique_code():
    metrics = analyze_code_health(SMALL_SCRIPT)
    assert metrics.duplicate_blocks == 0


def test_average_function_length_none_when_no_functions():
    metrics = analyze_code_health("int x = 1;\n")
    assert metrics.function_count == 0
    assert metrics.average_function_length is None
