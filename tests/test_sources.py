"""Isolated regression fixtures; none establishes live official coverage."""

import base64
from copy import deepcopy
import hashlib
from pathlib import Path
import zlib

import httpx
import pytest

from backend.domain.candidates import validate_candidate
from backend.sources import FetchError, Fetcher, discover, enrich, get_adapter
from backend.sources.common import decode_public_slots

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    school = name.split("_", 1)[0]
    return (FIXTURES / school / name).read_text(encoding="utf-8")


def config(channel="scut_cnsba"):
    scut = channel == "scut_cnsba"
    column = channel.removeprefix("gdut_")
    return {
        "source_key": channel, "school_key": "scut" if scut else "gdut",
        "channel_key": "scut_cnsba" if scut else column,
        "adapter": "scut" if scut else "gdut",
        "official_entry_url": "https://cnsba.scut.edu.cn/jysx/list.htm" if scut else f"https://career.gdut.edu.cn/{column}",
        "scope": {"fixture": True, "note": "synthetic isolated regression"},
    }


def compressed(slot, html, inner=23, outer=76, *, parent_html=False):
    decoded = "q" * outer + html
    encoded = "p" * inner + base64.b64encode(decoded.encode()).decode()
    payload = base64.b64encode(zlib.compress(encoded.encode())).decode()
    mode = "parent().html" if parent_html else "replaceWith"
    return (
        f'<script>$("#{slot}").each(function() {{ '
        f'$(this).{mode}(Base64.decode(unzip("{payload}").substr({inner})).substr({outer}));'
        " });</script>"
    )


def gdut_list(html=None):
    return '<section id="content10"></section>' + compressed("content10", html or fixture("gdut_teachin_list.html"))


def gdut_detail(*, date="2026-10-12", body=None):
    arrangement = (
        f"<dl><dt>宣讲时间：</dt><dd>{date} 14:30-16:30</dd>"
        "<dt>举办地点：</dt><dd>大学城校区教2-317</dd></dl>"
    )
    body = body or "<p>招聘岗位：电气开发岗，需求专业：电气工程及其自动化。</p>"
    return fixture("gdut_detail.html") + compressed("content101", arrangement, 17, 28) + compressed("content102", body, 35, 16)


def fetcher(tmp_path, pages, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, content=pages[str(request.url)].encode("utf-8"), headers={"content-type": "text/html"},
    )))
    return Fetcher(tmp_path / "materials", client=client, **kwargs)


def merge(candidate, patch):
    merged = {**deepcopy(candidate), **deepcopy(patch)}
    merged["field_observations"] = {**candidate["field_observations"], **patch.get("field_observations", {})}
    return merged


def test_scut_list_stable_ids_publication_and_real_next_href(tmp_path):
    source = config()
    page = discover(source, fetcher(tmp_path, {source["official_entry_url"]: fixture("scut_list.html")}))
    assert [item["source_identity"] for item in page["records"]] == ["9000001", "9000002"]
    assert page["next_cursor"] == "https://cnsba.scut.edu.cn/jysx/list2.htm"
    assert page["completeness"] == "partial"
    assert page["records"][0]["published_date"] == "2026-10-09"
    assert page["records"][0]["relevance"] == "unknown"
    validate_candidate(page["records"][0], source)


def test_scut_ambiguous_city_label_is_not_work_city_and_venue_not_applicable(tmp_path):
    source = config()
    client = fetcher(tmp_path, {
        source["official_entry_url"]: fixture("scut_list.html"),
        "https://cnsba.scut.edu.cn/2026/1009/c29313a9000001/page.htm": fixture("scut_announcement.html"),
    })
    candidate = discover(source, client)["records"][0]
    result = enrich(candidate, client)
    final = merge(candidate, result["patch"])
    assert final["work_locations"] == []
    assert final["field_observations"]["work_locations"]["state"] == "not_disclosed"
    assert final["field_observations"]["event_venue"]["state"] == "not_applicable"
    assert final["event_date"] is None and final["relevance"] == "unknown"
    validate_candidate(final, source)


