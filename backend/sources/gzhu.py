"""GZHU's public SSR recruitment briefs, with announcement-local tables."""
import re
from urllib.parse import parse_qs, urlsplit

from .common import (
    attachments, candidate_base, clean, deadline, evidence, explicit_locations,
    fill_missing, job_fragments, material_reference, observation, page_result,
    parse_date, safe_url, set_observation, soup, unread_materials,
)
from .transport import FetchError

HOST = "jy.gzhu.edu.cn"


def _identity(url):
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (parts.scheme != "https" or parts.netloc != HOST or parts.fragment
            or parts.path != "/web/Index/jobs-brief-detail" or set(query) != {"id"}
            or len(query["id"]) != 1 or not re.fullmatch(r"[A-Za-z0-9]{3,40}", query["id"][0])):
        return None
    return query["id"][0]


def discover(config, fetcher, cursor=None):
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
    identity = _identity(candidate["source_url"])
    if candidate["school_key"] != "gzhu" or identity != candidate["source_identity"]:
        raise FetchError("广州大学详情必须对应本条官方招聘简章")
    response = fetcher.get(candidate["source_url"])
    document = soup(response["text"])
    wrapper = document.select_one(".page-content-detail")
    body = wrapper.select_one(".content-wrapper") if wrapper else None
    material = material_reference(response, candidate["source_key"], identity)
    if _identity(response["url"]) != identity:
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material], "warnings": ["详情最终响应属于其他招聘简章，未补充本条字段"]}
    if body is None:
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material], "warnings": ["广州大学招聘正文未取得，保留列表基础公告"]}
    patch = {"field_observations": {}}
    title = wrapper.select_one(".header-wrapper .title")
    if title:
        patch["title"] = clean(title.get_text())
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
            if "工作地点" in cells and any(value in {"专业", "需求专业", "专业要求"} for value in cells):
                headers = cells
                continue
            if not headers or len(cells) != len(headers):
                continue
            major_column = next(index for index, value in enumerate(headers) if value in {"专业", "需求专业", "专业要求"})
            location = cells[headers.index("工作地点")]
            if location and len(location) <= 300 and location not in locations:
                locations.append(location)
            excerpt = "；".join(f"{key}：{value}" for key, value in zip(headers, cells))
            locator = f".content-wrapper table:nth-of-type({table_index}) tr:nth-of-type({row_index})"
            if len(fragments) < 8 and excerpt:
                fragments.append({"text": excerpt[:2000], "scope": "partial", "evidence": [evidence(material, locator, excerpt)]})
            if not related and re.search(r"电气|电力|电网|继电保护|(?<!机械设计制造及其)自动化", cells[major_column]):
                related = (locator, excerpt)
    if locations:
        set_observation(patch, candidate, "work_locations", locations[:30], material,
            ".content-wrapper table [工作地点列]", "、".join(locations))
        patch["work_locations_scope"] = "partial_disclosed"
    elif values := explicit_locations(text):
        set_observation(patch, candidate, "work_locations", values, material, ".content-wrapper [工作地点]", "、".join(values))
    if related:
        patch["relevance"] = "related"
        patch["field_observations"]["relevance"] = observation("known", "related", [evidence(material, *related)])
    cutoff, cutoff_text = deadline(text, ordinary=True)
    if cutoff:
        set_observation(patch, candidate, "deadline", cutoff, material, ".content-wrapper", cutoff_text)
    patch["job_fragments"] = fragments or job_fragments(body, material, ".content-wrapper")
    patch["attachments"] = attachments(body, response["url"], material)
    fill_missing(patch, candidate, material, body, ".content-wrapper", event_semantics=False)
    return {"patch": patch, "material_refs": [material], "warnings": []}


class GzhuAdapter:
    discover = staticmethod(discover)
    enrich = staticmethod(enrich)
