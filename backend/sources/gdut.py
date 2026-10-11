"""GDUT public columns and detail materials, without search or job requests."""

import re
from urllib.parse import urlsplit

from .common import (
    attachments, campus_key, candidate_base, clean, deadline, decode_public_slots,
    evidence, explicit_locations, fill_missing, job_fragments, labeled, material_reference,
    next_page, observation, page_result, parse_date, parse_times, related_evidence,
    safe_url, set_known, set_observation, soup, unread_materials,
)
from .transport import FetchError

CHANNELS = {"teachin": ("campus_talk", "event"), "jobfair": ("job_fair", "event"),
            "campus": ("announcement", "publication")}


def channel_name(config):
    channel = config["channel_key"].removeprefix("gdut_")
    if channel not in CHANNELS:
        raise ValueError("Unknown registered GDUT column")
    return channel


def _column_cursor(url, channel):
    parts = urlsplit(url)
    return (
        parts.scheme == "https" and parts.hostname == "career.gdut.edu.cn"
        and not parts.query
        and re.fullmatch(rf"/{channel}(?:/index(?:/do123/career\.gdut\.edu\.cn/domain/gdut(?:/city/?)?(?:/page/\d+)?)?)?/?", parts.path)
    )


def discover(source_config, fetcher, cursor=None):
    channel = channel_name(source_config)
    url = cursor or source_config["official_entry_url"]
    if not _column_cursor(url, channel):
        raise FetchError("广工来源游标不属于已核验的无关键词栏目")
    response = fetcher.get(url)
    document, warnings = decode_public_slots(response["text"])
    material = material_reference(response, source_config["source_key"], scope={
        "type": "source_list", "coverage": "complete_for_page", "page_url": response["url"],
    })
    records, seen = [], set()
    for row in document.select(".infoList"):
        link = row.select_one(f"a[href*='/{channel}/view/id/']")
        if not link:
            continue
        match = re.search(rf"/{channel}/view/id/(\d+)", link["href"])
        official_url = safe_url(link["href"], response["url"])
        title = clean(link.get("title") or link.get_text(" ", strip=True))
        cells = row.find_all("li", recursive=False)
        if not match or not official_url or not title or match[1] in seen or len(cells) < 2:
            continue
        seen.add(match[1])
        kind, date_basis = CHANNELS[channel]
        marker = row.select_one(".status-text")
        original_kind = clean(marker.get_text()) if marker else {"teachin": "宣讲会", "jobfair": "招聘会", "campus": "招聘简章"}[channel]
        if date_basis == "event" and original_kind in ("线上", "网络"):
            kind = "online_recruitment"
        record = candidate_base(source_config, match[1], title, official_url, kind, original_kind, date_basis)
        locator = f".infoList:has(a[href*='/{channel}/view/id/{match[1]}'])"
        if date_basis == "event":
            venue, schedule = clean(cells[1].get_text()), clean(cells[-1].get_text())
            if value := parse_date(schedule):
                set_known(record, "event_date", value, material, locator, schedule)
            start, end = parse_times(schedule)
            for name, value in (("start_time", start), ("end_time", end)):
                if value:
                    set_known(record, name, value, material, locator, schedule)
            if venue:
                set_known(record, "event_venue", venue, material, locator, venue)
                key = campus_key("gdut", venue)
                if key:
                    record["campus_key"] = key
        else:
            published = clean(cells[-1].get_text())
            if value := parse_date(published):
                set_known(record, "published_date", value, material, locator, published)
        records.append(record)
    next_cursor, pagination_warnings = next_page(document, response["url"])
    warnings.extend(pagination_warnings)
    if next_cursor and not _column_cursor(next_cursor, channel):
        next_cursor = None
        warnings.append("下一页不属于已核验公开栏目，已停止续跑")
    return page_result(source_config, response, records, next_cursor, warnings,
                       scope_note=f"广东工业大学公开{channel}栏目；单页发现，不宣称整校或全部类型覆盖")


