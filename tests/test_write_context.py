from copy import deepcopy
import json
from datetime import datetime, timedelta

import pytest

from backend.services.ingestion import commit_facts, commit_facts_in_transaction, ingest_page
from backend.services import maintenance
from backend.sources.common import candidate_base, evidence, set_known
from backend.storage.database import initialize_database, read_database
from backend.storage.write import WriteContext, WriteConflict, writer_transaction
from test_ingestion import source, material, candidate, run, snapshot, now
from test_maintenance import maintenance_setup, request, commit_request, import_record, revert


@pytest.fixture
def database(tmp_path):
    path=tmp_path/'contexts.sqlite3';initialize_database(path,fixture=True);return path


def operation(database,op='op-a',actor='maintainer'):
    with writer_transaction(database) as (connection,_):
        connection.execute("INSERT INTO manual_operations(id,actor,operation_type,preview_hash,input_json,difference_json,expires_at,status) VALUES (?,?,'manual_supplement','hash','{}','{}',?,'preview')",(op,actor,(datetime.fromisoformat(now())+timedelta(minutes=10)).isoformat()))
    return op


@pytest.mark.parametrize('kwargs',[{}, {'run_id':'run','operation_id':'operation'}, {'run_id':'run','base_version':True}])
def test_context_requires_exactly_one_real_origin_and_integer_version(kwargs):
    with pytest.raises(ValueError):WriteContext(actor='worker',reason='reason',idempotency_key='key',**kwargs)


def test_operation_facts_commit_with_no_fabricated_run_and_receipt_replays(database):
    config=source();archive=material(config);item=candidate(config,archive)
    op=operation(database)
    context=WriteContext(actor='maintainer',operation_id=op,reason='官方公开材料补录',idempotency_key='same',change_kind='manual_supplement',base_version=0)
    with writer_transaction(database) as (connection,metadata):
        result=commit_facts_in_transaction(connection,metadata,config,[item],[archive],context,fixture=True)
        connection.execute("UPDATE manual_operations SET status='committed',expires_at='2000-01-01T00:00:00+08:00' WHERE id=?",(op,))
    before=snapshot(database)
    assert commit_facts(database,config,[item],[archive],context,fixture=True)['replayed'] is True
    assert snapshot(database)==before
    with read_database(database) as (connection,_):
        assert connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==0
        change=connection.execute('SELECT * FROM changes').fetchone()
        assert change['manual_operation_id']==op and change['run_id'] is None
        assert change['actor']=='maintainer' and change['reason']==context.reason
        assert change['write_context_key']==result['context_key']
    changed=deepcopy(item);changed['title']='different'
    with pytest.raises(WriteConflict,match='不同输入'):
        commit_facts(database,config,[changed],[archive],context,fixture=True)
    assert snapshot(database)==before


def test_stale_version_rolls_back_material_receipt_and_fact_change(database):
    config=source();archive=material(config);item=candidate(config,archive);run_id=run(database)
    ingest_page(database,config,[item],[archive],run_id=run_id,fixture=True)
    op=operation(database)
    context=WriteContext(actor='maintainer',operation_id=op,reason='更正',idempotency_key='stale',change_kind='manual_correction',base_version=0)
    revised=material(config,'revision');item['title']='修订标题'
    before=snapshot(database)
    with pytest.raises(WriteConflict,match='版本'):
        commit_facts(database,config,[item],[revised],context,fixture=True)
    assert snapshot(database)==before


def automatic_list(config,title,reference):
    archive=material(config,reference)
    archive.update(source_url=request()['url'],official_record_id='1212')
    item=candidate_base(config,'1212',title,archive['source_url'],'campus_talk',None,'event')
    set_known(item,'published_date','2026-10-12',archive,'record:1212/published_date','合成自动列表发布时间 2026-10-12')
    return item,archive


