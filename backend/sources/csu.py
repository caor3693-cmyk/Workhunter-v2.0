"""CSU's previously observed 403 path stays stopped; no alternate channel."""
from .transport import FetchError


class CsuAdapter:
    @staticmethod
    def discover(config, fetcher, cursor=None):
        # A real 403 was observed on this tenant in this delivery. A fixture or
        # a different HTTP client must never turn that observation into access.
        raise FetchError("中南大学公开入口已观察到403；本轮停止该路径，待官方解除限制后重新核验", restricted=True, status_code=403)

    @staticmethod
    def enrich(candidate, fetcher):
        raise FetchError("中南大学403路径仍受限，未尝试详情或替代通道", restricted=True, status_code=403)
