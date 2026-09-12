"""Adapters that normalize Godot's GUT and Unreal's Automation test-run
output into the generic ``{"tests": [{"name", "status", "message"}, ...]}``
JSON shape ``core.test_result_parser._try_parse_json`` already understands
natively -- so neither ``test_result_parser.py`` nor ``TestingService.
analyze`` needs any change to handle either engine; only a new ``source_type``
constant is added per engine (see ``core.testing.SOURCE_GODOT_RUN``/
``SOURCE_UNREAL_RUN``).

**Why not teach ``test_result_parser._try_parse_xml`` GUT's shape directly.**
That parser only recognizes NUnit3's ``<test-case result="...">`` tag/
attribute convention. GUT's real ``-gjunit_xml_file`` output is genuine
JUnit XML: the tag is ``<testcase>`` (no hyphen), and pass/fail is signaled
by the *presence* of a child ``<failure>``/``<error>``/``<skipped>`` element,
not a ``result=`` attribute at all -- a different enough shape that widening
the shared parser risked confusing NUnit3 and JUnit inputs. Keeping the
adapter here, feeding the parser's own already-correct JSON path instead,
keeps that risk contained to one small, engine-named function.
"""

from __future__ import annotations

import json
from xml.etree import ElementTree


def godot_junit_to_generic_json(xml_text: str) -> str:
    """Parse GUT's real JUnit ``<testsuite>/<testcase>`` output and re-emit
    it as the generic ``{"tests": [...]}`` shape.

    Never raises -- malformed XML degrades to an empty test list rather than
    breaking the caller, matching every other parser in this codebase's
    "never raises on bad input" convention.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return json.dumps({"tests": []})

    tests: list[dict] = []
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "test")
        full_name = f"{classname}.{name}" if classname else name
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None or error is not None:
            node = failure if failure is not None else error
            message = (node.get("message") or (node.text or "") or "").strip()
            tests.append({"name": full_name, "status": "failed", "message": message})
        elif skipped is not None:
            tests.append({"name": full_name, "status": "skipped", "message": ""})
        else:
            tests.append({"name": full_name, "status": "passed", "message": ""})
    return json.dumps({"tests": tests})


def unreal_report_to_generic_json(report_json: str) -> str:
    """Best-effort adapter over Unreal Automation's ``index.json`` report.

    **Unverified against a real Unreal run** -- ``connectors.
    unreal_test_runner``'s own module docstring says this JSON schema
    hasn't been confirmed against a real Editor install, only checked
    against Epic's documentation; this adapter inherits that same caveat.
    Defensively reads a couple of plausible shapes (a per-test ``"tests"``
    list, or a top-level pass/fail count) and falls back to an empty test
    list -- never raises -- so an unexpected real shape degrades to "0
    results parsed, see the raw log" rather than crashing the UI. Validate
    this against a real Automation run before trusting its output blindly.
    """
    try:
        data = json.loads(report_json)
    except json.JSONDecodeError:
        return json.dumps({"tests": []})

    if isinstance(data, dict) and isinstance(data.get("tests"), list):
        tests: list[dict] = []
        for item in data["tests"]:
            if not isinstance(item, dict):
                continue
            name = str(
                item.get("testDisplayName")
                or item.get("fullTestPath")
                or item.get("name")
                or "test"
            )
            state = str(item.get("state") or item.get("status") or "").lower()
            if state in ("success", "pass", "passed"):
                status = "passed"
            elif state in ("skip", "skipped", "notrun", "not run"):
                status = "skipped"
            else:
                status = "failed"
            tests.append({"name": name, "status": status, "message": ""})
        return json.dumps({"tests": tests})

    if isinstance(data, dict):
        succeeded = data.get("succeeded")
        failed = data.get("failed")
        if isinstance(succeeded, int) or isinstance(failed, int):
            succeeded = succeeded if isinstance(succeeded, int) else 0
            failed = failed if isinstance(failed, int) else 0
            return json.dumps(
                {"passed": succeeded, "failed": failed, "skipped": 0, "total": succeeded + failed}
            )

    return json.dumps({"tests": []})
