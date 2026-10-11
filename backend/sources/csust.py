"""CSUST's officially linked, school-specific public Cloud Career tenant."""
import json
import re

from .common import candidate_base, campus_key, clean, page_result, parse_date, safe_url, set_known, soup
from .hnu import cloud_discover, cloud_enrich


def _embedded_careers(response, config):
    """Read only the JSON and route already published in this homepage."""
    document = soup(response["text"])
    route = "'/detail/career?id=' + itemChild['career_talk_id']"
    if not any(clean(link.get(":href")) == route for link in document.select("a")):
        return [], []
    payloads = []
    for script in document.find_all("script", src=False):
        text = script.get_text()
        if len(text.encode("utf-8")) > 2_000_000:
            continue
        matches = list(re.finditer(r"(?m)^\s*const\s+data\s*=\s*", text))
        for match in matches:
            try:
                value, end = json.JSONDecoder().raw_decode(text[match.end():])
            except (ValueError, RecursionError):
                continue
            if isinstance(value, dict) and text[match.end() + end:].lstrip().startswith(";"):
                payloads.append(value)
    if len(payloads) != 1:
        return [], ["公开首页内嵌宣讲数据缺失或不唯一，未执行页面脚本"]
    panels = payloads[0].get("panels")
    if not isinstance(panels, list) or len(panels) > 64:
        return [], ["公开首页宣讲面板结构未核验"]
    material = page_result(config, response, [], None, [], scope_note="公开首页内嵌宣讲面板")["material_refs"][0]
    records, seen = [], set()
    for panel_index, panel in enumerate(panels):
        children = panel.get("children") if isinstance(panel, dict) else None
        if not isinstance(children, list) or len(children) > 64:
            continue
        for child_index, child in enumerate(children):
            if not isinstance(child, dict) or str(child.get("panel_type")) != "1" or child.get("panel_name") != "宣讲会":
                continue
            rows = child.get("list")
            if not isinstance(rows, list) or len(rows) > 100:
                continue
            for row_index, row in enumerate(rows):
                if not isinstance(row, dict) or row.get("school_name") != "长沙理工大学" or str(row.get("inner_school")) != "1":
                    continue
                identity = str(row.get("career_talk_id", ""))
                name = row.get("meet_name")
                title = clean(name) if isinstance(name, str) else ""
                if not re.fullmatch(r"[1-9]\d{0,11}", identity) or not title or len(title) > 1000 or identity in seen or len(records) >= 100:
                    continue
                target = safe_url("/detail/career?id=" + identity, response["url"], school_key="csust")
                if not target:
                    continue
                seen.add(identity)
                item = candidate_base(config, identity, title, target, "campus_talk", "公开宣讲会", "event")
                locator = f"script [const data].panels[{panel_index}].children[{child_index}].list[{row_index}][career_talk_id={identity}]"
                day = row.get("meet_day")
                if isinstance(day, str) and (value := parse_date(day)):
                    set_known(item, "event_date", value, material, locator + ".meet_day", day)
                start, end = row.get("meet_time"), row.get("meet_end_time")
                for field, value in (("start_time", start), ("end_time", end)):
                    if isinstance(value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                        if field == "end_time" and item["start_time"] and value < item["start_time"]:
                            continue
                        set_known(item, field, value, material, locator + "." + ("meet_time" if field == "start_time" else "meet_end_time"), value)
                address = row.get("address")
                venue = clean(address) if isinstance(address, str) else ""
                if venue and len(venue) <= 2000:
                    set_known(item, "event_venue", venue, material, locator + ".address", venue)
                    if campus := campus_key("csust", venue):
                        item["campus_key"] = campus
                records.append(item)
    return records, []


class CsustAdapter:
    @staticmethod
    def discover(config, fetcher, cursor=None):
        class Capture:
            response = None

            def get(self, url):
                self.response = fetcher.get(url)
                return self.response

        capture = Capture()
        page = cloud_discover(config, capture, cursor, school_key="csust", host="csust.bysjy.com.cn")
        if page["records"] or config["channel_key"].removeprefix("csust_") not in {"careers", "career", "homepage"}:
            return page
        records, warnings = _embedded_careers(capture.response, config)
        return page_result(config, capture.response, records, None, warnings,
            scope_note="长沙理工官方公开首页已返回JSON的本校宣讲会面板；有限发现，不执行脚本、不访问猜测接口、不代表全校覆盖")

    @staticmethod
    def enrich(candidate, fetcher):
        return cloud_enrich(candidate, fetcher, school_key="csust", host="csust.bysjy.com.cn")
