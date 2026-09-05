from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from m365_copilot_openai_proxy.app import create_app
from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.routes_admin_debug import register_admin_debug_routes


def _jwt(tid: str, oid: str = "object-a") -> str:
    claims = {
        "aud": "https://substrate.office.com/",
        "exp": int(time.time()) + 3600,
        "tid": tid,
        "oid": oid,
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def test_admin_capture_payload_returns_version_and_short_circuits_unchanged_payload(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    app.state.capture_enabled = True
    client = TestClient(app)

    initial = client.get("/admin/capture-payload").json()
    assert initial["version"] == 0
    assert initial["payloads"] == []

    pushed = client.post("/admin/capture-payload", json={"payloads": [{"time": "12:00:00", "tone": "Magic"}]})
    assert pushed.status_code == 200

    changed = client.get("/admin/capture-payload?version=0").json()
    assert changed["version"] > 0
    assert changed["count"] == 1
    assert changed["payloads"] == [{"time": "12:00:00", "tone": "Magic"}]

    unchanged = client.get(f"/admin/capture-payload?version={changed['version']}").json()
    assert unchanged == {
        "version": changed["version"],
        "unchanged": True,
        "count": 1,
        "payloads": [],
    }


def test_admin_debug_routes_are_registered_by_debug_routes_module(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="admin-key"))

    paths = {route.path for route in app.routes}

    assert callable(register_admin_debug_routes)
    assert "/admin/stats" in paths
    assert "/admin/capture-payload" in paths
    assert "/admin/capture-payload/clear" in paths
    assert "/admin/capture-toggle" in paths


def test_admin_stats_reports_what_the_caches_are_buying(tmp_path):
    """`incremental` is the number that says whether session reuse works."""
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    now = time.time()
    app.state.call_log = [
        {"ts": now, "incremental": True},
        {"ts": now, "incremental": True},
        {"ts": now, "incremental": False},
        {"ts": now},  # entries with no flag (errors, non-chat) must not count
    ]
    app.state.session_store.get("t:model:magic").reserve_turn()
    client = TestClient(app)

    cache = client.get("/admin/stats").json()["cache"]

    assert cache["incremental_hits"] == 2
    assert cache["fresh_starts"] == 1
    assert cache["incremental_hit_rate"] == round(2 / 3, 4)
    assert cache["sessions"]["sessions"] == 1
    assert cache["sessions"]["changes"] >= 2
    assert "flush_interval" in cache["sessions"]
    assert "entries" in cache["history_index"] and "hit_rate" in cache["history_index"]
    assert "hit_rate" in cache["cloud_token"]


def test_admin_stats_cache_block_has_no_rate_before_any_traffic(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))

    cache = TestClient(app).get("/admin/stats").json()["cache"]

    assert cache["incremental_hit_rate"] is None
    assert cache["incremental_hits"] == 0 and cache["fresh_starts"] == 0


