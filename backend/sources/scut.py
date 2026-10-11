"""Public SCUT college announcements; the authenticated main portal stays restricted."""

import re

from .common import (
    attachments, campus_key, candidate_base, clean, deadline, evidence, explicit_locations,
    fill_missing, job_fragments, labeled, material_reference, next_page, normalized, observation,
    page_result, parse_date, parse_times, related_evidence, safe_url, set_known,
    set_observation, soup, unread_materials,
)
from .transport import FetchError


def discover(source_config, fetcher, cursor=None):
    url = cursor or source_config["official_entry_url"]
    # A cursor can only continue the registered public college column.
    if not re.fullmatch(r"https://cnsba\.scut\.edu\.cn/jysx/list(?:\d+)?\.htm", url):
        raise FetchError("华工来源游标不属于已核验的公开栏目")
    response = fetcher.get(url)
    document = soup(response["text"])
    material = material_reference(response, source_config["source_key"], scope={
        "type": "source_list", "coverage": "complete_for_page", "page_url": response["url"],
    })
    records, seen = [], set()
    for link in document.select(".title.clearfix a[href]"):
        identity = re.search(r"/20\d{2}/\d+/c29313a(\d+)/page\.htm", link["href"])
        official_url = safe_url(link["href"], response["url"])
        title = clean(link.get("title") or link.get_text(" ", strip=True))
        if not identity or not official_url or not title or identity[1] in seen:
            continue
        seen.add(identity[1])
        record = candidate_base(source_config, identity[1], title, official_url,
                                "announcement", "学院就业资讯", "publication")
        published = link.parent.select_one(".date")
        if published and (value := parse_date(published.get_text())):
            set_known(record, "published_date", value, material,
                      f".title a[href*='a{identity[1]}/'] + .date", published.get_text())
        records.append(record)
    next_cursor, warnings = next_page(document, response["url"])
    if next_cursor and not re.fullmatch(r"https://cnsba\.scut\.edu\.cn/jysx/list(?:\d+)?\.htm", next_cursor):
        warnings.append("下一页不属于已核验学院栏目，已停止该路径")
        next_cursor = None
    return page_result(source_config, response, records, next_cursor, warnings,
                       scope_note="华南理工大学工商管理学院就业资讯；学院局部材料，不代表全校自动覆盖")


def enrich(candidate, fetcher):
    if not re.fullmatch(r"https://cnsba\.scut\.edu\.cn/20\d{2}/\d+/c29313a\d+/page\.htm", candidate["source_url"]):
        raise FetchError("详情链接不属于已核验学院公告路径")
    response = fetcher.get(candidate["source_url"])
    document = soup(response["text"])
    content = document.select_one(".wp_articlecontent")
    material = material_reference(response, candidate["source_key"], candidate["source_identity"])
    if content is None:
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material],
                "warnings": ["学院公告正文未取得，基础公告及已知列表字段保留"]}
    material["scope"]["coverage"] = "partial" if unread_materials(content) else "complete_for_material"
    text = content.get_text("\n", strip=True)
    patch, warnings = {"field_observations": {}}, []
    title = document.select_one(".inner-text h2.big-title")
    if title and clean(title.get_text()):
        patch["title"] = clean(title.get_text())
    published = document.select_one(".info-time")
    if published and (value := parse_date(published.get_text())):
        set_observation(patch, candidate, "published_date", value, material, ".info-time", published.get_text())
    event_text = labeled(text, ["宣讲时间", "举办时间", "活动时间"])
    event_semantics = bool(event_text or re.search(r"宣讲地点|举办地点|活动地点", text)
                           or re.search(r"宣讲会|双选会|招聘会", patch.get("title", candidate["title"])))
    if event_semantics:
        patch.update({"kind": "campus_talk", "original_kind": "学院宣讲信息", "date_basis": "event", "event_status": "unknown"})
        value = parse_date(event_text or "")
        if value:
            set_observation(patch, candidate, "event_date", value, material, ".wp_articlecontent", event_text)
        elif event_text:
            set_observation(patch, candidate, "event_date", None, material,
                            ".wp_articlecontent", event_text, state="parse_failed")
            warnings.append("活动仅披露月日，未从发布日期或届次推断举办年份")
        start, end = parse_times(event_text or "")
        for name, value in (("start_time", start), ("end_time", end)):
            if value:
                set_observation(patch, candidate, name, value, material, ".wp_articlecontent", event_text)
        venue = labeled(text, ["宣讲地点", "举办地点", "活动地点"])
        if not venue and event_text:
            inline = re.search(
                r"\d{1,2}:\d{2}\s*[-~至]\s*\d{1,2}:\d{2}\s*[,，]\s*([^。；;\n]{1,160})",
                normalized(event_text),
            )
            if inline and campus_key("scut", inline[1]):
                venue = clean(inline[1])
        if venue:
            set_observation(patch, candidate, "event_venue", venue, material, ".wp_articlecontent", venue)
            key = campus_key("scut", venue)
            if key:
                patch["campus_key"] = key
    locations = explicit_locations(text)
    if locations:
        set_observation(patch, candidate, "work_locations", locations, material,
                        ".wp_articlecontent", "、".join(locations))
    cutoff, cutoff_text = deadline(text, ordinary=not event_semantics)
    if cutoff:
        set_observation(patch, candidate, "deadline", cutoff, material, ".wp_articlecontent", cutoff_text)
    related = related_evidence(text)
    if related:
        patch["relevance"] = "related"
        patch["field_observations"]["relevance"] = observation(
            "known", "related", [evidence(material, ".wp_articlecontent", related)],
        )
    patch["attachments"] = attachments(content, response["url"], material)
    patch["job_fragments"] = job_fragments(content, material, ".wp_articlecontent")
    fill_missing(patch, candidate, material, content, ".wp_articlecontent", event_semantics=event_semantics)
    return {"patch": patch, "material_refs": [material], "warnings": warnings}


class ScutAdapter:
    discover = staticmethod(discover)
    enrich = staticmethod(enrich)
