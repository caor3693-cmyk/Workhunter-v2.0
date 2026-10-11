"""Registered source adapters share one bounded fetch/material protocol."""

from .transport import FetchError, Fetcher
from .registry import ADAPTERS, get_adapter, register_adapter, capabilities


def discover(source_config, fetcher, cursor=None):
    return get_adapter(source_config).discover(source_config, fetcher, cursor)


def enrich(candidate, fetcher):
    from backend.domain.source_policy import school_policy
    sources = school_policy(candidate['school_key']).get('sources',[])
    config = next((item for item in sources if item['source_key']==candidate.get('source_key')),None)
    if config is None:
        raise ValueError('候选来源没有登记具体适配器。')
    return get_adapter(config).enrich(candidate,fetcher)


__all__ = ["ADAPTERS", "FetchError", "Fetcher", "discover", "enrich", "get_adapter"]
