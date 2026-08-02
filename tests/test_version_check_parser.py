from spiced.core.version_check_parser import scan_for_deprecated_apis

CLEAN_SCRIPT = """using UnityEngine;

public class Player : MonoBehaviour
{
    void Update()
    {
        transform.Translate(Vector3.forward * Time.deltaTime);
    }
}
"""

DIRTY_SCRIPT = """using UnityEngine;

public class Player : MonoBehaviour
{
    void Start()
    {
        var enemy = FindObjectOfType<Enemy>();
        rb.velocity = Vector3.zero;
        Application.LoadLevel("NextScene");
        var req = new WWW("http://example.com");
        if (req.isNetworkError) { }
    }
}
"""


def test_clean_script_has_no_hits():
    parsed = scan_for_deprecated_apis(CLEAN_SCRIPT)
    assert parsed.hits == []
    assert parsed.has_hits is False


def test_dirty_script_flags_each_known_deprecation():
    parsed = scan_for_deprecated_apis(DIRTY_SCRIPT)
    api_names = {h.api_name for h in parsed.hits}
    assert "FindObjectOfType / FindObjectsOfType" in api_names
    assert "Rigidbody.velocity" in api_names
    assert "Application.LoadLevel" in api_names
    assert "WWW" in api_names
    assert "UnityWebRequest.isNetworkError / isHttpError" in api_names


def test_hits_carry_line_numbers():
    parsed = scan_for_deprecated_apis(DIRTY_SCRIPT)
    find_object_hit = next(h for h in parsed.hits if h.api_name.startswith("FindObjectOfType"))
    raw_line = DIRTY_SCRIPT.splitlines()[find_object_hit.line_number - 1]
    assert raw_line.strip() == find_object_hit.line_text


def test_summary_dict_matches_hits():
    parsed = scan_for_deprecated_apis(DIRTY_SCRIPT)
    summary = parsed.as_summary_dict()
    assert summary["line_count"] == len(DIRTY_SCRIPT.splitlines())
    assert len(summary["hits"]) == len(parsed.hits)


def test_empty_input_produces_no_hits():
    parsed = scan_for_deprecated_apis("")
    assert parsed.hits == []
