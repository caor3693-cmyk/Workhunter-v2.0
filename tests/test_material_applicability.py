"""Announcement ownership is enforced by the production writer and projection."""
from copy import deepcopy
import json
import sqlite3

import pytest

from backend.services.ingestion import ingest_page, ingest_detail
from backend.storage.database import initialize_database, read_database
from backend.services.queries import detail
from test_ingestion import source, material, candidate, run, snapshot


@pytest.fixture
def database(tmp_path):
    path=tmp_path/'applicability.sqlite3'
    initialize_database(path,fixture=True)
    return path


@pytest.mark.parametrize('later_b',[False,True])
def test_a_cannot_borrow_detail_material_of_b_even_before_b_is_collected(database,later_b):
    config=source(); archive=material(config,'detail-b'); archive['official_record_id']='B'
    item=candidate(config,archive,identity='A')
    run_id=run(database)
    before=snapshot(database)
    with pytest.raises(ValueError,match='另一条公告'):
        ingest_page(database,config,[item],[archive],run_id=run_id,fixture=True)
    assert snapshot(database)==before
    if later_b:
        b=candidate(config,archive,identity='B')
        ingest_page(database,config,[b],[archive],run_id=run_id,fixture=True)
        assert snapshot(database)['rows'][0]['source_identity']=='B'


def test_shared_list_has_separate_verified_identity_locator_associations(database):
    config=source(); archive=material(config); run_id=run(database)
    a=candidate(config,archive,identity='A'); b=candidate(config,archive,identity='B')
    ingest_page(database,config,[a,b],[archive],run_id=run_id,fixture=True)
    with read_database(database) as (connection,_):
        assert connection.execute('SELECT COUNT(*) FROM source_materials').fetchone()[0]==1
        assert {r[0] for r in connection.execute('SELECT DISTINCT source_identity FROM opportunity_materials')}=={'A','B'}
        assert detail(connection,1)['published_date']==detail(connection,2)['published_date']
    del a['field_observations']['event_date']['evidence'][0]['source_identity']
    before=snapshot(database)
    with pytest.raises(ValueError): ingest_page(database,config,[a],[archive],run_id=run_id,fixture=True)
    assert snapshot(database)==before


def test_shared_list_claim_cannot_use_another_records_locator(database):
    config=source(); archive=material(config); item=candidate(config,archive,identity='A')
    item['field_observations']['event_date']['evidence'][0]['locator']='record:B/event_date'
    run_id=run(database)
    before=snapshot(database)
    with pytest.raises(ValueError,match='身份定位'):
        ingest_page(database,config,[item],[archive],run_id=run_id,fixture=True)
    assert snapshot(database)==before


def test_attachment_requires_parent_identity_locator_and_exact_link_chain(database):
    config=source(); archive=material(config,'detail-a'); archive['official_record_id']='A'
    item=candidate(config,archive,identity='A')
    proof=deepcopy(item['field_observations']['published_date']['evidence'][0]);proof['locator']="body a[href='https://jyzx.scut.edu.cn/attachment/a.pdf']"
    target='https://jyzx.scut.edu.cn/attachment/a.pdf'
    item['attachments']=[{'url':target,'label':'公开岗位附件','scope':'this_announcement','evidence':[proof],'link_chain':{**proof,'target_url':target}}]
    run_id=run(database)
    ingest_detail(database,config,item,[archive],run_id=run_id,fixture=True)
    with read_database(database) as (connection,_):
        assert detail(connection,1)['attachments'][0]['url']==target
    item['attachments'][0]['link_chain']['target_url']=target+'?other=1'
    before=snapshot(database)
    with pytest.raises(ValueError,match='链接链'):
        ingest_detail(database,config,item,[archive],run_id=run_id,fixture=True)
    assert snapshot(database)==before


