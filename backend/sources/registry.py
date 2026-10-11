"""Fixed school capability registry; pending registration never implies coverage."""
from backend.domain.source_policy import FIXED_SCHOOLS, school_policy

ADAPTERS = {}


def register_adapter(name, adapter):
    if not name or not callable(getattr(adapter, 'discover', None)) or not callable(getattr(adapter, 'enrich', None)):
        raise ValueError('适配器必须提供公开 discover/enrich 接口。')
    ADAPTERS[name] = adapter


def _defaults():
    from .scut import ScutAdapter, ScutNcssAdapter
    from .gdut import GdutAdapter
    for name, adapter in {'scut':ScutAdapter(),'scut_cnsba':ScutAdapter(),'scut_ncss':ScutNcssAdapter(),'gdut':GdutAdapter()}.items():
        ADAPTERS.setdefault(name,adapter)


def get_adapter(config_or_name):
    _defaults()
    name = (config_or_name.get('adapter') or config_or_name['school_key']) if isinstance(config_or_name,dict) else config_or_name
    if name not in ADAPTERS:
        raise ValueError('该来源适配器尚未实现，不能声明已覆盖。')
    return ADAPTERS[name]


def capabilities():
    _defaults()
    return [{ 'school_key':key, 'state':'implemented' if any(s.get('adapter') in ADAPTERS for s in school_policy(key).get('sources',[])) else 'pending',
              'sources':[{'source_key':s['source_key'],'implemented':s.get('adapter') in ADAPTERS} for s in school_policy(key).get('sources',[])] }
            for key in sorted(FIXED_SCHOOLS)]