def test_automatic_list_revives_visibility_once_without_withdrawn_manual_date_or_location(maintenance_setup):
    settings,principal=maintenance_setup;created=import_record(settings,principal)
    revert(settings,principal,created['operation_id'])
    hidden=maintenance.read_opportunity(settings,principal,1,environment='isolated')
    assert hidden['visible'] is False and hidden['event_date']=='2026-10-20' and hidden['work_locations']==['深圳市']
    before=snapshot(settings.acceptance_db_path)
    config=maintenance._config('gdut','gdut_teachin');item,archive=automatic_list(config,'合成自动列表的新标题','revival-list')
    run_id=run(settings.acceptance_db_path,'run-revival-list')
    receipt=ingest_page(settings.acceptance_db_path,config,[item],[archive],run_id=run_id,fixture=True,task_kind='list')
    record=maintenance.read_opportunity(settings,principal,1,environment='isolated',history=True)
    assert receipt['modified']==1 and receipt['new']==0 and record['visible'] is True
    assert record['version']==hidden['version']+1 and record['dataset_id']!=before['metadata']['dataset_id']
    assert record['title']==item['title'] and record['published_date']=='2026-10-12'
    for field in ('event_date','start_time','end_time','event_venue'):
        assert record[field] is None and record['field_observations'][field]['state']=='not_collected'
    assert record['work_locations']==[] and record['relevance']=='unknown'
    visibility=[change for change in record['history'] if change['field_name']=='__visibility__' and change['run_id']==run_id]
    assert len(visibility)==1 and json.loads(visibility[0]['before_json']) is False and json.loads(visibility[0]['after_json']) is True
    after=snapshot(settings.acceptance_db_path)
    assert ingest_page(settings.acceptance_db_path,config,[item],[archive],run_id=run_id,fixture=True,task_kind='list')['replayed']
    assert snapshot(settings.acceptance_db_path)==after


def test_noncore_manual_title_and_job_fragment_keep_later_official_contributions_on_revert(maintenance_setup):
    settings,principal=maintenance_setup;import_record(settings,principal)
    payload=request(operation_type='correction',fields=['title','job_fragments'])
    payload['public_text']=payload['public_text'].replace('标题：合成隔离电气招聘','标题：合成人工更正标题').replace('招聘岗位：电气工程师','招聘岗位：电气研发工程师')
    changed=maintenance.preview_materials(settings,principal,payload)
    correction=maintenance.commit_operation(settings,principal,commit_request(changed))
    config=maintenance._config('gdut','gdut_teachin');item,archive=automatic_list(config,'合成后来官方标题','noncore-later-official')
    item['job_fragments']=[{'text':'招聘岗位：电气测试工程师','scope':'partial','evidence':[
        evidence(archive,'record:1212/job_fragment','招聘岗位：电气测试工程师')]}]
    run_id=run(settings.acceptance_db_path,'run-noncore-official')
    ingest_page(settings.acceptance_db_path,config,[item],[archive],run_id=run_id,fixture=True,task_kind='detail')
    protected=maintenance.read_opportunity(settings,principal,1,environment='isolated')
    assert protected['title']=='合成人工更正标题'
    assert any('电气研发' in piece['text'] for piece in protected['job_fragments'])
    with read_database(settings.acceptance_db_path) as (connection,_):
        observed={row['field_name']:json.loads(row['snapshot_json']) for row in connection.execute('SELECT * FROM official_observations WHERE opportunity_id=1 AND run_id=?',(run_id,))}
        assert observed['title']['value']=='合成后来官方标题'
        assert observed['job_fragments']['value'][0]['text']=='招聘岗位：电气测试工程师'
        assert observed['title']['evidence'] and observed['job_fragments']['evidence']
    preview,receipt=revert(settings,principal,correction['operation_id'])
    assert preview['candidate']['title']=='合成后来官方标题' and receipt['visible'] is True
    record=maintenance.read_opportunity(settings,principal,1,environment='isolated')
    assert record['title']=='合成后来官方标题' and record['job_fragments'][0]['text']=='招聘岗位：电气测试工程师'


