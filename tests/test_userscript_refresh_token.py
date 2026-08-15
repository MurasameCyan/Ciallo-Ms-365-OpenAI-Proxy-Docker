from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "get_token.user.js").read_text(
    encoding="utf-8"
)


CLIENT_ID = "4765445b-32c6-49b0-83e6-1d93765276ca"
# The real M365 Copilot SPA acquires the substrate token through a broker app,
# so the issued token's appid is the broker's -- NOT the Copilot client id --
# and there is no azp. The RT it rides on is a FOCI family token the Copilot
# client can still redeem, which is why binding.client_id stays 4765445b.
BROKER_APP_ID = "c0ab8ce9-e9a0-42e7-b064-33d422df41f1"
HOME_TENANT = "11111111-1111-1111-1111-111111111111"
RESOURCE_TENANT = "22222222-2222-2222-2222-222222222222"
OBJECT_ID = "33333333-3333-3333-3333-333333333333"


def _jwt(aud: str = "https://substrate.office.com/sydney") -> str:
    # Mirror a real captured substrate token: aud=.../sydney, appid=broker.
    claims = {
        "aud": aud,
        "oid": OBJECT_ID,
        "tid": RESOURCE_TENANT,
        "appid": BROKER_APP_ID,
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.sig"


def _capture_source() -> str:
    start_marker = "    // ---- M365 refresh-token capture helpers -------------------------------"
    end_marker = "    // ---- End M365 refresh-token capture helpers ---------------------------"
    assert start_marker in SCRIPT
    assert end_marker in SCRIPT
    return SCRIPT.split(start_marker, 1)[1].split(end_marker, 1)[0]


def test_userscript_accepts_a_brokered_substrate_rt_and_rejects_non_substrate():
    source = _capture_source()
    # The real request body is a brokered MSAL exchange: its client_id is the
    # broker's and its scope is sydney.readwrite-style, NOT the literal Copilot
    # client id or ".../sydney/.default". The capture must accept it anyway --
    # the meaningful proof that this is a substrate RT lives in the *response*
    # (substrate aud + GUID tid/oid + a refresh_token), not the request.
    brokered_body = (
        "client_id=" + BROKER_APP_ID
        + "&scope=https%3A%2F%2Fsubstrate.office.com%2Fsydney.readwrite+openid+profile+offline_access"
    )
    program = f"""
const location={{href:'https://m365.cloud.microsoft/chat'}};
const M365_RT_CLIENT_ID={json.dumps(CLIENT_ID)};
let latestRefreshToken='';
let latestRefreshTokenBinding=null;
let latestToken='';
let refreshTokenGeneration=0;
let pushes=0;
function pushLatestRefreshTokenSilently(){{pushes++;}}
{source}
const rt='1.AT4A'+'r'.repeat(200);
const url='https://login.microsoftonline.com/{HOME_TENANT}/oauth2/v2.0/token';
const substrateResp={{refresh_token:rt,access_token:{json.dumps(_jwt())}}};
// A graph token response (non-substrate aud) that also carries an RT must be
// rejected so we never redeem a wrong-audience RT as if it were substrate.
const graphResp={{refresh_token:rt,access_token:{json.dumps(_jwt("https://graph.microsoft.com"))}}};
const noRtResp={{access_token:{json.dumps(_jwt())}}};
const accepted=captureM365RefreshToken(url,{json.dumps(brokered_body)},substrateResp);
const nonSubstrate=captureM365RefreshToken(url,{json.dumps(brokered_body)},graphResp);
const missingRt=captureM365RefreshToken(url,{json.dumps(brokered_body)},noRtResp);
const wrongUrl=captureM365RefreshToken('https://login.microsoftonline.com/consumers/oauth2/v2.0/token',{json.dumps(brokered_body)},substrateResp);
process.stdout.write(JSON.stringify({{accepted,nonSubstrate,missingRt,wrongUrl,latestToken,latestRefreshToken,latestRefreshTokenBinding,pushes}}));
"""
    completed = subprocess.run(
        ["node", "-e", program], check=True, capture_output=True, text=True
    )

    result = json.loads(completed.stdout)
    assert result == {
        "accepted": True,
        "nonSubstrate": False,
        "missingRt": False,
        "wrongUrl": False,
        "latestToken": _jwt(),
        "latestRefreshToken": "1.AT4A" + "r" * 200,
        "latestRefreshTokenBinding": {
            "client_id": CLIENT_ID,
            "authority": HOME_TENANT,
            "tenant_id": RESOURCE_TENANT,
            "object_id": OBJECT_ID,
        },
        "pushes": 1,
    }


def test_userscript_captures_target_token_responses_from_fetch_and_xhr():
    fetch_block = SCRIPT.split("const OrigFetch", 1)[1].split(
        "const OrigXMLHttpRequest", 1
    )[0]
    xhr_block = SCRIPT.split("const OrigXMLHttpRequest", 1)[1].split(
        "const OrigWebSocket", 1
    )[0]

    assert "captureM365RefreshToken" in fetch_block
    assert "const origSend = xhr.send" in xhr_block
    assert "captureM365RefreshToken" in xhr_block


def test_every_explicit_m365_push_updates_the_bound_rt_when_available():
    push_token = SCRIPT.split("async function pushToken", 1)[1].split(
        "async function pushCookies", 1
    )[0]
    push_cookies = SCRIPT.split("async function pushCookies", 1)[1].split(
        "async function pushConsumer", 1
    )[0]
    one_click = SCRIPT.split("async function oneClickSetup", 1)[1].split(
        "async function pushPayload", 1
    )[0]
    push_rt = SCRIPT.split("async function pushUserRefreshToken", 1)[1].split(
        "async function pushLatestRefreshTokenSilently", 1
    )[0]

    assert "pushLatestRefreshTokenSilently(true)" in push_token
    assert "pushLatestRefreshTokenSilently(true)" in push_cookies
    assert "pushLatestRefreshTokenSilently(true)" in one_click
    assert "pushUserRefreshToken(base)" not in push_token
    assert "pushUserRefreshToken(base)" not in push_cookies
    assert "pushUserRefreshToken(base)" not in one_click
    assert "latestRefreshTokenBinding" in push_rt


def test_cookie_push_binds_the_latest_access_token_before_pushing_rt():
    push_cookies = SCRIPT.split("async function pushCookies", 1)[1].split(
        "async function pushConsumer", 1
    )[0]

    assert "pushUserToken(base, latestToken)" in push_cookies
    token_index = push_cookies.index("pushUserToken(base, latestToken)")
    cookies_index = push_cookies.index("pushUserCookies(base, cookies)")
    rt_index = push_cookies.index("pushLatestRefreshTokenSilently(true)")
    assert token_index < cookies_index < rt_index


def test_silent_rt_push_drains_a_new_capture_that_arrives_in_flight(tmp_path):
    push_source = (
        "async function pushUserRefreshToken"
        + SCRIPT.split("async function pushUserRefreshToken", 1)[1].split(
            "// Push Token to proxy", 1
        )[0]
    )
    program = f"""
const assert=require('assert');
let latestRefreshToken='rt-old-'+'x'.repeat(40);
let latestRefreshTokenBinding={{client_id:'client',authority:'old',tenant_id:'tenant',object_id:'object'}};
let refreshTokenPushInFlight=false;
let refreshTokenPushPromise=null;
let refreshTokenGeneration=1;
const requests=[];
let releaseFirst;
function getUserApiKey(){{return 'key'}}
function getProxyBase(){{return 'https://proxy.example'}}
async function gmFetch(url, options){{
  requests.push(JSON.parse(options.body));
  if(requests.length===1){{
    return await new Promise(resolve=>{{releaseFirst=()=>resolve({{ok:true,json:async()=>({{}})}})}});
  }}
  return {{ok:true,json:async()=>({{}})}};
}}
{push_source}
(async()=>{{
  const pending=pushLatestRefreshTokenSilently();
  while(!releaseFirst) await Promise.resolve();
  latestRefreshToken='rt-new-'+'y'.repeat(40);
  latestRefreshTokenBinding={{client_id:'client',authority:'new',tenant_id:'tenant',object_id:'object'}};
  refreshTokenGeneration++;
  const queued=pushLatestRefreshTokenSilently();
  releaseFirst();
  await Promise.all([pending,queued]);
  assert.strictEqual(requests.length,2,JSON.stringify(requests));
  assert.ok(requests[0].refresh_token.startsWith('rt-old-'));
  assert.ok(requests[1].refresh_token.startsWith('rt-new-'));
  assert.strictEqual(requests[1].authority,'new');
}})().catch(e=>{{console.error(e);process.exit(1)}});
"""

    subprocess.run(["node", "-e", program], check=True, cwd=tmp_path)


def test_explicit_rt_push_replays_after_account_binding_while_silent_push_is_in_flight(
    tmp_path,
):
    push_source = (
        "async function pushUserRefreshToken"
        + SCRIPT.split("async function pushUserRefreshToken", 1)[1].split(
            "// Push Token to proxy", 1
        )[0]
    )
    program = f"""
const assert=require('assert');
let latestRefreshToken='rt-current-'+'x'.repeat(40);
let latestRefreshTokenBinding={{client_id:'client',authority:'tenant',tenant_id:'tenant',object_id:'object'}};
let refreshTokenPushPromise=null;
let refreshTokenGeneration=1;
const requests=[];
let releaseFirst;
function getUserApiKey(){{return 'key'}}
function getProxyBase(){{return 'https://proxy.example'}}
async function gmFetch(url, options){{
  requests.push(JSON.parse(options.body));
  if(requests.length===1){{
    return await new Promise(resolve=>{{releaseFirst=()=>resolve({{ok:false,json:async()=>({{error:'No bound account'}})}})}});
  }}
  return {{ok:true,json:async()=>({{status:'ok'}})}};
}}
{push_source}
(async()=>{{
  const pending=pushLatestRefreshTokenSilently();
  while(!releaseFirst) await Promise.resolve();
  const replay=pushLatestRefreshTokenSilently(true);
  releaseFirst();
  await Promise.all([pending,replay]);
  assert.strictEqual(requests.length,2,JSON.stringify(requests));
  assert.strictEqual(requests[0].refresh_token,requests[1].refresh_token);
}})().catch(e=>{{console.error(e);process.exit(1)}});
"""

    subprocess.run(["node", "-e", program], check=True, cwd=tmp_path)


def test_rt_capture_in_promise_cleanup_microtask_is_not_lost(tmp_path):
    push_source = (
        "async function pushUserRefreshToken"
        + SCRIPT.split("async function pushUserRefreshToken", 1)[1].split(
            "// Push Token to proxy", 1
        )[0]
    )
    program = f"""
const assert=require('assert');
let latestRefreshToken='rt-A';
let latestRefreshTokenBinding={{client_id:'client',authority:'A',tenant_id:'tenant',object_id:'object'}};
let refreshTokenPushPromise=null;
let refreshTokenGeneration=1;
const requests=[];
let releaseFirst;
function getUserApiKey(){{return 'key'}}
function getProxyBase(){{return 'https://proxy.example'}}
async function gmFetch(url, options){{
  requests.push(JSON.parse(options.body));
  if(requests.length===1){{
    await new Promise(resolve=>{{releaseFirst=resolve}});
  }}
  return {{ok:true,json:async()=>({{status:'ok'}})}};
}}
{push_source}
(async()=>{{
  const first=pushLatestRefreshTokenSilently();
  while(!releaseFirst) await Promise.resolve();
  releaseFirst();
  queueMicrotask(()=>queueMicrotask(()=>queueMicrotask(()=>queueMicrotask(()=>{{
    latestRefreshToken='rt-B';
    latestRefreshTokenBinding={{client_id:'client',authority:'B',tenant_id:'tenant',object_id:'object'}};
    refreshTokenGeneration++;
    pushLatestRefreshTokenSilently();
  }}))));
  await first;
  for(let i=0;i<12;i++) await Promise.resolve();
  assert.deepStrictEqual(requests.map(r=>r.refresh_token),['rt-A','rt-B']);
}})().catch(e=>{{console.error(e);process.exit(1)}});
"""

    subprocess.run(["node", "-e", program], check=True, cwd=tmp_path)
