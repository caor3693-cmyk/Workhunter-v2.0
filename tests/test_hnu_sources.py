"""Synthetic exact-school Cloud Career regressions; no live coverage claims."""
import hashlib

import pytest

from backend.domain import source_policy
from backend.domain.candidates import validate_candidate
from backend.sources import common
from backend.sources.hnu import HnuAdapter
from backend.sources.neepu import NeepuAdapter
from backend.sources.csust import CsustAdapter
from backend.sources.transport import FetchError


class Materials:
    def __init__(self, pages):
        self.pages, self.requests = pages, []

    def get(self, url):
        self.requests.append(url)
        text = self.pages[url]
        digest = hashlib.sha256(text.encode()).hexdigest()
        return {"url": url, "text": text, "material_hash": digest,
            "reference_key": hashlib.sha256((url + '\n' + digest).encode()).hexdigest(),
            "fetched_at": "2026-10-11T12:00:00+08:00", "raw_reference": "isolated-fixture/" + digest}


def policy_fixture(monkeypatch, key, host):
    original = source_policy.school_policy
    def fixture_policy(school_key, config_path=None):
        value = original(school_key, config_path)
        return {**value, "approved_hosts": [host], "platform_tenants": {},
                "campuses": [{"campus_key": "synthetic_main", "name": "合成主校区"}]} if school_key == key else value
    monkeypatch.setattr(source_policy, "school_policy", fixture_policy)
    monkeypatch.setattr(common, "school_policy", fixture_policy)


@pytest.mark.parametrize("key,host,adapter", [
    ("hnu", "scc.hnu.edu.cn", HnuAdapter),
    ("neepu", "jy.neepu.edu.cn", NeepuAdapter),
    ("csust", "csust.bysjy.com.cn", CsustAdapter),
])
def test_cloud_school_identity_full_event_year_start_only_and_explicit_major(monkeypatch, key, host, adapter):
    policy_fixture(monkeypatch, key, host)
    home, detail = f"https://{host}/", f"https://{host}/detail/career?id=9000201"
    config = {"school_key": key, "source_key": key + "_careers", "channel_key": "careers", "official_entry_url": home}
    listing = '<a href="/detail/career?id=9000201">合成单位</a><a href="https://other-school.example/detail/career?id=9000202">外校</a>'
    body = '<div class="main-inner"><div class="detail-module"><div class="dm-tit">宣讲会信息</div><div class="dm-cont">'
    body += '<h1 class="dm-text">宣讲单位：合成单位<a>企业工商信息</a></h1><p class="dm-text">宣讲时间：2026年10月12日 09:00</p><p class="dm-text">宣讲地点：合成主校区教室101</p></div></div>'
    body += '<div class="detail-module"><div class="dm-tit">单位简介</div><div class="dm-cont">企业开展电气业务。</div></div>'
    body += '<div class="detail-module"><div class="dm-tit">招聘简章</div><div class="dm-cont"><p>招聘岗位：研发工程师。</p><p>需求专业：电气工程、控制工程。</p><p>工作地点：重庆</p></div></div></div>'
    client = Materials({home: listing, detail: body})
    page = adapter.discover(config, client)
    assert len(page["records"]) == 1 and page["completeness"] == "partial"
    item = page["records"][0]
    patch = adapter.enrich(item, client)["patch"]
    final = {**item, **patch, "field_observations": {**item["field_observations"], **patch["field_observations"]}}
    assert final["event_date"] == "2026-10-12" and final["start_time"] == "09:00" and final["end_time"] is None
    assert final["title"] == "合成单位" and final["work_locations"] == ["重庆"]
    assert final["campus_key"] == "synthetic_main" and final["relevance"] == "related"
    validate_candidate(final, config)


def test_hnu_module_skeleton_not_counted_as_zero_or_coverage(monkeypatch):
    policy_fixture(monkeypatch, "hnu", "scc.hnu.edu.cn")
    source = {"school_key": "hnu", "source_key": "hnu_careers", "channel_key": "careers", "official_entry_url": "https://scc.hnu.edu.cn/index"}
    page = HnuAdapter.discover(source, Materials({source["official_entry_url"]: '<div id="careers"><script>loadJobs()</script></div>'}))
    assert not page["records"] and page["material_refs"][0]["parsing_status"] == "failed"


@pytest.mark.parametrize("url", ["https://hnu.bysjy.com.cn/", "https://scc.hnu.edu.cn/module/careers?menu_id=3231", "https://scc.hnu.edu.cn/index?token=bad"])
def test_hnu_unverified_cursor_never_requested(url):
    client = Materials({})
    config = {"school_key": "hnu", "source_key": "hnu_careers", "channel_key": "careers", "official_entry_url": "https://scc.hnu.edu.cn/index"}
    with pytest.raises(FetchError):
        HnuAdapter.discover(config, client, url)
    assert not client.requests


def test_hnu_missing_detail_body_keeps_known_fields():
    client = Materials({"https://scc.hnu.edu.cn/detail/career?id=9000201": '<div>登录后查看企业信息</div>'})
    item = {"school_key": "hnu", "source_key": "hnu_careers", "source_identity": "9000201", "source_url": "https://scc.hnu.edu.cn/detail/career?id=9000201", "date_basis": "event"}
    result = HnuAdapter.enrich(item, client)
    assert result["patch"] == {} and result["material_refs"][0]["parsing_status"] == "failed"


