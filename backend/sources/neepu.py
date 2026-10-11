"""NEEPU's exact public school subdomain, via visible homepage links."""
from .hnu import cloud_discover, cloud_enrich


class NeepuAdapter:
    @staticmethod
    def discover(config, fetcher, cursor=None):
        return cloud_discover(config, fetcher, cursor, school_key="neepu", host="jy.neepu.edu.cn")

    @staticmethod
    def enrich(candidate, fetcher):
        return cloud_enrich(candidate, fetcher, school_key="neepu", host="jy.neepu.edu.cn")
