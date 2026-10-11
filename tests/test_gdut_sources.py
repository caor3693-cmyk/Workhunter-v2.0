"""Synthetic GDUT announcement/role identity and date regressions."""
import hashlib

import pytest

from backend.sources.gdut import GdutAdapter
from backend.sources.transport import FetchError
from backend.domain.candidates import validate_candidate
from backend.sources.common import candidate_base, observation


class Materials:
    def __init__(self, pages):
        self.pages, self.requests = pages, []

    def get(self, url):
        self.requests.append(url)
        text = self.pages[url]
        digest = hashlib.sha256(text.encode()).hexdigest()
        return {"url": url, "text": text, "material_hash": digest,
            "reference_key": hashlib.sha256((url + '\n' + digest).encode()).hexdigest(),
            "fetched_at": "2026-10-11T12:00:00+08:00", "raw_reference": "synthetic/" + digest}


def test_gdut_current_explicit_major_and_venue_separate_from_work_city():
    config = {"school_key": "gdut", "source_key": "gdut_teachin", "channel_key": "teachin",
        "official_entry_url": "https://career.gdut.edu.cn/teachin"}
    detail = "https://career.gdut.edu.cn/teachin/view/id/9000101"
    listing = '<ul class="infoList"><li><a href="/teachin/view/id/9000101">合成单位2027校园招聘</a></li><li>大学城校区教2-317</li><li>2026-10-12 14:30-16:30</li></ul>'
    body = '<div class="zp-details"><div class="details-title"><ul class="share"><li>发布时间：2026-10-09</li></ul></div>'
    body += '<div class="details-mge"><div class="aContent"><p>招聘城市：广州</p></div></div>'
    body += '<table><thead><tr><th>序号</th><th>职位信息</th><th>需求专业</th></tr></thead><tbody>'
    body += '<tr><td>1</td><td><div class="info-text"><a href="/job/view/id/8000101/from_id/9000101">研发岗</a><ul><li>薪资未说明</li><li>深圳龙华</li></ul></div></td><td>电气工程及其自动化</td></tr></tbody></table></div>'
    client = Materials({config["official_entry_url"]: listing, detail: body})
    item = GdutAdapter.discover(config, client)["records"][0]
    result = GdutAdapter.enrich(item, client)
    final = {**item, **result["patch"], "field_observations": {**item["field_observations"], **result["patch"]["field_observations"]}}
    assert final["event_date"] == "2026-10-12" and final["published_date"] == "2026-10-09"
    assert final["event_venue"] == "大学城校区教2-317" and final["work_locations"] == ["深圳龙华"]
    assert final["relevance"] == "related"
    validate_candidate(final, config)


def test_job_link_from_other_announcement_is_not_promoted():
    config = {"school_key": "gdut", "source_key": "gdut_campus", "channel_key": "campus",
        "official_entry_url": "https://career.gdut.edu.cn/campus"}
    detail = "https://career.gdut.edu.cn/campus/view/id/9000102"
    listing = '<ul class="infoList"><li><a href="/campus/view/id/9000102">合成单位</a></li><li>2026-10-09</li></ul>'
    body = '<div class="zp-details"><div class="details-mge"><div class="aContent"><p>招聘综合管理人员。</p></div></div>'
    body += '<table><thead><tr><th>序号</th><th>职位信息</th><th>需求专业</th></tr></thead><tbody>'
    body += '<tr><td>1</td><td><div class="info-text"><a href="/job/view/id/8000102/from_id/9999999">电气岗</a><ul><li>薪资</li><li>北京</li></ul></div></td><td>电气工程</td></tr></tbody></table></div>'
    client = Materials({config["official_entry_url"]: listing, detail: body})
    item = GdutAdapter.discover(config, client)["records"][0]
    patch = GdutAdapter.enrich(item, client)["patch"]
    assert patch.get("relevance", "unknown") == "unknown"
    assert patch["work_locations"] == [] and not patch["job_fragments"]


def test_cross_school_detail_id_rejected_before_fetch():
    client = Materials({})
    with pytest.raises(FetchError):
        GdutAdapter.enrich({"school_key": "gdut", "source_url": "https://career.gdut.edu.cn/campus/view/id/9000102", "source_identity": "9999999"}, client)
    assert not client.requests


def test_redirected_other_announcement_is_not_bound_to_original():
    url = "https://career.gdut.edu.cn/campus/view/id/9000101"
    class Redirected(Materials):
        def get(self, request_url):
            result = super().get(request_url)
            result["url"] = request_url.replace("9000101", "9000102")
            return result
    item = {"school_key": "gdut", "source_key": "gdut_campus", "source_identity": "9000101", "source_url": url}
    result = GdutAdapter.enrich(item, Redirected({url: '<div class="zp-details">其它电气岗位公告</div>'}))
    assert result["patch"] == {} and result["material_refs"][0]["parsing_status"] == "failed"