def test_admin_stats_returns_persistent_usage_summary(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    app.state.usage_store.record("gpt-5.6", input_tokens=10, output_tokens=4)
    app.state.usage_store.record("Claude_Sonnet", input_tokens=7, output_tokens=3)
    app.state.usage_store.record("gpt-5.6", input_tokens=5, output_tokens=1)

    stats = TestClient(app).get("/admin/stats").json()

    assert stats["usage"] == {
        "calls_total": 3,
        "input_tokens": 22,
        "output_tokens": 8,
        "total_tokens": 30,
        "estimated": True,
        "model_counts": {"gpt-5.6": 2, "Claude_Sonnet": 1},
    }
    assert stats["calls_total"] == 3


def test_admin_capture_protocol_candidate_sanitizes_and_never_auto_applies(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    account = app.state.account_store.add(token=_jwt("tenant-a"))
    app.state.capture_enabled = True
    client = TestClient(app)

    pushed = client.post(
        "/admin/capture-payload",
        json={
            "payloads": [
                {
                    "variants": "feature.One, feature.Two",
                    "optionsSets": ["safe_one", "safe-two", "https://evil.invalid"],
                    "raw": "Bearer secret-must-not-be-promoted",
                }
            ]
        },
    )

    assert pushed.status_code == 200
    candidate = client.get("/admin/protocol-profile/candidate").json()
    assert candidate == {
        "variants": ["feature.One", "feature.Two"],
        "options_sets": ["safe_one", "safe-two"],
        "source_records": 1,
        "rejected": 1,
    }
    active = client.get(
        "/admin/protocol-profile", params={"account_id": account.id}
    ).json()
    assert active["source"] == "builtin"
    assert "feature.One" not in active["variants"]


def test_protocol_candidate_scans_every_item_in_nested_lists(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    app.state.capture_enabled = True
    client = TestClient(app)
    client.post(
        "/admin/capture-payload",
        json={
            "payloads": [
                {
                    "records": [
                        {"variants": ["feature.First"], "optionsSets": ["first_set"]},
                        {"variants": ["feature.Second"], "optionsSets": ["second_set"]},
                    ]
                }
            ]
        },
    )

    candidate = client.get("/admin/protocol-profile/candidate").json()

    assert candidate["variants"] == ["feature.First", "feature.Second"]
    assert candidate["options_sets"] == ["first_set", "second_set"]
    assert candidate["source_records"] == 1


def test_admin_protocol_profile_apply_and_rollback_are_explicit(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    account = app.state.account_store.add(token=_jwt("tenant-a"))
    app.state.capture_enabled = True
    client = TestClient(app)
    client.post(
        "/admin/capture-payload",
        json={"payloads": [{"variants": ["feature.Captured"], "optionsSets": ["captured_set"]}]},
    )

    scope = {"account_id": account.id, "scope": "account"}
    applied = client.post("/admin/protocol-profile/apply", json=scope)
    assert applied.status_code == 200
    profile = client.get(
        "/admin/protocol-profile", params={"account_id": account.id}
    ).json()
    assert profile["source"] == "captured"
    assert profile["scope"] == "account"
    assert profile["variants"] == ["feature.Captured"]
    assert profile["options_sets"] == ["captured_set"]

    rolled_back = client.post("/admin/protocol-profile/rollback", json=scope)
    assert rolled_back.status_code == 200
    restored = client.get(
        "/admin/protocol-profile", params={"account_id": account.id}
    ).json()
    assert restored["source"] == "builtin"
    assert "feature.Captured" not in restored["variants"]


def test_admin_protocol_profile_requires_scope_and_supports_tenant_fallback(tmp_path):
    app = create_app(Settings(TOKEN_DIR=str(tmp_path), API_KEY="", ADMIN_PASSWORD=""))
    first = app.state.account_store.add(token=_jwt("tenant-shared", "object-a"))
    second = app.state.account_store.add(token=_jwt("tenant-shared", "object-b"))
    app.state.capture_enabled = True
    client = TestClient(app)
    client.post(
        "/admin/capture-payload",
        json={"payloads": [{"variants": ["feature.Tenant"], "optionsSets": ["tenant_set"]}]},
    )

    assert client.post("/admin/protocol-profile/apply", json={}).status_code == 400
    assert client.post(
        "/admin/protocol-profile/apply",
        json={"account_id": first.id, "scope": "global"},
    ).status_code == 400

    applied = client.post(
        "/admin/protocol-profile/apply",
        json={"account_id": first.id, "scope": "tenant"},
    )
    inherited = client.get(
        "/admin/protocol-profile", params={"account_id": second.id}
    )

    assert applied.status_code == 200
    assert inherited.status_code == 200
    assert inherited.json()["scope"] == "tenant"
    assert inherited.json()["variants"] == ["feature.Tenant"]


def test_protocol_profile_controls_include_account_and_scope_selectors():
    from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS
    from m365_copilot_openai_proxy.template_admin_shell import _ADMIN_SHELL_HTML

    assert 'id="protocol-profile-account"' in _ADMIN_SHELL_HTML
    assert 'id="protocol-profile-scope"' in _ADMIN_SHELL_HTML
    assert "account_id:accountId" in _ADMIN_DASHBOARD_JS
    assert "scope:scope" in _ADMIN_DASHBOARD_JS


def test_dashboard_renders_the_cache_block_from_cached_stats():
    """Two-stage per the template convention: loadStats fetches, render only reads."""
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS

    assert 'id="dash-cache"' in _ADMIN_HTML
    assert "window.__cacheStats=d.cache||null;" in _ADMIN_DASHBOARD_JS
    assert "function renderCacheStats()" in _ADMIN_DASHBOARD_JS
    assert "if(typeof renderCacheStats==='function')renderCacheStats()" in _ADMIN_HTML
    for key in ("dash_cache_title", "dash_cache_reuse", "dash_cache_saved"):
        assert _ADMIN_HTML.count(f"{key}:'") == 2
    assert "dash_cache_detail:'" not in _ADMIN_HTML


def test_dashboard_renders_model_share_donut_with_total_tokens_in_center():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS

    assert 'id="dash-model-share"' in _ADMIN_HTML
    assert "function renderUsageOverview()" in _ADMIN_DASHBOARD_JS
    assert "d.usage||null" in _ADMIN_DASHBOARD_JS
    assert "usage.total_tokens" in _ADMIN_DASHBOARD_JS
    assert "usage.model_counts" in _ADMIN_DASHBOARD_JS
    assert _ADMIN_HTML.count("dash_cumulative_usage:'") == 2
    assert _ADMIN_HTML.count("dash_token_total:'") == 2


def test_cumulative_usage_ring_folds_what_cannot_be_drawn_into_one_grey_slice():
    """Twenty models produced twenty arcs on a 120px ring and a 6-row legend.

    Two rules fold the tail. The legend box hides its scrollbar, so rows past the
    sixth were invisible while still claiming a slice; and an arc under 16.5px is
    shorter than the ring is thick, so a 3%-of-331-calls model draws as an 8.7px
    block rather than an arc whatever it is drawn with. Three names survive the arc
    rule regardless, the folded slice is grey because it is not one model, and it
    merges with the store's own overflow bucket of the same name.
    """
    from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS

    assert "maxSlices=6,minShare=16.5/(2*Math.PI*46)" in _ADMIN_DASHBOARD_JS
    assert "let keep=ranked.length>maxSlices?maxSlices-1:ranked.length;" in _ADMIN_DASHBOARD_JS
    assert "while(keep>3&&ranked[keep-1][1]/sum<minShare)keep--;" in _ADMIN_DASHBOARD_JS
    assert "otherLabel='other',otherColor='#94a3b8'" in _ADMIN_DASHBOARD_JS
    assert "if(seen)seen[1]+=rest;else ranked.push([otherLabel,rest])" in _ADMIN_DASHBOARD_JS
    assert "entry[0]===otherLabel?otherColor:pal[index%pal.length]" in _ADMIN_DASHBOARD_JS
    # the share alone: the raw count cost the model name the width it needs
    assert "text:Math.round(entry[1]/sum*100)+'%'" in _ADMIN_DASHBOARD_JS
    # ...and the legend prints that label when a part carries one
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML

    assert "(p.text==null?p.value:esc(p.text))" in _ADMIN_HTML


def _donut_js() -> str:
    """The real donut() source, sliced out of the page it ships in."""
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML

    start = _ADMIN_HTML.index("function donut(")
    return _ADMIN_HTML[start : _ADMIN_HTML.index("function renderDashboard()", start)]


def _run_node(tmp_path, script: str) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to render the real donut JS")
    path = tmp_path / "donut-geometry.js"
    path.write_text(script, encoding="utf-8")
    done = subprocess.run(
        [node, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    assert done.returncode == 0, (done.stderr or "") + (done.stdout or "")
    return done.stdout


_DONUT_GEOMETRY_JS = r"""
const parts=[{value:114,color:'#38bdf8',label:'gpt-5.6',text:'34%'},
             {value:79,color:'#a78bfa',label:'copilot',text:'24%'},
             {value:43,color:'#22c55e',label:'deep',text:'13%'},
             {value:29,color:'#f59e0b',label:'sonnet',text:'9%'},
             {value:66,color:'#94a3b8',label:'other',text:'20%'}];
const html=donut(parts,'Token',331);
const fail=m=>{console.log('FAIL '+m);process.exit(1)};
if(/<animate/.test(html))fail('the ring animates again: '+html.match(/<animate[^>]*>/));
const band=/<g filter="url\(#\w+sh\)" opacity="0\.96">(.*?)<\/g>/.exec(html);
if(!band)fail('no single ring group: per-wedge opacity stacks 0.4 into 0.64 and 0.78');
const arcs=band[1].match(/<circle[^>]*>/g)||[];
const n=parts.length;
if(arcs.length!==n+1)fail('expected '+(n+1)+' arcs, one per slice plus the wrap cap, got '+arcs.length);
const C=2*Math.PI*46,total=parts.reduce((s,p)=>s+p.value,0),ends=[];
parts.reduce((a,p)=>{a+=C*(p.value/total);ends.push(a);return a},0);
if(Math.abs(ends[n-1]-C)>0.01)fail('shares cover '+ends[n-1].toFixed(2)+'px of a '+C.toFixed(2)+'px ring');
const paint=a=>({colour:/stroke="([^"]+)"/.exec(a)[1],
  width:Number(/stroke-width="([\d.]+)"/.exec(a)[1]),
  dash:/stroke-dasharray="([\d.]+) ([\d.]+)"/.exec(a),
  at:/stroke-dashoffset="(-?[\d.]+)"/.exec(a),
  round:/stroke-linecap="round"/.test(a)});
arcs.slice(0,n).forEach((arc,j)=>{
  // Painted last slice first, so every slice sits above the ones after it and the cap
  // on top at each boundary is the tail of the slice that ends there.
  const i=n-1-j,a=paint(arc),want=parts[i];
  if(a.colour!==want.color)fail('arc '+j+' is '+a.colour+' where '+want.label+' ('+want.color+') belongs: the wedges are not stacked last slice first, so the visible cap at a boundary is the head of the slice starting there instead of the tail of the one ending there');
  if(j===0){
    if(a.dash||a.at)fail('the bottom wedge is dashed, so the track shows through wherever no wedge reaches');
    console.log(want.label+' -> undashed base');
    return;
  }
  if(!a.dash||!a.at)fail(want.label+' is undashed and buries every wedge under it');
  if(!a.round)fail(want.label+' has no round cap, so its join is a straight radial cut, not a curve');
  // Each cap is a half-disc of half the stroke width reaching out from its end of the
  // dash, so a join lands where it should only if the dash stops a cap radius short of
  // that boundary. Off by that much either way and two slices are mis-sized: short of
  // the boundary leaves the next colour a nose over this one, past it noses the other
  // way. The other end is NOT inset: the dash starts on the ring's start, so its cap
  // laps a cap radius back over the ring's end, which is what the wrap cap below sits
  // on -- a cap only reads as a cap where the colour under it runs past its tip.
  const s=-Number(a.at[1]),len=Number(a.dash[1]),tip=s+len+a.width/2;
  if(len<=0)fail(want.label+' has a dash of '+len.toFixed(2)+'px; a negative dasharray is dropped and the wedge buries the ring');
  if(Math.abs(s)>0.01)fail(want.label+" starts "+s.toFixed(2)+"px into the ring, so its cap does not lap back over the ring's end and the wrap cap has nothing to sit on at 12 o'clock");
  if(Math.abs(tip-ends[i])>0.01)fail(want.label+' caps at '+tip.toFixed(2)+'px, its share boundary is '+ends[i].toFixed(2)+'px');
  console.log(want.label+' -> tail cap on '+tip.toFixed(2)+'px');
});
// 12 o'clock is the one join the stack cannot reach: the first slice is on top there, so
// the last slice's tail is drawn once more above everything, as a hair-length dash
// between two round caps placed a cap radius short of the end.
const wrap=paint(arcs[n]);
if(wrap.colour!==parts[n-1].color)fail('the wrap cap is '+wrap.colour+', not '+parts[n-1].label+", whose tail 12 o'clock is");
if(!wrap.round)fail("the wrap cap is not round, so the join at 12 o'clock is a straight radial cut");
// A hair, not zero: Skia drops a zero-length dash segment and paints no cap at all
// (measured). Any longer and it stops being one cap and repaints a stretch of the ring.
const wlen=wrap.dash?Number(wrap.dash[1]):-1;
if(!(wlen>0&&wlen<0.1))fail('the wrap cap is a '+(wrap.dash?wrap.dash[1]:'missing')+'px dash, not one cap');
const wtip=-Number(wrap.at[1])+wlen+wrap.width/2;
if(Math.abs(wtip-C)>0.01)fail('the wrap cap tips at '+wtip.toFixed(2)+'px, the ring ends at '+C.toFixed(2)+'px');
console.log('wrap cap -> tip on '+wtip.toFixed(2)+'px');

// A slice with less than one stroke width of ring behind it cannot host a cap: its dash
// would go negative, and a negative dasharray is dropped, which paints that colour over
// the whole ring. The wrap cap needs the same room at the other end -- half of it lies
// behind the ring's end, so a sliver last slice would put that half over its predecessor
// and read as the wrong colour there. Cap and lap-back come as a pair: with no wrap cap
// above it, a wedge lapping back would show as the first colour over the last slice.
const tiny=[{value:99,color:'#38bdf8',label:'big'},{value:1,color:'#94a3b8',label:'sliver'}];
const cut=h=>/<g filter="url\(#\w+sh\)" opacity="0\.96">(.*?)<\/g>/.exec(h)[1].match(/<circle[^>]*>/g)||[];
const tarcs=cut(donut(tiny,'Token',100));
if(tarcs.length!==2)fail('a 1% last slice has no room for the wrap cap, so 2 arcs were expected, got '+tarcs.length);
const base=paint(tarcs[0]),big=paint(tarcs[1]);
if(base.colour!=='#94a3b8'||base.dash)fail('the 1% sliver is not the undashed base, so nothing covers the ring before the first boundary');
const btip=-Number(big.at[1])+Number(big.dash[1])+big.width/2;
if(Math.abs(btip-C*0.99)>0.01)fail('the 99% wedge caps at '+btip.toFixed(2)+'px, its boundary is '+(C*0.99).toFixed(2)+'px, so the sliver is not 1% wide');
if(Math.abs(-Number(big.at[1])-big.width/2)>0.01)fail('the 99% wedge starts at '+(-Number(big.at[1])).toFixed(2)+'px with no wrap cap above it, so its leading cap laps '+(big.width/2).toFixed(2)+"px of the 1% sliver's share in the wrong colour");
// The same sliver first: 1% of the ring is less than one cap, so it draws butt on its
// exact interval instead of insetting a dash it has no room for.
const farcs=cut(donut([tiny[1],tiny[0]],'Token',100));
if(farcs.length!==3)fail('a 1% first slice: 3 arcs expected (base, sliver, wrap cap), got '+farcs.length);
const sliver=paint(farcs[1]);
if(sliver.round)fail('a 1% first slice kept its round cap, so its dash goes negative and its colour buries the ring');
if(Math.abs(Number(sliver.at[1]))>0.01||Math.abs(Number(sliver.dash[1])-C*0.01)>0.01)fail('the 1% first slice draws '+Number(sliver.dash[1]).toFixed(2)+'px from '+(-Number(sliver.at[1])).toFixed(2)+'px; its share is 0 to '+(C*0.01).toFixed(2)+'px');
const breathe=html.slice(html.indexOf('<g class="donut-breathe">'));
const closed=breathe.indexOf('</g></g>');
if(html.indexOf('<g class="donut-breathe">')<0||closed<0)fail('the halo no longer breathes');
if(/opacity="0\.96"/.test(breathe.slice(0,closed)))fail('the colour band breathes; it was asked to hold still');
console.log('OK');
"""


def test_donut_wedges_tile_the_ring_with_no_seam_and_no_animation(tmp_path):
    """Every join is an overpaint, so no join can show a gap -- and every one curves
    the same way round.

    Two butt caps meeting at a point still leave an antialiased hairline of the track
    between them, which is what a gap looked like here. Each slice is now a wedge from
    the ring's start to its own boundary, painted last slice first so it lies over the
    slices after it, with the last wedge undashed so the ring is covered before any
    boundary exists. Stacked that way the cap on top at each boundary belongs to the
    slice that ENDS there: the ")" faces the same way at every join. Stacked the other
    way up it belongs to the slice that starts there, and then 12 o'clock -- always the
    last slice's tail -- curves against all the others.

    Measured off the emitted SVG rather than asserted about the source, because what
    matters is where the arcs land: each cap reaches half a stroke width out from its end
    of the dash, so a wedge that does not stop exactly that far short of its own boundary
    draws its join in the wrong place, by 2.6% of the ring. The other end laps that far
    back over the ring's end instead, which is the only thing the wrap cap at 12 o'clock
    has to sit on.
    """
    out = _run_node(tmp_path, "const esc=s=>String(s==null?'':s);\n" + _donut_js() + _DONUT_GEOMETRY_JS)
    assert "OK" in out, out


def test_donut_legend_keeps_every_part_on_one_row():
    """A wrapped model name pushed the rows below it out of a 120px box.

    The box scrolls with its scrollbar styled ``display:none``, so ``gpt-5.6``
    wrapping to two lines did not scroll -- it deleted the fourth part from view.
    The same squeeze flattened the 10px swatch into a 5px bar, because a flex
    item shrinks below its own width before the text beside it does. Only the
    name may be clipped, and it keeps a title so a clipped name is still legible.
    """
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML

    assert "color:var(--muted);white-space:nowrap" in _ADMIN_HTML
    assert "border-radius:3px;flex-shrink:0;background:" in _ADMIN_HTML
    assert "color:var(--strong);flex-shrink:0" in _ADMIN_HTML
    assert (
        "<span title=\"'+p.label+'\" style=\"overflow:hidden;text-overflow:ellipsis\">'+p.label+'</span>"
        in _ADMIN_HTML
    )


def test_donut_legend_values_share_one_right_edge_with_the_column():
    """Values trailing names of four different widths read as a ragged column.

    Two halves: the value takes the row's slack as a left margin, and the legend
    box grows to the ring column instead of shrink-wrapping its own text -- which
    is what puts that shared edge on the column border, i.e. on the right border
    of the KPI card directly above (measured in .probe/check_legend_alignment.py:
    dropping either half moves values 2-35px off the edge).
    """
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML

    assert "color:var(--strong);flex-shrink:0;margin-left:auto" in _ADMIN_HTML
    assert ".donut-legend-scroll{height:120px;max-height:120px;flex:1;" in _ADMIN_HTML


def test_dashboard_donut_shows_center_unit_and_scrolls_long_model_legend_inline():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS

    assert 'class="donut-center-label"' in _ADMIN_HTML
    assert "centerUnit" in _ADMIN_HTML
    assert "function _fmtCompactNumber(value)" in _ADMIN_DASHBOARD_JS
    assert ",'Token');" not in _ADMIN_DASHBOARD_JS
    assert 'class="donut-legend-scroll"' in _ADMIN_HTML
    assert 'class="donut-legend-items"' in _ADMIN_HTML
    assert "height:120px" in _ADMIN_HTML
    assert "max-height:120px" in _ADMIN_HTML
    assert "overflow-y:auto" in _ADMIN_HTML
    assert "flex-direction:column" in _ADMIN_HTML
    assert "margin-block:auto" in _ADMIN_HTML
    assert "scrollbar-width:none" in _ADMIN_HTML
    assert ".donut-legend-scroll::-webkit-scrollbar" in _ADMIN_HTML
    assert "display:none" in _ADMIN_HTML


def test_dashboard_puts_four_overview_donuts_on_one_row_and_removes_cache_detail_copy():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS

    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in _ADMIN_HTML
    assert "dash_model_share" not in _ADMIN_HTML
    assert "dash_token_estimated" not in _ADMIN_DASHBOARD_JS
    assert "dash_cache_detail" not in _ADMIN_DASHBOARD_JS


def test_dashboard_stacks_overview_donuts_on_mobile():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML

    assert ".dash-overview-donuts{grid-template-columns:1fr!important}" in _ADMIN_HTML


def test_admin_account_token_control_uses_two_rows_and_fixed_width():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML

    assert 'class="acct-token-control"' in _ADMIN_HTML
    assert 'class="acct-token-primary"' in _ADMIN_HTML
    assert 'class="acct-token-secondary"' in _ADMIN_HTML
    assert 'class="acct-token-remove"' in _ADMIN_HTML
    assert 'class="acct-token-refresh"' in _ADMIN_HTML
    assert 'class="acct-token-update"' in _ADMIN_HTML
    assert 'min-width:250px' not in _ADMIN_HTML
    assert 'grid-template-columns:minmax(112px,1fr) auto auto' not in _ADMIN_HTML
    assert '.accounts-table{width:100%;min-width:698px;max-width:none;table-layout:fixed}' in _ADMIN_HTML
    assert 'overflow-y:auto;overflow-x:auto' in _ADMIN_HTML
    assert '.acct-token-control{display:grid;grid-template-rows:auto auto;gap:4px;width:131px;min-width:131px' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(6),.accounts-table td:nth-child(6){width:78px;white-space:nowrap}' in _ADMIN_HTML


def test_admin_account_actions_and_timestamps_remain_visible_and_readable():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS

    assert 'class="acct-actions-head"' in _ADMIN_HTML
    assert 'class="acct-actions-cell"' in _ADMIN_HTML
    assert '.acct-actions-cell{' in _ADMIN_HTML
    assert 'position:sticky' in _ADMIN_HTML
    assert 'right:0' in _ADMIN_HTML
    assert '.acct-token-update{' in _ADMIN_HTML
    assert 'color:var(--strong)' in _ADMIN_HTML
    assert '.acct-token-control{display:grid;grid-template-rows:auto auto;gap:4px;width:131px;min-width:131px' in _ADMIN_HTML
    assert 'toLocaleString' not in _ADMIN_DASHBOARD_JS


def test_admin_accounts_table_uses_fixed_columns_for_actions():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML

    assert '.accounts-table{width:100%;min-width:698px;max-width:none;table-layout:fixed}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(1),.accounts-table td:nth-child(1){width:32px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(2),.accounts-table td:nth-child(2){width:auto;min-width:216px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(3),.accounts-table td:nth-child(3){width:146px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(4),.accounts-table td:nth-child(4){width:80px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(5),.accounts-table td:nth-child(5){width:74px}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(6),.accounts-table td:nth-child(6){width:78px;white-space:nowrap}' in _ADMIN_HTML
    assert '.accounts-table th:nth-child(7),.accounts-table td:nth-child(7){width:72px}' in _ADMIN_HTML


def test_dashboard_separates_call_log_clear_from_cumulative_usage_clear():
    from m365_copilot_openai_proxy.template_admin import _ADMIN_HTML
    from m365_copilot_openai_proxy.template_admin_dashboard import _ADMIN_DASHBOARD_JS

    call_clear = _ADMIN_DASHBOARD_JS.split("async function clearCallStats(){", 1)[1].split("\n}", 1)[0]
    usage_clear = _ADMIN_DASHBOARD_JS.split("async function clearUsageStats(){", 1)[1].split("\n}", 1)[0]

    assert "/admin/call-log/clear" in call_clear
    assert "/admin/usage/clear" not in call_clear
    assert "confirm_clear_call_log" in call_clear
    assert "/admin/usage/clear" in usage_clear
    assert "confirm_clear_usage" in usage_clear
    assert "clearUsageStats()" in _ADMIN_DASHBOARD_JS
    for key in (
        "dash_clear_call_log",
        "dash_clear_usage",
        "confirm_clear_call_log",
        "confirm_clear_usage",
    ):
        assert _ADMIN_HTML.count(f"{key}:'") == 2
