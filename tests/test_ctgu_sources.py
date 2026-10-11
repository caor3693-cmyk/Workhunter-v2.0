"""Synthetic CTGU compressed columns and announcement-local major table."""
from backend.sources.ctgu import CtguAdapter
from backend.domain.candidates import validate_candidate
from test_hnu_sources import Materials, policy_fixture


def test_ctgu_current_major_table_without_body_is_known_but_partial(monkeypatch):
    policy_fixture(monkeypatch, "ctgu", "ctgu.91wllm.cn")
    config = {"school_key": "ctgu", "source_key": "ctgu_campus", "channel_key": "campus", "official_entry_url": "https://ctgu.91wllm.cn/campus"}
    url = "https://ctgu.91wllm.cn/campus/view/id/9000401"
    listing = '<ul class="infoList"><li><a href="/campus/view/id/9000401">合成集团2027校园招聘</a></li><li>2026-10-09</li></ul>'
    detail = '<div class="zp-details"><div class="details-title"><ul class="share"><li>发布时间：2026-10-09 16:25</li></ul></div><div class="details-mge"><div class="aContent"></div></div>'
    detail += '<table><thead><tr><th>序号</th><th>职位信息</th><th>需求专业</th></tr></thead><tbody><tr><td>1</td><td><div class="info-text"><a href="/job/view/id/2/from_type/4/from_id/9000401">综合研发</a><ul><li>7500-8499</li><li>湖南省 - 长沙市</li><li>本科</li></ul></div></td><td>土木类、电气类、自动化类</td></tr></tbody></table></div>'
    client = Materials({config["official_entry_url"]: listing, url: detail})
    item = CtguAdapter.discover(config, client)["records"][0]
    result = CtguAdapter.enrich(item, client)
    patch = result["patch"]
    final = {**item, **patch, "field_observations": {**item["field_observations"], **patch["field_observations"]}}
    assert final["relevance"] == "related" and final["work_locations"] == ["湖南省 - 长沙市"]
    assert final["deadline"] is None and final["event_date"] is None
    assert result["material_refs"][0]["scope"]["coverage"] == "partial"
    page_scope = result["material_refs"][0]["scope"]
    assert page_scope["type"] == "this_announcement"
    validate_candidate(final, config)


def test_ctgu_five_cell_event_venue_and_tenant_pagination(monkeypatch):
    policy_fixture(monkeypatch, "ctgu", "ctgu.91wllm.cn")
    url = "https://ctgu.91wllm.cn/teachin"
    config = {"school_key": "ctgu", "source_key": "ctgu_teachin", "channel_key": "teachin", "official_entry_url": url}
    html = '<ul class="infoList"><li><a href="/teachin/view/id/9000402">合成单位</a></li><li>线下宣讲会</li><li>三峡大学</li><li>合成主校区机械楼M2404</li><li>2026-10-12 14:30-18:00（周一）</li></ul><a href="/teachin/index/domain/ctgu/page/2">下一页</a>'
    page = CtguAdapter.discover(config, Materials({url: html}))
    item = page["records"][0]
    assert item["event_venue"] == "合成主校区机械楼M2404" and item["event_date"] == "2026-10-12"
    assert item["original_kind"] == "线下宣讲会" and item["campus_key"] == "synthetic_main"
    assert page["next_cursor"] == "https://ctgu.91wllm.cn/teachin/index/domain/ctgu/page/2"
