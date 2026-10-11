from backend.sources.registry import capabilities, get_adapter
from backend.domain.source_policy import FIXED_SCHOOLS
import pytest


def test_fixed_ten_school_registry_separates_registration_and_coverage():
    rows=capabilities()
    assert {row['school_key'] for row in rows}==FIXED_SCHOOLS
    assert {row['school_key'] for row in rows if row['state']=='implemented'}==FIXED_SCHOOLS-{'ncepu','csu'}
    assert all(row['state']=='registered_limited' for row in rows if row['school_key'] in {'ncepu','csu'})
    assert all(row['coverage']=='requires_run_evidence' for row in rows)
    with pytest.raises(ValueError,match='尚未实现'):get_adapter({'school_key':'ncepu','adapter':'unimplemented'})
