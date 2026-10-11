"""Synthetic GZHU SSR source and merged job-table applicability checks."""
import pytest
from backend.sources.gzhu import GzhuAdapter
from backend.domain.candidates import validate_candidate
from backend.sources.transport import FetchError
from test_hnu_sources import Materials, policy_fixture


def test_gzhu_full_publication_and_merged_major_work_location_table(monkeypatch):
    policy_fixture(monkeypatch, "gzhu", "jy.gzhu.edu.cn")
    home = "https://jy.gzhu.edu.cn/web/Index/index"
    url = "https://jy.gzhu.edu.cn/web/Index/jobs-brief-detail?id=SYNTH01"
    config = {"school_key": "gzhu", "source_key": "gzhu_jobs", "channel_key": "jobs", "official_entry_url": home}
    listing = '<a href="/web/Index/jobs-brief-detail?id=SYNTH01">合成2027校园招聘</a>'
    body = '<div class="page-content-detail"><div class="header-wrapper"><div class="title">合成2027校园招聘</div><div class="caption" title="2026/10/10 10:37">2026/10/10</div></div><div class="content-wrapper">'
    body += '<table><tbody><tr><td>岗位类型</td><td>岗位方向</td><td>需求数量</td><td>学历要求</td><td>专业</td><td>工作地点</td></tr>'
    body += '<tr><td rowspan="2">职能类</td><td>产品经理</td><td>5</td><td>本科</td><td>电气工程及自动化</td><td>佛山</td></tr>'
    body += '<tr><td>营销</td><td>2</td><td>本科</td><td>管理专业</td><td>全国</td></tr></tbody></table></div></div>'
    client = Materials({home: listing, url: body})
    item = GzhuAdapter.discover(config, client)["records"][0]
    patch = GzhuAdapter.enrich(item, client)["patch"]
    final = {**item, **patch, "field_observations": {**item["field_observations"], **patch["field_observations"]}}
    assert final["published_date"] == "2026-10-10" and final["relevance"] == "related"
    assert final["work_locations"] == ["佛山", "全国"] and final["work_locations_scope"] == "partial_disclosed"
    assert len(final["job_fragments"]) == 2 and final["event_venue"] is None
    validate_candidate(final, config)


def test_gzhu_background_only_does_not_supply_electric_applicability(monkeypatch):
    policy_fixture(monkeypatch, "gzhu", "jy.gzhu.edu.cn")
    url = "https://jy.gzhu.edu.cn/web/Index/jobs-brief-detail?id=SYNTH02"
    item = {"school_key": "gzhu", "source_key": "gzhu_jobs", "source_identity": "SYNTH02", "source_url": url, "title": "合成招聘", "field_observations": {}}
    html = '<div class="page-content-detail"><div class="content-wrapper"><p>公司从事电气制造。</p><p>招聘行政岗位。</p><img src="/poster.jpg"></div></div>'
    result = GzhuAdapter.enrich(item, Materials({url: html}))
    assert result["patch"].get("relevance", "unknown") == "unknown"
    assert result["patch"]["field_observations"]["work_locations"]["state"] == "pending_extraction"


def test_gzhu_detail_identity_is_exact_before_request():
    client = Materials({})
    with pytest.raises(FetchError):
        GzhuAdapter.enrich({"school_key": "gzhu", "source_identity": "SYNTH01", "source_url": "https://jy.gzhu.edu.cn/web/Index/jobs-brief-detail?id=SYNTH02"}, client)
    assert not client.requests


def test_gzhu_redirected_other_record_keeps_fields():
    requested = "https://jy.gzhu.edu.cn/web/Index/jobs-brief-detail?id=SYNTH01"
    class Redirected(Materials):
        def get(self, url):
            value = super().get(url)
            value["url"] = url.replace("SYNTH01", "SYNTH02")
            return value
    result = GzhuAdapter.enrich({"school_key": "gzhu", "source_key": "gzhu_jobs", "source_identity": "SYNTH01", "source_url": requested}, Redirected({requested: '<div class="page-content-detail"><div class="content-wrapper">电气工程师</div></div>'}))
    assert result["patch"] == {} and result["material_refs"][0]["parsing_status"] == "failed"


def test_gzhu_homepage_card_title_excludes_long_body_preview(monkeypatch):
    policy_fixture(monkeypatch, "gzhu", "jy.gzhu.edu.cn")
    home = "https://jy.gzhu.edu.cn/web/Index/index"
    config = {"school_key": "gzhu", "source_key": "gzhu_jobs", "channel_key": "jobs", "official_entry_url": home}
    html = '<a class="timeline-item" href="jobs-brief-detail?id=SYNTH03"><div class="title">合成校园招聘标题</div>'
    html += '<p class="truncate">' + '企业介绍和正文预览。' * 180 + '</p><div>10月10日</div></a>'
    page = GzhuAdapter.discover(config, Materials({home: html}))
    item = page["records"][0]
    assert item["title"] == "合成校园招聘标题" and item["published_date"] is None
    assert item["relevance"] == "unknown"
    validate_candidate(item, config)


def test_gzhu_unbounded_anchor_without_explicit_title_is_not_a_valid_card(monkeypatch):
    policy_fixture(monkeypatch, "gzhu", "jy.gzhu.edu.cn")
    home = "https://jy.gzhu.edu.cn/web/Index/index"
    config = {"school_key": "gzhu", "source_key": "gzhu_jobs", "channel_key": "jobs", "official_entry_url": home}
    html = '<a href="jobs-brief-detail?id=SYNTH04">' + '正文。' * 400 + '</a>'
    page = GzhuAdapter.discover(config, Materials({home: html}))
    assert not page["records"] and page["material_refs"][0]["parsing_status"] == "failed"
