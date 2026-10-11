"""Synthetic NCSS school-source boundaries; fixtures are not live samples."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from backend.sources.scut import (
    NCSS_OWNER_URL, NCSS_SCHOOL_ID, ScutNcssAdapter, ncss_list_url,
)
from backend.sources.transport import FetchError


JOB = "SyntheticSchoolJob0001"
DETAIL = f"https://www.ncss.cn/student/jobs/{JOB}/detail.html"


class Materials:
    def __init__(self, pages):
        self.pages, self.requests = pages, []

    def get(self, url):
        self.requests.append(url)
        value = self.pages[url]
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        digest = hashlib.sha256(text.encode()).hexdigest()
        return {"url": url, "text": text, "material_hash": digest,
            "reference_key": hashlib.sha256((url + '\n' + digest).encode()).hexdigest(),
            "fetched_at": "2026-10-11T12:00:00+08:00", "raw_reference": "isolated-fixture/" + digest}


def source():
    return {"school_key": "scut", "source_key": "scut_ncss", "channel_key": "scut_ncss",
        "adapter": "scut_ncss", "official_entry_url": ncss_list_url(), "scope": {"fixture": True}}


def row(**overrides):
    return {"jobId": JOB, "jobName": "电气工程师", "sourcesName": NCSS_SCHOOL_ID,
        "sourcesNameCh": "华南理工大学", "sourcesType": 12, "publishDate": 1790668800000, **overrides}


def pages(rows=None, html=None):
    return {NCSS_OWNER_URL: {"flag": True, "data": [{"id": NCSS_SCHOOL_ID, "name": "华南理工大学"}]},
        ncss_list_url(): {"flag": True, "data": {"list": rows if rows is not None else [row()]}},
        DETAIL: html or (Path(__file__).parent / "fixtures/scut/ncss_school_detail.html").read_text(encoding="utf-8")}


def test_school_source_directory_list_detail_and_full_publication_identity():
    client = Materials(pages())
    page = ScutNcssAdapter.discover(source(), client)
    item = page["records"][0]
    assert item["published_date"] == "2026-09-29"
    assert item["source_identity"] == JOB
    assert item["field_observations"]["published_date"]["evidence"][0]["source_identity"] == JOB
    assert [ref["scope"]["type"] for ref in page["material_refs"]] == ["source_list", "source_owner"]
    result = ScutNcssAdapter.enrich(item, client)
    assert result["patch"]["relevance"] == "related"
    assert result["patch"]["work_locations"] == []
    assert result["patch"]["field_observations"]["work_locations"]["state"] == "pending_extraction"
    assert "published_date" not in result["patch"]  # Month/day update cannot replace full list year.
    assert result["material_refs"][0]["official_record_id"] == JOB
    assert page["completeness"] == "partial"


@pytest.mark.parametrize("changes", [{"sourcesName": "other-school"}, {"sourcesNameCh": "其它学校"}, {"sourcesType": 0}])
def test_national_or_other_school_rows_are_rejected(changes):
    page = ScutNcssAdapter.discover(source(), Materials(pages([row(**changes)])))
    assert not page["records"] and page["material_refs"][0]["parsing_status"] == "failed"


@pytest.mark.parametrize("html", [
    '<div class="mainContent-geshi">招聘岗位：电气工程师</div>',
    '<input id="sourcesName" value="other"><span class="source-sp" data-sourcesType="12">华南理工大学</span><div class="mainContent-geshi">电气岗位</div>',
    f'<input id="sourcesName" value="{NCSS_SCHOOL_ID}"><span class="source-sp" data-sourcesType="1">华南理工大学</span><div class="mainContent-geshi">电气岗位</div>',
])
def test_missing_or_wrong_detail_school_marker_preserves_list_fields(html):
    client = Materials(pages(html=html))
    item = ScutNcssAdapter.discover(source(), client)["records"][0]
    before = deepcopy(item)
    result = ScutNcssAdapter.enrich(item, client)
    assert result["patch"] == {} and result["material_refs"][0]["parsing_status"] == "failed"
    assert item == before


@pytest.mark.parametrize("url", [
    ncss_list_url().replace(NCSS_SCHOOL_ID, "other"),
    ncss_list_url() + "&sourcesName=other", ncss_list_url() + "&jobType=03",
    ncss_list_url().replace("offset=1", "offset=-1"),
])
def test_scope_change_cursor_rejected_before_network(url):
    client = Materials({})
    with pytest.raises(FetchError):
        ScutNcssAdapter.discover(source(), client, url)
    assert client.requests == []


def test_directory_must_confirm_public_school_source_id():
    data = pages()
    data[NCSS_OWNER_URL]["data"][0]["name"] = "其它学校"
    client = Materials(data)
    with pytest.raises(FetchError):
        ScutNcssAdapter.discover(source(), client)
    assert client.requests == [NCSS_OWNER_URL]


def test_background_electric_word_without_role_or_major_remains_unknown():
    html = f'<input id="sourcesName" value="{NCSS_SCHOOL_ID}">'
    html += '<span class="source-sp" data-sourcesType="12">华南理工大学</span>'
    html += '<h1 class="job-title">综合管理</h1><div class="mainContent-geshi"><p>企业从事电气产业。</p><p>招聘岗位：行政助理。</p></div>'
    client = Materials(pages(html=html))
    item = ScutNcssAdapter.discover(source(), client)["records"][0]
    # Two unrelated paragraphs must not create applicability via their adjacency.
    result = ScutNcssAdapter.enrich(item, client)
    assert result["patch"].get("relevance", "unknown") == "unknown"


def test_explicit_role_section_major_coverage_is_related():
    html = f'<input id="sourcesName" value="{NCSS_SCHOOL_ID}">'
    html += '<span class="source-sp" data-sourcesType="12">华南理工大学</span><h1 class="job-title">各类岗位</h1>'
    html += '<div class="mainContent-geshi"><p>公司生产电气设备。</p><p>二、我们的招聘岗位</p><p>研发、设计、工艺岗位。</p><p>涵盖机械类、电气类、自动化类等；</p><p>三、申请办法</p></div>'
    client = Materials(pages(html=html))
    item = ScutNcssAdapter.discover(source(), client)["records"][0]
    proof = ScutNcssAdapter.enrich(item, client)["patch"]["field_observations"]["relevance"]
    assert proof["value"] == "related" and "我们的招聘岗位" in proof["evidence"][0]["excerpt"]


def test_other_section_coverage_does_not_supply_role_applicability():
    html = f'<input id="sourcesName" value="{NCSS_SCHOOL_ID}">'
    html += '<span class="source-sp" data-sourcesType="12">华南理工大学</span><h1 class="job-title">各类岗位</h1>'
    html += '<div class="mainContent-geshi"><p>我们的招聘岗位</p><p>行政与综合岗位。</p><p>三、集团简介</p><p>涵盖机械类、电气类、自动化类产业；</p></div>'
    client = Materials(pages(html=html))
    item = ScutNcssAdapter.discover(source(), client)["records"][0]
    assert ScutNcssAdapter.enrich(item, client)["patch"].get("relevance", "unknown") == "unknown"


def test_redirected_other_job_is_not_bound_to_original_job():
    class Redirected(Materials):
        def get(self, url):
            value = super().get(url)
            if url == DETAIL:
                value["url"] = url.replace(JOB, "OtherSchoolJob00002")
            return value
    client = Redirected(pages())
    item = ScutNcssAdapter.discover(source(), client)["records"][0]
    result = ScutNcssAdapter.enrich(item, client)
    assert result["patch"] == {} and result["material_refs"][0]["parsing_status"] == "failed"


def test_redirected_other_offset_is_not_bound_to_requested_page():
    class Redirected(Materials):
        def get(self, url):
            value = super().get(url)
            if url == ncss_list_url():
                value["url"] = ncss_list_url(2)
            return value
    with pytest.raises(FetchError):
        ScutNcssAdapter.discover(source(), Redirected(pages()))


@pytest.mark.parametrize("replacement", [
    '<div class="hide" id="sourcesName">other-school</div>',
    f'<div id="sourcesName">{NCSS_SCHOOL_ID}</div><div id="sourcesName">other-school</div>',
])
def test_real_div_shape_does_not_relax_school_ownership(replacement):
    html = (Path(__file__).parent / "fixtures/scut/ncss_school_detail.html").read_text(encoding="utf-8")
    html = html.replace(f'<div class="hide" id="sourcesName">{NCSS_SCHOOL_ID}</div>', replacement)
    client = Materials(pages(html=html))
    item = ScutNcssAdapter.discover(source(), client)["records"][0]
    result = ScutNcssAdapter.enrich(item, client)
    assert result["patch"] == {} and result["material_refs"][0]["parsing_status"] == "failed"