def test_list_without_job_body_cannot_claim_empty_job_fragment_as_later_official_fact(maintenance_setup):
    settings,principal=maintenance_setup;import_record(settings,principal)
    original=maintenance.read_opportunity(settings,principal,1,environment='isolated')['job_fragments']
    assert original
    payload=request(operation_type='correction',fields=['job_fragments'])
    payload['public_text']=payload['public_text'].replace('招聘岗位：电气工程师','招聘岗位：电气研发工程师')
    preview=maintenance.preview_materials(settings,principal,payload)
    changed=maintenance.commit_operation(settings,principal,commit_request(preview))
    config=maintenance._config('gdut','gdut_teachin');item,archive=automatic_list(config,'合成列表重见，仅披露标题与发布日期','list-no-job-body')
    ingest_page(settings.acceptance_db_path,config,[item],[archive],run_id=run(settings.acceptance_db_path,'run-list-no-job-body'),fixture=True,task_kind='list')
    restored,_=revert(settings,principal,changed['operation_id'])
    assert restored['candidate']['job_fragments']
    assert [piece['text'] for piece in restored['candidate']['job_fragments']]==[piece['text'] for piece in original]


def test_same_value_manual_contribution_invalidates_older_correction_preview_without_version_change(maintenance_setup):
    settings,principal=maintenance_setup;created=import_record(settings,principal)
    stale=maintenance.preview_materials(settings,principal,request(date='2026-10-21',operation_type='correction',fields=['event_date']))
    same=maintenance.preview_materials(settings,principal,request(date='2026-10-20',operation_type='correction',fields=['event_date']))
    later=maintenance.commit_operation(settings,principal,commit_request(same))
    assert later['modified']==0 and later['version']==stale['base_version']
    with read_database(settings.acceptance_db_path) as (connection,_):
        assert connection.execute("SELECT operation_id FROM field_decisions WHERE opportunity_id=1 AND field_name='event_date'").fetchone()[0]==later['operation_id']
    unchanged=snapshot(settings.acceptance_db_path)
    with pytest.raises(WriteConflict,match='人工贡献'):
        maintenance.commit_operation(settings,principal,commit_request(stale))
    assert snapshot(settings.acceptance_db_path)==unchanged
    fresh=maintenance.preview_materials(settings,principal,request(date='2026-10-21',operation_type='correction',fields=['event_date']))
    current=maintenance.commit_operation(settings,principal,commit_request(fresh))
    revert(settings,principal,created['operation_id'])
    restored,receipt=revert(settings,principal,current['operation_id'])
    assert receipt['visible'] is True and restored['candidate']['event_date']=='2026-10-20'
    with read_database(settings.acceptance_db_path) as (connection,_):
        assert connection.execute("SELECT operation_id FROM field_decisions WHERE opportunity_id=1 AND field_name='event_date'").fetchone()[0]==later['operation_id']


def test_revert_of_manual_revival_with_later_list_never_restores_hidden_history_fields(maintenance_setup):
    settings,principal=maintenance_setup;created=import_record(settings,principal)
    revert(settings,principal,created['operation_id'])
    payload=request()
    payload['public_text']='标题：合成维护重新取得的公告\n发布时间：2026-10-12\n招聘岗位：销售、人力、市场'
    preview=maintenance.preview_materials(settings,principal,payload)
    restored=maintenance.commit_operation(settings,principal,commit_request(preview))
    config=maintenance._config('gdut','gdut_teachin');item,archive=automatic_list(config,'合成后来列表的明确标题','list-after-manual-revival')
    ingest_page(settings.acceptance_db_path,config,[item],[archive],run_id=run(settings.acceptance_db_path,'run-after-manual-revival'),fixture=True,task_kind='list')
    reverted,receipt=revert(settings,principal,restored['operation_id'])
    assert receipt['visible'] is True
    record=maintenance.read_opportunity(settings,principal,1,environment='isolated')
    assert record['event_date'] is None and record['event_venue'] is None and record['work_locations']==[]
    assert reverted['candidate']['title']==item['title'] and record['title']==item['title']
