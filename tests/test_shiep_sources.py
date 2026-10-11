"""SHIEP exact tenant and stable announcement identity, without live claims."""
import pytest
from backend.sources.shiep import ShiepAdapter
from backend.sources.transport import FetchError
from backend.sources.common import candidate_base
from backend.domain.candidates import validate_candidate
from test_hnu_sources import Materials, policy_fixture


def test_shiep_homepage_literal_links_not_calendar_inference(monkeypatch):
    policy_fixture(monkeypatch, "shiep", "career.shiep.edu.cn")
    url = "https://career.shiep.edu.cn/"
    config = {"school_key": "shiep", "source_key": "shiep_homepage", "channel_key": "homepage", "official_entry_url": url}
    html = '<a href="/campus/view/id/9000501">合成单位</a><a href="/teachin/view/id/9000502">合成活动</a>'
    page = ShiepAdapter.discover(config, Materials({url: html}))
    assert [item["source_identity"] for item in page["records"]] == ["9000501"]
    assert all(item["published_date"] is None and item["event_date"] is None for item in page["records"])
    assert page["completeness"] == "partial"


def test_shiep_another_tenant_never_requested():
    client = Materials({})
    config = {"school_key": "shiep", "channel_key": "campus", "official_entry_url": "https://career.shiep.edu.cn/campus"}
    with pytest.raises(FetchError):
        ShiepAdapter.discover(config, client, "https://career.gdut.edu.cn/campus")
    assert not client.requests


def test_shiep_public_next_href_keeps_exact_school_tenant(monkeypatch):
    policy_fixture(monkeypatch, "shiep", "career.shiep.edu.cn")
    url = "https://career.shiep.edu.cn/campus"
    config = {"school_key": "shiep", "source_key": "shiep_campus", "channel_key": "campus", "official_entry_url": url}
    html = '<ul class="infoList"><li><a href="/campus/view/id/9000501">合成单位</a></li><li>2026-10-08</li></ul><a href="/campus/index/domain/shiep/city//page/2">下一页</a>'
    page = ShiepAdapter.discover(config, Materials({url: html}))
    assert page["next_cursor"] == "https://career.shiep.edu.cn/campus/index/domain/shiep/city//page/2"


def test_shiep_announcement_body_major_table_is_specific_role_proof(monkeypatch):
    policy_fixture(monkeypatch, "shiep", "career.shiep.edu.cn")
    url = "https://career.shiep.edu.cn/campus/view/id/9000503"
    config = {"school_key": "shiep", "source_key": "shiep_campus"}
    item = candidate_base(config, "9000503", "合成2027招聘", url, "announcement", "招聘简章", "publication")
    html = '<div class="zp-details"><div class="details-mge"><div class="aContent"><table><tbody><tr><td>招聘岗位类别</td><td>招聘专业</td><td>计划招聘人数</td></tr><tr><td>港口技术</td><td>电气工程、电气工程及其自动化、控制工程</td><td>22</td></tr></tbody></table></div></div></div>'
    client = Materials({url: html})
    result = ShiepAdapter.enrich(item, client)
    patch = result["patch"]
    final = {**item, **patch, "field_observations": {**item["field_observations"], **patch["field_observations"]}}
    assert final["relevance"] == "related" and "招聘专业" in final["field_observations"]["relevance"]["evidence"][0]["locator"]
    assert client.requests == [url]  # The specialized table uses the same actual response.
    assert final["work_locations"] == []
    validate_candidate(final, config)
