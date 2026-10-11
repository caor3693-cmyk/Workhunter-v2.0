"""Beijing restriction and Baoding's unverified structure stay distinct."""
import pytest
from backend.sources.ncepu import NcepuBeijingAdapter, NcepuBaodingAdapter
from backend.sources.transport import FetchError
from test_hnu_sources import Materials


def test_ncepu_beijing_483_stays_stopped():
    client = Materials({})
    with pytest.raises(FetchError) as error:
        NcepuBeijingAdapter.discover({"school_key": "ncepu"}, client)
    assert error.value.restricted and error.value.status_code == 483 and not client.requests


def test_baoding_is_not_beijing_or_automatic_coverage():
    url = "https://jiuye.ncepu.edu.cn/"
    source = {"school_key": "ncepu", "source_key": "ncepu_baoding", "channel_key": "baoding", "official_entry_url": url}
    page = NcepuBaodingAdapter.discover(source, Materials({url: "<html>结构待核验</html>"}))
    assert not page["records"] and page["material_refs"][0]["parsing_status"] == "failed"
    with pytest.raises(FetchError):
        NcepuBaodingAdapter.discover(source, Materials({}), "https://job.ncepu.edu.cn/")
