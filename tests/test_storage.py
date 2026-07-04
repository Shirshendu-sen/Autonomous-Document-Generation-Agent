"""
tests/test_storage.py
-----------------------
Covers Step 10: the minimal in-memory request_id -> record registry.
"""
from app import storage


def test_get_returns_none_for_unknown_id():
    assert storage.get("does-not-exist") is None


def test_save_then_get_round_trips_the_record():
    record = {"path": "/tmp/x.docx", "plan": {"title": "X"}, "reflection_log": []}
    storage.save("req-a", record)
    assert storage.get("req-a") == record


def test_save_overwrites_existing_record_for_same_id():
    storage.save("req-b", {"path": "/tmp/first.docx", "plan": {}, "reflection_log": []})
    storage.save("req-b", {"path": "/tmp/second.docx", "plan": {}, "reflection_log": []})
    assert storage.get("req-b")["path"] == "/tmp/second.docx"


def test_different_ids_do_not_collide():
    storage.save("req-c", {"path": "/tmp/c.docx", "plan": {}, "reflection_log": []})
    storage.save("req-d", {"path": "/tmp/d.docx", "plan": {}, "reflection_log": []})
    assert storage.get("req-c")["path"] == "/tmp/c.docx"
    assert storage.get("req-d")["path"] == "/tmp/d.docx"
