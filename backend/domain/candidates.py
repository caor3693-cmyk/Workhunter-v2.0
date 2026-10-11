"""Validate bounded source candidates without HTTP, SQL or private adapter flags."""
from copy import deepcopy
from datetime import date, datetime, time
import ipaddress
from urllib.parse import urlsplit

CORE_FIELDS = ('published_date', 'event_date', 'start_time', 'end_time', 'deadline', 'event_venue', 'work_locations')
STATES = {'known', 'not_collected', 'pending_extraction', 'parse_failed', 'not_disclosed', 'not_applicable', 'conflict'}
KINDS = {'campus_talk', 'job_fair', 'online_recruitment', 'announcement'}
MAX_INTEGER = 9223372036854775807
OFFICIAL_HOSTS = {'scut': {'cnsba.scut.edu.cn', 'jyzx.scut.edu.cn'}, 'gdut': {'career.gdut.edu.cn'}}


def safe_url(value, school_key=None):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError('来源链接无效。')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError('来源链接无效。') from error
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or port not in {None, 80, 443}:
        raise ValueError('仅接受官方公开 HTTP(S) 链接。')
    host = parsed.hostname.lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('来源链接必须为官方域名。')
    if school_key and host not in OFFICIAL_HOSTS.get(school_key, set()):
        raise ValueError('来源链接不属于本轮学校官方域名。')
    if host == 'localhost' or '.' not in host:
        raise ValueError('不能读取本机或内部链接。')
    return value


def _text(value, label, limit=2000, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()) or '\x00' in value:
        raise ValueError(f'{label}缺失或超过长度限制。')
    return value


