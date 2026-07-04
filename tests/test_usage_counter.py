from spiced.core.usage_counter import UsageCounter
from spiced.storage.database import Database
from spiced.storage.settings import SettingsRepository
from spiced.storage.usage import UsageRepository


def _counter() -> UsageCounter:
    db = Database(":memory:")
    return UsageCounter(UsageRepository(db), SettingsRepository(db))


def test_default_plan_is_free():
    counter = _counter()
    assert counter.current_plan().key == "free"


def test_records_increment_usage_and_reduce_remaining():
    counter = _counter()
    start = counter.status()
    assert start.used == 0
    assert start.remaining == start.plan.monthly_prompts

    counter.record_prompt("mock")
    counter.record_prompt("mock")
    status = counter.status()
    assert status.used == 2
    assert status.remaining == status.plan.monthly_prompts - 2


def test_studio_plan_is_unlimited():
    counter = _counter()
    counter.set_plan("studio")
    counter.record_prompt("mock")
    status = counter.status()
    assert status.plan.is_unlimited
    assert status.remaining is None
    assert "Unlimited" in status.summary()


def test_remaining_never_negative():
    counter = _counter()
    counter.set_plan("free")
    for _ in range(counter.current_plan().monthly_prompts + 5):
        counter.record_prompt("mock")
    assert counter.status().remaining == 0