def test_scut_month_day_does_not_borrow_year_from_publication(tmp_path):
    source = config()
    client = fetcher(tmp_path, {
        source["official_entry_url"]: fixture("scut_list.html"),
        "https://cnsba.scut.edu.cn/2026/1009/c29313a9000001/page.htm": fixture("scut_month_day.html"),
    })
    candidate = discover(source, client)["records"][0]
    final = merge(candidate, enrich(candidate, client)["patch"])
    assert final["date_basis"] == "event" and final["kind"] == "campus_talk"
    assert final["event_date"] is None
    assert final["field_observations"]["event_date"]["state"] == "parse_failed"
    assert final["start_time"] == "19:00" and final["campus_key"] == "wushan"
    validate_candidate(final, source)


def test_scut_inline_event_venue_has_its_own_official_scope(tmp_path):
    source = config()
    url = "https://cnsba.scut.edu.cn/2026/1009/c29313a9000001/page.htm"
    client = fetcher(tmp_path, {
        source["official_entry_url"]: fixture("scut_list.html"),
        url: '<div class="wp_articlecontent"><p>宣讲时间：9月13日19:00–21:00，华工五山校区33号楼203室。</p></div>',
    })
    candidate = discover(source, client)["records"][0]
    final = merge(candidate, enrich(candidate, client)["patch"])
    assert final["event_venue"] == "华工五山校区33号楼203室"
    assert final["campus_key"] == "wushan" and final["event_date"] is None
    assert final["field_observations"]["event_venue"]["state"] == "known"
    validate_candidate(final, source)


def test_gdut_public_compression_list_fact_first_and_date_precision(tmp_path):
    source = config("gdut_teachin")
    page = discover(source, fetcher(tmp_path, {source["official_entry_url"]: gdut_list()}))
    first, second = page["records"]
    assert first["event_date"] == "2026-10-12" and first["start_time"] == "14:30"
    assert first["event_venue"] == "大学城校区教2-317" and first["campus_key"] == "university_city"
    assert second["event_date"] == "2026-10-13" and second["start_time"] is None
    assert second["campus_key"] == "longdong"
    assert first["relevance"] == "unknown"
    assert page["next_cursor"].endswith("/page/2")
    validate_candidate(first, source)


def test_gdut_detail_work_locations_are_from_this_not_venue_or_footer(tmp_path):
    source = config("gdut_teachin")
    client = fetcher(tmp_path, {
        source["official_entry_url"]: gdut_list(),
        "https://career.gdut.edu.cn/teachin/view/id/9000001": gdut_detail(),
    })
    candidate = discover(source, client)["records"][0]
    result = enrich(candidate, client)
    final = merge(candidate, result["patch"])
    assert final["work_locations"] == ["广东省深圳市龙华区"]
    assert final["relevance"] == "related"
    assert final["published_date"] == "2026-10-09"
    assert final["job_fragments"] and final["job_fragments"][0]["scope"] == "partial"
    assert all("北京" not in value for value in final["work_locations"])
    validate_candidate(final, source)


def test_conflicting_current_list_detail_preserves_list_value_and_both_evidence(tmp_path):
    source = config("gdut_teachin")
    client = fetcher(tmp_path, {
        source["official_entry_url"]: gdut_list(),
        "https://career.gdut.edu.cn/teachin/view/id/9000001": gdut_detail(date="2026-10-13"),
    })
    candidate = discover(source, client)["records"][0]
    result = enrich(candidate, client)
    assert "event_date" not in result["patch"]
    final = merge(candidate, result["patch"])
    assert final["event_date"] == "2026-10-12"
    proof = final["field_observations"]["event_date"]
    assert proof["state"] == "conflict" and proof["value"] is None and len(proof["evidence"]) == 2
    validate_candidate(final, source)