def test_bad_optional_attachment_does_not_hide_reliable_core_and_get_never_writes(database):
    config=source(); archive=material(config); item=candidate(config,archive); run_id=run(database)
    ingest_page(database,config,[item],[archive],run_id=run_id,fixture=True)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE opportunities SET attachments_json='[{\"url\":\"javascript:bad\"}]'")
    before=database.read_bytes()
    with read_database(database) as (connection,_):
        result=detail(connection,1)
        assert result['title']==item['title'] and result['event_venue']==item['event_venue']
        assert result['attachments']==[] and result['supplemental_status']=='pending_verification'
    assert database.read_bytes()==before


def test_sqlite_rejects_material_reassignment_after_verified_association(database):
    config=source(); archive=material(config,'detail-a');archive['official_record_id']='A';run_id=run(database)
    ingest_page(database,config,[candidate(config,archive,identity='A')],[archive],run_id=run_id,fixture=True)
    with sqlite3.connect(database) as connection,pytest.raises(sqlite3.IntegrityError,match='applicability'):
        connection.execute("UPDATE source_materials SET official_record_id='B'")


def test_short_numeric_id_cannot_match_another_list_record(database):
    config=source();archive=material(config);item=candidate(config,archive,identity='12');run_id=run(database)
    item['field_observations']['event_date']['evidence'][0]['locator']='record:312/event_date'
    before=snapshot(database)
    with pytest.raises(ValueError,match='身份定位'):ingest_page(database,config,[item],[archive],run_id=run_id,fixture=True)
    assert snapshot(database)==before


def attachment_candidate(config,core,body):
    item=candidate(config,core,identity='A')
    target='https://jyzx.scut.edu.cn/attachment/a.pdf'
    proof=deepcopy(candidate(config,body,identity='A')['field_observations']['published_date']['evidence'][0])
    proof['locator']="body a[href='"+target+"']"
    item['attachments']=[{'url':target,'label':'岗位附件','scope':'this_announcement','evidence':[proof],'link_chain':{**proof,'target_url':target}}]
    return item


def test_reobserving_identical_attachment_time_or_material_hash_is_not_fact_change(database):
    config=source();body=material(config,'body');body['official_record_id']='A'
    item=attachment_candidate(config,body,body)
    ingest_detail(database,config,item,[body],run_id=run(database,'run-a'),fixture=True)
    before=snapshot(database)
    repeated=deepcopy(item)
    repeated['attachments'][0]['link_chain']['observed_at']='2026-10-11T18:00:00+08:00'
    repeated['attachments'][0]['link_chain']['parser_version']='fixture-2'
    result=ingest_detail(database,config,repeated,[body],run_id=run(database,'run-b'),fixture=True)
    after=snapshot(database)
    assert result['unchanged']==1 and after['rows']==before['rows']
    assert after['metadata']['dataset_id']==before['metadata']['dataset_id'] and after['changes']==before['changes']


def test_optional_material_bad_metadata_is_isolated_in_get_and_explicit_write(database):
    config=source();core=material(config,'list');body=material(config,'attachment-body');body['official_record_id']='A'
    item=attachment_candidate(config,core,body)
    ingest_detail(database,config,item,[core,body],run_id=run(database,'run-a'),fixture=True)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE source_materials SET scope_json='broken-json' WHERE reference_key='attachment-body'")
    before=database.read_bytes()
    with read_database(database) as (connection,_):
        result=detail(connection,1)
        assert result['event_date']=='2026-10-20' and result['attachments']==[]
        assert result['supplemental_status']=='pending_verification'
    assert database.read_bytes()==before
    fresh=candidate(config,core,identity='A')
    fresh['title']='更新后的原标题'
    ingest_page(database,config,[fresh],[core],run_id=run(database,'run-b'),fixture=True)
    with read_database(database) as (connection,_):
        result=detail(connection,1)
        assert result['event_date']=='2026-10-20' and result['attachments']==[]
        assert connection.execute('SELECT COUNT(*) FROM quarantined_evidence').fetchone()[0]==1
        assert connection.execute("SELECT COUNT(*) FROM processing_tasks WHERE task_kind='maintenance'").fetchone()[0]==1
