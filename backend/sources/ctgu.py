"""China Three Gorges University's exact, officially linked JYSD tenant."""
import re
from urllib.parse import urljoin, urlsplit

from .gdut import CHANNELS, jysd_enrich
from .common import (
    campus_key, candidate_base, clean, decode_public_slots, material_reference,
    next_page, page_result, parse_date, parse_times, safe_url, set_known,
)
from .transport import FetchError


def _school_column(url, channel, host, key):
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.netloc == host and not parts.query and not parts.fragment
        and re.fullmatch(rf"/{channel}(?:/index(?:/(?:do123/{re.escape(host)}/)?domain/{key}(?:/city/[^/]*)?(?:/page/[1-9]\d*)?)?)?/?", parts.path))


def school_column_discover(config, fetcher, cursor=None, *, key, host):
    """SHIEP/CTGU public row layout and exact per-school paging format."""
    channel = config["channel_key"].removeprefix(key + "_")
    homepage = channel == "homepage"
    if homepage:
        channel = "campus"  # Never put two type-specific ID namespaces in one source.
    url = cursor or config["official_entry_url"]
    home_url = f"https://{host}/"
    if config["school_key"] != key or channel not in CHANNELS or not (url == home_url if homepage else _school_column(url, channel, host, key)):
        raise FetchError("学校栏目游标不属于已核验的独立公开租户")
    response = fetcher.get(url)
    if response["url"] != url:
        raise FetchError("学校栏目最终响应改变游标身份，已停止解析", material_ref=response)
    document, warnings = decode_public_slots(response["text"])
    material = material_reference(response, config["source_key"], scope={"type": "source_list", "coverage": "complete_for_page", "page_url": response["url"]})
    records, seen = [], set()
    rows = document.select(f"a[href*='/{channel}/view/id/']") if homepage else document.select(".infoList")
    for row in rows:
        link = row if homepage else row.select_one(f"a[href*='/{channel}/view/id/']")
        if not link:
            continue
        # These exact school hosts publish both http and https link spellings;
        # only their already verified public HTTPS counterparts are requested.
        raw_target = urljoin(response["url"], link["href"])
        raw_parts = urlsplit(raw_target)
        if raw_parts.scheme == "http" and raw_parts.netloc == host:
            raw_target = "https:" + raw_target[len("http:"):]
        target = safe_url(raw_target, response["url"])
        identity = re.fullmatch(rf"https://{re.escape(host)}/{channel}/view/id/(\d+)", target or "")
        title = clean(link.get("title") or link.get_text(" ", strip=True))
        cells = row.find_all("li", recursive=False)
        if not identity or not title or identity[1] in seen or (not homepage and len(cells) < 2):
            continue
        seen.add(identity[1])
        kind, basis = CHANNELS[channel]
        original = {"teachin": "宣讲会", "jobfair": "招聘会", "campus": "招聘简章"}[channel]
        if basis == "event" and len(cells) >= 4:
            marker = clean(cells[1].get_text())
            if marker:
                original = marker
            if "线上" in marker or "网络" in marker:
                kind = "online_recruitment"
        item = candidate_base(config, identity[1], title, target, kind, original, basis)
        locator = f".infoList:has(a[href*='/{channel}/view/id/{identity[1]}'])"
        if not homepage and basis == "event":
            schedule, venue = clean(cells[-1].get_text()), clean(cells[-2].get_text())
            if value := parse_date(schedule):
                set_known(item, "event_date", value, material, locator + " li:last-child", schedule)
            start, end = parse_times(schedule)
            for name, value in (("start_time", start), ("end_time", end)):
                if value:
                    set_known(item, name, value, material, locator + " li:last-child", schedule)
            if venue:
                set_known(item, "event_venue", venue, material, locator + " li:nth-last-child(2)", venue)
                if campus := campus_key(key, venue):
                    item["campus_key"] = campus
        elif not homepage and (value := parse_date(cells[-1].get_text())):
            set_known(item, "published_date", value, material, locator + " li:last-child", cells[-1].get_text())
        records.append(item)
    cursor, page_warnings = (None, []) if homepage else next_page(document, response["url"])
    warnings.extend(page_warnings)
    if cursor and not _school_column(cursor, channel, host, key):
        warnings.append("下一页不属于同校同栏目公开租户，停止续跑")
        cursor = None
    return page_result(config, response, records, cursor, warnings,
        scope_note=f"{key}官方公开{channel}栏目；有限分页，学校/会场/工作地保持各自含义")


class CtguAdapter:
    @staticmethod
    def discover(config, fetcher, cursor=None):
        return school_column_discover(config, fetcher, cursor, key="ctgu", host="ctgu.91wllm.cn")

    @staticmethod
    def enrich(candidate, fetcher):
        return jysd_enrich(candidate, fetcher, school_key="ctgu", host="ctgu.91wllm.cn")
