"""Protected material previews and contribution-aware operations on schema 3."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import html
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit, unquote
from uuid import uuid4

from backend.domain.candidates import CORE_FIELDS, safe_url, validate_candidate
from backend.domain.source_policy import approved_hosts, school_policy, validate_url
from backend.services.ingestion import (
    BUSINESS_FIELDS, _bind_evidence, _prepare_materials, _semantic, commit_facts_in_transaction,
    encoded, now,
)
from backend.services.queries import _stored_evidence, detail
from backend.services.semantic_revision import _input_candidate
from backend.sources.common import (
    candidate_base, clean, deadline, evidence, explicit_locations, fill_missing,
    job_fragments, labeled, material_reference, observation, parse_date, parse_times,
    related_evidence, set_known, soup,
)
from backend.sources.registry import get_adapter
from backend.sources.transport import FetchError, Fetcher
from backend.storage.database import DatabaseUnavailable, read_database
from backend.storage.write import WriteConflict, WriteContext, writer_transaction


EDITABLE_FIELDS = frozenset((*CORE_FIELDS, 'relevance', 'title', 'kind', 'original_kind',
    'date_basis', 'campus_key', 'work_locations_scope', 'event_status', 'recruitment_status',
    'roster_fragments', 'job_fragments', 'attachments'))
PREVIEW_KEYS = frozenset(('environment', 'operation_type', 'school_key', 'source_key', 'url',
    'public_text', 'opportunity_id', 'fields', 'reason'))
COMMIT_KEYS = frozenset(('environment', 'operation_id', 'preview_hash', 'input_hash', 'base_version'))
PLACEHOLDER_TITLE = '材料正文尚待核实'


class MaintenanceError(ValueError):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.status = code, status


def _hash(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def _reason(value):
    if not isinstance(value, str) or not value.strip() or len(value)>1000 or '\x00' in value:
        raise MaintenanceError('maintenance_reason', '请填写不超过 1000 字的操作原因。')
    return value.strip()


def _active(settings, principal, connection=None):
    if not isinstance(principal, dict) or not principal.get('session_id') or not principal.get('actor'):
        raise MaintenanceError('maintenance_unauthorized', '请先登录维护账号。', 401)
    if connection is None:
        with read_database(settings.db_path) as (auth_connection, _):
            return _active(settings, principal, auth_connection)
    row=connection.execute('SELECT actor,expires_at,revoked_at FROM maintenance_sessions WHERE session_hash=?',
        (principal['session_id'],)).fetchone()
    if not row or row['actor']!=principal['actor'] or row['revoked_at']:
        raise MaintenanceError('maintenance_unauthorized', '维护会话已失效，请重新登录。', 401)
    try:
        expiry=datetime.fromisoformat(row['expires_at'])
        if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc): raise ValueError()
    except (TypeError,ValueError):
        raise MaintenanceError('maintenance_unauthorized', '维护会话已失效，请重新登录。', 401)
    return expiry


def target_database(settings, environment):
    if environment not in ('real', 'isolated'):
        raise MaintenanceError('maintenance_environment', '操作环境只接受 real 或 isolated。')
    path=settings.db_path if environment=='real' else getattr(settings, 'acceptance_db_path', None)
    if not path:
        raise MaintenanceError('maintenance_isolation_unavailable', '尚未配置隔离演练库。', 503)
    path=Path(path).resolve()
    if environment=='isolated' and path==Path(settings.db_path).resolve():
        raise MaintenanceError('maintenance_environment', '隔离演练库不能指向真实数据库。', 503)
    with read_database(path) as (_, metadata):
        if environment=='isolated' and metadata['data_mode']!='isolated_fixture':
            raise MaintenanceError('maintenance_environment', '隔离操作只允许显式初始化的样例库。', 503)
        if environment=='real' and metadata['data_mode']=='isolated_fixture':
            raise MaintenanceError('maintenance_environment', '真实维护不能写入样例库。', 503)
    return path, environment=='isolated'


def _config(school_key, source_key):
    school=school_policy(school_key)
    matches=[config for config in school.get('sources', []) if config['source_key']==source_key]
    if len(matches)!=1:
        raise MaintenanceError('maintenance_source', '学校与来源必须使用已登记的同一公开来源。')
    config={**deepcopy(matches[0]), 'campuses':deepcopy(school.get('campuses', []))}
    get_adapter(config)
    return config


def _identity(config, url):
    validate_url(url, config['school_key'], fetch=True)
    parts=urlsplit(url)
    if parts.hostname!=urlsplit(config['official_entry_url']).hostname:
        raise MaintenanceError('maintenance_record_url','链接不是所选登记来源的公开主机。')
    channel=re.match(r'^/(teachin|jobfair|campus)/',parts.path)
    if channel and config.get('channel_key') in ('teachin','jobfair','campus') and channel[1]!=config['channel_key']:
        raise MaintenanceError('maintenance_record_url','链接栏目与所选登记来源不一致。')
    patterns=(r'/(?:teachin|jobfair|campus)/view/id/([1-9]\d*)/?',
        r'/student/jobs/([A-Za-z0-9]{8,80})/detail\.html', r'.*c\d+a([1-9]\d*)/page\.htm')
    for pattern in patterns:
        match=re.fullmatch(pattern, parts.path)
        if match and not parts.query: return match[1]
    query=parse_qs(parts.query, keep_blank_values=True)
    if (parts.path in ('/detail/career', '/detail/jobfair', '/detail/job', '/detail/general',
            '/web/Index/jobs-brief-detail') and set(query)=={'id'} and len(query['id'])==1
            and re.fullmatch(r'[A-Za-z0-9]{1,80}',query['id'][0])):
        return query['id'][0]
    raise MaintenanceError('maintenance_record_url', '请提供已登记来源中单条公告的公开详情链接。')


def _archive_supplied(path, environment, url, text):
    body=text.encode('utf-8')
    digest=hashlib.sha256(body).hexdigest()
    root=path.parent/'.maintenance-materials'/environment
    root.mkdir(parents=True, exist_ok=True)
    target=root/digest
    try:
        with target.open('xb') as stream: stream.write(body)
    except FileExistsError:
        if target.read_bytes()!=body: raise MaintenanceError('maintenance_archive', '材料归档校验失败。', 503)
    return {'url':url, 'text':text, 'body':body, 'reference_key':_hash({'url':url,'hash':digest,'provenance':'maintainer_public_text'}),
        'material_hash':digest, 'raw_reference':target.as_posix(), 'fetched_at':now(),
        'content_type':'text/plain; charset=utf-8', 'status_code':None}


def _base(config, identity, url):
    path=urlsplit(url).path
    event='/teachin/' in path or '/jobfair/' in path or '/detail/career' in path or '/detail/jobfair' in path
    kind='job_fair' if 'jobfair' in path else 'campus_talk' if event else 'online_recruitment'
    return candidate_base(config,identity,PLACEHOLDER_TITLE,url,kind,None,'event' if event else 'publication')


def _plain_candidate(config, base, response):
    # Maintainers may provide lawful public text. It is not an HTTP success or
    # an automatic source observation, and never supplies platform ownership.
    if school_policy(config['school_key']).get('requires_adapter_identity') or config.get('adapter')=='scut_ncss':
        raise MaintenanceError('maintenance_owner_evidence', '共享平台须提供保留学校身份标记的公开页面，单独正文不能证明学校归属。')
    text=response['text']; title=labeled(text,['标题','公告标题','岗位名称'])
    if not title: raise MaintenanceError('maintenance_material_unusable', '提供的公开正文缺少明确标题，请补齐原文标题与内容。')
    item={**deepcopy(base),'title':title}
    archive=material_reference(response,config['source_key'],item['source_identity'],scope={
        'type':'this_announcement','coverage':'partial','provenance':'maintainer_public_text',
        'acquisition_mode':'manual_public_text','note':'维护者提供的公开正文，未宣称网络获取成功'})
    for field,labels in (('published_date',['发布时间','发布日期']),('event_date',['宣讲时间','举办时间'])):
        value=labeled(text,labels)
        if value and (stamp:=parse_date(value)) and (field!='event_date' or item['date_basis']=='event'):
            set_known(item,field,stamp,archive,'maintainer_public_text/'+field,value)
    schedule=labeled(text,['宣讲时间','举办时间'])
    if schedule and item['date_basis']=='event':
        start,end=parse_times(schedule)
        if start:set_known(item,'start_time',start,archive,'maintainer_public_text/schedule',schedule)
        if end:set_known(item,'end_time',end,archive,'maintainer_public_text/schedule',schedule)
    venue=labeled(text,['宣讲地点','举办地点','举办地址'])
    if venue and item['date_basis']=='event':set_known(item,'event_venue',venue,archive,'maintainer_public_text/venue',venue)
    if locations:=explicit_locations(text):set_known(item,'work_locations',locations,archive,'maintainer_public_text/work_locations','、'.join(locations))
    cutoff,excerpt=deadline(text,ordinary=True)
    if cutoff:set_known(item,'deadline',cutoff,archive,'maintainer_public_text/deadline',excerpt)
    if related:=related_evidence(text):
        item['relevance']='related';item['field_observations']['relevance']=observation('known','related',[
            evidence(archive,'maintainer_public_text/recruitment',related)])
    content=soup('<div>'+''.join('<p>'+html.escape(line)+'</p>' for line in text.splitlines())+'</div>')
    patch={};fill_missing(patch,item,archive,content,'maintainer_public_text',event_semantics=item['date_basis']=='event')
    item.update({k:v for k,v in patch.items() if k!='field_observations'})
    item['field_observations'].update(patch.get('field_observations',{}))
    item['job_fragments']=job_fragments(content,archive,'maintainer_public_text')
    return item,[archive],['维护者提供的公开正文；网络来源状态不因此变为检查成功。']


def _parse_material(path, environment, config, identity, payload, fetcher_factory):
    base=_base(config,identity,payload['url'])
    supplied=payload.get('public_text')
    if supplied is not None:
        response=_archive_supplied(path,environment,payload['url'],supplied)
        if Fetcher._restricted_body(supplied):
            raise MaintenanceError('maintenance_restricted', '提供的材料含登录或验证限制，不能当作公开招聘正文。')
        if not re.search(r'<[A-Za-z][^>]*>',supplied):return _plain_candidate(config,base,response)
        class Provided:
            def get(self,url):
                if url!=payload['url']:raise FetchError('提供的正文不适用于另一材料链接')
                return response
        parsed=get_adapter(config).enrich(base,Provided())
        for material in parsed.get('material_refs',[]):
            material['scope']={**material.get('scope',{}),'provenance':'maintainer_public_text',
                'acquisition_mode':'manual_public_text','note':'维护者提供的公开正文，未宣称网络获取成功'}
    else:
        with fetcher_factory(material_root=path.parent/'.maintenance-materials'/environment,
                allowed_hosts=approved_hosts(config['school_key']),school_key=config['school_key'],
                max_requests=3,max_bytes=512_000,max_seconds=15,max_retries=0) as fetcher:
            parsed=get_adapter(config).enrich(base,fetcher)
    materials=parsed.get('material_refs',[])
    if not materials or any(m.get('acquisition_status')!='success' or m.get('parsing_status')=='failed' for m in materials):
        raise MaintenanceError('maintenance_material_unusable','材料未可靠取得或解析，未生成可提交事实。')
    for material in materials:
        if material.get('official_record_id')==identity and _identity(config,material['source_url'])!=identity:
            raise MaintenanceError('maintenance_material_unusable','实际取得的材料不属于本条公告身份。')
    patch=parsed.get('patch',{})
    base.update({k:v for k,v in patch.items() if k!='field_observations'})
    base['field_observations'].update(patch.get('field_observations',{}))
    if base['title']==PLACEHOLDER_TITLE:
        raise MaintenanceError('maintenance_material_unusable','正文未取得本条公告标题，不能只用 URL 补造机会。')
    return base,materials,parsed.get('warnings',[])


def _normalize(payload):
    if not isinstance(payload,dict) or set(payload)-PREVIEW_KEYS:
        raise MaintenanceError('maintenance_input','维护预览含不支持的输入字段。')
    result=deepcopy(payload)
    result['reason']=_reason(result.get('reason'))
    if result.get('environment') not in ('real','isolated') or result.get('operation_type') not in ('supplement','correction'):
        raise MaintenanceError('maintenance_operation','请选择操作环境及补录或纠错类型。')
    for name in ('school_key','source_key','url'):
        if not isinstance(result.get(name),str) or not result[name].strip() or len(result[name])>2048:
            raise MaintenanceError('maintenance_input','学校、来源和官方链接无效。')
        result[name]=result[name].strip()
    if 'opportunity_id' in result and (type(result['opportunity_id']) is not int or result['opportunity_id']<=0):
        raise MaintenanceError('maintenance_target','目标记录身份无效。')
    if 'fields' in result:
        if not isinstance(result['fields'],list) or any(not isinstance(field,str) for field in result['fields']) or set(result['fields'])-EDITABLE_FIELDS:
            raise MaintenanceError('maintenance_fields','修订字段不属于允许的公告字段。')
        result['fields']=sorted(set(result['fields']))
    if 'public_text' in result:
        text=result['public_text']
        if not isinstance(text,str) or not text.strip() or len(text.encode('utf-8'))>262_144 or '\x00' in text:
            raise MaintenanceError('maintenance_material_size','公开正文为空或超过 256 KiB。')
        result['public_text']=text.replace('\r\n','\n').replace('\r','\n').strip()
    decoded_path = urlsplit(result['url']).path
    for _ in range(len(decoded_path)+1):
        following = unquote(decoded_path)
        if following == decoded_path: break
        decoded_path = following
    if '/__isolated_fixture__/' in decoded_path and (result['environment']!='isolated' or not result.get('public_text')):
        raise MaintenanceError('maintenance_environment','隔离占位链接仅接受演练环境及本机提供的合成正文，不得写入真实库或访问外站。')
    return result


def _selected_field(field):return 'campus_id' if field=='campus_key' else field


def _difference(before,after,fields):
    return {field:{'before':deepcopy(before.get(field)) if before else None,'after':deepcopy(after.get(field)),
        'before_observation':deepcopy(before.get('field_observations',{}).get(field)) if before else None,
        'after_observation':deepcopy(after.get('field_observations',{}).get(field))} for field in fields}


def _save_preview(settings,principal,path,fixture,payload,envelope,ttl_seconds):
    expiry=_active(settings,principal)
    if type(ttl_seconds) is not int or not 1<=ttl_seconds<=3600:raise MaintenanceError('maintenance_expiry','预览有效期无效。')
    expires=min(expiry,datetime.now(timezone.utc)+timedelta(seconds=ttl_seconds)).isoformat()
    operation_id='maintenance-'+uuid4().hex
    envelope={**envelope,'normalized_input':payload,'environment':payload['environment'],
        'session_id':principal['session_id'],'actor':principal['actor'],'operation_id':operation_id,'expires_at':expires}
    input_hash=_hash(payload);preview_hash=_hash(envelope)
    target=envelope['target']
    with writer_transaction(path) as (connection,_):
        _active(settings,principal,connection if not fixture else None)
        connection.execute('INSERT INTO manual_operations(id,actor,operation_type,opportunity_id,preview_hash,base_version,input_json,difference_json,expires_at,status,reverts_operation_id,session_id,input_hash,idempotency_key,expected_version,target_source_key,target_identity) VALUES (?,?,?,?,?,?,?,?,?,\'preview\',?,?,?,?,?,?,?)',
            (operation_id,principal['actor'],envelope['change_kind'],target.get('opportunity_id'),preview_hash,envelope['base_version'],
                encoded(envelope),encoded(envelope['differences']),expires,envelope.get('reverts_operation_id'),principal['session_id'],input_hash,preview_hash,
                envelope['base_version'],target['source_key'],target['source_identity']))
    return {'operation_id':operation_id,'preview_hash':preview_hash,'input_hash':input_hash,
        'base_version':envelope['base_version'],'expires_at':expires,'environment':payload['environment'],
        'operation_type':envelope['change_kind'],'target':target,'candidate':envelope.get('after'),
        'differences':envelope['differences'],'warnings':envelope.get('warnings',[]),
        'retained_fields':envelope.get('retained_fields',[]),'visible':envelope.get('visible',True)}


def preview_materials(settings,principal,payload,*,fetcher_factory=Fetcher,ttl_seconds=900):
    normalized=_normalize(payload);_active(settings,principal)
    path,fixture=target_database(settings,normalized['environment'])
    config=_config(normalized['school_key'],normalized['source_key'])
    try:
        normalized['url']=safe_url(normalized['url'],config['school_key'])
        identity=_identity(config,normalized['url'])
    except MaintenanceError:raise
    except ValueError as exc:raise MaintenanceError('maintenance_source_url','材料链接不属于本学校已批准的公开来源。') from exc
    parsed,materials,warnings=_parse_material(path,normalized['environment'],config,identity,normalized,fetcher_factory)
    if parsed.get('relevance')=='unknown' and not parsed['field_observations'].get('relevance'):
        owned=next((item for item in materials if item.get('official_record_id')==identity and item.get('acquisition_status')=='success'),None)
        if owned:
            parsed['field_observations']['relevance']=observation('pending_extraction',None,[
                evidence(owned,'maintenance_material/relevance_pending',parsed['title'])])
    prepared=_prepare_materials(materials,config,fixture)
    with read_database(path) as (connection,_):
        registered=connection.execute('SELECT school_key FROM sources WHERE source_key=?',(config['source_key'],)).fetchone()
        if not registered or registered['school_key']!=config['school_key']:raise MaintenanceError('maintenance_source','来源尚未在目标环境显式登记。')
        row=connection.execute('SELECT * FROM opportunities WHERE source_key=? AND source_identity=?',(config['source_key'],identity)).fetchone()
        if normalized.get('opportunity_id') is not None and (not row or row['id']!=normalized['opportunity_id']):
            raise MaintenanceError('maintenance_target','官方材料不属于所选目标记录。')
        if normalized['operation_type']=='correction' and not row:raise MaintenanceError('maintenance_target','纠错目标不存在，请先使用补录。',404)
        before=_input_candidate(connection,row) if row else None
        visibility=connection.execute("SELECT value_json FROM field_decisions WHERE opportunity_id=? AND field_name='__visibility__'",(row['id'],)).fetchone() if row else None
        before_visible=visibility is None or json.loads(visibility[0]) is not False
        parsed=validate_candidate(parsed,config)
        fields=normalized.get('fields')
        if fields is None:
            fields=sorted(field for field in EDITABLE_FIELDS if
                (_semantic(parsed.get(field))!=_semantic(before.get(field) if before else None)
                    or (field in CORE_FIELDS and _semantic(parsed['field_observations'][field])!=_semantic(before['field_observations'][field] if before else None)))
                and (field not in (*CORE_FIELDS,'relevance') or parsed['field_observations'].get(field,{}).get('evidence')))
            if before is None:
                fields=[field for field in fields if parsed.get(field) not in (None,[], 'unknown','not_applicable')
                    and (field not in CORE_FIELDS or parsed['field_observations'][field]['state']=='known')]
        if normalized['operation_type']=='supplement' and before and before_visible:
            fields=[field for field in fields if (field in CORE_FIELDS and before['field_observations'][field]['state'] not in ('known','conflict'))
                or field in ('roster_fragments','job_fragments','attachments') or (field=='relevance' and before['relevance']=='unknown')]
        after=deepcopy(before if before and before_visible else parsed)
        if before and not before_visible:
            # Reviving a withdrawn contribution must not resurrect its old known
            # fields through the ordinary conservative merge.
            fields=sorted(set(fields)|{field for field in EDITABLE_FIELDS if
                _semantic(before.get(field))!=_semantic(parsed.get(field)) or
                (field in CORE_FIELDS and _semantic(before['field_observations'][field])!=_semantic(parsed['field_observations'][field]))})
            warnings.append('已撤回记录重新收录，以本次取得的材料重建事实，请核对完整差异。')
        for field in fields:
            if field in CORE_FIELDS or field=='relevance':
                proof=parsed['field_observations'].get(field,{})
                if not proof.get('evidence'):raise MaintenanceError('maintenance_field_evidence','选定字段没有本条材料依据，不能提交更正。')
                after['field_observations'][field]=deepcopy(proof)
            if field=='campus_key' and parsed.get(field) is None:after.pop(field,None)
            else:after[field]=deepcopy(parsed.get(field))
        after=validate_candidate(after,config)
        _bind_evidence(connection,deepcopy(after),prepared)
        decisions=[dict(decision) for decision in connection.execute('SELECT * FROM field_decisions WHERE opportunity_id=?',(row['id'],))] if row else []
        version=row['version'] if row else 0
        contribution_hash=_contribution_hash(connection,row['id']) if row else None
    envelope={'change_kind':'manual_supplement' if normalized['operation_type']=='supplement' else 'manual_correction',
        'source_config':config,'target':{'school_key':config['school_key'],'source_key':config['source_key'],
            'source_identity':identity,'opportunity_id':row['id'] if row else None},'base_version':version,'before':before,'after':after,
        'fields':fields,'materials':prepared,'before_decisions':decisions,'before_visible':before_visible,'contribution_hash':contribution_hash,
        'differences':_difference(before,after,fields),'warnings':warnings,'visible':True}
    if not before_visible:envelope['differences']['__visibility__']={'before':False,'after':True}
    return _save_preview(settings,principal,path,fixture,normalized,envelope,ttl_seconds)


def _load_operation(connection,principal,request,expected_revert=None):
    if not isinstance(request,dict) or set(request)!=COMMIT_KEYS or type(request['base_version']) is not int:
        raise MaintenanceError('maintenance_commit_input','提交只接受完整预览绑定，不能提交任意字段。')
    if any(not isinstance(request[key],str) for key in ('operation_id','preview_hash','input_hash','environment')):
        raise MaintenanceError('maintenance_commit_input','提交预览绑定无效。')
    row=connection.execute('SELECT * FROM manual_operations WHERE id=?',(request['operation_id'],)).fetchone()
    if not row:raise WriteConflict('预览操作不存在，请重新预览。')
    envelope=json.loads(row['input_json'])
    if (row['session_id']!=principal['session_id'] or row['actor']!=principal['actor']
            or envelope['environment']!=request['environment'] or row['expected_version']!=request['base_version']
            or not hmac.compare_digest(row['preview_hash'],request['preview_hash'])
            or not hmac.compare_digest(row['input_hash'],request['input_hash'])
            or row['preview_hash']!=_hash(envelope) or row['input_hash']!=_hash(envelope['normalized_input'])
            or (expected_revert is not None and row['reverts_operation_id']!=expected_revert)):
        raise WriteConflict('预览的会话、环境、输入、类型、目标或版本绑定不一致。')
    return row,envelope


def _decision_restore(connection,target_id,original_id,envelope):
    for field in envelope.get('release_fields',[]):
        connection.execute('DELETE FROM field_decisions WHERE opportunity_id=? AND field_name=? AND operation_id=?',
            (target_id,_selected_field(field),original_id))
    for previous in envelope.get('restore_decisions',[]):
        if not _contribution_active(connection,previous['operation_id'],previous['field_name']):continue
        exists=connection.execute('SELECT operation_id FROM field_decisions WHERE opportunity_id=? AND field_name=?',
            (target_id,previous['field_name'])).fetchone()
        if exists:continue
        connection.execute('INSERT INTO field_decisions(opportunity_id,field_name,operation_id,value_json,evidence_json,base_version,committed_at) VALUES (?,?,?,?,?,?,?)',
            (target_id,previous['field_name'],previous['operation_id'],previous['value_json'],previous['evidence_json'],previous['base_version'],previous['committed_at']))


def _visibility(connection,metadata,target_id,context,receipt,visible,fixture):
    marker=connection.execute("SELECT value_json FROM field_decisions WHERE opportunity_id=? AND field_name='__visibility__'",(target_id,)).fetchone()
    old_visible=marker is None or json.loads(marker[0]) is not False
    if old_visible==visible:return receipt
    connection.execute("INSERT INTO field_decisions(opportunity_id,field_name,operation_id,value_json,evidence_json,base_version,committed_at) VALUES (?,'__visibility__',?,?,'[]',?,?) ON CONFLICT(opportunity_id,field_name) DO UPDATE SET operation_id=excluded.operation_id,value_json=excluded.value_json,evidence_json=excluded.evidence_json,base_version=excluded.base_version,committed_at=excluded.committed_at",
        (target_id,context.operation_id,encoded(visible),context.base_version or 0,receipt['committed_at']))
    connection.execute('INSERT INTO changes(opportunity_id,field_name,before_json,after_json,change_kind,manual_operation_id,actor,committed_at,reason,write_context_key) VALUES (?,\'__visibility__\',?,?,?,?,?,?,?,?)',
        (target_id,encoded(old_visible),encoded(visible),context.change_kind,context.operation_id,context.actor,receipt['committed_at'],context.reason,context.key))
    if receipt['new']==0 and receipt['modified']==0:
        connection.execute('UPDATE opportunities SET version=version+1,content_changed_at=? WHERE id=?',(receipt['committed_at'],target_id))
        metadata['dataset_id']=('fixture-ds-' if fixture else 'ds-')+str(uuid4())
        connection.execute("UPDATE metadata SET value=? WHERE key='dataset_id'",(metadata['dataset_id'],))
        receipt={**receipt,'modified':1,'dataset_id':metadata['dataset_id'],'opportunity_ids':[target_id]}
    return receipt


def commit_operation(settings,principal,request,*,expected_revert=None):
    _active(settings,principal)
    if not isinstance(request,dict):raise MaintenanceError('maintenance_commit_input','提交输入无效。')
    path,fixture=target_database(settings,request.get('environment'))
    with writer_transaction(path) as (connection,metadata):
        _active(settings,principal,connection if not fixture else None)
        operation,envelope=_load_operation(connection,principal,request,expected_revert)
        if operation['status']=='committed' and operation['receipt_json']:
            return {**json.loads(operation['receipt_json']),'replayed':True}
        if operation['status']!='preview':raise WriteConflict('预览已失效，请重新预览。')
        if datetime.fromisoformat(operation['expires_at'])<=datetime.now(timezone.utc):raise WriteConflict('预览已过期，请重新预览。')
        target=envelope['target']
        current=connection.execute('SELECT id,version FROM opportunities WHERE source_key=? AND source_identity=?',
            (target['source_key'],target['source_identity'])).fetchone()
        if (current['version'] if current else 0)!=envelope['base_version'] or (target['opportunity_id'] is not None and (not current or current['id']!=target['opportunity_id'])):
            raise WriteConflict('目标记录已更新，请重新预览。')
        if envelope['contribution_hash']!=(_contribution_hash(connection,current['id']) if current else None):
            raise WriteConflict('预览后出现新的官方观察或人工贡献，请重新预览。')
        if envelope.get('resolves_task_id'):
            task=connection.execute('SELECT * FROM processing_tasks WHERE id=?',(envelope['resolves_task_id'],)).fetchone()
            if not task or _task_binding(task)!=envelope['task_binding']:
                raise WriteConflict('待办状态或目标已改变，请重新预览；受限路径不能重试。')
        context=WriteContext(actor=principal['actor'],operation_id=operation['id'],reason=envelope['normalized_input']['reason'],
            idempotency_key=operation['idempotency_key'],change_kind=envelope['change_kind'],base_version=envelope['base_version'])
        connection.execute("UPDATE manual_operations SET status='committing' WHERE id=?",(operation['id'],))
        candidates=[envelope['after']] if envelope.get('after') is not None else []
        receipt=commit_facts_in_transaction(connection,metadata,envelope['source_config'],candidates,envelope['materials'],context,
            fixture=fixture,replace_fields=[_selected_field(field) for field in envelope['fields']])
        target_id=receipt['opportunity_ids'][0] if receipt['opportunity_ids'] else current['id']
        if envelope.get('reverts_operation_id'):
            _decision_restore(connection,target_id,envelope['reverts_operation_id'],envelope)
        receipt=_visibility(connection,metadata,target_id,context,receipt,envelope.get('visible',True),fixture)
        receipt={**receipt,'operation_id':operation['id'],'environment':request['environment'],
            'visible':envelope.get('visible',True),'retained_fields':envelope.get('retained_fields',[]),'warnings':envelope.get('warnings',[]),
            'version':connection.execute('SELECT version FROM opportunities WHERE id=?',(target_id,)).fetchone()[0]}
        connection.execute('UPDATE write_receipts SET receipt_json=? WHERE context_key=?',(encoded(receipt),context.key))
        connection.execute("UPDATE manual_operations SET status='committed',opportunity_id=?,receipt_json=?,committed_at=? WHERE id=?",(target_id,encoded(receipt),receipt['committed_at'],operation['id']))
        if envelope.get('resolves_task_id'):
            connection.execute("UPDATE processing_tasks SET status='resolved',result_json=?,committed_at=? WHERE id=? AND source_key=?",(encoded({'operation_id':operation['id'],'receipt':receipt}),receipt['committed_at'],envelope['resolves_task_id'],target['source_key']))
        return receipt


def _proof_references(connection,value):
    result=deepcopy(value)
    def visit(item):
        if isinstance(item,dict):
            if 'material_id' in item:
                material=connection.execute('SELECT reference_key FROM source_materials WHERE id=?',(item.pop('material_id'),)).fetchone()
                if not material:raise ValueError('观察材料缺失')
                item['material_ref']=material[0];item.pop('association_id',None)
            for nested in list(item.values()):visit(nested)
        elif isinstance(item,list):
            for nested in item:visit(nested)
    visit(result);return result


def _contribution_hash(connection,opportunity_id):
    decisions=[dict(row) for row in connection.execute('SELECT * FROM field_decisions WHERE opportunity_id=? ORDER BY field_name',(opportunity_id,))]
    latest=connection.execute('SELECT COALESCE(MAX(id),0) FROM official_observations WHERE opportunity_id=?',(opportunity_id,)).fetchone()[0]
    # A covered older contribution can be withdrawn without changing the public
    # version or the latest decision. That still invalidates a restore preview.
    withdrawals=[row[0] for row in connection.execute("SELECT id FROM manual_operations WHERE opportunity_id=? AND status='committed' AND reverts_operation_id IS NOT NULL ORDER BY id",(opportunity_id,))]
    return _hash({'decisions':decisions,'last_official_observation_id':latest,'withdrawals':withdrawals})


def _contribution_active(connection,operation_id,field):
    for row in connection.execute("SELECT input_json FROM manual_operations WHERE reverts_operation_id=? AND status='committed'",(operation_id,)):
        withdrawn=json.loads(row[0])
        fields=withdrawn.get('withdrawn_fields')
        if fields is None:
            original=connection.execute('SELECT input_json FROM manual_operations WHERE id=?',(operation_id,)).fetchone()
            fields=json.loads(original[0]).get('fields',[]) if original else withdrawn.get('release_fields',[])
        if field in {_selected_field(name) for name in fields}:return False
    return True


def _prior_contribution(connection,previous,field):
    """Walk past withdrawn manual predecessors; never resurrect their value."""
    name=_selected_field(field);seen=set()
    for _ in range(32):
        before=previous.get('before')
        if before is None:return None,None
        decision=next((item for item in previous.get('before_decisions',[]) if item['field_name']==name),None)
        if not decision:
            return (None,None) if previous.get('before_visible') is False else (before,None)
        if _contribution_active(connection,decision['operation_id'],name):return before,decision
        if decision['operation_id'] in seen:break
        seen.add(decision['operation_id'])
        original=connection.execute('SELECT input_json FROM manual_operations WHERE id=?',(decision['operation_id'],)).fetchone()
        if not original:break
        previous=json.loads(original[0])
    raise WriteConflict('前值贡献链不完整，请核实材料后重新纠错。')


def _manual_creation(connection,opportunity_id):
    first=connection.execute("SELECT manual_operation_id,committed_at FROM changes WHERE opportunity_id=? AND field_name='__record__' ORDER BY id LIMIT 1",(opportunity_id,)).fetchone()
    if not first or not first['manual_operation_id']:return None
    original=connection.execute('SELECT input_json FROM manual_operations WHERE id=?',(first['manual_operation_id'],)).fetchone()
    if original and json.loads(original[0]).get('before') is None:return first['committed_at']
    return None


def _official_snapshot(connection,row,field,after_time):
    for stored in connection.execute('SELECT * FROM official_observations WHERE opportunity_id=? AND field_name=? ORDER BY julianday(committed_at) DESC,id DESC LIMIT 200',
            (row['id'],_selected_field(field))):
        try:
            if datetime.fromisoformat(stored['committed_at'])<=datetime.fromisoformat(after_time):continue
            snapshot=json.loads(stored['snapshot_json'])
            from backend.services.ingestion import reliable_official_snapshot
            if not reliable_official_snapshot(_selected_field(field),snapshot):continue
            proofs=snapshot.get('evidence') or (snapshot.get('observation') or {}).get('evidence')
            if not proofs:continue
            _stored_evidence(proofs,row,connection)
            return _proof_references(connection,snapshot)
        except (ValueError,TypeError,KeyError,DatabaseUnavailable):continue
    return None


def preview_revert(settings,principal,original_id,payload,*,ttl_seconds=900):
    if not isinstance(payload,dict) or set(payload)!={'environment','reason'}:
        raise MaintenanceError('maintenance_revert_input','撤回预览只接受环境和操作原因。')
    normalized={'environment':payload['environment'],'reason':_reason(payload['reason']),'operation_type':'revert','original_operation_id':original_id}
    _active(settings,principal);path,fixture=target_database(settings,payload['environment'])
    with read_database(path) as (connection,_):
        original=connection.execute('SELECT * FROM manual_operations WHERE id=?',(original_id,)).fetchone()
        if not original or original['status']!='committed' or not original['receipt_json']:
            raise MaintenanceError('maintenance_operation_missing','只能撤回已成功提交的人工操作。',404)
        if original['operation_type'] not in ('manual_supplement','manual_correction'):
            raise MaintenanceError('maintenance_revert_type','此操作不是可撤回的补录或纠错。')
        previous=json.loads(original['input_json'])
        if previous['environment']!=payload['environment']:raise WriteConflict('原操作不属于当前环境。')
        row=connection.execute('SELECT * FROM opportunities WHERE id=?',(original['opportunity_id'],)).fetchone()
        if not row:raise MaintenanceError('maintenance_target','原操作目标不存在。',404)
        before=_input_candidate(connection,row);after=deepcopy(before)
        decisions={r['field_name']:dict(r) for r in connection.execute('SELECT * FROM field_decisions WHERE opportunity_id=?',(row['id'],))}
        fields=[];retained=[];release=[];restore=[];warnings=[]
        independent=any(name!='__visibility__' and decision['operation_id']!=original_id
            and _contribution_active(connection,decision['operation_id'],name) for name,decision in decisions.items())
        for field in previous.get('fields',[]):
            latest=decisions.get(_selected_field(field))
            if latest and latest['operation_id']==original_id:
                _,prior_decision=_prior_contribution(connection,previous,field)
                if prior_decision:independent=True;break
        creation_time=_manual_creation(connection,row['id'])
        for record in connection.execute('SELECT DISTINCT field_name FROM official_observations WHERE opportunity_id=?',(row['id'],)):
            if _official_snapshot(connection,row,record[0],creation_time or original['committed_at']):independent=True;break
        was_new=previous.get('before') is None
        marker=decisions.get('__visibility__')
        current_visible=marker is None or json.loads(marker['value_json']) is not False
        revived=previous.get('before_visible') is False and marker and marker['operation_id']==original_id
        # Reverting an ordinary correction cannot unhide a withdrawn record.
        # Removing the last surviving contribution to a manual-only record does
        # hide it, even when the original creator was withdrawn in an older step.
        visible=current_visible and not ((was_new or revived or creation_time) and not independent)
        for field in previous.get('fields',[]):
            name=_selected_field(field);decision=decisions.get(name)
            if not decision or decision['operation_id']!=original_id:
                retained.append(field);continue
            release.append(field)
            if not visible:continue
            official=_official_snapshot(connection,row,field,original['committed_at'])
            if official:
                value=official['value']
                if field=='campus_key':
                    campus=connection.execute('SELECT campus_key FROM campuses WHERE id=? AND school_key=?',(value,row['school_key'])).fetchone() if value else None
                    value=campus[0] if campus else None
                after[field]=value
                if field in CORE_FIELDS or field=='relevance':after['field_observations'][field]=official['observation']
                warnings.append('撤回保留 '+field+' 的后来官方观察，请核对当前预览。')
            else:
                prior,prior_decision=_prior_contribution(connection,previous,field)
                if prior is not None:
                    after[field]=deepcopy(prior.get(field))
                    if field in CORE_FIELDS or field=='relevance':after['field_observations'][field]=deepcopy(prior['field_observations'].get(field))
                    if prior_decision:restore.append(prior_decision)
                elif field in CORE_FIELDS or field=='relevance':
                    after[field]=[] if field=='work_locations' else 'unknown' if field=='relevance' else None
                    after['field_observations'][field]=observation('not_collected')
                elif field in ('roster_fragments','job_fragments','attachments'):
                    after[field]=[]
                else:
                    retained.append(field);warnings.append('该字段没有可恢复的独立前值，保留当前值并待核实：'+field)
                    continue
            fields.append(field)
        after=validate_candidate(after,previous['source_config'])
        _bind_evidence(connection,deepcopy(after))
        differences=_difference(before,after,fields)
        if current_visible!=visible:differences['__visibility__']={'before':current_visible,'after':visible}
        envelope={'change_kind':'manual_withdrawal' if not visible else 'manual_revert','source_config':previous['source_config'],
            'target':{'school_key':row['school_key'],'source_key':row['source_key'],'source_identity':row['source_identity'],'opportunity_id':row['id']},
            'base_version':row['version'],'before':before,'after':after if fields else None,'fields':fields,'materials':[],
            'differences':differences,'reverts_operation_id':original_id,'release_fields':release,'restore_decisions':restore,
            'withdrawn_fields':previous.get('fields',[]),'retained_fields':retained,'warnings':warnings,'visible':visible}
        envelope['contribution_hash']=_contribution_hash(connection,row['id'])
    return _save_preview(settings,principal,path,fixture,normalized,envelope,ttl_seconds)


def read_opportunity(settings,principal,opportunity_id,*,environment='real',history=False):
    _active(settings,principal);path,_=target_database(settings,environment)
    with read_database(path) as (connection,metadata):
        result=detail(connection,opportunity_id,include_hidden=True)
        if result is None:raise MaintenanceError('maintenance_target','记录不存在。',404)
        marker=connection.execute("SELECT value_json FROM field_decisions WHERE opportunity_id=? AND field_name='__visibility__'",(opportunity_id,)).fetchone()
        result={**result,'environment':environment,'dataset_id':metadata['dataset_id'],'visible':marker is None or json.loads(marker[0]) is not False}
        if history:result['history']=[dict(row) for row in connection.execute('SELECT * FROM changes WHERE opportunity_id=? ORDER BY id DESC LIMIT 200',(opportunity_id,))]
        return result


def list_operations(settings,principal,*,environment='real',limit=20,before=None):
    _active(settings,principal);path,_=target_database(settings,environment)
    if type(limit) is not int or not 1<=limit<=100 or (before is not None and (not isinstance(before,str) or len(before)>200)):
        raise MaintenanceError('maintenance_pagination','操作分页参数无效。')
    with read_database(path) as (connection,metadata):
        cursor=connection.execute('SELECT COALESCE(committed_at,expires_at) AS stamp,id FROM manual_operations WHERE id=?',(before,)).fetchone() if before else None
        if before and not cursor:raise MaintenanceError('maintenance_pagination','操作分页游标不存在。')
        rows=connection.execute('SELECT * FROM manual_operations WHERE (? IS NULL OR COALESCE(committed_at,expires_at)<? OR (COALESCE(committed_at,expires_at)=? AND id<?)) ORDER BY COALESCE(committed_at,expires_at) DESC,id DESC LIMIT ?',
            (before,cursor['stamp'] if cursor else None,cursor['stamp'] if cursor else None,before,limit+1)).fetchall()
        items=[{'operation_id':row['id'],'actor':row['actor'],'operation_type':row['operation_type'],'opportunity_id':row['opportunity_id'],
            'status':row['status'],'committed_at':row['committed_at'],'expires_at':row['expires_at'],
            'reverts_operation_id':row['reverts_operation_id'],'reason':json.loads(row['input_json']).get('normalized_input',{}).get('reason',row['operation_type']),
            'differences':json.loads(row['difference_json']),'receipt':json.loads(row['receipt_json']) if row['receipt_json'] else None,
            'materials':json.loads(row['input_json']).get('materials',[])} for row in rows[:limit]]
        from backend.services.updates import build_summary,SHANGHAI
        return {'environment':environment,'items':items,'has_more':len(rows)>limit,'next_cursor':items[-1]['operation_id'] if len(rows)>limit else None,
            'summary':build_summary(connection,metadata,datetime.now(SHANGHAI).date(),recent_days=getattr(settings,'recent_days',30))}


def list_tasks(settings,principal,*,environment='real',limit=20,before=None):
    _active(settings,principal);path,_=target_database(settings,environment)
    if type(limit) is not int or not 1<=limit<=100 or (before is not None and (type(before) is not int or before<=0)):
        raise MaintenanceError('maintenance_pagination','待办分页参数无效。')
    with read_database(path) as (connection,metadata):
        from backend.services.maintenance_tasks import project_tasks
        return {'environment':environment,**project_tasks(connection,metadata,limit=limit,before=before)}


def _task_binding(task):
    return {key:task[key] for key in ('id','source_key','opportunity_id','status','attempts','last_attempt_at')}


def retry_task_preview(settings,principal,task_id,payload,*,fetcher_factory=Fetcher):
    if not isinstance(payload,dict) or set(payload)!={'environment','reason'}:raise MaintenanceError('maintenance_retry_input','重试只接受环境和原因。')
    _active(settings,principal);path,fixture=target_database(settings,payload['environment'])
    with read_database(path) as (connection,_):
        task=connection.execute('SELECT * FROM processing_tasks WHERE id=?',(task_id,)).fetchone()
        if not task:raise MaintenanceError('maintenance_task','待办不存在。',404)
        if task['status']=='restricted':raise MaintenanceError('maintenance_restricted','受限路径已停止，不能通过维护重试绕过。')
        if task['status'] not in ('pending','failed','partial'):raise MaintenanceError('maintenance_task_status','此待办已处理，请核对操作历史。')
        target=connection.execute('SELECT * FROM opportunities WHERE id=?',(task['opportunity_id'],)).fetchone() if task['opportunity_id'] else None
        if not target:raise MaintenanceError('maintenance_task_target','此来源待办没有单条公告目标，请使用来源同步入口处理。')
        request={'environment':payload['environment'],'operation_type':'correction','school_key':target['school_key'],
            'source_key':target['source_key'],'url':target['source_url'],'opportunity_id':target['id'],'reason':payload['reason']}
        binding=_task_binding(task)
    preview=preview_materials(settings,principal,request,fetcher_factory=fetcher_factory)
    with writer_transaction(path) as (connection,_):
        row=connection.execute('SELECT input_json FROM manual_operations WHERE id=?',(preview['operation_id'],)).fetchone()
        envelope=json.loads(row['input_json']);envelope['resolves_task_id']=task_id;envelope['task_binding']=binding
        digest=_hash(envelope)
        connection.execute('UPDATE manual_operations SET input_json=?,preview_hash=?,idempotency_key=? WHERE id=?',(encoded(envelope),digest,digest,preview['operation_id']))
    return {**preview,'preview_hash':digest}
