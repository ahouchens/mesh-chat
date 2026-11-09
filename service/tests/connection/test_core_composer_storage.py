"""Real transaction faults, expiry and serialized composer writers."""

from concurrent.futures import ThreadPoolExecutor
import time

import pytest

from mesh_chat.core_api.service_composer import STATE, UPDATES
from test_core_messages import host
from test_core_composer import open_composer, query, save, send


def rows(service):
    return service.store._db.execute("SELECT * FROM records ORDER BY kind,record_id").fetchall()


def floor(service):
    return service.store._db.execute("SELECT value FROM meta WHERE name='schema_version'").fetchone()[0]


@pytest.mark.parametrize("operation", ["update", "enqueue"])
@pytest.mark.parametrize("phase", ["seal", "write", "commit"])
def test_mutation_rolls_back_all_rows_and_format_floor(host, monkeypatch, operation, phase):
    service = host()
    client, scope = open_composer(service)
    state = (save(client, scope, "atomic content")["result"]["composer"] if operation == "enqueue"
             else query(client, scope)["result"])
    before, version = rows(service), floor(service)
    store = service.store
    if phase == "seal":
        original = store._seal

        def fail(kind, identifier, value):
            if kind == STATE:
                raise OSError("injected composer seal fault")
            return original(kind, identifier, value)
        monkeypatch.setattr(store, "_seal", fail)
    elif phase == "write":
        original = store._write_records_locked

        def fail(*args):
            original(*args)
            raise OSError("injected composer batch fault")
        monkeypatch.setattr(store, "_write_records_locked", fail)
    else:
        original = store._db

        class FailCommit:
            def execute(self, statement, *args, **kwargs):
                if statement == "COMMIT":
                    raise OSError("injected composer COMMIT fault")
                return original.execute(statement, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(original, name)
        monkeypatch.setattr(store, "_db", FailCommit())
    reply = (send(client, scope, state["revision"]) if operation == "enqueue"
             else save(client, scope, "atomic content", state))
    assert reply["error"]["code"] == "unavailable", reply
    assert rows(service) == before and floor(service) == version
    monkeypatch.setattr(store, {"seal": "_seal", "write": "_write_records_locked", "commit": "_db"}[phase], original)
    retry = (send(client, scope, state["revision"]) if operation == "enqueue"
             else save(client, scope, "atomic content", state))
    assert retry["ok"], retry
    assert floor(service) == "2"


def test_retired_noop_update_key_remains_fenced_after_receipt_pruning(host):
    service = host()
    client, scope = open_composer(service)
    current = save(client, scope, "unchanged")["result"]["composer"]
    assert save(client, scope, "unchanged", current)["ok"]
    for identifier, receipt in service.store.items(UPDATES):
        receipt["expires_at"] = time.time() - 1
        service.store.put(UPDATES, identifier, receipt)
    newest = save(client, scope, "newer")
    assert newest["ok"], newest
    rejected = save(client, scope, "resurrected", current)
    assert rejected["error"]["code"] == "idempotency_expired", rejected
    assert query(client, scope)["result"]["text"] == "newer"


def test_separate_framed_clients_share_one_update_and_acceptance(host):
    service = host()
    first, scope = open_composer(service)
    second, second_scope = open_composer(service)
    initial = query(first, scope)["result"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        saved = list(pool.map(lambda client: save(client, scope, "concurrent", initial), [first, second]))
    assert saved[0] == saved[1] and saved[0]["ok"], saved
    revision = saved[0]["result"]["applied_revision"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = list(pool.map(lambda client: send(client, scope, revision), [first, second]))
    assert accepted[0] == accepted[1] and accepted[0]["ok"], accepted
    assert scope == second_scope and len(service.store.list("message")) == 1


def test_postcommit_lost_enqueue_reply_survives_reopen(host, monkeypatch):
    service = host()
    client, scope = open_composer(service)
    revision = save(client, scope, "lost reply")["result"]["applied_revision"]
    from mesh_chat.core_api.service_messages import ServiceMessages
    original = ServiceMessages._wake_outbox

    def fail(*_):
        raise OSError("injected after commit before reply")
    monkeypatch.setattr(ServiceMessages, "_wake_outbox", fail)
    reply = send(client, scope, revision)
    assert reply["error"]["code"] == "unavailable", reply
    assert len(service.store.list("message")) == 1
    monkeypatch.setattr(ServiceMessages, "_wake_outbox", original)
    service.close()
    reopened = host()
    client, scope = open_composer(reopened)
    assert send(client, scope, revision)["ok"]
    assert query(client, scope)["result"]["text"] == ""
    assert len(reopened.store.list("message")) == 1


def test_history_erasure_retires_draft_and_old_autosave_identity(host):
    service = host()
    client, scope = open_composer(service)
    state = save(client, scope, "erase this draft")["result"]["composer"]
    service.delete_conversation("direct", "internal-peer")
    erased = query(client, scope)["result"]
    assert erased["text"] == "" and erased["revision"] != state["revision"]
    assert save(client, scope, "late autosave", state)["ok"] is False
    assert query(client, scope)["result"]["text"] == ""
