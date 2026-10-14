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


def event_config(channel):
    return {"school_key": "gzhu", "source_key": "gzhu_" + channel, "channel_key": channel,
        "official_entry_url": f"https://jy.gzhu.edu.cn/web/Index/{channel}-list"}


def event_card(channel, identity, *, schedule="2026/10/14 14:30 - 2026/10/14 16:30", venue="合成主校区文新220"):
    return (f'<a class="item" href="{channel}-detail?id={identity}"><div class="title">合成活动{identity}</div>'
        f'<div class="text"><span class="icon-shijian"></span>{schedule}</div>'
        f'<div class="text"><span class="icon-didian"></span>{venue}</div></a>')


@pytest.mark.parametrize("channel,kind", [("preach", "campus_talk"), ("jobfair", "job_fair")])
def test_gzhu_public_event_list_pagination_and_immediate_fields(monkeypatch, channel, kind):
    policy_fixture(monkeypatch, "gzhu", "jy.gzhu.edu.cn")
    config = event_config(channel)
    first = config["official_entry_url"]
    second = f"https://jy.gzhu.edu.cn/index.php/web/Index/{channel}-list?p=2"
    html = '<div class="container">' + event_card(channel, "90001") * 2 + '</div>'
    html += f'<ul class="pagination"><li><a aria-label="下一页" href="{second.replace("https:", "http:")}">下一页</a></li></ul>'
    client = Materials({first: html, second: '<div class="container">' + event_card(channel, "90002") + '</div>'})
    page = GzhuAdapter.discover(config, client)
    assert len(page["records"]) == 1 and page["next_cursor"] == second
    item = page["records"][0]
    assert item["kind"] == kind and item["date_basis"] == "event" and item["published_date"] is None
    assert item["event_date"] == "2026-10-14" and item["start_time"] == "14:30" and item["end_time"] == "16:30"
    assert item["event_venue"] == "合成主校区文新220" and item["campus_key"] == "synthetic_main"
    assert item["work_locations"] == [] and item["relevance"] == "unknown"
    validate_candidate(item, config)
    tail = GzhuAdapter.discover(config, client, page["next_cursor"])
    assert tail["records"][0]["source_identity"] == "90002" and tail["next_cursor"] is None
    validate_candidate(tail["records"][0], config)


@pytest.mark.parametrize("cursor", [
    "https://jy.gzhu.edu.cn/web/Index/jobfair-list?p=2",
    "https://jy.gzhu.edu.cn/index.php/web/Index/preach-list?p=2&p=3",
    "https://jy.gzhu.edu.cn/web/Index/preach-list?p=0",
    "https://jy.gzhu.edu.cn/web/Index/preach-list?p=2&keyword=x",
    "https://jy.gzhu.edu.cn/stu/Index/preach-list?p=2",
    "https://other.example/web/Index/preach-list?p=2",
    "http://jy.gzhu.edu.cn/web/Index/preach-list?p=2",
])
def test_gzhu_event_cursor_boundaries_reject_before_request(cursor):
    client = Materials({})
    with pytest.raises(FetchError):
        GzhuAdapter.discover(event_config("preach"), client, cursor)
    assert not client.requests


@pytest.mark.parametrize("target", [
    "https://jy.gzhu.edu.cn/web/Index/preach-list",
    "https://jy.gzhu.edu.cn/index.php/web/Index/preach-list?p=70",
    "https://jy.gzhu.edu.cn/index.php/web/Index/jobfair-list?p=2",
    "https://other.example/index.php/web/Index/preach-list?p=2",
])
def test_gzhu_event_bad_next_page_stops_without_reporting_complete(target):
    config = event_config("preach")
    html = '<div class="container">' + event_card("preach", "90001") + '</div>'
    html += f'<ul class="pagination"><li><a href="{target}">下一页</a></li></ul>'
    result = GzhuAdapter.discover(config, Materials({config["official_entry_url"]: html}))
    assert result["next_cursor"] is None and result["warnings"] and result["completeness"] == "partial"


def test_gzhu_event_empty_page_cannot_be_successful_zero():
    config = event_config("jobfair")
    page = GzhuAdapter.discover(config, Materials({config["official_entry_url"]: '<div class="container">暂无相关信息</div>'}))
    assert not page["records"] and page["material_refs"][0]["parsing_status"] == "failed"
    assert page["completeness"] == "partial" and page["warnings"]


def test_gzhu_event_start_only_keeps_date_precision_and_detail_failure(monkeypatch):
    policy_fixture(monkeypatch, "gzhu", "jy.gzhu.edu.cn")
    config = event_config("jobfair")
    html = '<div class="container">' + event_card("jobfair", "90001", schedule="2026/10/27 10:00") + '</div>'
    client = Materials({config["official_entry_url"]: html,
        "https://jy.gzhu.edu.cn/web/Index/jobfair-detail?id=90001": '<div>正文暂不可读</div>'})
    item = GzhuAdapter.discover(config, client)["records"][0]
    assert item["event_date"] == "2026-10-27" and item["start_time"] == "10:00" and item["end_time"] is None
    result = GzhuAdapter.enrich(item, client)
    assert result["patch"] == {} and result["material_refs"][0]["parsing_status"] == "failed"
    assert item["event_venue"] == "合成主校区文新220"


