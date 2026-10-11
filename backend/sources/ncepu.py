"""NCEPU Beijing and Baoding keep separate source identities and limitations."""
from .common import page_result
from .transport import FetchError


class NcepuBeijingAdapter:
    @staticmethod
    def discover(config, fetcher, cursor=None):
        raise FetchError("华北电力北京就业入口已观察到483；本轮停止该路径，不尝试替代通道", restricted=True, status_code=483)

    @staticmethod
    def enrich(candidate, fetcher):
        raise FetchError("华北电力北京483路径仍受限，未尝试详情", restricted=True, status_code=483)


class NcepuBaodingAdapter:
    @staticmethod
    def discover(config, fetcher, cursor=None):
        url = cursor or config["official_entry_url"]
        if config["school_key"] != "ncepu" or url != "https://jiuye.ncepu.edu.cn/":
            raise FetchError("保定必须使用独立已登记的官方校区首页")
        response = fetcher.get(url)
        # The live endpoint has so far failed to connect. Its unknown content
        # and routes must not be fabricated as a working adapter/zero result.
        return page_result(config, response, [], None,
            ["保定公开首页尚未取得可核验的招聘栏目结构，等待官方材料核验后扩充适配"],
            scope_note="华北电力保定校区独立官方入口；结构未核验，不计自动采集覆盖")

    @staticmethod
    def enrich(candidate, fetcher):
        raise FetchError("保定详情路径尚未核验，未请求未知详情")


class NcepuAdapter(NcepuBeijingAdapter):
    """Default Beijing capability; Baoding requires its own registration."""
