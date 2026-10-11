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


def _body_location_groups(body):
    """Each explicit role-workplace block keeps its own original locator."""
    for tag in ("p", "li", "td"):
        for index, node in enumerate(body.find_all(tag), 1):
            if tag != "p" and node.find(["p", "li", "td"]):
                continue  # A nested paragraph is already examined independently.
            text = node.get_text("\n", strip=True)
            if not re.search(r"(?:工作地点|工作城市|任职地点|岗位地点|就业地点)\s*[:：]|【工作城市】", text):
                continue
            prefix = re.split(r"(?:工作地点|工作城市|任职地点|岗位地点|就业地点)\s*[:：]|【工作城市】", text, maxsplit=1)[0]
            if re.search(r"公司简介|集团简介|企业背景|总部地址", prefix) and not re.search(r"招聘|岗位|任职", prefix):
                continue
            values = explicit_locations(text)
            output = []
            for value in values:
                # A project travel arrangement is evidence attached to the
                # stated base, not an invented city/standalone workplace.
                if re.match(r"^(?:(?:结合|根据|随|视|按).*(?:项目|需求|安排)|往返|出差|轮岗)", value):
                    continue
                value = re.sub(r"[（(]总部[）)]$", "", value).strip()
                if value and value not in output:
                    output.append(value)
            if output:
                yield output, f".details-mge .aContent [正文{tag}序号{index}，工作地点]", clean(text)


def channel_name(config):
    channel = config["channel_key"].removeprefix(config["school_key"] + "_")
    if channel not in {*CHANNELS, "homepage"}:
        raise ValueError("Unknown registered public column")
    return channel


def _column_cursor(url, channel, host="career.gdut.edu.cn", tenant="gdut"):
    parts = urlsplit(url)
    return (
        parts.scheme == "https" and parts.netloc == host
        and not parts.query and not parts.fragment
        and (parts.path in ("", "/") if channel == "homepage" else re.fullmatch(
            rf"/{channel}(?:/index(?:/do123/{re.escape(host)}/domain/{re.escape(tenant)}(?:/city/?)?(?:/page/\d+)?)?)?/?", parts.path))
    )


def discover(source_config, fetcher, cursor=None):
    return jysd_discover(source_config, fetcher, cursor, school_key="gdut", host="career.gdut.edu.cn")


def jysd_discover(source_config, fetcher, cursor=None, *, school_key, host):
    """Exact registered school/tenant wrapper; public slots never execute JS."""
    if source_config["school_key"] != school_key:
        raise FetchError("公开栏目学校归属不一致")
    channel = channel_name(source_config)
    url = cursor or source_config["official_entry_url"]
    if not _column_cursor(url, channel, host, school_key):
        raise FetchError("来源游标不属于已核验的无关键词公开栏目")
    response = fetcher.get(url)
    if response["url"] != url or not _column_cursor(response["url"], channel, host, school_key):
        raise FetchError("公开栏目最终响应改变游标身份，已停止解析", material_ref=response)
    document, warnings = decode_public_slots(response["text"])
    material = material_reference(response, source_config["source_key"], scope={
        "type": "source_list", "coverage": "complete_for_page", "page_url": response["url"],
    })
    records, seen = [], set()
    rows = document.select("a[href]") if channel == "homepage" else document.select(".infoList")
    for row in rows:
        link = row if channel == "homepage" else row.select_one(f"a[href*='/{channel}/view/id/']")
        if not link:
            continue
        match = re.search(r"/(teachin|jobfair|campus)/view/id/(\d+)", link["href"])
        official_url = safe_url(link["href"], response["url"])
        title = clean(link.get("title") or link.get_text(" ", strip=True))
        cells = row.find_all("li", recursive=False)
        if (not match or not official_url or urlsplit(official_url).netloc != host
                or not title or (match[1], match[2]) in seen or (channel != "homepage" and len(cells) < 2)):
            continue
        seen.add((match[1], match[2]))
        actual_channel = match[1]
        kind, date_basis = CHANNELS[actual_channel]
        marker = row.select_one(".status-text")
        original_kind = clean(marker.get_text()) if marker else {"teachin": "宣讲会", "jobfair": "招聘会", "campus": "招聘简章"}[actual_channel]
        if date_basis == "event" and original_kind in ("线上", "网络"):
            kind = "online_recruitment"
        record = candidate_base(source_config, match[2], title, official_url, kind, original_kind, date_basis)
        locator = f".infoList:has(a[href*='/{actual_channel}/view/id/{match[2]}'])"
        if channel == "homepage":
            records.append(record)
            continue  # Homepage position is not a reliable event date or venue.
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
                key = campus_key(school_key, venue)
                if key:
                    record["campus_key"] = key
        else:
            published = clean(cells[-1].get_text())
            if value := parse_date(published):
                set_known(record, "published_date", value, material, locator, published)
        records.append(record)
    next_cursor, pagination_warnings = next_page(document, response["url"])
    warnings.extend(pagination_warnings)
    if next_cursor and not _column_cursor(next_cursor, channel, host, school_key):
        next_cursor = None
        warnings.append("下一页不属于已核验公开栏目，已停止续跑")
    return page_result(source_config, response, records, next_cursor, warnings,
                       scope_note=f"{school_key}公开{channel}栏目；有限发现，不宣称整校或全部类型覆盖")


def enrich(candidate, fetcher):
    return jysd_enrich(candidate, fetcher, school_key="gdut", host="career.gdut.edu.cn")


