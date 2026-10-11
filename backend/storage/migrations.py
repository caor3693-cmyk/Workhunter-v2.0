"""Explicit schema 1/2 to 3 migration: consistent backup, atomic rollback."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from backend.storage.database import DatabaseUnavailable, REQUIRED_COLUMNS, _validate
from backend.storage.write import _file_lock, refresh_lock, WriterBusy, WriteContext, context_request_hash, begin_fact_write, finish_fact_write
from backend.version import PROJECT, SCHEMA_VERSION
from backend.domain.candidates import locator_identifies_identity, safe_url

NEW_TABLES = {'opportunity_materials','write_receipts','field_decisions','official_observations','maintenance_sessions','maintenance_login_failures','quarantined_evidence'}
NEW_COLUMNS = {'processing_tasks':{'last_attempt_at':'TEXT','next_eligible_at':'TEXT','queued_at':'TEXT'},
 'manual_operations':{'session_id':'TEXT','input_hash':'TEXT','idempotency_key':'TEXT','receipt_json':'TEXT','expected_version':'INTEGER','target_source_key':'TEXT','target_identity':'TEXT'},
 'changes':{'reason':'TEXT','write_context_key':'TEXT'}}


def _statements(script):
    buffer=''
    for line in script.splitlines(keepends=True):
        buffer+=line
        if sqlite3.complete_statement(buffer):
            yield buffer
            buffer=''
    if buffer.strip(): raise ValueError('迁移SQL不完整。')


def _columns(connection,table):
    return {row[1] for row in connection.execute('PRAGMA table_info("'+table+'")')}


def _bind_legacy(connection,opportunity,value,timestamp):
    if isinstance(value,dict):
        if 'material_id' in value or 'material_ref' in value:
            if type(value.get('material_id')) is not int or value.get('material_ref'):
                raise ValueError('旧证据缺少实际材料ID。')
            material=connection.execute('SELECT * FROM source_materials WHERE id=?',(value['material_id'],)).fetchone()
            identity=opportunity['source_identity']
            locator=value.get('locator')
            if not material or material['source_key']!=opportunity['source_key'] or material['source_url']!=value.get('source_url') or material['acquisition_status']!='success' or not locator or value.get('source_identity',identity)!=identity:
                raise ValueError('旧材料、URL、身份或定位不一致。')
            material_scope=json.loads(material['scope_json'])
            if not isinstance(material_scope,dict): raise ValueError('旧材料范围结构无效。')
            if material['official_record_id'] is not None:
                if material['official_record_id']!=identity: raise ValueError('旧单公告材料属于另一公告。')
            elif material_scope.get('type')!='source_list' or not locator_identifies_identity(locator,identity):
                raise ValueError('旧共享列表没有本条身份与定位，不信任NULL归属。')
            if material['opportunity_id'] not in (None,opportunity['id']): raise ValueError('旧材料绑定另一条机会。')
            value['source_identity']=identity
            chain={k:v for k,v in value.items() if k not in {'material_id','association_id'}} if 'target_url' in value else {}
            basis={k:value[k] for k in ('source_identity','source_url','locator','excerpt','observed_at','parser_version')}
            basis['material_hash']=material['material_hash']
            kind='attachment_link' if chain else 'body' if material['official_record_id'] is not None else 'list'
            connection.execute('INSERT INTO opportunity_materials(opportunity_id,material_id,school_key,source_key,source_identity,relation_kind,locator,scope_json,basis_json,link_chain_json,verified_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(opportunity_id,material_id,locator) DO NOTHING',
                               (opportunity['id'],material['id'],opportunity['school_key'],opportunity['source_key'],identity,kind,locator,json.dumps(value['scope'],ensure_ascii=False),json.dumps(basis,ensure_ascii=False),json.dumps(chain,ensure_ascii=False),timestamp))
            relation=connection.execute('SELECT id FROM opportunity_materials WHERE opportunity_id=? AND material_id=? AND locator=?',(opportunity['id'],material['id'],locator)).fetchone()
            value['association_id']=relation[0]
            if chain:
                connection.execute("UPDATE opportunity_materials SET link_chain_json=?,relation_kind='attachment_link' WHERE id=?",(json.dumps(chain,ensure_ascii=False),relation[0]))
        for nested in list(value.values()): _bind_legacy(connection,opportunity,nested,timestamp)
    elif isinstance(value,list):
        for nested in value: _bind_legacy(connection,opportunity,nested,timestamp)


def _migrate_evidence(connection,timestamp):
    from backend.services.queries import _observations, _stored_evidence, _attachment_chain
    revised=[]
    for row in connection.execute('SELECT * FROM opportunities ORDER BY id').fetchall():
        observations=json.loads(row['field_observations_json'])
        try:
            _bind_legacy(connection,row,observations,timestamp)
            connection.execute('UPDATE opportunities SET field_observations_json=? WHERE id=?',(json.dumps(observations,ensure_ascii=False),row['id']))
            refreshed=connection.execute('SELECT * FROM opportunities WHERE id=?',(row['id'],)).fetchone()
            _observations(refreshed,connection)
        except (ValueError,TypeError,KeyError,DatabaseUnavailable) as exc:
            raise DatabaseUnavailable('旧核心字段材料关联不可核实，原库与备份保留；须显式修订后重试。') from exc
        for field in ('roster_fragments','job_fragments','attachments'):
            raw=row[field+'_json']
            try:
                values=json.loads(raw)
                if not isinstance(values,list) or len(values)>8: raise ValueError('附加范围无效')
            except (ValueError,TypeError): values=[{'_unreadable':raw}]
            kept=[]
            bad=[]
            for fragment in values:
                original=json.loads(json.dumps(fragment,ensure_ascii=False))
                connection.execute('SAVEPOINT legacy_supplement')
                try:
                    _bind_legacy(connection,row,fragment,timestamp)
                    if not isinstance(fragment,dict) or not fragment.get('scope') or not isinstance(fragment['scope'],(str,dict)) or not fragment.get('evidence'): raise ValueError('附加范围或证据缺失')
                    _stored_evidence(fragment['evidence'],row,connection)
                    if field=='attachments':
                        safe_url(fragment.get('url'),row['school_key'])
                        if not isinstance(fragment.get('label'),str) or not fragment['label'].strip() or len(fragment['label'])>500 or '\x00' in fragment['label']:
                            raise ValueError('附件标题无效')
                        # Old attachments only name the parent page. An explicit
                        # stored link locator and target are required to migrate.
                        _attachment_chain(fragment,row,connection)
                    elif fragment.get('scope') not in ('partial','complete_for_material','unknown') or not isinstance(fragment.get('text'),str) or not fragment['text'].strip() or len(fragment['text'])>2000 or '\x00' in fragment['text']:
                        raise ValueError('片段范围无效')
                    connection.execute('RELEASE SAVEPOINT legacy_supplement')
                    kept.append(fragment)
                except (ValueError,TypeError,KeyError,DatabaseUnavailable,sqlite3.IntegrityError):
                    connection.execute('ROLLBACK TO SAVEPOINT legacy_supplement')
                    connection.execute('RELEASE SAVEPOINT legacy_supplement')
                    bad.append(original)
            if bad:
                for fragment in bad:
                    encoded=json.dumps(fragment,ensure_ascii=False,sort_keys=True)
                    digest=hashlib.sha256(encoded.encode()).hexdigest()
                    connection.execute('INSERT OR IGNORE INTO quarantined_evidence(opportunity_id,field_name,input_hash,original_json,reason,recorded_at) VALUES (?,?,?,?,?,?)',(row['id'],field,digest,encoded,'legacy_applicability_unverified',timestamp))
                task_identity='quarantine:'+str(row['id'])+':'+field
                connection.execute("INSERT INTO processing_tasks(source_key,task_identity,opportunity_id,task_kind,budget_json,status,result_json,queued_at) VALUES (?,?,?,'maintenance','{}','pending',?,?) ON CONFLICT(source_key,task_identity,task_kind) DO NOTHING",
                                   (row['source_key'],task_identity,row['id'],json.dumps({'type':'material_applicability','field':field}),timestamp))
                revised.append((row['id'],field,raw,json.dumps(kept,ensure_ascii=False),row['version']))
            connection.execute('UPDATE opportunities SET '+field+'_json=? WHERE id=?',(json.dumps(kept,ensure_ascii=False),row['id']))
    if revised:
        operation_id='migration-'+uuid4().hex
        reason='显式迁移隔离不可核实附加证据，保留原证据与可靠核心事实'
        connection.execute("INSERT INTO manual_operations(id,actor,operation_type,preview_hash,input_json,difference_json,expires_at,status) VALUES (?,'migration','migration_revision',?,'{}',?,?,'preview')",(operation_id,hashlib.sha256(reason.encode()).hexdigest(),json.dumps(revised,ensure_ascii=False),(datetime.fromisoformat(timestamp)+timedelta(hours=1)).isoformat()))
        context=WriteContext(actor='migration',operation_id=operation_id,reason=reason,idempotency_key='schema3-quarantine',change_kind='migration_revision')
        request_hash=context_request_hash(context,revised)
        begin_fact_write(connection,context,request_hash)
        for opportunity_id,field,before,after,version in revised:
            connection.execute('INSERT INTO changes(opportunity_id,field_name,before_json,after_json,change_kind,manual_operation_id,actor,committed_at,reason,write_context_key) VALUES (?,?,?,?,?,?,?,?,?,?)',
                               (opportunity_id,field,before,after,'migration_revision',operation_id,'migration',timestamp,reason,context.key))
        ids=sorted({r[0] for r in revised})
        for opportunity_id in ids: connection.execute('UPDATE opportunities SET version=version+1,content_changed_at=? WHERE id=?',(timestamp,opportunity_id))
        data_mode=connection.execute("SELECT value FROM metadata WHERE key='data_mode'").fetchone()[0]
        dataset_id=('fixture-ds-' if data_mode=='isolated_fixture' else 'ds-')+str(uuid4())
        connection.execute("UPDATE metadata SET value=? WHERE key='dataset_id'",(dataset_id,))
        receipt={'modified':len(ids),'opportunity_ids':ids,'dataset_id':dataset_id}
        finish_fact_write(connection,context,request_hash,receipt,timestamp)
        connection.execute("UPDATE manual_operations SET status='committed',receipt_json=?,committed_at=? WHERE id=?",(json.dumps(receipt,ensure_ascii=False),timestamp,operation_id))
    # Every detail, including old successful tasks, keeps a usable candidate for
    # an ordinary future due check; list rediscovery must not be required.
    from backend.services.semantic_revision import _input_candidate
    for task in connection.execute("SELECT * FROM processing_tasks WHERE task_kind='detail' AND opportunity_id IS NOT NULL").fetchall():
        opportunity=connection.execute('SELECT * FROM opportunities WHERE id=?',(task['opportunity_id'],)).fetchone()
        if opportunity is None: continue
        try: result=json.loads(task['result_json'] or '{}')
        except (ValueError,TypeError): result={}
        if not isinstance(result,dict): result={}
        result['candidate']=_input_candidate(connection,opportunity)
        result.setdefault('list_title',opportunity['title'])
        connection.execute('UPDATE processing_tasks SET result_json=? WHERE id=?',(json.dumps(result,ensure_ascii=False),task['id']))
    return len({r[0] for r in revised})


def _schema1(connection):
    if 'reference_key' not in _columns(connection,'source_materials'):
        connection.execute("ALTER TABLE source_materials ADD COLUMN reference_key TEXT NOT NULL DEFAULT ''")
        connection.execute("UPDATE source_materials SET reference_key='legacy:' || id")
        connection.execute('CREATE UNIQUE INDEX source_material_reference ON source_materials(source_key,reference_key)')
    if 'task_identity' not in _columns(connection,'processing_tasks'):
        connection.execute("ALTER TABLE processing_tasks ADD COLUMN task_identity TEXT NOT NULL DEFAULT ''")
        seen=set()
        for row in connection.execute('SELECT * FROM processing_tasks ORDER BY id').fetchall():
            if row['opportunity_id'] is None:
                identity='list:'+connection.execute('SELECT channel_key FROM sources WHERE source_key=?',(row['source_key'],)).fetchone()[0]
            else:
                identity='detail:'+connection.execute('SELECT source_identity FROM opportunities WHERE id=?',(row['opportunity_id'],)).fetchone()[0]
            key=(row['source_key'],identity,row['task_kind'])
            duplicate=key in seen
            seen.add(key)
            if duplicate: identity+=':legacy:'+str(row['id'])
            connection.execute('UPDATE processing_tasks SET task_identity=?,status=CASE WHEN ? THEN ? ELSE status END WHERE id=?',(identity,duplicate,'superseded',row['id']))
        connection.execute('CREATE UNIQUE INDEX processing_task_identity ON processing_tasks(source_key,task_identity,task_kind)')


def migrate_database(database_path):
    path=Path(database_path).resolve()
    if not path.is_file(): raise DatabaseUnavailable('待迁移独立新库不存在；不会自动建库。')
    with refresh_lock(path),_file_lock(path.with_name(path.name+'.write.lock'),10,WriterBusy):
        connection=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)
        connection.row_factory=sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            metadata=dict(connection.execute('SELECT key,value FROM metadata'))
            if metadata.get('project')!=PROJECT: raise DatabaseUnavailable('数据库项目身份不匹配，禁止迁移。')
            if metadata.get('schema_version')==SCHEMA_VERSION: return {**_validate(connection),'migration':'already_current'}
            old_version=metadata.get('schema_version')
            if old_version not in {'1','2'} or metadata.get('data_mode') not in {'empty','real','isolated_fixture'} or not metadata.get('dataset_id'):
                raise DatabaseUnavailable('只能显式迁移已识别的schema1/2独立新库。')
            for table,fields in REQUIRED_COLUMNS.items():
                if table in NEW_TABLES: continue
                expected=set(fields.split())-set(NEW_COLUMNS.get(table,{}))
                if old_version=='1': expected-={'reference_key','task_identity'}
                if not expected.issubset(_columns(connection,table)): raise DatabaseUnavailable('旧库结构残缺，保留原库，不迁移。')
            if connection.execute('PRAGMA quick_check(1)').fetchone()[0]!='ok': raise DatabaseUnavailable('数据库损坏，保留原库。')
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
            backup=path.with_name(path.name+'.schema'+old_version+'-'+stamp+'-'+uuid4().hex[:8]+'.sqlite3')
            with backup.open('xb'): pass
            target=sqlite3.connect(backup)
            try: connection.backup(target)
            finally: target.close()
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('PRAGMA foreign_key_check').fetchone(): raise DatabaseUnavailable('旧库外键异常，保留原库与备份。')
            if connection.execute("""SELECT 1 FROM opportunities o JOIN sources s ON s.source_key=o.source_key
                LEFT JOIN campuses c ON c.id=o.campus_id WHERE o.school_key<>s.school_key
                OR (o.campus_id IS NOT NULL AND c.school_key<>o.school_key) LIMIT 1""").fetchone():
                raise DatabaseUnavailable('旧库学校/来源/校区归属冲突，保留原库与备份。')
            if connection.execute("""SELECT 1 FROM sources s JOIN campuses c ON c.id=s.campus_id WHERE s.school_key<>c.school_key
                UNION ALL SELECT 1 FROM source_materials m JOIN opportunities o ON o.id=m.opportunity_id WHERE m.source_key<>o.source_key
                UNION ALL SELECT 1 FROM processing_tasks t JOIN opportunities o ON o.id=t.opportunity_id WHERE t.source_key<>o.source_key
                UNION ALL SELECT 1 FROM changes x JOIN source_materials m ON m.id=x.material_id JOIN opportunities o ON o.id=x.opportunity_id WHERE m.source_key<>o.source_key LIMIT 1""").fetchone():
                raise DatabaseUnavailable('旧库来源与材料归属冲突，保留原库与备份。')
            _schema1(connection)
            for table,columns in NEW_COLUMNS.items():
                present=_columns(connection,table)
                for name,definition in columns.items():
                    if name not in present: connection.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)
            schema=(Path(__file__).parent/'schema.sql').read_text(encoding='utf-8')
            additions=schema.split('-- Schema 3 additions',1)[1].split('-- Ownership constraints',1)[0]
            for statement in _statements('-- Schema 3 additions'+additions):
                statement=statement.replace('CREATE TABLE ','CREATE TABLE IF NOT EXISTS ',1)
                connection.execute(statement)
            constraints=schema.split('-- Ownership constraints',1)[1]
            for statement in _statements('-- Ownership constraints'+constraints):
                connection.execute(statement.replace('CREATE TRIGGER ','CREATE TRIGGER IF NOT EXISTS ',1))
            timestamp=datetime.now(timezone.utc).isoformat()
            revised=_migrate_evidence(connection,timestamp)
            connection.execute("UPDATE processing_tasks SET last_attempt_at=CASE WHEN attempts>0 THEN committed_at ELSE NULL END,queued_at=COALESCE(queued_at,committed_at),next_eligible_at=CASE WHEN status='committed' AND task_kind='detail' THEN datetime(committed_at,'+24 hours') WHEN status IN ('failed','partial') THEN datetime(committed_at,'+1 hours') ELSE next_eligible_at END")
            connection.execute("UPDATE metadata SET value=? WHERE key='schema_version'",(SCHEMA_VERSION,))
            current=_validate(connection)
            if connection.execute('PRAGMA foreign_key_check').fetchone(): raise DatabaseUnavailable('迁移外键核验失败。')
            connection.commit()
            return {**current,'migration':'completed','backup':str(backup),'revised_opportunities':revised}
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
