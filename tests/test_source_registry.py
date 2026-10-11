from backend.sources.registry import capabilities, get_adapter
from backend.domain.source_policy import FIXED_SCHOOLS
import pytest


def test_fixed_ten_school_registry_reports_pending_honestly():
    rows=capabilities()
    assert {row['school_key'] for row in rows}==FIXED_SCHOOLS
    assert {row['school_key'] for row in rows if row['state']=='implemented'}=={'scut','gdut'}
    assert all(row['state']=='pending' for row in rows if row['school_key'] not in {'scut','gdut'})
    with pytest.raises(ValueError,match='尚未实现'):get_adapter({'school_key':'ncepu','adapter':'unimplemented'})