def jysd_enrich(candidate, fetcher, *, school_key, host):
    match = re.fullmatch(rf"https://{re.escape(host)}/(teachin|jobfair|campus)/view/id/(\d+)", candidate["source_url"])
    if candidate["school_key"] != school_key or not match or match[2] != candidate["source_identity"]:
        raise FetchError("详情链接不属于本公告的已核验公开路径")
    response = fetcher.get(candidate["source_url"])
    document, warnings = decode_public_slots(response["text"])
    wrapper = document.select_one(".zp-details")
    material = material_reference(response, candidate["source_key"], candidate["source_identity"])
    final_identity = re.fullmatch(rf"https://{re.escape(host)}/(teachin|jobfair|campus)/view/id/(\d+)", response["url"])
    if not final_identity or final_identity.groups() != match.groups():
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material], "warnings": ["详情最终响应属于其他公告，未补充本条字段"]}
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
            key = campus_key(school_key, venue)
            if key:
                patch["campus_key"] = key
        if re.search(r"关于取消.*(?:宣讲|招聘会)|(?:宣讲会|招聘会).{0,12}(?:已取消|取消通知)", candidate["title"]):
            patch["event_status"] = "cancelled"
    locations, location_evidence = [], []
    previous_locations = candidate.get("field_observations", {}).get("work_locations", {})
    evidence_budget = max(0, 16 - len(previous_locations.get("evidence", []))) if previous_locations.get("state") == "known" else 16

    def add_locations(values, locator, excerpt):
        if len(location_evidence) >= evidence_budget or len(locations) >= 30:
            warnings.append("本公告工作地汇总达到定位证据限额；保留已取得范围，未宣称完整岗位覆盖")
            return
        for value in values:
            if value and len(value) <= 300 and value not in locations and len(locations) < 30:
                locations.append(value)
        location_evidence.append(evidence(material, locator, excerpt))
    rejected_rows = []
    for info in wrapper.select("table .info-text"):
        job_link = info.select_one("a[href*='/job/view/id/']")
        if not job_link:
            continue
        job_identity = re.search(r"/job/view/id/(\d+)(?:/|$)", job_link["href"])
        if not job_identity:
            continue
        from_id = re.search(r"/from_id/(\d+)(?:/|$)", job_link["href"])
        if from_id and from_id[1] != candidate["source_identity"]:
            rejected_rows.append(info.find_parent("tr"))
            warnings.append("岗位行链接指向其他公告身份，未用于本条字段或片段")
            continue
        cells = info.select("ul > li")
        if len(cells) >= 2:
            location = clean(cells[1].get_text())
            if location and len(location) <= 120:
                job_id = job_identity[1]
                add_locations([location], f"table .info-text:has(a[href*='/job/view/id/{job_id}']) ul > li:nth-child(2)", location)
    for values, locator, excerpt in _body_location_groups(body):
        add_locations(values, locator, excerpt)
    if locations:
        previous = previous_locations
        if previous.get("state") == "known" and candidate.get("work_locations") != locations:
            patch["field_observations"]["work_locations"] = observation(
                "conflict", None, [*previous.get("evidence", []), *location_evidence],
            )
        else:
            patch["work_locations"] = locations
            patch["field_observations"]["work_locations"] = observation("known", locations, location_evidence)
            patch["work_locations_scope"] = "partial_disclosed"
    elif "岗位遍布江西全省各设区市" in clean(body_text):
        set_observation(patch, candidate, "work_locations", ["江西省各设区市"], material,
                        ".details-mge .aContent", "岗位遍布江西全省各设区市")
    cutoff, cutoff_text = deadline(body_text, ordinary=not event_semantics)
    if cutoff:
        set_observation(patch, candidate, "deadline", cutoff, material, ".details-mge .aContent", cutoff_text)
    related = related_evidence(body_text)
    related_locator = ".details-mge .aContent"
    if not related:
        for row in wrapper.select("table tbody tr"):
            if row in rejected_rows or not row.select_one("a[href*='/job/view/id/']"):
                continue
            # The containing table explicitly labels its third column as job
            # major requirements. A bare employer background never supplies it.
            table = row.find_parent("table")
            cells = row.find_all("td", recursive=False)
            if (table and "需求专业" in table.get_text(" ", strip=True) and len(cells) >= 3
                    and re.search(r"电气|电力|电网|继电保护|(?<!机械设计制造及其)自动化", cells[2].get_text())):
                related = "需求专业：" + clean(cells[2].get_text(" ", strip=True))
                related_locator = "table:has(th) tbody tr td:nth-child(3) [需求专业]"
                break
            related = related_evidence(row.get_text(" ", strip=True))
            if related:
                related_locator = "table tbody tr [本公告岗位行]"
                break
    if related:
        patch["relevance"] = "related"
        patch["field_observations"]["relevance"] = observation(
            "known", "related", [evidence(material, related_locator, related)],
        )
    for row in rejected_rows:
        if row:
            row.decompose()
    patch["job_fragments"] = job_fragments(wrapper, material, ".zp-details")
    patch["attachments"] = attachments(body, response["url"], material)
    if body_text:
        fill_missing(patch, candidate, material, body, ".details-mge .aContent", event_semantics=event_semantics)
    return {"patch": patch, "material_refs": [material], "warnings": warnings}


class GdutAdapter:
    discover = staticmethod(discover)
    enrich = staticmethod(enrich)