def test_detail_absent_preserves_basic_record_and_does_not_claim_not_disclosed(tmp_path):
    source = config("gdut_teachin")
    client = fetcher(tmp_path, {
        source["official_entry_url"]: gdut_list(),
        "https://career.gdut.edu.cn/teachin/view/id/9000001": "<html><p>暂未取得正文</p></html>",
    })
    candidate = discover(source, client)["records"][0]
    result = enrich(candidate, client)
    assert result["patch"] == {}
    assert result["material_refs"][0]["parsing_status"] == "failed"
    assert candidate["event_venue"] == "大学城校区教2-317"


def test_partial_body_image_does_not_make_uncovered_fields_not_disclosed(tmp_path):
    source = config()
    client = fetcher(tmp_path, {
        source["official_entry_url"]: fixture("scut_list.html"),
        "https://cnsba.scut.edu.cn/2026/1009/c29313a9000001/page.htm":
            '<div class="wp_articlecontent"><p>校园招聘</p><img src="/poster.jpg"></div>',
    })
    candidate = discover(source, client)["records"][0]
    result = enrich(candidate, client)
    assert result["patch"]["field_observations"]["work_locations"]["state"] == "pending_extraction"
    assert result["material_refs"][0]["scope"]["coverage"] == "partial"


def test_public_slot_malformed_and_zip_expansion_are_bounded():
    raw = '<section id="content10"></section><script>Base64.decode(unzip("invalid"))</script>'
    _, warnings = decode_public_slots(raw)
    assert warnings
    bomb = '<section id="content10"></section>' + compressed("content10", "a" * 10_000)
    document, warnings = decode_public_slots(bomb, max_decoded_bytes=500)
    assert warnings and "a" * 1000 not in document.get_text()


def test_public_body_parent_html_expression_preserves_body_container():
    raw = '<div class="aContent"><div id="content102"></div></div>' + compressed(
        "content102", "<p>招聘岗位：电气开发岗。</p>", parent_html=True,
    )
    document, warnings = decode_public_slots(raw)
    assert not warnings
    assert document.select_one(".aContent").get_text() == "招聘岗位：电气开发岗。"


def test_scut_category_heading_does_not_replace_article_title(tmp_path):
    source = config()
    url = "https://cnsba.scut.edu.cn/2026/1009/c29313a9000001/page.htm"
    page = '<h2 class="big-title">就业资讯</h2><div class="inner-text"><h2 class="big-title">隔离真实文章结构</h2></div>'
    client = fetcher(tmp_path, {
        source["official_entry_url"]: fixture("scut_list.html"),
        url: page + '<div class="wp_articlecontent"><p>校园招聘</p></div>',
    })
    candidate = discover(source, client)["records"][0]
    assert enrich(candidate, client)["patch"]["title"] == "隔离真实文章结构"


def test_repeated_self_cursor_stops_without_complete_claim(tmp_path):
    source = config("gdut_jobfair")
    html = (
        '<ul class="infoList jobfairList"><li><a href="/jobfair/view/id/9000001">隔离双选会</a></li>'
        '<li>大学城校区</li><li>2026-10-29 14:00-17:00</li></ul>'
        '<a href="/jobfair">下一页</a>'
    )
    result = discover(source, fetcher(tmp_path, {source["official_entry_url"]: gdut_list(html)}))
    assert result["next_cursor"] is None
    assert result["completeness"] == "partial" and result["warnings"]


