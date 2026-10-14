"""GZHU's public SSR recruitment briefs, with announcement-local tables."""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from .common import (
    attachments, campus_key, candidate_base, clean, deadline, evidence, explicit_locations,
    fill_missing, job_fragments, material_reference, observation, page_result,
    parse_date, related_evidence, safe_url, set_known, set_observation, soup, unread_materials, workplace_blocks,
)
from .transport import FetchError

HOST = "jy.gzhu.edu.cn"
EVENT_CHANNELS = {"preach": ("campus_talk", "公开宣讲会"), "jobfair": ("job_fair", "公开招聘会")}


def _identity(url, channel="jobs-brief"):
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (parts.scheme != "https" or parts.netloc != HOST or parts.fragment
            or parts.path not in {f"/web/Index/{channel}-detail", f"/index.php/web/Index/{channel}-detail"}
            or set(query) != {"id"} or len(query["id"]) != 1
            or not re.fullmatch(r"[A-Za-z0-9]{3,40}" if channel == "jobs-brief" else r"[1-9]\d{0,11}", query["id"][0])):
        return None
    return query["id"][0]


def _event_page(url, channel):
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    return (parts.scheme == "https" and parts.netloc == HOST and not parts.fragment
        and parts.path in {f"/web/Index/{channel}-list", f"/index.php/web/Index/{channel}-list"}
        and (not parts.query or (set(query) == {"p"} and len(query["p"]) == 1
            and re.fullmatch(r"[1-9]\d{0,5}", query["p"][0]))))


