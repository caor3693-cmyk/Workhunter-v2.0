"""A previously observed real restriction cannot be erased by a fixture."""
import pytest
from backend.sources.csu import CsuAdapter
from backend.sources.transport import FetchError
from test_hnu_sources import Materials


def test_csu_403_stops_every_request_without_changing_channel():
    client = Materials({"https://career.csu.edu.cn/": "pretend success"})
    with pytest.raises(FetchError) as error:
        CsuAdapter.discover({"school_key": "csu"}, client)
    assert error.value.restricted and error.value.status_code == 403 and not client.requests
    with pytest.raises(FetchError):
        CsuAdapter.enrich({"school_key": "csu"}, client)
    assert not client.requests
