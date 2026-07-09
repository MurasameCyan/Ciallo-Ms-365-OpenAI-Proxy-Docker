from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from m365_copilot_openai_proxy.cli import _classify_resource_token


def test_classify_designer_from_officeapps_target():
    assert _classify_resource_token("acct-x-accesstoken", "https://designerapp.officeapps.live.com/.default") == "designer"


def test_classify_media_from_teams_target():
    assert _classify_resource_token("acct-x-accesstoken", "https://teams.microsoft.com/.default") == "media"


def test_classify_media_from_asyncgw_target():
    assert _classify_resource_token("acct-x-accesstoken", "https://jp-prod.asyncgw.teams.microsoft.com/.default") == "media"


def test_classify_excludes_substrate_token():
    assert _classify_resource_token("acct-x-accesstoken-substrate", "https://substrate.office.com/.default") is None


def test_classify_returns_none_for_unrelated_resource():
    assert _classify_resource_token("acct-x-accesstoken", "https://graph.microsoft.com/.default") is None
