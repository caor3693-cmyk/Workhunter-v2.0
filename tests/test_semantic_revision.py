from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest

from backend.services.ingestion import ingest_page, ingest_detail
from backend.services.semantic_revision import preview_semantic_revision, apply_semantic_revision
from backend.storage.database import initialize_database, read_database
from backend.storage.write import WriteConflict
from test_ingestion import source, material, candidate, run, snapshot


@pytest.fixture
def prepared(tmp_path):
    db=tmp_path/'semantic.sqlite3';initialize_database(db,fixture=True)
    config=source();archive=material(config);item=candidate(config,archive);run_id=run(db)
    proof=deepcopy(item['field_observations']['published_date']['evidence'][0])
    item['relevance']='related';item['field_observations']['relevance']={'state':'known','value':'related','evidence':[proof]}
    ingest_page(db,config,[item],[archive],run_id=run_id,fixture=True)
    return db,config,archive,item,run_id,proof


def test_explicit_semantic_downgrade_is_readonly_preview_targeted_and_idempotent(prepared,monkeypatch):
    db,config,archive,item,run_id,proof=prepared
    incoming=deepcopy(item);incoming['relevance']='unknown';incoming['field_observations'].pop('relevance')
    ingest_detail(db,config,incoming,[],run_id=run_id,fixture=True)
    before=snapshot(db)
    assert before['rows'][0]['relevance']=='related'
    patch={'relevance':'unknown','field_observations':{'relevance':{'state':'pending_extraction','value':None,'evidence':[proof]}}}
    preview=preview_semantic_revision(db,config,1,patch,fields=['relevance'],reason='原定位仅为公司背景，岗位图未解析',fixture=True)
    assert snapshot(db)==before
    result=apply_semantic_revision(db,preview)
    after=snapshot(db)
    assert result['modified']==1 and after['rows'][0]['relevance']=='unknown'
    assert after['rows'][0]['event_date']==before['rows'][0]['event_date']
    assert after['rows'][0]['version']==2 and after['metadata']['dataset_id']!=before['metadata']['dataset_id']
    assert after['changes'][:-1]==before['changes']
    assert after['changes'][-1]['change_kind']=='semantic_revision'
    assert after['changes'][-1]['manual_operation_id']==preview['operation_id'] and after['changes'][-1]['run_id'] is None
    import backend.services.semantic_revision as revision
    monkeypatch.setattr(revision,'now',lambda:'2099-01-01T00:00:00+08:00')
    assert apply_semantic_revision(db,preview)['replayed'] is True
    assert snapshot(db)==after


def test_preview_rejects_untargeted_fields_and_apply_rejects_tampering(prepared):
    db,config,archive,item,run_id,proof=prepared
    patch={'title':'未选字段','relevance':'unknown','field_observations':{'relevance':{'state':'parse_failed','value':None,'evidence':[proof]}}}
    with pytest.raises(ValueError,match='未选定'):preview_semantic_revision(db,config,1,patch,fields=['relevance'],reason='原因',fixture=True)
    patch.pop('title')
    preview=preview_semantic_revision(db,config,1,patch,fields=['relevance'],reason='原因',fixture=True)
    preview['reason']='tampered'
    before=snapshot(db)
    with pytest.raises(WriteConflict,match='变化'):apply_semantic_revision(db,preview)
    assert snapshot(db)==before


def test_automatic_revisit_cannot_overwrite_reviewed_decision(prepared):
    db,config,archive,item,run_id,proof=prepared
    preview=preview_semantic_revision(db,config,1,{'relevance':'unknown','field_observations':{'relevance':{'state':'pending_extraction','value':None,'evidence':[proof]}}},fields=['relevance'],reason='岗位证据尚未取得',fixture=True)
    apply_semantic_revision(db,preview)
    run_id=run(db,'run-2')
    ingest_detail(db,config,item,[archive],run_id=run_id,fixture=True)
    assert snapshot(db)['rows'][0]['relevance']=='unknown'
    with read_database(db) as (connection,_):
        task=connection.execute("SELECT * FROM processing_tasks WHERE task_kind='maintenance'").fetchone()
        assert task and json.loads(task['result_json'])['type']=='manual_decision_conflict'


def test_explicit_same_value_evidence_repair_preserves_public_identity_and_old_audit(prepared):
    db,config,archive,item,run_id,proof=prepared
    before=snapshot(db)
    replacement=deepcopy(proof)
    replacement.update(locator="[data-id='official-42'] [本公告招聘专业]",excerpt='招聘专业：电气工程',parser_version='reviewed-proof')
    patch={'relevance':'related','field_observations':{'relevance':{'state':'known','value':'related','evidence':[replacement]}}}
    preview=preview_semantic_revision(db,config,1,patch,fields=['relevance'],reason='修复摘录定位，判断和值不变',fixture=True)
    assert snapshot(db)==before
    result=apply_semantic_revision(db,preview)
    after=snapshot(db)
    assert result['modified']==0 and result['unchanged']==1
    assert after['metadata']['dataset_id']==before['metadata']['dataset_id']
    assert after['rows'][0]['version']==before['rows'][0]['version']
    assert after['rows'][0]['content_changed_at']==before['rows'][0]['content_changed_at']
    observation=json.loads(after['rows'][0]['field_observations_json'])['relevance']
    assert observation['evidence'][0]['excerpt']=='招聘专业：电气工程'
    assert observation['evidence'][0]['observed_at']==proof['observed_at']
    assert after['changes'][:-1]==before['changes']
    assert after['changes'][-1]['field_name']=='__evidence__:relevance'
    assert after['changes'][-1]['manual_operation_id']==preview['operation_id']
    assert apply_semantic_revision(db,preview)['replayed'] is True
    assert snapshot(db)==after
