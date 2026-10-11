from copy import deepcopy
import json
from datetime import datetime, timedelta

import pytest

from backend.services.ingestion import commit_facts, commit_facts_in_transaction, ingest_page
from backend.storage.database import initialize_database, read_database
from backend.storage.write import WriteContext, WriteConflict, writer_transaction
from test_ingestion import source, material, candidate, run, snapshot, now


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
