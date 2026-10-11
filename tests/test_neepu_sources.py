"""NEEPU boundaries: public role rows cannot use another announcement."""
from backend.sources.neepu import NeepuAdapter
from backend.sources.transport import FetchError
from test_hnu_sources import Materials, policy_fixture
import pytest


def test_neepu_wrong_detail_identity_rejected_before_request():
    client = Materials({})
    with pytest.raises(FetchError):
        NeepuAdapter.enrich({"school_key": "neepu", "date_basis": "event", "source_identity": "9000301", "source_url": "https://jy.neepu.edu.cn/detail/career?id=9000302"}, client)
    assert not client.requests


def test_neepu_foreign_career_job_row_not_promoted(monkeypatch):
    policy_fixture(monkeypatch, "neepu", "jy.neepu.edu.cn")
    url = "https://jy.neepu.edu.cn/detail/career?id=9000301"
    text = '<div class="main-inner"><div class="detail-module"><div class="dm-tit">招聘职位</div><div class="dm-cont">'
    text += '<div class="dm-text"><a href="/detail/job?id=1&amp;career_id=9999999">电气岗</a><p>招聘专业：电气类</p></div></div></div></div>'
    item = {"school_key": "neepu", "source_key": "neepu_careers", "date_basis": "event", "source_identity": "9000301", "source_url": url, "field_observations": {}}
    result = NeepuAdapter.enrich(item, Materials({url: text}))
    assert result["patch"].get("relevance", "unknown") == "unknown"
    assert result["material_refs"][0]["parsing_status"] == "partial"
