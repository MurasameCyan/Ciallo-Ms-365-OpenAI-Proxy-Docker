"""Per-user override for the tool planning mode.

The setting compensates for a property of the tone (whether it honours the inline
tool contract) and the extra router turn is billed to the key's own account, so
"global template + per-user override" is the only layering that matches who is
affected. Kept a plain override rather than run_permission's admin ceiling: the
choice has no safety dimension -- worst case is spending more upstream turns, and
rate_limit_rpm / the per-account round cap already bound that.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.key_store import ApiKey
from m365_copilot_openai_proxy.routes_api_common import effective_tool_planning_mode
from m365_copilot_openai_proxy.templates import _USER_HTML

# Measured "unsupported" in TONE_TOOL_CALLING, so its reported status is the one
# that changes with the planning mode.
UNSUPPORTED_MODEL = "Copilot_自动"


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))


@pytest.fixture
def user_client(app):
    account = app.state.account_store.add(name="Test User")
    key = app.state.key_store.add(name="Test Key", account_id=account.id)
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {key.key}"
    return client, key


def test_empty_value_inherits_the_global_template(app):
    app.state.tool_planning_mode = "router"

    assert effective_tool_planning_mode(app, None) == "router"
    assert effective_tool_planning_mode(app, ApiKey(tool_planning_mode="")) == "router"


def test_key_value_wins_over_the_global_template(app):
    app.state.tool_planning_mode = "native"

    assert effective_tool_planning_mode(app, ApiKey(tool_planning_mode="router")) == "router"
    assert effective_tool_planning_mode(app, ApiKey(tool_planning_mode="auto")) == "auto"


def test_unrecognized_stored_value_falls_back_to_the_global_template(app):
    # A hand-edited keys.json must not silently turn into "auto" when the operator
    # picked something else globally.
    app.state.tool_planning_mode = "router"

    assert effective_tool_planning_mode(app, ApiKey(tool_planning_mode="Router ")) == "router"
    assert effective_tool_planning_mode(app, ApiKey(tool_planning_mode="nonsense")) == "router"


def test_user_me_reports_the_override_and_what_it_would_inherit(app, user_client):
    client, key = user_client
    app.state.tool_planning_mode = "native"

    body = client.get("/user/me").json()

    assert body["tool_planning_mode"] == ""
    assert body["default_tool_planning_mode"] == "native"

    app.state.key_store.update(key.id, tool_planning_mode="router")

    assert client.get("/user/me").json()["tool_planning_mode"] == "router"


def test_user_tone_persists_the_override_and_rejects_garbage(app, user_client):
    client, key = user_client

    saved = client.post("/user/tone", json={"tone": "Magic", "tool_planning_mode": "router"})

    assert saved.status_code == 200
    assert saved.json()["tool_planning_mode"] == "router"
    assert app.state.key_store.get(key.id).tool_planning_mode == "router"

    rejected = client.post("/user/tone", json={"tone": "Magic", "tool_planning_mode": "turbo"})

    assert rejected.status_code == 400
    assert app.state.key_store.get(key.id).tool_planning_mode == "router"

    cleared = client.post("/user/tone", json={"tone": "Magic", "tool_planning_mode": ""})

    assert cleared.status_code == 200
    assert app.state.key_store.get(key.id).tool_planning_mode == ""


def test_a_save_that_omits_the_field_keeps_the_stored_override(app, user_client):
    # /user has other forms POSTing to this endpoint; none of them may reset it.
    client, key = user_client
    app.state.key_store.update(key.id, tool_planning_mode="native")

    client.post("/user/tone", json={"tone": "Magic"})

    assert app.state.key_store.get(key.id).tool_planning_mode == "native"


def test_the_override_survives_a_restart(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))
    key = app.state.key_store.add(name="Test Key")
    app.state.key_store.update(key.id, tool_planning_mode="router")

    reloaded = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    assert reloaded.state.key_store.get(key.id).tool_planning_mode == "router"


def test_models_list_reports_the_status_this_key_will_actually_get(app):
    # The read site clients gate on: with the global set to native, an unsupported
    # tone reports unsupported -- unless this key routes, in which case tools do
    # work for it and saying otherwise makes the client withhold them.
    key = app.state.key_store.add(name="Unbound Key")
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {key.key}"
    app.state.tool_planning_mode = "native"

    entry = _model_entry(client.get("/v1/models").json())

    assert entry["tool_calling"] == "unsupported"
    assert entry["capabilities"]["tools"] is False

    app.state.key_store.update(key.id, tool_planning_mode="router")
    entry = _model_entry(client.get("/v1/models").json())

    assert entry["tool_calling"] == "router"
    assert entry["capabilities"]["tools"] is True


def _model_entry(payload: dict) -> dict:
    for item in payload["data"]:
        if item["id"] == UNSUPPORTED_MODEL:
            return item
    raise AssertionError(f"{UNSUPPORTED_MODEL} missing from {[i['id'] for i in payload['data']]}")


def test_no_per_turn_read_site_resolves_the_mode_from_the_global_alone():
    # Three sites decide a turn's planning: /v1/models, the OpenAI chat route and
    # the Anthropic messages route. Any of them reading app.state directly hands
    # that user the global answer and quietly ignores their override.
    import inspect

    from m365_copilot_openai_proxy import routes_admin_settings, routes_api_chat, routes_api_messages

    for module in (routes_api_chat, routes_api_messages):
        source = inspect.getsource(module)
        assert 'app.state, "tool_planning_mode"' not in source, (
            f"{module.__name__} reads the global planning mode past the key"
        )
        assert "effective_tool_planning_mode(app" in source
    # The admin tone matrix stays global on purpose: it describes the template, not
    # any one user's key.
    assert 'app.state, "tool_planning_mode"' in inspect.getsource(routes_admin_settings)


def test_user_page_offers_the_override_with_the_admin_wording(app):
    field = _user_field(_USER_HTML, "user-tool-planning")

    assert 'data-i18n="tool_planning_label"' in field
    assert 'class="field-tip"' in field, "the three modes have nowhere to be explained"
    for mode in ("auto", "native", "router"):
        assert f'<b data-i18n="tool_planning_{mode}">' in field
        assert f'data-i18n="tool_planning_hint_{mode}"' in field
    # Same copy as /admin, in both languages, so the two pages cannot drift.
    for key in ("tool_planning_label", "tool_planning_inherit", "tool_planning_hint_auto"):
        assert len(re.findall(rf"{key}:'([^']*)'", _USER_HTML)) == 2, f"{key} lacks zh+en"


def test_user_page_can_express_inheriting_the_global(app):
    # An empty value is the inherit choice, and the tip names the global it
    # resolves to -- /user is the only place a user can see that value at all.
    assert "tool_planning_inherit" in _USER_HTML
    assert "_defaultToolPlanning" in _USER_HTML
    assert re.search(r"<option value=\"\">'\+t\('tool_planning_inherit'\)\+'</option>'", _USER_HTML), (
        "the inherit label carries more than its own name again -- spelled out in "
        "the option it wrapped out of the 180px trigger"
    )
    assert 'id="user-tool-planning-default"' in _USER_HTML
    assert "tool_planning_mode:tool_planning_mode" in _USER_HTML, (
        "saveTone stopped sending the field, so the picker would be decorative"
    )


def test_the_tip_bubble_has_a_containing_block_and_is_not_clipped(app):
    # The bubble is absolutely positioned against its grid cell; without
    # position:relative on the cell it escapes to the nearest positioned ancestor.
    assert re.search(r"\.user-config-field\{[^}]*position:relative", _USER_HTML)
    assert ".card:has(.field-tip:hover)" in _USER_HTML
    # The English ellipsis rule must not apply to the label row: display:block
    # collapses it and overflow:hidden erases the bubble.
    assert 'body[data-lang="en"] .user-config-field>span:not(.field-row)' in _USER_HTML
    assert 'body[data-lang="en"] .field-row>span:not(.field-tip)' in _USER_HTML


def _user_field(html: str, control_id: str) -> str:
    marker = '<label class="user-config-field"'
    for chunk in html.split(marker):
        if f'id="{control_id}"' in chunk:
            return marker + chunk.split("</label>")[0]
    raise AssertionError(f"#{control_id} is not inside a .user-config-field")
