"""Registered source adapters share one bounded fetch/material protocol."""

from .gdut import GdutAdapter
from .scut import ScutAdapter
from .transport import FetchError, Fetcher

ADAPTERS = {"scut": ScutAdapter(), "scut_cnsba": ScutAdapter(), "gdut": GdutAdapter()}


def get_adapter(config_or_name):
    name = (config_or_name.get("adapter") or config_or_name["school_key"]
            if isinstance(config_or_name, dict) else config_or_name)
    try:
        return ADAPTERS[name]
    except KeyError as exc:
        raise ValueError("Source adapter is not registered") from exc


def discover(source_config, fetcher, cursor=None):
    return get_adapter(source_config).discover(source_config, fetcher, cursor)


def enrich(candidate, fetcher):
    return get_adapter(candidate["school_key"]).enrich(candidate, fetcher)


__all__ = ["ADAPTERS", "FetchError", "Fetcher", "discover", "enrich", "get_adapter"]