def enrich(candidate, fetcher):
    if not re.fullmatch(r"https://career\.gdut\.edu\.cn/(teachin|jobfair|campus)/view/id/\d+", candidate["source_url"]):
        raise FetchError("详情链接不属于本公告的已核验公开路径")
    response = fetcher.get(candidate["source_url"])
    document, warnings = decode_public_slots(response["text"])
    wrapper = document.select_one(".zp-details")
    material = material_reference(response, candidate["source_key"], candidate["source_identity"])
    if wrapper is None:
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material],
                "warnings": [*warnings, "详情主体未取得，基础公告及已知列表字段保留"]}
    title = wrapper.select_one(".title-message h5")
    patch = {"field_observations": {}}
    if title and clean(title.get_text()):
        patch["title"] = clean(title.get_text())
    body_nodes = [node for node in wrapper.select(".aContent")
                  if node.find_parent(class_="details-mge")]
    body = soup("<div></div>").div
    for node in body_nodes:
        body.append(soup(str(node)))
    body_text = body.get_text("\n", strip=True)
    full_text = wrapper.get_text("\n", strip=True)
    material["scope"]["coverage"] = "partial" if unread_materials(body) else "complete_for_material"
    if not body_text:
        material["parsing_status"] = "partial"
        material["scope"]["coverage"] = "partial"
        warnings.append("详情正文尚未可靠取得；仅补充本页已取得的明确事实")
    for item in wrapper.select(".details-title .share li"):
        text = clean(item.get_text())
        if "发布时间" in text and (value := parse_date(text)):
            set_observation(patch, candidate, "published_date", value, material,
                            ".details-title .share li", text)
            break
    event_semantics = candidate["date_basis"] == "event"
    if event_semantics:
        # Structured detail labels describe this specific record; the invitation
        # body may also advertise other sessions and must not replace that date.
        schedule = labeled(full_text, ["宣讲时间", "举办时间"])
        if schedule and (value := parse_date(schedule)):
            set_observation(patch, candidate, "event_date", value, material,
                            ".zp-details [公开安排正文槽]", schedule)
        start, end = parse_times(schedule or "")
        for name, value in (("start_time", start), ("end_time", end)):
            if value:
                set_observation(patch, candidate, name, value, material,
                                ".zp-details [公开安排正文槽]", schedule)
        venue = labeled(full_text, ["举办地点", "举办地址", "宣讲地点"])
        if venue:
            set_observation(patch, candidate, "event_venue", venue, material,
                            ".zp-details [公开安排正文槽]", venue)
            key = campus_key("gdut", venue)
            if key:
                patch["campus_key"] = key
        if re.search(r"关于取消.*(?:宣讲|招聘会)|(?:宣讲会|招聘会).{0,12}(?:已取消|取消通知)", candidate["title"]):
            patch["event_status"] = "cancelled"
    locations, location_evidence = [], []
    for info in wrapper.select("table .info-text"):
        if not info.select_one("a[href*='/job/view/id/']"):
            continue
        cells = info.select("ul > li")
        if len(cells) >= 2:
            location = clean(cells[1].get_text())
            if location and len(location) <= 120:
                if location not in locations:
                    locations.append(location)
                    location_evidence.append(evidence(material, "table .info-text ul > li:nth-child(2)", location))
    if locations:
        previous = candidate.get("field_observations", {}).get("work_locations", {})
        if previous.get("state") == "known" and candidate.get("work_locations") != locations:
            patch["field_observations"]["work_locations"] = observation(
                "conflict", None, [*previous.get("evidence", []), *location_evidence],
            )
        else:
            patch["work_locations"] = locations
            patch["field_observations"]["work_locations"] = observation("known", locations, location_evidence)
    elif values := explicit_locations(body_text):
        set_observation(patch, candidate, "work_locations", values, material, ".details-mge .aContent", "、".join(values))
    elif "岗位遍布江西全省各设区市" in clean(body_text):
        set_observation(patch, candidate, "work_locations", ["江西省各设区市"], material,
                        ".details-mge .aContent", "岗位遍布江西全省各设区市")
    cutoff, cutoff_text = deadline(body_text, ordinary=not event_semantics)
    if cutoff:
        set_observation(patch, candidate, "deadline", cutoff, material, ".details-mge .aContent", cutoff_text)
    related = related_evidence(body_text + "\n" + "\n".join(
        row.get_text(" ", strip=True) for row in wrapper.select("table tbody tr")
        if row.select_one("a[href*='/job/view/id/']")
    ))
    if related:
        patch["relevance"] = "related"
        patch["field_observations"]["relevance"] = observation(
            "known", "related", [evidence(material, ".details-mge .aContent / table tbody tr", related)],
        )
    patch["job_fragments"] = job_fragments(wrapper, material, ".zp-details")
    patch["attachments"] = attachments(body, response["url"], material)
    if body_text:
        fill_missing(patch, candidate, material, body, ".details-mge .aContent", event_semantics=event_semantics)
    return {"patch": patch, "material_refs": [material], "warnings": warnings}


class GdutAdapter:
    discover = staticmethod(discover)
    enrich = staticmethod(enrich)
