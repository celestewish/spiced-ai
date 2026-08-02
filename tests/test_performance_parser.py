from spiced.core.performance_parser import (
    FORMAT_CSV,
    FORMAT_JSON,
    FORMAT_TEXT,
    SEVERITY_NOTABLE,
    SEVERITY_SEVERE,
    parse_performance_data,
)

TEXT_SAMPLE = "Waterfall Area: fps=25, memory=900MB, load=6.5s\nTown: fps=58, memory=400MB\n"


def test_empty_input_is_low_confidence():
    parsed = parse_performance_data("")
    assert parsed.sample_count == 0
    assert parsed.confidence == "low"


def test_text_parses_both_fps_directions():
    parsed = parse_performance_data("Dock — 42fps, 850mb, load 3.2s")
    assert parsed.source_format == FORMAT_TEXT
    sample = parsed.samples[0]
    assert sample.fps == 42.0
    assert sample.memory_mb == 850.0
    assert sample.load_time_s == 3.2


def test_text_key_value_style_also_parses():
    parsed = parse_performance_data(TEXT_SAMPLE)
    assert parsed.sample_count == 2
    waterfall = parsed.samples[0]
    assert waterfall.location == "Waterfall Area"
    assert waterfall.fps == 25.0
    assert waterfall.memory_mb == 900.0
    assert waterfall.load_time_s == 6.5


def test_severe_fps_spike_detected():
    parsed = parse_performance_data(TEXT_SAMPLE)
    fps_spikes = [s for s in parsed.spikes if s.metric == "fps"]
    assert fps_spikes and fps_spikes[0].severity == SEVERITY_SEVERE
    assert fps_spikes[0].location == "Waterfall Area"


def test_long_load_time_is_notable_not_severe_at_6_5s():
    parsed = parse_performance_data(TEXT_SAMPLE)
    load_spikes = [s for s in parsed.spikes if s.metric == "load_time_s"]
    assert load_spikes and load_spikes[0].severity == SEVERITY_NOTABLE


def test_memory_jump_flagged_against_batch_average():
    text = "A: fps=60, memory=200MB\nB: fps=60, memory=210MB\nC: fps=60, memory=900MB\n"
    parsed = parse_performance_data(text)
    memory_spikes = [s for s in parsed.spikes if s.metric == "memory_mb"]
    assert len(memory_spikes) == 1
    assert memory_spikes[0].location == "C"


def test_csv_parses_with_header():
    csv_text = "location,fps,memory_mb,load_time_s\nDungeon,20,700,4\nHub,55,300,1\n"
    parsed = parse_performance_data(csv_text)
    assert parsed.source_format == FORMAT_CSV
    assert parsed.sample_count == 2
    assert parsed.min_fps == 20


def test_json_list_parses():
    import json

    payload = json.dumps(
        [
            {"location": "Boss Arena", "fps": 28, "memory_mb": 600, "load_time_s": 2},
            {"location": "Overworld", "fps": 60},
        ]
    )
    parsed = parse_performance_data(payload)
    assert parsed.source_format == FORMAT_JSON
    assert parsed.sample_count == 2
    assert parsed.avg_fps == 44


def test_json_samples_key_parses():
    import json

    payload = json.dumps({"samples": [{"location": "X", "fps": 30}]})
    parsed = parse_performance_data(payload)
    assert parsed.sample_count == 1


def test_no_spikes_when_all_healthy():
    parsed = parse_performance_data("Hub: fps=60, memory=200MB, load=1.0s\n")
    assert parsed.spikes == []
