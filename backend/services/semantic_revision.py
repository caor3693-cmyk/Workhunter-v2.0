"""Read-only, targeted correction previews; explicit operation-bound application."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from uuid import uuid4

from backend.domain.candidates import CORE_FIELDS, validate_candidate
from backend.services.ingestion import _from_row, _prepare_materials, _bind_evidence, commit_facts_in_transaction, encoded, now, BUSINESS_FIELDS
from backend.storage.database import read_database
from backend.storage.write import writer_transaction, WriteContext, WriteConflict


def _input_candidate(connection, row):
    candidate = _from_row(row)
    def visit(value):
        if isinstance(value,dict):
            if 'material_id' in value:
                material = connection.execute('SELECT reference_key FROM source_materials WHERE id=? AND source_key=?',(value.pop('material_id'),row['source_key'])).fetchone()
                if material is None: raise ValueError('原字段材料缺失，无法预览。')
                value['material_ref']=material[0]
                value.pop('association_id',None)
            for nested in list(value.values()): visit(nested)
        elif isinstance(value,list):
            for nested in value: visit(nested)
    visit(candidate)
    for key in ('id','first_seen_at','content_changed_at','version','campus_id'):
        candidate.pop(key,None)
    if row['campus_id']:
        candidate['campus_key']=connection.execute('SELECT campus_key FROM campuses WHERE id=?',(row['campus_id'],)).fetchone()[0]
    return candidate


def preview_semantic_revision(database_path, source_config, opportunity_id, patch, materials=(), *, fields, reason, actor='reviewer', fixture=False, ttl_seconds=900):
    """Returns a signed-by-content preview. No rows, facts or tasks are written.

    A downgrade must carry a replacement field_observation with this record's
    real material_ref/source_identity/locator. Ordinary ingestion cannot clear a
    known value; only these explicitly selected fields use replacement semantics.
    """
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000 or not 1<=ttl_seconds<=3600:
        raise ValueError('修订原因或预览有效期无效。')
    fields=sorted(set(fields))
    if not fields or set(fields)-set(BUSINESS_FIELDS) or 'field_observations' in fields:
        raise ValueError('修订字段无效。')
    if set(patch)-set(fields)-{'field_observations'} or set(patch.get('field_observations',{}))-set(fields):
        raise ValueError('预览输入不得修改未选定字段。')
    prepared=_prepare_materials(materials,source_config,fixture)
    with read_database(database_path) as (connection,metadata):
        row=connection.execute('SELECT * FROM opportunities WHERE id=?',(opportunity_id,)).fetchone()
        if row is None or row['source_key']!=source_config['source_key']:
            raise ValueError('修订目标不属于该来源。')
        candidate=_input_candidate(connection,row)
        before=_from_row(row)
        candidate.update({k:deepcopy(v) for k,v in patch.items() if k!='field_observations'})
        candidate['field_observations'].update(deepcopy(patch.get('field_observations',{})))
        for field in fields:
            if field in CORE_FIELDS or field=='relevance':
                proof=candidate['field_observations'].get(field,{})
                if field not in patch.get('field_observations',{}) or not proof.get('evidence'):
                    raise ValueError('定向字段修订必须显式提供新的本条观察与依据。')
        candidate=validate_candidate(candidate,source_config)
        # Existing references are checked now. New archived materials are checked
        # without storing them, and again atomically on apply.
        _bind_evidence(connection,candidate,prepared)
        differences={field:{'before':before[field],'after':candidate[field],
                     'before_observation':before['field_observations'].get(field),
                     'after_observation':candidate['field_observations'].get(field)} for field in fields}
        payload={'operation_id':'semantic-'+uuid4().hex,'actor':actor,'reason':reason,'source_config':deepcopy(source_config),
                 'opportunity_id':opportunity_id,'base_version':row['version'],'fields':fields,'candidate':candidate,
                 'materials':prepared,'fixture':fixture,'dataset_id':metadata['dataset_id'],
                 'expires_at':(datetime.fromisoformat(now())+timedelta(seconds=ttl_seconds)).isoformat(),'differences':differences}
    return {**payload,'preview_hash':hashlib.sha256(encoded(payload).encode()).hexdigest()}


def apply_semantic_revision(database_path, preview):
    payload={k:v for k,v in preview.items() if k!='preview_hash'}
    digest=hashlib.sha256(encoded(payload).encode()).hexdigest()
    if digest!=preview.get('preview_hash'): raise WriteConflict('预览内容已变化。')
    context=WriteContext(actor=payload['actor'],operation_id=payload['operation_id'],reason=payload['reason'],
                         idempotency_key=digest,change_kind='semantic_revision',base_version=payload['base_version'])
    with writer_transaction(database_path) as (connection,metadata):
        receipt=connection.execute('SELECT receipt_json FROM write_receipts WHERE context_key=?',(context.key,)).fetchone()
        if receipt: return {**json.loads(receipt[0]),'replayed':True}
        if datetime.fromisoformat(payload['expires_at'])<=datetime.fromisoformat(now()): raise WriteConflict('预览已过期，请重新预览。')
        connection.execute("INSERT INTO manual_operations(id,actor,operation_type,opportunity_id,preview_hash,base_version,input_json,difference_json,expires_at,status,input_hash,idempotency_key,expected_version,target_source_key,target_identity) VALUES (?,?,'semantic_revision',?,?,?,?,?,?,'preview',?,?,?,?,?)",
                           (context.operation_id,context.actor,payload['opportunity_id'],digest,context.base_version,encoded(payload['candidate']),encoded(payload['differences']),payload['expires_at'],digest,digest,context.base_version,payload['source_config']['source_key'],payload['candidate']['source_identity']))
        result=commit_facts_in_transaction(connection,metadata,payload['source_config'],[payload['candidate']],payload['materials'],context,
                                           fixture=payload['fixture'],replace_fields=payload['fields'])
        connection.execute("UPDATE manual_operations SET status='committed',receipt_json=?,committed_at=? WHERE id=?",(encoded(result),result['committed_at'],context.operation_id))
        return result
