from spiced.core.hardware_simulation import available_tiers, simulate_hardware
from spiced.core.performance_parser import parse_performance_data


def test_available_tiers_non_empty():
    tiers = available_tiers()
    assert "Low-end PC" in tiers
    assert "Handheld (Switch-like)" in tiers


def test_unknown_tier_returns_none():
    parsed = parse_performance_data("Hub: fps=60\n")
    assert simulate_hardware(parsed, "Not a real tier") is None


def test_low_end_pc_flags_at_risk_locations():
    parsed = parse_performance_data("Hub: fps=60\nDungeon: fps=50\n")
    result = simulate_hardware(parsed, "Low-end PC")
    assert result.tier == "Low-end PC"
    # 60 * 0.5 = 30 (not below 30, not at risk); 50 * 0.5 = 25 (at risk)
    at_risk_locations = {s.location for s in result.at_risk_samples}
    assert at_risk_locations == {"Dungeon"}


def test_caveat_is_always_present():
    parsed = parse_performance_data("Hub: fps=60\n")
    result = simulate_hardware(parsed, "Handheld (Switch-like)")
    assert "not a real device test" in result.caveat.lower()


def test_samples_without_fps_are_skipped():
    parsed = parse_performance_data("Hub: memory=200MB\n")
    result = simulate_hardware(parsed, "Mid-range PC")
    assert result.samples == []
