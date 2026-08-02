"""Curated table of deprecated/obsolete Unity C# APIs.

Kept intentionally small and factual: every entry is an API Unity itself has
marked ``[Obsolete]`` or removed, with the version that happened. This is not
an exhaustive or live-updated list — new deprecations won't appear here until
someone adds them — so Version-Aware Suggestions should always be read as "at
least these known ones," not a complete audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DeprecatedApiRule:
    pattern: re.Pattern
    api_name: str
    replacement: str
    reason: str
    deprecated_in: str


DEPRECATED_API_RULES: tuple[DeprecatedApiRule, ...] = (
    DeprecatedApiRule(
        re.compile(r"\bnew\s+WWW\s*\(|\bWWW\s+\w+\s*="),
        "WWW",
        "UnityWebRequest",
        "WWW has been obsolete since Unity 2018; UnityWebRequest has better error handling "
        "and async-friendly coroutines.",
        "2018.x",
    ),
    DeprecatedApiRule(
        re.compile(r"Application\.LoadLevel(Async)?\s*\("),
        "Application.LoadLevel",
        "SceneManager.LoadScene / LoadSceneAsync",
        "Application.LoadLevel was removed in favor of UnityEngine.SceneManagement.SceneManager, "
        "which supports additive scene loading.",
        "5.3",
    ),
    DeprecatedApiRule(
        re.compile(r"\bFindObjectOfType\s*<|\bFindObjectsOfType\s*<"),
        "FindObjectOfType / FindObjectsOfType",
        "FindFirstObjectByType / FindObjectsByType",
        "Marked obsolete in Unity 2023.1 — the replacements are explicit about sort order and "
        "are faster by default.",
        "2023.1",
    ),
    DeprecatedApiRule(
        re.compile(r"\.velocity\b(?!\w)"),
        "Rigidbody.velocity",
        "Rigidbody.linearVelocity",
        "Renamed in Unity 6 to disambiguate from angularVelocity naming; the old name still "
        "compiles but is marked obsolete.",
        "6000.0",
    ),
    DeprecatedApiRule(
        re.compile(r"\.isNetworkError\b|\.isHttpError\b"),
        "UnityWebRequest.isNetworkError / isHttpError",
        "UnityWebRequest.result",
        "Obsolete since 2020.1 — result is a single enum covering every outcome instead of two "
        "overlapping bools.",
        "2020.1",
    ),
)
