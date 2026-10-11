"""Protected, read-only task projection; derived gaps never create fake tasks."""
import json

from backend.domain.candidates import CORE_FIELDS
from backend.storage.database import DatabaseUnavailable, read_database


LABELS={'public_restriction':'公开路径受限','source_failure':'来源获取失败',
    'parse_failure':'材料尚未可靠解析','field_pending':'字段材料待补或待核实',
    'material_quarantine':'材料适用关系待核实','manual_conflict':'人工更正与自动观察待核对'}
ACTIONS={'public_restriction':'此路径已停止；核对公开限制，或预览合法官方材料。',
    'source_failure':'核对失败原因及官方入口，在允许范围内重新预览材料。',
    'parse_failure':'核对已取得材料的实际正文和本条身份，再预览更正。',
    'field_pending':'核对本条官方材料；尚未取得不等于原文未披露。',
    'material_quarantine':'核对材料属于本条公告的定位及附件取得链。',
    'manual_conflict':'比较人工决策和后来官方材料，重新预览后确认适用值。'}
ACTIVE={'pending','failed','partial','restricted','checking','running'}


def _json(value,expected):
    try:
        result=json.loads(value)
        if not isinstance(result,expected):raise ValueError()
        return result
    except (TypeError,ValueError) as exc:
        raise DatabaseUnavailable('维护待办资料无法读取。') from exc


def _reason(task,result,history):
    status=task['status']
    if status not in ACTIVE and history:status=history[0]['previous_status'] or status
    if status=='restricted' or result.get('reason')=='restricted':return 'public_restriction'
    if result.get('type')=='manual_decision_conflict' or task['task_identity'].startswith('manual-conflict:'):return 'manual_conflict'
    if result.get('type')=='material_applicability' or task['task_identity'].startswith('quarantine:'):return 'material_quarantine'
    if result.get('reason')=='list_parse_failed':return 'parse_failure'
    if status=='failed' or result.get('reason')=='failed':return 'source_failure'
    return 'field_pending'


def _resolutions(connection):
    results={}
    for operation in connection.execute("SELECT * FROM manual_operations WHERE status='committed' ORDER BY committed_at DESC,id DESC"):
        envelope=_json(operation['input_json'],dict)
        target=envelope.get('resolves_task_id')
        if type(target) is not int:continue
        normalized=envelope.get('normalized_input')
        if not isinstance(normalized,dict):raise DatabaseUnavailable('维护待办处理原因无法读取。')
        binding=envelope.get('task_binding',{})
        if not isinstance(binding,dict):raise DatabaseUnavailable('维护待办处理范围无法读取。')
        history=results.setdefault(target,[])
        if len(history)>=30:continue
        history.append({'operation_id':operation['id'],'committed_at':operation['committed_at'],
            'reason':normalized.get('reason'),
            'previous_status':binding.get('status'),'target':binding,
            'resolved_fields':envelope.get('fields',[]),
            'receipt':_json(operation['receipt_json'],dict) if operation['receipt_json'] else None})
    return results