def test_gdut_ordinary_expired_time_does_not_replace_explicit_deadline(tmp_path):
    source = config("gdut_campus")
    html = '<ul class="infoList"><li><a href="/campus/view/id/9000003">隔离普通招聘</a></li><li>2026-10-09 14:31:52</li></ul>'
    detail = (
        '<div class="zp-details"><div class="details-title"><div class="title-message"><h5>隔离普通招聘</h5>'
        '<span class="expired_time">过期时间：2027-01-05</span></div></div>'
        '<div class="details-mge"><div class="aContent"><p>岗位遍布江西全省各设区市。</p>'
        '<p>简历投递（2026年10月15日截止）。</p></div></div></div>'
    )
    client = fetcher(tmp_path, {
        source["official_entry_url"]: gdut_list(html),
        "https://career.gdut.edu.cn/campus/view/id/9000003": detail,
    })
    candidate = discover(source, client)["records"][0]
    final = merge(candidate, enrich(candidate, client)["patch"])
    assert final["deadline"] == "2026-10-15"
    assert final["event_date"] is None and final["date_basis"] == "publication"
    assert final["work_locations"] == ["江西省各设区市"]
    assert final["field_observations"]["event_venue"]["state"] == "not_applicable"
    validate_candidate(final, source)


def test_material_hash_exact_bytes_and_reference_includes_url(tmp_path):
    url = "https://career.gdut.edu.cn/teachin"
    client = fetcher(tmp_path, {url: "公开测试字节"})
    result = client.get(url)
    digest = hashlib.sha256("公开测试字节".encode()).hexdigest()
    assert result["body"] == Path(result["raw_reference"]).read_bytes()
    assert result["material_hash"] == digest
    assert result["reference_key"] == hashlib.sha256((url + "\n" + digest).encode()).hexdigest()
    assert result["text"] == "公开测试字节"


@pytest.mark.parametrize("status", [401, 403, 412, 429, 483])
def test_restricted_status_archives_but_does_not_retry(tmp_path, status):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(status, content=b"restricted")
    transport = httpx.Client(transport=httpx.MockTransport(handler))
    client = Fetcher(tmp_path / "materials", client=transport)
    with pytest.raises(FetchError) as raised:
        client.get("https://career.gdut.edu.cn/teachin")
    assert raised.value.restricted and len(requests) == 1
    assert Path(raised.value.material_ref["raw_reference"]).read_bytes() == b"restricted"


def test_auth_redirect_is_archived_and_auth_target_never_requested(tmp_path):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://sso.scut.edu.cn/cas/login"}, content=b"redirect")
    client = Fetcher(tmp_path / "materials", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(FetchError) as raised:
        client.get("https://jyzx.scut.edu.cn/")
    assert raised.value.restricted and len(requests) == 1
    assert Path(raised.value.material_ref["raw_reference"]).exists()


@pytest.mark.parametrize("url", [
    "https://career.gdut.edu.cn/search/list?keyword=test",
    "https://career.gdut.edu.cn/campus?keyword=test",
    "https://untrusted.example/teachin",
    "http://career.gdut.edu.cn/teachin",
    "https://user:password@career.gdut.edu.cn/teachin",
])
def test_unsupported_targets_are_rejected_before_request(tmp_path, url):
    client = fetcher(tmp_path, {})
    with pytest.raises(FetchError):
        client.get(url)
    assert client.requests == 0


def test_bounded_connection_retry_and_request_budget(tmp_path):
    calls = []
    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("isolated network failure", request=request)
    client = Fetcher(tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)), max_requests=2)
    with pytest.raises(FetchError) as raised:
        client.get("https://career.gdut.edu.cn/teachin")
    assert raised.value.status == "network_failed" and len(calls) == 2
    with pytest.raises(FetchError) as raised:
        client.get("https://career.gdut.edu.cn/jobfair")
    assert raised.value.status == "budget_exhausted" and len(calls) == 2


def test_response_size_is_bounded(tmp_path):
    client = fetcher(tmp_path, {"https://career.gdut.edu.cn/teachin": "a" * 200}, max_bytes=100)
    with pytest.raises(FetchError) as raised:
        client.get("https://career.gdut.edu.cn/teachin")
    assert raised.value.status == "response_too_large"


def test_registered_config_adapter_and_unregistered_adapter():
    assert get_adapter(config("gdut_teachin")).__class__.__name__ == "GdutAdapter"
    with pytest.raises(ValueError):
        get_adapter("unregistered")
