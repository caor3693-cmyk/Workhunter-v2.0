"""One config-owned boundary for approved school hosts and platform tenants."""
from functools import lru_cache
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs, unquote

from backend.config import ROOT

FIXED_SCHOOLS = frozenset({'scut','gdut','ncepu','shiep','neepu','csust','ctgu','gzhu','hnu','csu'})
RESTRICTED_PATH = re.compile(r'/(?:cas(?:/|$)|authserver(?:/|$)|user/login|default/ulogin|frontend_static/frontend/login)', re.I)


@lru_cache(maxsize=4)
def _read(path, stamp):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    schools = {s['school_key']: s for s in data['schools']}
    if set(schools) != FIXED_SCHOOLS:
        raise ValueError('来源策略必须保持固定十校。')
    return schools


def school_policy(school_key, config_path=None):
    path = Path(config_path or ROOT / 'config/schools.json').resolve()
    schools = _read(str(path), path.stat().st_mtime_ns)
    if school_key not in schools:
        raise ValueError('学校不在固定范围内。')
    return schools[school_key]


def approved_hosts(school_key=None):
    keys = [school_key] if school_key else sorted(FIXED_SCHOOLS)
    return frozenset(host for key in keys for host in school_policy(key).get('approved_hosts', []))


def validate_url(value, school_key=None, *, fetch=False):
    if not isinstance(value, str) or not value or len(value)>2048 or any(ord(c)<32 for c in value):
        raise ValueError('来源链接无效。')
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ValueError('来源链接无效。') from exc
    if parts.scheme not in ({'https'} if fetch else {'http','https'}) or not parts.hostname or parts.username or parts.password or port not in ({None,443} if fetch else {None,80,443}):
        raise ValueError('仅接受已批准的官方公开链接。')
    host = parts.hostname.lower()
    decoded_path = parts.path
    for _ in range(3):
        next_path = unquote(decoded_path)
        if next_path == decoded_path:
            break
        decoded_path = next_path
    if '\\' in decoded_path or any(segment in {'.','..'} for segment in decoded_path.split('/')):
        raise ValueError('来源路径含改变租户或目录的点段。')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('链接必须使用批准的官方域名。')
    if host=='localhost' or '.' not in host or RESTRICTED_PATH.search(parts.path) or host.startswith(('sso.','authserver.')):
        raise ValueError('登录和内部路径不可用于公开采集。')
    if school_key:
        policy = school_policy(school_key)
        if host not in policy.get('approved_hosts', []):
            raise ValueError('来源链接不属于该校批准主机。')
        tenants = policy.get('platform_tenants', {})
        # A shared platform host is not evidence of school ownership. Its config
        # must identify an exact path/query tenant and a reviewed owner URL.
        if host in tenants:
            tenant = tenants[host]
            prefixes = tenant.get('path_prefixes',[])
            query = parse_qs(parts.query)
            expected=tenant.get('query_identity',{})
            query_ok=bool(expected) and all(query.get(k)==[v] for k,v in expected.items())
            path_ok=any(parts.path==p.rstrip('/') or parts.path.startswith(p.rstrip('/')+'/') for p in prefixes)
            simple_ok=(path_ok and query_ok) if expected else path_ok
            public_ok=parts.path in tenant.get('public_paths',[])
            scoped_ok=any(parts.path==path and bool(required) and all(query.get(k)==[v] for k,v in required.items()) for path,required in tenant.get('scoped_paths',{}).items())
            record_pattern=tenant.get('record_path_pattern')
            record_ok=bool(tenant.get('requires_adapter_identity') and record_pattern and re.fullmatch(record_pattern,parts.path) and not parts.query)
            if not tenant.get('owner_evidence_url') or not (simple_ok or public_ok or scoped_ok or record_ok):
                raise ValueError('共享平台链接没有该校明确租户身份。')
    elif fetch and host not in approved_hosts():
        raise ValueError('主机未登记公开采集策略。')
    if fetch and host=='career.gdut.edu.cn' and (parts.path.startswith('/search') or re.search(r'(?:^|&)(?:keyword|title)=', parts.query)):
        raise ValueError('广工关键词搜索路径不在批准范围。')
    return value


def validate_public_addresses(addresses):
    addresses = list(addresses)
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise ValueError('来源解析到非公开网络，已停止该路径。')
    return addresses