def test_hnu_redirected_other_record_keeps_fields():
    requested = "https://scc.hnu.edu.cn/detail/career?id=9000201"
    class Redirected(Materials):
        def get(self, url):
            value = super().get(url)
            value["url"] = url.replace("9000201", "9000202")
            return value
    result = HnuAdapter.enrich({"school_key": "hnu", "source_key": "hnu_careers", "source_identity": "9000201", "source_url": requested, "date_basis": "event"}, Redirected({requested: "其它公告"}))
    assert result["patch"] == {} and result["material_refs"][0]["parsing_status"] == "failed"


@pytest.mark.parametrize('body,locations,state', [
    ('<table><tr><td>工作地点</td><td>专业要求</td></tr><tr><td>深圳</td><td>电气</td></tr><tr><td>全国</td><td>机械</td></tr></table>', ['深圳', '全国'], 'known'),
    ('<table><tr><td>岗位名称</td><td>工作地点</td></tr><tr><td>有机合成类</td><td>上海</td></tr><tr><td>管理培训生（职能方向）</td><td>长沙</td></tr></table>', ['上海', '长沙'], 'known'),
    ('<table><tr><td>工作地点</td><td>专业要求</td></tr></table>', [], 'parse_failed'),
    ('<table><tr><td>岗位名称</td><td>工作地点</td></tr><tr><td colspan="2">不明确列归属</td></tr></table>', [], 'parse_failed'),
    ('<table><tr><td>工作地点</td><td>重庆主城区</td></tr></table>', ['重庆主城区'], 'known'),
    ('<p>工作地点：广东省广州市黄埔区科学大道18号B3栋1层、7层<span>（</span><span>实际岗位安排）</span></p>', ['广东省广州市黄埔区科学大道18号B3栋1层、7层（实际岗位安排）'], 'known'),
    ('<table><tr><td>岗位名称</td><td>学历要求</td><td>工作城市</td></tr><tr><td>有机合成类</td><td>本科</td><td rowspan="2">上海</td></tr><tr><td>分析类</td><td>硕士</td></tr></table>', ['上海'], 'known'),
    ('<p>招聘城市：深圳</p>', [], 'pending_extraction'),
    ('<table><tr><th>工作地点</th><th>职位类别</th></tr><tr><td>深圳</td><td>电气工程师</td></tr></table>', ['深圳'], 'known'),
    ('<table><tr><td>工作地点</td><td>职位类别</td></tr><tr><td>深圳</td><td>电气工程师</td></tr></table>', ['深圳'], 'known'),
    ('<p>工作地点：深圳<br>专业要求：电气工程<br>招聘岗位：研发工程师</p>', ['深圳'], 'known'),
    ('<p>工作地点：深圳 专业要求：电气工程 招聘岗位：研发工程师</p>', ['深圳'], 'known'),
])
def test_cloud_workplaces_follow_columns_not_next_flattened_text(body, locations, state):
    config = {'school_key':'hnu', 'source_key':'hnu_careers', 'channel_key':'careers', 'official_entry_url':'https://scc.hnu.edu.cn/'}
    url = 'https://scc.hnu.edu.cn/detail/career?id=9000201'
    listing = HnuAdapter.discover(config, Materials({config['official_entry_url']:'<a href="'+url+'">隔离表格单位</a>'}))['records'][0]
    html = '<div class="main-inner"><div class="detail-module"><div class="dm-tit">招聘简章</div><div class="dm-cont">'+body+'</div></div></div>'
    patch = HnuAdapter.enrich(listing, Materials({url:html}))['patch']
    assert patch['work_locations'] == locations
    assert patch['field_observations']['work_locations']['state'] == state
    assert all(value not in {'专业要求','有机合成类','管理培训生（职能方向）'} for value in locations)
    assert all(item['source_identity'] == '9000201' for item in patch['field_observations']['work_locations']['evidence'])


def test_cloud_location_conflict_retains_both_sides_at_evidence_limit():
    config = {'school_key':'hnu', 'source_key':'hnu_careers', 'channel_key':'careers', 'official_entry_url':'https://scc.hnu.edu.cn/'}
    url = 'https://scc.hnu.edu.cn/detail/career?id=9000201'
    item = HnuAdapter.discover(config, Materials({config['official_entry_url']:'<a href="'+url+'">隔离冲突单位</a>'}))['records'][0]
    item['work_locations'] = ['广州']
    item['field_observations']['work_locations'] = {'state':'known', 'value':['广州'], 'evidence':[{'locator':'old-'+str(index)} for index in range(16)]}
    html = '<div class="main-inner"><div class="detail-module"><div class="dm-tit">招聘简章</div><div class="dm-cont"><p>工作地点：深圳</p></div></div></div>'
    patch = HnuAdapter.enrich(item, Materials({url:html}))['patch']
    proof = patch['field_observations']['work_locations']
    assert proof['state'] == 'conflict' and 'work_locations' not in patch
    assert len(proof['evidence']) <= 16
    assert any(entry['locator'].startswith('old-') for entry in proof['evidence'])
    assert any('深圳' in entry.get('excerpt','') for entry in proof['evidence'])
    assert item['work_locations'] == ['广州']
