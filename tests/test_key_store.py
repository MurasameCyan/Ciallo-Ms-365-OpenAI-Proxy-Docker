from __future__ import annotations

from m365_copilot_openai_proxy.key_store import KeyStore


def test_key_store_reloads_run_permission(tmp_path):
    path = tmp_path / "keys.json"
    store = KeyStore(path)
    key = store.add(name="Proxy User", username="proxyuser", password="password1")
    store.update(key.id, run_permission="read_only")

    reloaded = KeyStore(path)
    loaded = reloaded.get(key.id)

    assert loaded is not None
    assert loaded.run_permission == "read_only"