def test_redirected_other_list_page_cannot_supply_requested_page():
    url = "https://career.gdut.edu.cn/campus"
    class Redirected(Materials):
        def get(self, request_url):
            result = super().get(request_url)
            result["url"] = "https://career.gdut.edu.cn/campus/index/do123/career.gdut.edu.cn/domain/gdut/page/2"
            return result
    with pytest.raises(FetchError):
        GdutAdapter.discover({"school_key": "gdut", "source_key": "gdut_campus", "channel_key": "campus", "official_entry_url": url}, Redirected({url: "其它页"}))


def test_all_explicit_role_locations_include_national_marketing_scope():
    url = "https://career.gdut.edu.cn/campus/view/id/9000601"
    config = {"school_key": "gdut", "source_key": "gdut_campus"}
    item = candidate_base(config, "9000601", "合成校招", url, "announcement", "招聘简章", "publication")
    html = '<div class="zp-details"><div class="details-mge"><div class="aContent">'
    html += '<p>研发技术类</p><p>工作地点：佛山顺德、佛山高明</p><p>国内营销类</p><p>工作地点：全国</p>'
    html += '<p>国际营销类</p><p>工作地点：佛山顺德（总部），结合项目需求往返高明厂区</p><p>电子商务类</p><p>工作地点：佛山顺德</p>'
    html += '<p>招聘城市：广州</p><p>公司简介：总部地址：北京。</p></div></div></div>'
    patch = GdutAdapter.enrich(item, Materials({url: html}))["patch"]
    final = {**item, **patch, "field_observations": {**item["field_observations"], **patch["field_observations"]}}
    assert final["work_locations"] == ["佛山顺德", "佛山高明", "全国"]
    assert final["work_locations_scope"] == "partial_disclosed"
    proof = final["field_observations"]["work_locations"]["evidence"]
    assert any("工作地点：全国" in entry["excerpt"] and "序号4" in entry["locator"] for entry in proof)
    assert any("往返高明厂区" in entry["excerpt"] for entry in proof)
    validate_candidate(final, config)


def test_job_table_and_body_locations_merge_with_per_block_evidence():
    url = "https://career.gdut.edu.cn/campus/view/id/9000602"
    config = {"school_key": "gdut", "source_key": "gdut_campus"}
    item = candidate_base(config, "9000602", "合成校招", url, "announcement", "招聘简章", "publication")
    html = '<div class="zp-details"><div class="details-mge"><div class="aContent"><p>营销工作地点：全国</p><p>工作地点：深圳龙华</p><p>招聘城市：广州</p><p>公司简介 工作地点：北京</p></div></div>'
    html += '<table><tbody><tr><td><div class="info-text"><a href="/job/view/id/8000602/from_id/9000602">研发岗</a><ul><li>薪资</li><li>深圳龙华</li></ul></div></td></tr></tbody></table></div>'
    patch = GdutAdapter.enrich(item, Materials({url: html}))["patch"]
    assert patch["work_locations"] == ["深圳龙华", "全国"]
    proof = patch["field_observations"]["work_locations"]["evidence"]
    assert any("8000602" in entry["locator"] for entry in proof)
    assert any("工作地点：全国" in entry["excerpt"] for entry in proof)


def test_location_reparse_conflict_preserves_existing_known_value():
    url = "https://career.gdut.edu.cn/campus/view/id/9000603"
    config = {"school_key": "gdut", "source_key": "gdut_campus"}
    item = candidate_base(config, "9000603", "合成校招", url, "announcement", "招聘简章", "publication")
    item["work_locations"] = ["佛山顺德"]
    old = {"material_ref": "old", "source_url": url, "source_identity": "9000603", "locator": "旧正文工作地点", "excerpt": "工作地点：佛山顺德", "scope": "this_announcement", "observed_at": "2026-10-10T12:00:00+08:00", "parser_version": "synthetic-old"}
    item["field_observations"]["work_locations"] = observation("known", item["work_locations"], [old])
    html = '<div class="zp-details"><div class="details-mge"><div class="aContent"><p>研发工作地点：佛山顺德</p><p>营销工作地点：全国</p></div></div></div>'
    patch = GdutAdapter.enrich(item, Materials({url: html}))["patch"]
    assert patch["field_observations"]["work_locations"]["state"] == "conflict"
    assert patch["field_observations"]["work_locations"]["evidence"][0] == old
    assert "work_locations" not in patch and item["work_locations"] == ["佛山顺德"]


def test_recruiting_city_and_employer_background_are_not_work_locations():
    url = "https://career.gdut.edu.cn/campus/view/id/9000604"
    item = candidate_base({"school_key": "gdut", "source_key": "gdut_campus"}, "9000604", "合成公告", url, "announcement", "招聘简章", "publication")
    html = '<div class="zp-details"><div class="details-mge"><div class="aContent"><p>招聘城市：广州</p><p>公司简介 工作地点：北京</p></div></div></div>'
    patch = GdutAdapter.enrich(item, Materials({url: html}))["patch"]
    assert patch["work_locations"] == []
