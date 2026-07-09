from spiced.core.feedback_parser import (
    CONFIDENCE_HIGH,
    FORMAT_CSV,
    FORMAT_JSON,
    FORMAT_MARKDOWN,
    FORMAT_TEXT,
    MAX_ENTRIES,
    MAX_EXCERPT_CHARS,
    parse_feedback,
)


def test_plain_text_one_entry_per_line():
    parsed = parse_feedback("The dash feels great.\nI got lost after the first room.\n")
    assert parsed.source_format == FORMAT_TEXT
    assert parsed.entry_count == 2
    assert parsed.entries[0].text == "The dash feels great."


def test_text_splits_speaker_label():
    parsed = parse_feedback("Playtester 1: the boss is too tanky\n")
    assert parsed.entries[0].author == "Playtester 1"
    assert parsed.entries[0].text == "the boss is too tanky"


def test_markdown_strips_bullets_and_skips_headings():
    md = "# Playtest notes\n\n- Loved the music\n- Confused by the map\n"
    parsed = parse_feedback(md, filename="notes.md")
    assert parsed.source_format == FORMAT_MARKDOWN
    assert parsed.entry_count == 2
    assert parsed.entries[0].text == "Loved the music"


def test_csv_with_header_detects_fields_and_high_confidence():
    csv_text = "author,comment,rating\nAlex,The pause menu is broken,2\nSam,Great movement,5\n"
    parsed = parse_feedback(csv_text, filename="feedback.csv")
    assert parsed.source_format == FORMAT_CSV
    assert parsed.entry_count == 2
    assert parsed.confidence == CONFIDENCE_HIGH
    assert "comment" in parsed.detected_fields
    assert parsed.entries[0].author == "Alex"
    assert parsed.entries[0].rating == "2"


def test_json_array_of_objects():
    data = '[{"author": "Kim", "comment": "Enemies are bullet sponges"}, '
    data += '{"author": "Lee", "comment": "Music is fantastic"}]'
    parsed = parse_feedback(data, filename="reviews.json")
    assert parsed.source_format == FORMAT_JSON
    assert parsed.entry_count == 2
    assert parsed.entries[0].text == "Enemies are bullet sponges"
    assert parsed.entries[0].author == "Kim"


def test_json_array_of_strings():
    parsed = parse_feedback('["fun game", "too hard"]')
    assert parsed.source_format == FORMAT_JSON
    assert parsed.entry_count == 2


def test_json_dict_with_feedback_key():
    parsed = parse_feedback('{"feedback": [{"text": "loved it"}, {"text": "laggy"}]}')
    assert parsed.source_format == FORMAT_JSON
    assert parsed.entry_count == 2


def test_empty_input_is_low_confidence_zero_entries():
    parsed = parse_feedback("   \n  ")
    assert parsed.entry_count == 0
    assert not parsed.has_entries


def test_excerpt_is_capped():
    long_line = "x" * (MAX_EXCERPT_CHARS + 500)
    parsed = parse_feedback(long_line)
    assert len(parsed.excerpt) <= MAX_EXCERPT_CHARS + len("\n… (truncated)")
    assert parsed.excerpt.endswith("… (truncated)")


def test_entry_count_is_capped():
    many = "\n".join(f"comment {i}" for i in range(MAX_ENTRIES + 50))
    parsed = parse_feedback(many)
    assert parsed.entry_count == MAX_ENTRIES


def test_prose_with_commas_is_not_treated_as_csv():
    prose = "I loved the movement, especially the dash.\nThe music, though, was too loud.\n"
    parsed = parse_feedback(prose)
    assert parsed.source_format == FORMAT_TEXT
