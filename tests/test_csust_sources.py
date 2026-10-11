"""CSUST supports the exact public tenant without implying live reachability."""
import json
import pytest
from backend.domain.candidates import validate_candidate
from backend.sources.csust import CsustAdapter
from backend.sources.transport import FetchError
from test_hnu_sources import Materials, policy_fixture


@pytest.mark.parametrize("url", ["https://hnu.bysjy.com.cn/", "https://csust.bysjy.com.cn/default/ulogin", "https://csust.bysjy.com.cn/?school_id=other"])
def test_csust_other_tenant_login_or_query_rejected(url):
    client = Materials({})
    config = {"school_key": "csust", "channel_key": "careers", "official_entry_url": "https://csust.bysjy.com.cn/"}
    with pytest.raises(FetchError):
        CsustAdapter.discover(config, client, url)
    assert not client.requests


def embedded_homepage(rows, *, route=True, payload=None):
    data = {"panels": [{"children": [{"panel_type": 1, "panel_name": "宣讲会", "list": rows}]}]}
    html = '<script>\nconst data = ' + (payload if payload is not None else json.dumps(data, ensure_ascii=False)) + ';\n</script>'
    if route:
        html += '''<a :href="'/detail/career?id=' + itemChild['career_talk_id']">{{ itemChild.meet_name }}</a>'''
    return html


def career_row(**changes):
    return {"career_talk_id": "9000501", "meet_name": "合成单位公开宣讲", "school_name": "长沙理工大学", "inner_school": "1",
            "meet_day": "2026-10-12", "meet_time": "14:30", "meet_end_time": "16:00", "address": "合成主校区教室101",
            "city_name": "外省总部城市", "job_city": "未知字段城市", "professionals": "电气工程", **changes}


def source_config():
    return {"school_key": "csust", "source_key": "csust_careers", "channel_key": "careers", "official_entry_url": "https://csust.bysjy.com.cn/"}


def test_csust_embedded_public_career_panel_validates_without_script_execution(monkeypatch):
    policy_fixture(monkeypatch, "csust", "csust.bysjy.com.cn")
    config = source_config()
    client = Materials({config["official_entry_url"]: embedded_homepage([career_row()])})
    page = CsustAdapter.discover(config, client)
    item = page["records"][0]
    assert client.requests == [config["official_entry_url"]]
    assert item["source_url"] == "https://csust.bysjy.com.cn/detail/career?id=9000501"
    assert item["event_date"] == "2026-10-12" and item["start_time"] == "14:30" and item["end_time"] == "16:00"
    assert item["campus_key"] == "synthetic_main" and item["event_venue"] == "合成主校区教室101"
    assert item["work_locations"] == [] and item["published_date"] is None and item["relevance"] == "unknown"
    assert page["completeness"] == "partial" and page["next_cursor"] is None
    assert page["material_refs"][0]["parsing_status"] == "success"
    assert all("career_talk_id=9000501" in proof["locator"] for value in item["field_observations"].values() for proof in value["evidence"])
    validate_candidate(item, config)


def test_csust_embedded_other_school_invalid_identity_and_missing_year_do_not_supply_facts(monkeypatch):
    policy_fixture(monkeypatch, "csust", "csust.bysjy.com.cn")
    config = source_config()
    rows = [career_row(school_name="其他学校"), career_row(inner_school="0"), career_row(career_talk_id="9000502&token=wrong"),
            career_row(career_talk_id="9000503", meet_day="10月12日", meet_time="25:00", meet_end_time="unknown")]
    page = CsustAdapter.discover(config, Materials({config["official_entry_url"]: embedded_homepage(rows)}))
    assert len(page["records"]) == 1
    item = page["records"][0]
    assert item["source_identity"] == "9000503" and item["event_date"] is None and item["start_time"] is None and item["end_time"] is None
    assert item["relevance"] == "unknown" and item["work_locations"] == []
    validate_candidate(item, config)


@pytest.mark.parametrize("html", [
    embedded_homepage([career_row()], route=False),
    embedded_homepage([], payload="loadRemoteJobs()"),
    embedded_homepage([], payload="{\"panels\": makePanels()}"),
    embedded_homepage([career_row()]) + '<script>\nconst data = {};\n</script>',
])
def test_csust_missing_route_nonliteral_or_ambiguous_data_remains_unknown_scope(monkeypatch, html):
    policy_fixture(monkeypatch, "csust", "csust.bysjy.com.cn")
    config = source_config()
    client = Materials({config["official_entry_url"]: html})
    page = CsustAdapter.discover(config, client)
    assert client.requests == [config["official_entry_url"]]
    assert not page["records"] and page["material_refs"][0]["parsing_status"] == "failed"