def _date(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 10 or date.fromisoformat(value).isoformat() != value:
        raise ValueError('日期必须为明确的 YYYY-MM-DD。')
    return value


def _time(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 5 or time.fromisoformat(value).strftime('%H:%M') != value:
        raise ValueError('时段必须为明确的 HH:MM，不补造时刻。')
    return value


def validate_evidence(items, school_key):
    if not isinstance(items, list) or len(items) > 16:
        raise ValueError('证据必须为有界数组。')
    result = []
    for evidence in items:
        if not isinstance(evidence, dict):
            raise ValueError('证据结构无效。')
        item = deepcopy(evidence)
        # Adapters have references; stored projections have real material IDs.
        if not item.get('material_ref') and not (type(item.get('material_id')) is int and 0 < item['material_id'] <= MAX_INTEGER):
            raise ValueError('证据未绑定实际材料。')
        if item.get('material_ref'):
            _text(item['material_ref'], '材料引用', 256, True)
        item['source_url'] = safe_url(item.get('source_url'), school_key)
        for field in ('locator', 'excerpt', 'parser_version'):
            _text(item.get(field), field, 2000, True)
        scope = item.get('scope')
        if not isinstance(scope, (dict, str)) or not scope:
            raise ValueError('证据缺少适用范围。')
        _text(item.get('observed_at'), '观察时间', 100, True)
        stamp = datetime.fromisoformat(item['observed_at'])
        if stamp.tzinfo is None:
            raise ValueError('证据观察时间必须有时区。')
        result.append(item)
    return result


def validate_candidate(candidate, source_config):
    if not isinstance(candidate, dict):
        raise ValueError('候选结构无效。')
    data = deepcopy(candidate)
    for key in ('school_key', 'source_key'):
        if data.get(key) != source_config.get(key):
            raise ValueError('学校与来源归属不一致。')
    _text(data.get('source_identity'), '官方记录身份', 2048, True)
    _text(data.get('title'), '原标题', 1000, True)
    data['source_url'] = safe_url(data.get('source_url'), data['school_key'])
    if not isinstance(data.get('kind'),str) or data['kind'] not in KINDS or data.get('date_basis') not in ('event', 'publication'):
        raise ValueError('招聘类型或时间含义无效。')
    data.setdefault('original_kind', None)
    _text(data['original_kind'], '来源类型', 1000)
    data.setdefault('source_updated_at', None)
    if data['source_updated_at'] is not None:
        _text(data['source_updated_at'], '官方修改时间',100,True)
        if datetime.fromisoformat(data['source_updated_at']).tzinfo is None:
            raise ValueError('官方修改时间必须有时区。')
    for field in ('published_date', 'event_date', 'deadline'):
        data[field] = _date(data.get(field))
    for field in ('start_time', 'end_time'):
        data[field] = _time(data.get(field))
    if data['start_time'] and data['end_time'] and data['end_time'] < data['start_time']:
        raise ValueError('未标跨日的结束时间早于开始时间。')
    data['event_venue'] = _text(data.get('event_venue'), '本场会场')
    locations = data.get('work_locations', [])
    if not isinstance(locations, list) or len(locations) > 50:
        raise ValueError('工作地结构无效。')
    data['work_locations'] = list(dict.fromkeys(_text(value, '工作地', 300, True) for value in locations))
    data.setdefault('work_locations_scope', 'this_announcement')
    if data['work_locations_scope'] not in ('this_announcement', 'disclosed_employers', 'partial_disclosed'):
        raise ValueError('工作地适用范围无效。')
    campus = data.get('campus_key')
    if campus is not None:
        _text(campus, '校区key', 100, True)
    observations = data.get('field_observations', {})
    if not isinstance(observations, dict) or set(observations) - (set(CORE_FIELDS) | {'relevance'}):
        raise ValueError('字段观察结构无效。')
    for field in CORE_FIELDS:
        observations.setdefault(field, {'state': 'not_collected', 'value': None, 'evidence': []})
    for field, observation in observations.items():
        if not isinstance(observation, dict) or not isinstance(observation.get('state'),str) or observation['state'] not in STATES:
            raise ValueError('字段证据状态无效。')
        observation['evidence'] = validate_evidence(observation.get('evidence', []), data['school_key'])
        value = observation.get('value')
        if observation['state'] == 'known':
            if value is None or value == '' or value == [] or not observation['evidence']:
                raise ValueError('已知字段必须有真实值及定位证据。')
            if field in CORE_FIELDS and value != data.get(field):
                raise ValueError('业务字段与已知观察不一致。')
        elif value is not None:
            raise ValueError('未知观察不得存伪值。')
        if observation['state'] in {'not_disclosed', 'not_applicable'} and not observation['evidence']:
            raise ValueError('已检查未披露或不适用必须有材料依据。')
        if field in CORE_FIELDS and observation['state'] not in {'known', 'conflict'} and data.get(field) not in (None, []):
            raise ValueError('未知字段不得显示为已知事实。')
        if observation['state'] == 'conflict' and len(observation['evidence']) < 2:
            raise ValueError('冲突需保留两份有效证据。')
    data['field_observations'] = observations
    data.setdefault('relevance', 'unknown')
    if data['relevance'] not in ('related', 'unknown', 'unrelated'):
        raise ValueError('相关性无效。')
    if observations.get('relevance', {}).get('state') == 'known' and observations['relevance']['value'] != data['relevance']:
        raise ValueError('相关性业务值与观察不一致。')
    if data['relevance'] != 'unknown':
        proof = observations.get('relevance', {})
        if proof.get('state') != 'known' or proof.get('value') != data['relevance']:
            raise ValueError('明确相关或无关必须有本条材料依据。')
    for field in ('event_status', 'recruitment_status'):
        data.setdefault(field, 'not_applicable' if field == 'event_status' and data['date_basis'] == 'publication' else 'unknown')
        if data[field] not in ('unknown', 'scheduled', 'rescheduled', 'cancelled', 'open', 'closed', 'not_applicable'):
            raise ValueError('活动或招聘状态无效。')
    for field in ('roster_fragments', 'job_fragments', 'attachments'):
        values = data.get(field, [])
        if not isinstance(values, list) or len(values) > 8:
            raise ValueError('片段或附件超过限量。')
        for value in values:
            if not isinstance(value, dict) or not value.get('scope'):
                raise ValueError('片段缺少适用范围。')
            if field == 'attachments':
                safe_url(value.get('url'), data['school_key'])
                _text(value.get('label'), '附件名', 500, True)
            else:
                if value['scope'] not in ('partial', 'complete_for_material', 'unknown'):
                    raise ValueError('片段适用范围无效。')
                _text(value.get('text'), '片段', 2000, True)
            value['evidence'] = validate_evidence(value.get('evidence', []), data['school_key'])
            if not value['evidence']:
                raise ValueError('片段或附件缺少材料证据。')
        data[field] = values
    return data
