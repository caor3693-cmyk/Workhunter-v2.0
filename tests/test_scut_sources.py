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


def pagination_page(rows, *, count, offset=1, **overrides):
    pagination = {"count": count, "total": (count + 9) // 10, "limit": 10, "offset": offset, **overrides}
    return {"flag": True, "data": {"list": rows, "pagenation": pagination}}


def ten_rows():
    return [row(jobId=f"SyntheticSchoolJob{index:04}") for index in range(10)]


def test_short_intermediate_page_uses_official_next_page_instead_of_row_count():
    data = pages()
    data[ncss_list_url(2)] = pagination_page(ten_rows()[:4], count=100, offset=2)
    page = ScutNcssAdapter.discover(source(), Materials(data), ncss_list_url(2))
    assert page["next_cursor"] == ncss_list_url(3)
    assert page["completeness"] == "partial"
    assert page["scope"]["pagination"]["total"] == 10


@pytest.mark.parametrize("count,offset,rows", [(14, 2, ten_rows()[:4]), (10, 1, ten_rows()), (0, 1, [])])
def test_valid_official_terminal_is_complete_only_for_the_registered_query(count, offset, rows):
    data = pages()
    data[ncss_list_url(offset)] = pagination_page(rows, count=count, offset=offset)
    page = ScutNcssAdapter.discover(source(), Materials(data), ncss_list_url(offset))
    assert page["next_cursor"] is None and page["completeness"] == "complete_for_channel"
    assert page["scope"]["school_wide"] is False and page["scope"]["query_keyword"] == "电气"
    assert page["material_refs"][0]["parsing_status"] == "success"
    if count == 0:
        assert page["material_refs"][0]["scope"]["coverage"] == "verified_empty"
        assert page["warnings"] == []


def test_empty_intermediate_page_does_not_end_official_pagination():
    data = pages()
    data[ncss_list_url(2)] = pagination_page([], count=100, offset=2)
    page = ScutNcssAdapter.discover(source(), Materials(data), ncss_list_url(2))
    assert page["next_cursor"] == ncss_list_url(3) and page["completeness"] == "partial"
    assert page["material_refs"][0]["scope"]["coverage"] == "verified_empty"


@pytest.mark.parametrize("overrides", [
    {"offset": 2}, {"offset": True}, {"limit": 20}, {"limit": "10"},
    {"count": -1}, {"count": True}, {"total": 2}, {"total": 10000},
])
def test_invalid_pagination_metadata_cannot_claim_terminal_or_control_cursor(overrides):
    data = pages()
    data[ncss_list_url()] = pagination_page([row()], count=1)
    data[ncss_list_url()]["data"]["pagenation"].update(overrides)
    page = ScutNcssAdapter.discover(source(), Materials(data))
    assert page["completeness"] == "partial" and page["next_cursor"] is None
    assert page["material_refs"][0]["parsing_status"] == "failed"


@pytest.mark.parametrize("rows", [[row(sourcesName="other")], [row(), row()], [None], [row(jobId="bad")], [row(jobName="")], ten_rows() + [row()]])
def test_invalid_or_duplicate_rows_cannot_be_complete_even_with_terminal_metadata(rows):
    data = pages()
    data[ncss_list_url()] = pagination_page(rows, count=len(rows))
    page = ScutNcssAdapter.discover(source(), Materials(data))
    assert page["completeness"] == "partial"
    assert page["material_refs"][0]["parsing_status"] == "failed"


def test_missing_metadata_and_contradictory_empty_terminal_remain_unverified():
    missing = ScutNcssAdapter.discover(source(), Materials(pages()))
    assert missing["completeness"] == "partial"
    data = pages()
    data[ncss_list_url(10)] = pagination_page([], count=100, offset=10)
    contradictory = ScutNcssAdapter.discover(source(), Materials(data), ncss_list_url(10))
    assert contradictory["completeness"] == "partial"
    assert contradictory["material_refs"][0]["parsing_status"] == "failed"


@pytest.mark.parametrize("payload", ["<html>login</html>", {"flag": False, "data": {"list": []}}, {"flag": True, "data": {}}, {"flag": True, "data": {"list": None}}])
def test_unrecognized_empty_responses_are_not_verified_empty(payload):
    data = pages()
    data[ncss_list_url()] = payload
    with pytest.raises(FetchError):
        ScutNcssAdapter.discover(source(), Materials(data))


def registered_fixture_source(database):
    from backend.config import ROOT
    from backend.services.discovery import register_sources
    seeds = json.loads((ROOT / "config/schools.json").read_text(encoding="utf-8"))
    configs = register_sources(database, seeds, fixture=True)
    return next(config for config in configs if config["source_key"] == "scut_ncss")


def test_production_refresh_consumes_full_pagination_and_repeat_preserves_dataset(tmp_path):
    from backend.services.discovery import refresh_sources
    from backend.storage.database import initialize_database, read_database
    database = tmp_path / "isolated.sqlite3"
    initialize_database(database, fixture=True)
    config = registered_fixture_source(database)
    rows = ten_rows()
    data = pages()
    data[ncss_list_url()] = pagination_page(rows, count=11)
    data[ncss_list_url(2)] = pagination_page([row(jobId="SyntheticSchoolJob0010")], count=11, offset=2)
    body = data[DETAIL]
    for entry in rows + [row(jobId="SyntheticSchoolJob0010")]:
        data[f'https://www.ncss.cn/student/jobs/{entry["jobId"]}/detail.html'] = body
    first_client = Materials(data)
    first = refresh_sources(database, [config], transport=first_client, school_keys=("scut",), page_budget=2, detail_budget=11, fixture=True)
    assert first["status"] == "complete" and first["sources"][0]["pages"] == 2
    assert first["sources"][0]["pending_details"] == 0 and first["commits"]["new"] == 11
    with read_database(database) as (connection, metadata):
        before = dict(metadata)
        before_changes = connection.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
    repeated = refresh_sources(database, [config], transport=Materials(data), school_keys=("scut",), page_budget=2, detail_budget=11, fixture=True)
    assert repeated["status"] == "complete" and repeated["commits"]["new"] == repeated["commits"]["modified"] == 0
    with read_database(database) as (connection, metadata):
        assert dict(metadata) == before
        assert connection.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == before_changes
        assert connection.execute("SELECT completeness FROM runs WHERE id=?", (repeated["run_id"],)).fetchone()[0] == "complete_for_selected_channels"


def test_production_refresh_keeps_detail_failure_partial_at_valid_terminal(tmp_path):
    from backend.services.discovery import refresh_sources
    from backend.storage.database import initialize_database, read_database
    database = tmp_path / "isolated.sqlite3"
    initialize_database(database, fixture=True)
    config = registered_fixture_source(database)
    data = pages(html="<div>正文未取得</div>")
    data[ncss_list_url()] = pagination_page([row()], count=1)
    result = refresh_sources(database, [config], transport=Materials(data), school_keys=("scut",), fixture=True)
    assert result["status"] == "partial" and result["sources"][0]["detail_failures"] == 1
    with read_database(database) as (connection, _):
        assert connection.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1
        assert connection.execute("SELECT status FROM sources WHERE source_key='scut_ncss'").fetchone()[0] == "partial"


@pytest.mark.parametrize("duplicate_name", ["华南理工大学", "其它学校"])
def test_ambiguous_owner_directory_cannot_prove_complete_scope(duplicate_name):
    data = pages()
    data[NCSS_OWNER_URL]["data"].append({"id": NCSS_SCHOOL_ID, "name": duplicate_name})
    data[ncss_list_url()] = pagination_page([row()], count=1)
    with pytest.raises(FetchError):
        ScutNcssAdapter.discover(source(), Materials(data))


def test_production_refresh_rejects_mixed_terminal_without_losing_old_facts(tmp_path):
    from backend.services.discovery import refresh_sources
    from backend.storage.database import initialize_database, read_database
    database = tmp_path / "isolated.sqlite3"
    initialize_database(database, fixture=True)
    config = registered_fixture_source(database)
    data = pages()
    data[ncss_list_url()] = pagination_page([row()], count=1)
    first = refresh_sources(database, [config], transport=Materials(data), school_keys=("scut",), fixture=True)
    assert first["status"] == "complete"
    with read_database(database) as (connection, metadata):
        before_dataset = metadata["dataset_id"]
        before = dict(connection.execute("SELECT * FROM opportunities").fetchone())
    data[ncss_list_url()] = pagination_page([row(), row(jobId="OtherSchoolJob0001", sourcesName="other")], count=2)
    failed = refresh_sources(database, [config], transport=Materials(data), school_keys=("scut",), fixture=True)
    assert failed["status"] == "failed"
    with read_database(database) as (connection, metadata):
        assert metadata["dataset_id"] == before_dataset
        assert dict(connection.execute("SELECT * FROM opportunities").fetchone()) == before


@pytest.mark.parametrize("message,restricted", [
    ("请登录后查看", True), ("系统暂时繁忙", False), ("登录后查看联系方式", False),
])
def test_explicit_login_json_is_restricted_but_other_api_failure_is_not(message, restricted):
    data = pages()
    data[ncss_list_url()] = {"flag": False, "global": [{"type": 0, "des": message, "refs": []}], "errors": [], "data": None}
    with pytest.raises(FetchError) as caught:
        ScutNcssAdapter.discover(source(), Materials(data))
    assert caught.value.restricted is restricted
    assert caught.value.status == ("restricted" if restricted else "failed")
    assert caught.value.material_ref["url"] == ncss_list_url()


def test_successful_json_with_login_text_does_not_hide_public_records():
    data = pages()
    data[ncss_list_url()] = pagination_page([row()], count=1)
    data[ncss_list_url()]["global"] = [{"type": 0, "des": "请登录后查看", "refs": []}]
    page = ScutNcssAdapter.discover(source(), Materials(data))
    assert page["records"][0]["source_identity"] == JOB
    assert page["completeness"] == "complete_for_channel"


def test_production_refresh_records_explicit_login_and_skips_restricted_path(tmp_path):
    from backend.services.discovery import refresh_sources
    from backend.storage.database import initialize_database, read_database
    database = tmp_path / "isolated.sqlite3"
    initialize_database(database, fixture=True)
    config = registered_fixture_source(database)
    data = pages()
    data[ncss_list_url()] = pagination_page([row()], count=1)
    first = refresh_sources(database, [config], transport=Materials(data), school_keys=("scut",), fixture=True)
    assert first["status"] == "complete"
    with read_database(database) as (connection, metadata):
        before_dataset = metadata["dataset_id"]
        before = dict(connection.execute("SELECT * FROM opportunities").fetchone())
    data[ncss_list_url()] = {"flag": False, "global": [{"type": 0, "des": "请登录后查看", "refs": []}], "errors": [], "data": None}
    blocked = refresh_sources(database, [config], transport=Materials(data), school_keys=("scut",), fixture=True)
    assert blocked["sources"][0]["status"] == "restricted"
    skipped_client = Materials({})
    skipped = refresh_sources(database, [config], transport=skipped_client, school_keys=("scut",), fixture=True, skip_restricted=True)
    assert skipped["sources"][0]["status"] == "skipped_restricted" and skipped_client.requests == []
    with read_database(database) as (connection, metadata):
        assert metadata["dataset_id"] == before_dataset
        assert dict(connection.execute("SELECT * FROM opportunities").fetchone()) == before
        assert connection.execute("SELECT status FROM sources WHERE source_key='scut_ncss'").fetchone()[0] == "restricted"
