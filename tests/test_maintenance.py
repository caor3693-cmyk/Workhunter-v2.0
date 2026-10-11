"""Real production services on synthetic, isolated files; no official sample claims."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
import httpx

from backend.config import ROOT
from backend.services import maintenance
from backend.services.discovery import register_sources
from backend.services.ingestion import ingest_detail, save_task
from backend.storage.database import initialize_database, read_database
from backend.storage.write import WriteConflict, writer_transaction
from test_ingestion import candidate, material, run, snapshot
from test_sources import gdut_detail


@pytest.fixture
def maintenance_setup(tmp_path):
    real=tmp_path/'auth-and-real.synthetic.sqlite3';isolated=tmp_path/'isolated.synthetic.sqlite3'
    initialize_database(real);initialize_database(isolated,fixture=True)
    config=json.loads((ROOT/'config/schools.json').read_text(encoding='utf-8'))
    register_sources(real,config);register_sources(isolated,config,fixture=True)
    principal={'session_id':'a'*64,'actor':'synthetic-maintainer'}
    expires=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    with writer_transaction(real) as (connection,_):
        connection.execute('INSERT INTO maintenance_sessions(session_hash,csrf_hash,actor,created_at,expires_at) VALUES (?,?,?,?,?)',
            (principal['session_id'],'b'*64,principal['actor'],datetime.now(timezone.utc).isoformat(),expires))
    return SimpleNamespace(db_path=real,acceptance_db_path=isolated),principal


def request(environment='isolated',date='2026-10-20',**extra):
    return {'environment':environment,'operation_type':'supplement','school_key':'gdut','source_key':'gdut_teachin',
        'url':'https://career.gdut.edu.cn/teachin/view/id/1212','reason':'合成隔离验收：补录明确公开材料',
        'public_text':'标题：合成隔离电气招聘\n发布时间：2026-10-12\n宣讲时间：'+date+
            ' 14:30-16:00\n举办地点：大学城校区教学楼\n工作地点：深圳市\n招聘岗位：电气工程师',**extra}


def commit_request(preview):
    return {key:preview[key] for key in maintenance.COMMIT_KEYS}


def import_record(settings,principal,environment='isolated'):
    preview=maintenance.preview_materials(settings,principal,request(environment))
    return maintenance.commit_operation(settings,principal,commit_request(preview))


def test_preview_has_no_business_effect_and_commit_archives_manual_provenance(maintenance_setup):
    settings,principal=maintenance_setup
    original=snapshot(settings.acceptance_db_path)
    preview=maintenance.preview_materials(settings,principal,request())
    assert preview['candidate']['event_date']=='2026-10-20' and preview['base_version']==0
    after=snapshot(settings.acceptance_db_path)
    assert after['rows']==original['rows'] and after['changes']==original['changes'] and after['materials']==[]
    assert after['metadata']==original['metadata']
    result=maintenance.commit_operation(settings,principal,commit_request(preview))
    assert result['new']==1 and result['version']==1 and result['environment']=='isolated'
    saved=snapshot(settings.acceptance_db_path)
    assert saved['metadata']['data_mode']=='isolated_fixture'
    assert json.loads(saved['materials'][0]['scope_json'])['provenance']=='maintainer_public_text'
    assert saved['changes'][0]['manual_operation_id']==preview['operation_id'] and saved['changes'][0]['run_id'] is None
    with read_database(settings.acceptance_db_path) as (connection,_):
        assert connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==0
        assert connection.execute("SELECT last_success_at FROM sources WHERE source_key='gdut_teachin'").fetchone()[0] is None
    assert snapshot(settings.db_path)['rows']==[]


def test_same_commit_replays_after_expiry_and_later_target_update(maintenance_setup):
    settings,principal=maintenance_setup
    preview=maintenance.preview_materials(settings,principal,request());binding=commit_request(preview)
    first=maintenance.commit_operation(settings,principal,binding)
    second=maintenance.preview_materials(settings,principal,request(date='2026-10-21',operation_type='correction',fields=['event_date']))
    maintenance.commit_operation(settings,principal,commit_request(second))
    with writer_transaction(settings.acceptance_db_path) as (connection,_):
        connection.execute("UPDATE manual_operations SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(first['operation_id'],))
    before=snapshot(settings.acceptance_db_path)
    replay=maintenance.commit_operation(settings,principal,binding)
    assert replay=={**first,'replayed':True} and snapshot(settings.acceptance_db_path)==before


@pytest.mark.parametrize('changed',[
    {'preview_hash':'0'*64},{'input_hash':'0'*64},{'base_version':1},{'environment':'real'},
    {'actor':'forged'},{'target':'another-record'},{'db_path':'C:/unrelated.sqlite3'},
])
def test_binding_tampering_rejected_without_fact_changes(maintenance_setup,changed):
    settings,principal=maintenance_setup
    preview=maintenance.preview_materials(settings,principal,request());binding={**commit_request(preview),**changed}
    before=snapshot(settings.acceptance_db_path)
    with pytest.raises((WriteConflict,maintenance.MaintenanceError)):
        maintenance.commit_operation(settings,principal,binding)
    assert snapshot(settings.acceptance_db_path)==before


def test_cross_session_revoked_session_expiry_and_version_conflict_are_distinct(maintenance_setup):
    settings,principal=maintenance_setup
    preview=maintenance.preview_materials(settings,principal,request())
    other={**principal,'session_id':'c'*64}
    with writer_transaction(settings.db_path) as (connection,_):
        connection.execute('INSERT INTO maintenance_sessions SELECT ?,csrf_hash,actor,created_at,expires_at,NULL FROM maintenance_sessions WHERE session_hash=?',
            (other['session_id'],principal['session_id']))
    with pytest.raises(WriteConflict):maintenance.commit_operation(settings,other,commit_request(preview))
    with writer_transaction(settings.acceptance_db_path) as (connection,_):
        connection.execute("UPDATE manual_operations SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(preview['operation_id'],))
    with pytest.raises(WriteConflict,match='过期'):maintenance.commit_operation(settings,principal,commit_request(preview))
    import_record(settings,principal)
    left=maintenance.preview_materials(settings,principal,request(date='2026-10-21',operation_type='correction',fields=['event_date']))
    right=maintenance.preview_materials(settings,principal,request(date='2026-10-22',operation_type='correction',fields=['event_date']))
    maintenance.commit_operation(settings,principal,commit_request(left))
    with pytest.raises(WriteConflict,match='已更新'):maintenance.commit_operation(settings,principal,commit_request(right))
    with writer_transaction(settings.db_path) as (connection,_):
        connection.execute('UPDATE maintenance_sessions SET revoked_at=? WHERE session_hash=?',(datetime.now(timezone.utc).isoformat(),principal['session_id']))
    with pytest.raises(maintenance.MaintenanceError,match='失效'):maintenance.commit_operation(settings,principal,commit_request(left))


def test_real_environment_uses_separate_target_and_never_claims_automatic_fetch(maintenance_setup):
    settings,principal=maintenance_setup
    receipt=import_record(settings,principal,'real')
    assert receipt['new']==1 and snapshot(settings.db_path)['metadata']['data_mode']=='real'
    assert snapshot(settings.acceptance_db_path)['rows']==[]
    broken=SimpleNamespace(db_path=settings.db_path,acceptance_db_path=settings.db_path)
    with pytest.raises(maintenance.MaintenanceError):maintenance.target_database(broken,'isolated')
    missing=SimpleNamespace(db_path=settings.db_path,acceptance_db_path=None)
    with pytest.raises(maintenance.MaintenanceError):maintenance.target_database(missing,'isolated')


def test_correction_revert_restores_only_its_contribution_and_later_manual_wins(maintenance_setup):
    settings,principal=maintenance_setup;import_record(settings,principal)
    correction=maintenance.preview_materials(settings,principal,request(date='2026-10-21',operation_type='correction',fields=['event_date']))
    committed=maintenance.commit_operation(settings,principal,commit_request(correction))
    revert=maintenance.preview_revert(settings,principal,committed['operation_id'],{'environment':'isolated','reason':'撤回该日期更正'})
    assert revert['candidate']['event_date']=='2026-10-20'
    maintenance.commit_operation(settings,principal,commit_request(revert),expected_revert=committed['operation_id'])
    assert maintenance.read_opportunity(settings,principal,1,environment='isolated')['event_date']=='2026-10-20'
    later=maintenance.preview_materials(settings,principal,request(date='2026-10-23',operation_type='correction',fields=['event_date']))
    maintenance.commit_operation(settings,principal,commit_request(later))
    stale=maintenance.preview_revert(settings,principal,committed['operation_id'],{'environment':'isolated','reason':'重复撤回不可覆盖后来更正'})
    assert 'event_date' in stale['retained_fields']
    receipt=maintenance.commit_operation(settings,principal,commit_request(stale),expected_revert=committed['operation_id'])
    assert receipt['modified']==0
    assert maintenance.read_opportunity(settings,principal,1,environment='isolated')['event_date']=='2026-10-23'


def test_new_manual_contribution_withdrawal_hides_without_official_cancellation(maintenance_setup):
    settings,principal=maintenance_setup;original=import_record(settings,principal)
    preview=maintenance.preview_revert(settings,principal,original['operation_id'],{'environment':'isolated','reason':'撤销该人工新增可见贡献'})
    assert preview['visible'] is False and preview['operation_type']=='manual_withdrawal'
    result=maintenance.commit_operation(settings,principal,commit_request(preview),expected_revert=original['operation_id'])
    record=maintenance.read_opportunity(settings,principal,1,environment='isolated',history=True)
    assert result['modified']==1 and record['visible'] is False
    assert record['event_status']=='unknown' and record['recruitment_status']=='unknown'
    assert any(change['field_name']=='__visibility__' and change['change_kind']=='manual_withdrawal' for change in record['history'])
    before=snapshot(settings.acceptance_db_path)
    assert maintenance.commit_operation(settings,principal,commit_request(preview),expected_revert=original['operation_id'])['replayed']
    assert snapshot(settings.acceptance_db_path)==before


def test_later_official_observation_survives_revert_of_manual_correction(maintenance_setup):
    settings,principal=maintenance_setup;import_record(settings,principal)
    preview=maintenance.preview_materials(settings,principal,request(date='2026-10-21',operation_type='correction',fields=['event_date']))
    correction=maintenance.commit_operation(settings,principal,commit_request(preview))
    config=maintenance._config('gdut','gdut_teachin');archive=material(config,'later-official')
    archive.update(source_url=request()['url'],official_record_id='1212')
    item=candidate(config,archive,identity='1212');item['event_date']='2026-10-24'
    item['field_observations']['event_date']['value']='2026-10-24'
    ingest_detail(settings.acceptance_db_path,config,item,[archive],run_id=run(settings.acceptance_db_path,'run-later-official'),fixture=True)
    assert maintenance.read_opportunity(settings,principal,1,environment='isolated')['event_date']=='2026-10-21'
    revert=maintenance.preview_revert(settings,principal,correction['operation_id'],{'environment':'isolated','reason':'撤回人工更正，保留后来原文观察'})
    assert revert['candidate']['event_date']=='2026-10-24' and revert['warnings']
    maintenance.commit_operation(settings,principal,commit_request(revert),expected_revert=correction['operation_id'])
    assert maintenance.read_opportunity(settings,principal,1,environment='isolated')['event_date']=='2026-10-24'


def test_material_url_without_content_and_shared_platform_plain_text_cannot_create_facts(maintenance_setup):
    settings,principal=maintenance_setup
    class Missing:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url):raise maintenance.FetchError('synthetic unavailable')
    payload=request();payload.pop('public_text')
    with pytest.raises(maintenance.FetchError):maintenance.preview_materials(settings,principal,payload,fetcher_factory=Missing)
    with pytest.raises(maintenance.MaintenanceError):
        maintenance.preview_materials(settings,principal,request(url='http://127.0.0.1/private'))
    with pytest.raises(maintenance.MaintenanceError,match='栏目'):
        maintenance.preview_materials(settings,principal,request(url='https://career.gdut.edu.cn/campus/view/id/1212'))
    payload=request(school_key='scut',source_key='scut_ncss',url='https://www.ncss.cn/student/jobs/ABCDEFGH1234/detail.html')
    with pytest.raises(maintenance.MaintenanceError,match='学校归属'):maintenance.preview_materials(settings,principal,payload)
    assert snapshot(settings.acceptance_db_path)['rows']==[]


def test_atomic_failure_rolls_back_facts_decisions_receipts_and_operation_state(maintenance_setup,monkeypatch):
    settings,principal=maintenance_setup
    preview=maintenance.preview_materials(settings,principal,request());before=snapshot(settings.acceptance_db_path)
    original=maintenance._visibility
    def fault(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('synthetic failure after fact commit')
    monkeypatch.setattr(maintenance,'_visibility',fault)
    with pytest.raises(RuntimeError,match='after fact commit'):maintenance.commit_operation(settings,principal,commit_request(preview))
    assert snapshot(settings.acceptance_db_path)==before
    with read_database(settings.acceptance_db_path) as (connection,_):
        assert connection.execute('SELECT COUNT(*) FROM write_receipts').fetchone()[0]==0
        assert connection.execute('SELECT COUNT(*) FROM field_decisions').fetchone()[0]==0
        assert connection.execute('SELECT status FROM manual_operations WHERE id=?',(preview['operation_id'],)).fetchone()[0]=='preview'


def test_protected_reads_do_not_create_tasks_or_mutate_dataset(maintenance_setup):
    settings,principal=maintenance_setup;import_record(settings,principal)
    before=snapshot(settings.acceptance_db_path)
    assert len(maintenance.list_operations(settings,principal,environment='isolated')['items'])==1
    assert maintenance.list_tasks(settings,principal,environment='isolated')['items']==[]
    assert maintenance.read_opportunity(settings,principal,1,environment='isolated',history=True)['history']
    assert snapshot(settings.acceptance_db_path)==before


def test_revert_preview_is_stale_when_later_conflicting_observation_does_not_change_public_version(maintenance_setup):
    settings,principal=maintenance_setup;import_record(settings,principal)
    changed=maintenance.preview_materials(settings,principal,request(date='2026-10-21',operation_type='correction',fields=['event_date']))
    correction=maintenance.commit_operation(settings,principal,commit_request(changed))
    revert=maintenance.preview_revert(settings,principal,correction['operation_id'],{'environment':'isolated','reason':'先生成撤回预览'})
    config=maintenance._config('gdut','gdut_teachin');archive=material(config,'after-revert-preview')
    archive.update(source_url=request()['url'],official_record_id='1212')
    with read_database(settings.acceptance_db_path) as (connection,_):
        item=maintenance._input_candidate(connection,connection.execute('SELECT * FROM opportunities WHERE id=1').fetchone())
    item['event_date']='2026-10-25'
    proof=deepcopy(item['field_observations']['event_date']['evidence'][0])
    proof.update(material_ref=archive['reference_key'],source_url=archive['source_url'],
        observed_at=archive['fetched_at'],parser_version=archive['parser_version'],excerpt='合成后来官方日期 2026-10-25')
    item['field_observations']['event_date']={'state':'known','value':'2026-10-25','evidence':[proof]}
    ingest_detail(settings.acceptance_db_path,config,item,[archive],run_id=run(settings.acceptance_db_path,'run-after-preview'),fixture=True)
    assert maintenance.read_opportunity(settings,principal,1,environment='isolated')['version']==revert['base_version']
    with pytest.raises(WriteConflict,match='新的官方观察'):
        maintenance.commit_operation(settings,principal,commit_request(revert),expected_revert=correction['operation_id'])
    refreshed=maintenance.preview_revert(settings,principal,correction['operation_id'],{'environment':'isolated','reason':'重新核对后来材料'})
    assert refreshed['candidate']['event_date']=='2026-10-25'


def test_reimport_hidden_record_uses_current_material_and_its_visibility_can_be_withdrawn(maintenance_setup):
    settings,principal=maintenance_setup;original=import_record(settings,principal)
    withdrawal=maintenance.preview_revert(settings,principal,original['operation_id'],{'environment':'isolated','reason':'撤回首次人工贡献'})
    maintenance.commit_operation(settings,principal,commit_request(withdrawal),expected_revert=original['operation_id'])
    fresh=request()
    fresh['public_text']='标题：合成隔离再次收录\n发布时间：2026-10-12\n招聘岗位：销售、人力、市场'
    revived=maintenance.preview_materials(settings,principal,fresh)
    assert revived['candidate']['event_date'] is None and revived['candidate']['work_locations']==[]
    saved=maintenance.commit_operation(settings,principal,commit_request(revived))
    assert saved['visible'] is True
    record=maintenance.read_opportunity(settings,principal,1,environment='isolated')
    assert record['title']=='合成隔离再次收录' and record['event_date'] is None and record['relevance']=='unknown'
    revert=maintenance.preview_revert(settings,principal,saved['operation_id'],{'environment':'isolated','reason':'撤回重新收录贡献'})
    assert revert['visible'] is False
    maintenance.commit_operation(settings,principal,commit_request(revert),expected_revert=saved['operation_id'])
    assert maintenance.read_opportunity(settings,principal,1,environment='isolated')['visible'] is False


def correction(settings,principal,date):
    preview=maintenance.preview_materials(settings,principal,request(date=date,operation_type='correction',fields=['event_date']))
    return maintenance.commit_operation(settings,principal,commit_request(preview))


def revert(settings,principal,operation_id):
    preview=maintenance.preview_revert(settings,principal,operation_id,{'environment':'isolated','reason':'合成撤回贡献链核验'})
    return preview,maintenance.commit_operation(settings,principal,commit_request(preview),expected_revert=operation_id)


def test_withdraw_creator_then_later_correction_never_revives_withdrawn_before_value(maintenance_setup):
    settings,principal=maintenance_setup;created=import_record(settings,principal)
    changed=correction(settings,principal,'2026-10-21')
    _,withdrawn=revert(settings,principal,created['operation_id'])
    assert withdrawn['visible'] is True
    assert maintenance.read_opportunity(settings,principal,1,environment='isolated')['event_date']=='2026-10-21'
    preview,receipt=revert(settings,principal,changed['operation_id'])
    assert preview['candidate'] is None and receipt['visible'] is False
    with read_database(settings.acceptance_db_path) as (connection,_):
        assert connection.execute("SELECT COUNT(*) FROM field_decisions WHERE opportunity_id=1 AND field_name!='__visibility__'").fetchone()[0]==0
        assert connection.execute("SELECT COUNT(*) FROM field_decisions WHERE operation_id=?",(created['operation_id'],)).fetchone()[0]==0


def test_revert_walks_past_withdrawn_middle_correction_to_active_creator(maintenance_setup):
    settings,principal=maintenance_setup;created=import_record(settings,principal)
    middle=correction(settings,principal,'2026-10-21');latest=correction(settings,principal,'2026-10-22')
    _,receipt=revert(settings,principal,middle['operation_id'])
    assert receipt['modified']==0
    preview,receipt=revert(settings,principal,latest['operation_id'])
    assert preview['candidate']['event_date']=='2026-10-20' and receipt['visible'] is True
    with read_database(settings.acceptance_db_path) as (connection,_):
        assert connection.execute("SELECT operation_id FROM field_decisions WHERE opportunity_id=1 AND field_name='event_date'").fetchone()[0]==created['operation_id']
    assert maintenance.read_opportunity(settings,principal,1,environment='isolated')['event_date']=='2026-10-20'


def test_withdrawn_predecessor_invalidates_restore_preview_without_public_version_change(maintenance_setup):
    settings,principal=maintenance_setup;import_record(settings,principal)
    middle=correction(settings,principal,'2026-10-21');latest=correction(settings,principal,'2026-10-22')
    preview=maintenance.preview_revert(settings,principal,latest['operation_id'],{'environment':'isolated','reason':'先预览最后一次更正撤回'})
    _,receipt=revert(settings,principal,middle['operation_id'])
    assert receipt['modified']==0 and receipt['version']==preview['base_version']
    with pytest.raises(WriteConflict,match='人工贡献'):
        maintenance.commit_operation(settings,principal,commit_request(preview),expected_revert=latest['operation_id'])


def test_repeated_revert_of_old_correction_preserves_hidden_visibility(maintenance_setup):
    settings,principal=maintenance_setup;created=import_record(settings,principal)
    changed=correction(settings,principal,'2026-10-21')
    revert(settings,principal,changed['operation_id']);revert(settings,principal,created['operation_id'])
    before=snapshot(settings.acceptance_db_path)
    preview,receipt=revert(settings,principal,changed['operation_id'])
    assert preview['visible'] is False and receipt['modified']==0
    assert snapshot(settings.acceptance_db_path)==before


def test_operation_history_paginates_by_commit_time_not_random_operation_id(maintenance_setup):
    settings,principal=maintenance_setup;created=import_record(settings,principal)
    changed=correction(settings,principal,'2026-10-21')
    with writer_transaction(settings.acceptance_db_path) as (connection,_):
        connection.execute("UPDATE manual_operations SET committed_at='2026-10-01T00:00:00+00:00' WHERE id=?",(created['operation_id'],))
        connection.execute("UPDATE manual_operations SET committed_at='2026-10-02T00:00:00+00:00' WHERE id=?",(changed['operation_id'],))
    first=maintenance.list_operations(settings,principal,environment='isolated',limit=1)
    assert first['items'][0]['operation_id']==changed['operation_id'] and first['has_more']
    second=maintenance.list_operations(settings,principal,environment='isolated',limit=1,before=first['next_cursor'])
    assert second['items'][0]['operation_id']==created['operation_id'] and not second['has_more']
    with pytest.raises(maintenance.MaintenanceError):maintenance.list_operations(settings,principal,environment='isolated',before='missing-operation')


def test_task_retry_previews_without_facts_then_resolves_atomically_and_stops_new_restriction(maintenance_setup):
    settings,principal=maintenance_setup;import_record(settings,principal)
    config=maintenance._config('gdut','gdut_teachin')
    with writer_transaction(settings.acceptance_db_path) as (connection,_):
        save_task(connection,config,task_kind='maintenance',task_identity='synthetic-retry:1',opportunity_id=1,status='failed',result={'field':'event_date'})
        task_id=connection.execute("SELECT id FROM processing_tasks WHERE task_identity='synthetic-retry:1'").fetchone()[0]
    def fetcher_factory(**kwargs):
        client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,
            text=gdut_detail(date='2026-10-24'),headers={'content-type':'text/html; charset=utf-8'})))
        return maintenance.Fetcher(**kwargs,client=client)
    before=snapshot(settings.acceptance_db_path)
    preview=maintenance.retry_task_preview(settings,principal,task_id,{'environment':'isolated','reason':'合成重试公开材料'},fetcher_factory=fetcher_factory)
    assert snapshot(settings.acceptance_db_path)==before
    result=maintenance.commit_operation(settings,principal,commit_request(preview))
    assert result['modified']==1
    with read_database(settings.acceptance_db_path) as (connection,_):
        assert connection.execute('SELECT status FROM processing_tasks WHERE id=?',(task_id,)).fetchone()[0]=='resolved'
    assert maintenance.commit_operation(settings,principal,commit_request(preview))['replayed']
    with writer_transaction(settings.acceptance_db_path) as (connection,_):
        connection.execute("UPDATE processing_tasks SET status='failed' WHERE id=?",(task_id,))
    later=maintenance.retry_task_preview(settings,principal,task_id,{'environment':'isolated','reason':'合成竞争状态复验'},fetcher_factory=fetcher_factory)
    with writer_transaction(settings.acceptance_db_path) as (connection,_):
        connection.execute("UPDATE processing_tasks SET status='restricted' WHERE id=?",(task_id,))
    unchanged=snapshot(settings.acceptance_db_path)
    with pytest.raises(WriteConflict,match='受限路径'):
        maintenance.commit_operation(settings,principal,commit_request(later))
    assert snapshot(settings.acceptance_db_path)==unchanged
    with pytest.raises(maintenance.MaintenanceError,match='受限路径'):
        maintenance.retry_task_preview(settings,principal,task_id,{'environment':'isolated','reason':'不能绕过限制'},fetcher_factory=fetcher_factory)