def project_tasks(connection,metadata,*,limit=20,before=None,source_key=None,include_resolved=True):
    """Caller authenticates first. Items retain real integer task IDs for retry.

    Groups also cover current source/field/quarantine gaps that have no stored
    task. Those gaps have stable scope keys but cannot manufacture retry IDs.
    Reopening a stored task preserves its earlier operation receipts in history.
    """
    if (type(limit) is not int or not 1<=limit<=100 or before is not None and (type(before) is not int or before<=0)
            or type(include_resolved) is not bool or source_key is not None and (not isinstance(source_key,str) or not source_key or len(source_key)>120)):
        raise ValueError('维护待办筛选或分页参数无效。')
    sources={row['source_key']:dict(row) for row in connection.execute('SELECT * FROM sources')}
    if source_key is not None and source_key not in sources:raise ValueError('维护来源不存在。')
    resolutions=_resolutions(connection);groups={};items=[]
    def group(key,reason,*,opportunity_id=None,field=None,task_id=None,active=True,basis=None):
        if source_key is not None and key!=source_key:return
        stable=key+':'+reason
        entry=groups.setdefault(stable,{'group_key':stable,'source_key':key,'school_key':sources[key]['school_key'],
            'reason':reason,'reason_label':LABELS[reason],'next_action':ACTIONS[reason],
            '_active':set(),'_resolved':set(),'_opportunities':set(),'_fields':set(),'_tasks':set(),'_basis':set()})
        scope=str(opportunity_id or 'source')+':'+str(field or '*')
        entry['_active' if active else '_resolved'].add(scope)
        if opportunity_id:entry['_opportunities'].add(opportunity_id)
        if field:entry['_fields'].add(field)
        if task_id:entry['_tasks'].add(task_id)
        if basis:entry['_basis'].add(basis)
    for task in connection.execute('SELECT t.*,o.title,o.source_url FROM processing_tasks t LEFT JOIN opportunities o ON o.id=t.opportunity_id ORDER BY t.id DESC'):
        if source_key is not None and task['source_key']!=source_key:continue
        if task['task_kind']!='maintenance' and task['status'] not in ACTIVE and task['id'] not in resolutions:continue
        active=task['status'] in ACTIVE
        if not active and not include_resolved:continue
        history=resolutions.get(task['id'],[])
        result=_json(task['result_json'] or '{}',dict);reason=_reason(task,result,history)
        field=result.get('field') if isinstance(result.get('field'),str) else None
        if field is None and task['task_identity'].startswith(('quarantine:','manual-conflict:')):
            pieces=task['task_identity'].split(':',2)
            field=pieces[2] if len(pieces)==3 else None
        group(task['source_key'],reason,opportunity_id=task['opportunity_id'],field=field,
            task_id=task['id'],active=active,basis='stored_task')
        if before is not None and task['id']>=before:continue
        items.append({**dict(task),'result':result,'task_key':task['source_key']+':'+task['task_kind']+':'+task['task_identity'],
            'reason':reason,'reason_label':LABELS[reason],'next_action':ACTIONS[reason],
            'retry_supported':bool(task['opportunity_id'] and task['source_url'] and task['status'] in ('pending','failed','partial')),
            'resolution_history':history})
    for key,source in sources.items():
        if source['status']=='restricted':group(key,'public_restriction',basis='source_status')
        elif source['status']=='failed':group(key,'source_failure',basis='source_status')
    for row in connection.execute("SELECT o.* FROM opportunities o WHERE NOT EXISTS (SELECT 1 FROM field_decisions d WHERE d.opportunity_id=o.id AND d.field_name='__visibility__' AND d.value_json='false')"):
        observations=_json(row['field_observations_json'],dict)
        for field in (*CORE_FIELDS,'relevance'):
            if row['date_basis']=='publication' and field in ('event_date','start_time','end_time','event_venue'):continue
            observation=observations.get(field)
            state=observation.get('state') if isinstance(observation,dict) else 'not_collected'
            if state in ('not_collected','pending_extraction','parse_failed','conflict'):
                group(row['source_key'],'field_pending',opportunity_id=row['id'],field=field,basis='current_field_state')
    for row in connection.execute('SELECT q.*,o.source_key FROM quarantined_evidence q JOIN opportunities o ON o.id=q.opportunity_id'):
        # A resolved stored quarantine task is historical, while its immutable
        # retained evidence is still audit data rather than a fresh active gap.
        stored=connection.execute("SELECT status FROM processing_tasks WHERE source_key=? AND task_kind='maintenance' AND task_identity=?",
            (row['source_key'],'quarantine:'+str(row['opportunity_id'])+':'+row['field_name'])).fetchone()
        active=not stored or stored['status'] in ACTIVE
        if active or include_resolved:
            group(row['source_key'],'material_quarantine',opportunity_id=row['opportunity_id'],field=row['field_name'],active=active,basis='quarantined_evidence')
    projected=[]
    for entry in sorted(groups.values(),key=lambda item:item['group_key']):
        projected.append({key:value for key,value in entry.items() if not key.startswith('_')}|
            {'active_scope_count':len(entry['_active']),'resolved_scope_count':len(entry['_resolved']),
             'opportunity_count':len(entry['_opportunities']),'opportunity_ids':sorted(entry['_opportunities']),
             'fields':sorted(entry['_fields']),'task_ids':sorted(entry['_tasks']),'basis':sorted(entry['_basis'])})
    page=items[:limit]
    return {'dataset_id':metadata['dataset_id'],'data_mode':metadata['data_mode'],'items':page,'groups':projected,
        'has_more':len(items)>limit,'next_cursor':page[-1]['id'] if len(items)>limit else None,
        'include_resolved':include_resolved,'source_key':source_key,
        'message':'按来源及原因去重；处理完成的待办保留历史。字段未取得不等于未披露。'}


def read_tasks(database_path,**kwargs):
    with read_database(database_path) as (connection,metadata):return project_tasks(connection,metadata,**kwargs)