@pytest.mark.parametrize("channel", ["preach", "jobfair"])
def test_gzhu_event_detail_same_announcement_major_and_workplace(monkeypatch, channel):
    policy_fixture(monkeypatch, "gzhu", "jy.gzhu.edu.cn")
    config = event_config(channel)
    html = '<div class="container">' + event_card(channel, "90001") + '</div>'
    url = f"https://jy.gzhu.edu.cn/web/Index/{channel}-detail?id=90001"
    content = '<p>公司总部广州，开展电气业务。</p><p>招聘岗位：研发工程师。</p><p>需求专业：电气工程。</p><p>工作地点：深圳</p>'
    header = '<div class="header-wrapper">' + event_card(channel, "90001") + '</div>'
    body = ('<div class="activity-page-wrapper">' + header + '<div class="content-wrapper"><div class="col-xs-8"><div class="content">' + content + '</div></div></div></div>') if channel == "preach" else '<div class="page-content-detail">' + header + '<div class="content-wrapper">' + content + '</div></div>'
    client = Materials({config["official_entry_url"]: html, url: body})
    item = GzhuAdapter.discover(config, client)["records"][0]
    patch = GzhuAdapter.enrich(item, client)["patch"]
    final = {**item, **patch, "field_observations": {**item["field_observations"], **patch["field_observations"]}}
    assert final["work_locations"] == ["深圳"] and final["event_venue"] == "合成主校区文新220"
    assert final["relevance"] == "related" and final["published_date"] is None
    validate_candidate(final, config)


def test_gzhu_event_redirect_same_id_other_channel_does_not_supply_facts():
    requested = "https://jy.gzhu.edu.cn/web/Index/preach-detail?id=90001"
    class Redirected(Materials):
        def get(self, url):
            value = super().get(url)
            value["url"] = url.replace("preach-detail", "jobfair-detail")
            return value
    item = {"school_key": "gzhu", "source_key": "gzhu_preach", "source_identity": "90001", "source_url": requested}
    result = GzhuAdapter.enrich(item, Redirected({requested: '<div class="page-content-detail"><div class="content-wrapper">电气工程师</div></div>'}))
    assert result["patch"] == {} and result["material_refs"][0]["parsing_status"] == "failed"


def test_gzhu_real_jobfair_card_shape_and_p_marker_preserve_start_only():
    # Minimal public selector shape observed 2026-10-14; text and IDs synthetic.
    config = event_config("jobfair")
    html = '<div class="container"><a class="card content-block" href="jobfair-detail?id=90001">'
    html += '<h4 class="card-title">合成专场招聘会</h4><p class="card-text"><span class="icon-shijian"></span>2026/10/27 10:00</p>'
    html += '<p class="card-text"><span class="icon-didian"></span>合成校区体育馆</p></a></div>'
    item = GzhuAdapter.discover(config, Materials({config["official_entry_url"]: html}))["records"][0]
    assert item["title"] == "合成专场招聘会" and item["event_date"] == "2026-10-27"
    assert item["event_venue"] == "合成校区体育馆" and item["start_time"] == "10:00" and item["end_time"] is None
    validate_candidate(item, config)


def test_gzhu_event_job_location_column_does_not_promote_header_or_venue():
    # Minimal four-column public table shape from the same-announcement detail;
    # the employer, places, duties and IDs are synthetic; no full raw response.
    config = event_config("preach")
    listing = '<div class="container">' + event_card("preach", "90001") + '</div>'
    url = "https://jy.gzhu.edu.cn/web/Index/preach-detail?id=90001"
    body = '<div class="activity-page-wrapper"><div class="content-wrapper"><div class="col-xs-8"><div class="content">'
    body += '<table><tr><td>序号</td><td>岗位名称</td><td>工作地点</td><td>岗位 JD</td></tr>'
    body += '<tr><td>1</td><td>研发工程师</td><td>深圳</td><td><p>任职要求：电气工程专业。</p></td></tr>'
    body += '<tr><td>2</td><td>工程技术岗</td><td>东莞</td><td><p>任职要求：机械专业。</p></td></tr></table></div></div></div></div>'
    client = Materials({config["official_entry_url"]: listing, url: body})
    item = GzhuAdapter.discover(config, client)["records"][0]
    patch = GzhuAdapter.enrich(item, client)["patch"]
    assert patch["work_locations"] == ["深圳", "东莞"] and "岗位" not in patch["work_locations"]
    assert patch["relevance"] == "related" and item["event_venue"] == "合成主校区文新220"
    final = {**item, **patch, "field_observations": {**item["field_observations"], **patch["field_observations"]}}
    validate_candidate(final, config)


def test_gzhu_event_background_only_is_unknown_and_cross_day_end_not_invented():
    config = event_config("preach")
    listing = '<div class="container">' + event_card("preach", "90001", schedule="2026/10/14 20:00 - 2026/10/15 01:00") + '</div>'
    url = "https://jy.gzhu.edu.cn/web/Index/preach-detail?id=90001"
    body = '<div class="activity-page-wrapper"><div class="content-wrapper"><div class="col-xs-8"><div class="content"><p>公司从事电气制造。</p><p>招聘行政岗位。</p></div></div></div></div>'
    client = Materials({config["official_entry_url"]: listing, url: body})
    item = GzhuAdapter.discover(config, client)["records"][0]
    assert item["event_date"] == "2026-10-14" and item["start_time"] == "20:00" and item["end_time"] is None
    patch = GzhuAdapter.enrich(item, client)["patch"]
    assert patch.get("relevance", "unknown") == "unknown" and patch["work_locations"] == []