def _event_values(node):
    values = {}
    for symbol, field in (("icon-shijian", "event_date"), ("icon-didian", "event_venue")):
        marker = node.select_one("." + symbol)
        container = (marker.find_parent(class_="caption") or marker.find_parent(class_="text")
            or marker.find_parent("p")) if marker else None
        text = clean(container.get_text(" ", strip=True)) if container else ""
        if not text:
            continue
        if field == "event_venue":
            values[field] = re.sub(r"^地点\s*[:：]?\s*", "", text)
            continue
        schedule = text.replace("/", "-")
        if value := parse_date(schedule):
            values[field] = value
        times = re.findall(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", schedule)
        if times:
            values["start_time"] = f"{int(times[0][0]):02}:{times[0][1]}"
        dates = re.findall(r"20\d{2}-\d{1,2}-\d{1,2}", schedule)
        if len(times) == 2 and (len(dates) < 2 or dates[0] == dates[1]):
            end = f"{int(times[1][0]):02}:{times[1][1]}"
            if end >= values["start_time"]:
                values["end_time"] = end
    return values


def _event_discover(config, fetcher, cursor, channel):
    url = cursor or config["official_entry_url"]
    if config["school_key"] != "gzhu" or not _event_page(url, channel):
        raise FetchError("广州大学游标不属于已核验的本校公开活动栏目")
    response = fetcher.get(url)
    if response["url"] != url:
        raise FetchError("广州大学活动列表最终响应改变栏目或分页身份，已停止解析", material_ref=response)
    document = soup(response["text"])
    material = material_reference(response, config["source_key"], scope={"type": "source_list", "coverage": "complete_for_page", "page_url": url})
    records, seen, warnings = [], set(), []
    for link in document.select(f".container a[href*='{channel}-detail']"):
        target = safe_url(link["href"], url)
        identity = _identity(target, channel) if target else None
        heading = link.select_one(".title, .card-title")
        title = clean(link.get("title") or (heading.get_text(" ", strip=True) if heading else ""))
        if not identity or not title or len(title) > 1000 or identity in seen:
            continue
        seen.add(identity)
        kind, original = EVENT_CHANNELS[channel]
        item = candidate_base(config, identity, title, target, kind, original, "event")
        locator = f"a[href='{link['href']}']"
        for field, value in _event_values(link).items():
            set_known(item, field, value, material, locator + " [活动时间或地点]", link.get_text(" ", strip=True))
        if key := campus_key("gzhu", item["event_venue"]):
            item["campus_key"] = key
        records.append(item)
    next_cursor = None
    for link in document.select(".pagination a[href]"):
        if link.get("aria-label") != "下一页" and clean(link.get_text()) != "下一页":
            continue
        if "disabled" in link.get("class", []) or "disabled" in link.parent.get("class", []):
            break
        target = urljoin(url, link["href"])
        parts = urlsplit(target)
        # This school's published pagination spells HTTP; the same exact
        # endpoints were independently verified over HTTPS before registration.
        if parts.scheme == "http" and parts.netloc == HOST:
            target = "https:" + target[len("http:"):]
        current_page = int(parse_qs(urlsplit(url).query).get("p", ["1"])[0])
        if (_event_page(target, channel)
                and int(parse_qs(urlsplit(target).query).get("p", ["1"])[0]) == current_page + 1):
            next_cursor = safe_url(target, url)
        if not next_cursor:
            warnings.append("广州大学下一页未对应本栏目相邻页，停止续跑，不能宣称完整覆盖")
        break
    return page_result(config, response, records, next_cursor, warnings,
        scope_note=f"广州大学官方公开{EVENT_CHANNELS[channel][1]}栏目有限分页；不含其他栏目、登录或完整名单，不宣称全校覆盖")


def discover(config, fetcher, cursor=None):
    if config.get("channel_key") in EVENT_CHANNELS:
        return _event_discover(config, fetcher, cursor, config["channel_key"])
    url = cursor or config["official_entry_url"]
    parts = urlsplit(url)
    if (config["school_key"] != "gzhu" or parts.scheme != "https" or parts.netloc != HOST
            or parts.path not in {"", "/", "/web/Index/index"} or parts.query or parts.fragment):
        raise FetchError("广州大学来源游标不属于已核验的公开首页")
    response = fetcher.get(url)
    final = urlsplit(response["url"])
    if final.scheme != "https" or final.netloc != HOST or final.path not in {"", "/", "/web/Index/index"} or final.query or final.fragment:
        raise FetchError("广州大学首页跳转至未经核验栏目，已停止解析", material_ref=response)
    document = soup(response["text"])
    records, seen = [], set()
    for link in document.select("a[href*='jobs-brief-detail']"):
        target = safe_url(link["href"], response["url"])
        identity = _identity(target) if target else None
        heading = link.select_one(".title")
        # The public homepage wraps both the title and a long body preview in
        # one anchor. Only its explicit heading is the announcement title.
        title = clean(link.get("title") or (heading.get_text(" ", strip=True) if heading else link.get_text(" ", strip=True)))
        if identity and title and len(title) <= 1000 and identity not in seen:
            seen.add(identity)
            records.append(candidate_base(config, identity, title, target,
                "announcement", "公开招聘简章", "publication"))
    return page_result(config, response, records, None, [],
        scope_note="广州大学官方就业首页公开招聘简章显式链接；首页有限发现，不宣称十校完整覆盖")


def _table_grid(table):
    """Keep source column semantics when job tables merge their cells."""
    pending = {}
    for index, row in enumerate(table.select("tr"), 1):
        cells, column = {}, 0
        for key, (remaining, value) in list(pending.items()):
            cells[key] = value
            if remaining > 1:
                pending[key] = (remaining - 1, value)
            else:
                del pending[key]
        for cell in row.find_all(["td", "th"], recursive=False):
            while column in cells:
                column += 1
            try:
                colspan = min(20, max(1, int(cell.get("colspan", 1))))
                rowspan = min(100, max(1, int(cell.get("rowspan", 1))))
            except (TypeError, ValueError):
                colspan = rowspan = 1
            value = clean(cell.get_text(" ", strip=True))
            for key in range(column, column + colspan):
                cells[key] = value
                if rowspan > 1:
                    pending[key] = (rowspan - 1, value)
            column += colspan
        yield index, [cells.get(key, "") for key in range(max(cells, default=-1) + 1)]


def enrich(candidate, fetcher):
    channel = next((value for value in ("jobs-brief", *EVENT_CHANNELS)
        if _identity(candidate["source_url"], value)), "jobs-brief")
    identity = _identity(candidate["source_url"], channel)
    if candidate["school_key"] != "gzhu" or identity != candidate["source_identity"]:
        raise FetchError("广州大学详情必须对应本条官方招聘公告或活动")
    response = fetcher.get(candidate["source_url"])
    document = soup(response["text"])
    event = channel in EVENT_CHANNELS
    wrapper = document.select_one(".activity-page-wrapper" if channel == "preach" else ".page-content-detail")
    body = wrapper.select_one(".content-wrapper .col-xs-8 > .content" if channel == "preach" else ".content-wrapper") if wrapper else None
    if channel == "jobfair" and body is not None:
        combined = soup("<div></div>").div
        for section in wrapper.select(".content-wrapper"):
            combined.append(soup(str(section)))
        body = combined
    material = material_reference(response, candidate["source_key"], identity)
    if _identity(response["url"], channel) != identity:
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material], "warnings": ["详情最终响应属于其他招聘简章，未补充本条字段"]}
    if body is None:
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material], "warnings": ["广州大学招聘正文未取得，保留列表基础公告"]}
    patch = {"field_observations": {}}
    title = wrapper.select_one(".header-wrapper .title")
    if title:
        patch["title"] = clean(title.get_text())
    if event:
        header = wrapper.select_one(".header-wrapper") if channel == "preach" else wrapper
        for field, value in (_event_values(header) if header else {}).items():
            set_observation(patch, candidate, field, value, material,
                ".header-wrapper [活动时间或地点]" if channel == "preach" else ".page-content-detail [活动时间或地点]",
                str(value))
        if key := campus_key("gzhu", patch.get("event_venue", candidate.get("event_venue"))):
            patch["campus_key"] = key
    stamp = wrapper.select_one(".header-wrapper .caption[title]")
    if stamp:
        value = stamp.get("title", "").replace("/", "-")
        if date_value := parse_date(value):
            set_observation(patch, candidate, "published_date", date_value, material,
                ".page-content-detail .header-wrapper .caption[title]", stamp.get("title"))
    text = body.get_text("\n", strip=True)
    material["scope"]["coverage"] = "partial" if unread_materials(body) else "complete_for_material"
    locations, fragments, related = [], [], None
    for table_index, table in enumerate(body.select("table"), 1):
        headers = None
        for row_index, cells in _table_grid(table):
            if "工作地点" in cells and any(value in ({"专业", "需求专业", "专业要求", "岗位名称", "招聘岗位"} if event else {"专业", "需求专业", "专业要求"}) for value in cells):
                headers = cells
                continue
            if not headers or len(cells) != len(headers):
                continue
            major_column = next((index for index, value in enumerate(headers) if value in {"专业", "需求专业", "专业要求"}), None)
            location = cells[headers.index("工作地点")]
            if location and len(location) <= 300 and location not in locations:
                locations.append(location)
            excerpt = "；".join(f"{key}：{value}" for key, value in zip(headers, cells))
            locator = f".content-wrapper table:nth-of-type({table_index}) tr:nth-of-type({row_index})"
            if len(fragments) < 8 and excerpt:
                fragments.append({"text": excerpt[:2000], "scope": "partial", "evidence": [evidence(material, locator, excerpt)]})
            if major_column is not None and not related and re.search(r"电气|电力|电网|继电保护|(?<!机械设计制造及其)自动化", cells[major_column]):
                related = (locator, excerpt)
    if locations:
        set_observation(patch, candidate, "work_locations", locations[:30], material,
            ".content-wrapper table [工作地点列]", "、".join(locations))
        patch["work_locations_scope"] = "partial_disclosed"
    elif event:
        groups = workplace_blocks(body)
        values = list(dict.fromkeys(value for group, _, _ in groups for value in group))[:30]
        if values:
            set_observation(patch, candidate, "work_locations", values, material,
                ".content-wrapper " + groups[0][1], "、".join(values))
    elif values := explicit_locations(text):
        set_observation(patch, candidate, "work_locations", values, material, ".content-wrapper [工作地点]", "、".join(values))
    if related:
        patch["relevance"] = "related"
        patch["field_observations"]["relevance"] = observation("known", "related", [evidence(material, *related)])
    elif event:
        # Use the shared announcement-local job/major rule, never the title or
        # company background; public event schedules do not imply relevance.
        paragraphs = "\n".join(node.get_text(" ", strip=True) for node in body.find_all(["p", "li"]))
        if proof := related_evidence(paragraphs):
            patch["relevance"] = "related"
            patch["field_observations"]["relevance"] = observation("known", "related", [evidence(material, ".content-wrapper [招聘岗位或专业]", proof)])
    cutoff, cutoff_text = deadline(text, ordinary=True)
    if cutoff:
        set_observation(patch, candidate, "deadline", cutoff, material, ".content-wrapper", cutoff_text)
    patch["job_fragments"] = fragments or job_fragments(body, material, ".content-wrapper")
    patch["attachments"] = attachments(body, response["url"], material)
    fill_missing(patch, candidate, material, body, ".content-wrapper", event_semantics=event)
    return {"patch": patch, "material_refs": [material], "warnings": []}


class GzhuAdapter:
    discover = staticmethod(discover)
    enrich = staticmethod(enrich)
