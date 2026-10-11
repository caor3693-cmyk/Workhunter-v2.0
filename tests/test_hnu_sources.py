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
