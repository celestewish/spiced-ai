from spiced.core.feedback_classifier import (
    BALANCE,
    BUG,
    CONFUSION,
    FEATURE,
    PERFORMANCE,
    PRAISE,
    PREFERENCE,
    UIUX,
    UNKNOWN,
    classify,
    classify_entry,
)
from spiced.core.feedback_parser import FeedbackEntry


def test_bug_classification():
    assert classify_entry("The game crashed when I opened the pause menu") == BUG


def test_confusion_classification():
    assert classify_entry("I got lost and didn't understand where to go") == CONFUSION


def test_praise_classification():
    assert classify_entry("Absolutely loved the movement, it feels so smooth") == PRAISE


def test_feature_request_classification():
    assert classify_entry("It would be nice if you could add more checkpoints") == FEATURE


def test_preference_classification():
    assert classify_entry("Personally I'd rather the art style was less cartoony") == PREFERENCE


def test_balance_classification():
    assert classify_entry("The enemies are too tanky and take forever to kill") == BALANCE


def test_performance_classification():
    assert classify_entry("The framerate drops and it gets really laggy") == PERFORMANCE


def test_uiux_classification():
    assert classify_entry("The HUD text is too small and hard to read") == UIUX


def test_unknown_when_no_keywords():
    assert classify_entry("I played it yesterday") == UNKNOWN


def test_technical_signal_outranks_subjective_on_tie():
    # Mentions both a bug word and a preference word; the bug should win.
    assert classify_entry("Personally I think it crashed") == BUG


def test_classify_tallies_counts():
    entries = [
        FeedbackEntry(text="it crashed"),
        FeedbackEntry(text="loved it"),
        FeedbackEntry(text="also loved the music"),
    ]
    result = classify(entries)
    assert result.counts[BUG] == 1
    assert result.counts[PRAISE] == 2
    assert result.labels == [BUG, PRAISE, PRAISE]
