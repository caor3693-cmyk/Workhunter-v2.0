"""Exact public Cloud Career school pages; no login or inferred API endpoints."""
import re
from urllib.parse import parse_qs, urlsplit

from .common import (
    attachments, campus_key, candidate_base, clean, deadline, evidence,
    fill_missing, job_fragments, labeled, material_reference, workplace_blocks,
    observation, page_result, parse_date, parse_times, related_evidence,
    safe_url, set_observation, soup, unread_materials,
)
from .transport import FetchError


def _cloud_detail(url, host, channel):
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (parts.scheme != "https" or parts.netloc != host or parts.fragment
            or parts.path != f"/detail/{channel}" or set(query) != {"id"}
            or len(query["id"]) != 1 or not re.fullmatch(r"[1-9]\d{0,11}", query["id"][0])):
        return None
    return query["id"][0]


def cloud_discover(config, fetcher, cursor=None, *, school_key, host):
    if config["school_key"] != school_key:
        raise FetchError("云就业学校来源归属不一致")
    channel = config["channel_key"].removeprefix(school_key + "_")
    channel = {"careers": "career", "homepage": "career", "onlines": "online"}.get(channel, channel)
    if channel not in {"career", "online"}:
        raise FetchError("只接受已核验的公开宣讲或招聘简章栏目")
    url = cursor or config["official_entry_url"]
    parts = urlsplit(url)
    # Only literal links from the registered homepage are currently verified.
    # Skeleton modules and guessed Ajax paths cannot count as working sources.
    if (parts.scheme != "https" or parts.netloc != host or parts.query or parts.fragment
            or parts.path not in {"", "/", "/index"}):
        raise FetchError("云就业游标不属于已核验的公开首页")
    response = fetcher.get(url)
    final = urlsplit(response["url"])
    if final.scheme != "https" or final.netloc != host or final.path not in {"", "/", "/index"} or final.query or final.fragment:
        raise FetchError("公开首页跳转至未经核验栏目，已停止解析", material_ref=response)
    document = soup(response["text"])
    records, seen = [], set()
    for link in document.select(f"a[href*='/detail/{channel}?']"):
        target = safe_url(link["href"], response["url"])
        identity = _cloud_detail(target, host, channel) if target else None
        title = clean(link.get("title") or link.get_text(" ", strip=True))
        if not identity or not title or identity in seen:
            continue
        seen.add(identity)
        records.append(candidate_base(config, identity, title, target,
            "campus_talk" if channel == "career" else "announcement",
            "公开宣讲会" if channel == "career" else "公开招聘简章",
            "event" if channel == "career" else "publication"))
    return page_result(config, response, records, None, [],
        scope_note=f"{school_key}官方公开首页的{channel}显式链接；仅首页有限发现，不含登录、猜测接口或全校完整覆盖")


def cloud_enrich(candidate, fetcher, *, school_key, host):
    channel = "career" if candidate["date_basis"] == "event" else "online"
    identity = _cloud_detail(candidate["source_url"], host, channel)
    if candidate["school_key"] != school_key or identity != candidate["source_identity"]:
        raise FetchError("云就业详情不属于本校本条官方公告")
    response = fetcher.get(candidate["source_url"])
    document = soup(response["text"])
    wrapper = document.select_one(".main-inner")
    material = material_reference(response, candidate["source_key"], identity)
    if _cloud_detail(response["url"], host, channel) != identity:
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material], "warnings": ["详情最终响应属于其他公告，未补充本条字段"]}
    if wrapper is None or not wrapper.select_one(".detail-module .dm-cont"):
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material], "warnings": ["云就业详情主体未取得，保留已知基础公告"]}
    patch, warnings = {"field_observations": {}}, []
    title = wrapper.select_one("h1.dm-text") or wrapper.select_one("h1")
    if title:
        title_copy = soup(str(title))
        for control in title_copy.select("a, button"):
            control.decompose()
        value = re.sub(r"^(?:宣讲单位|招聘单位)\s*[:：]\s*", "", clean(title_copy.get_text(" ", strip=True)))
        if value:
            patch["title"] = value
    body = soup("<div></div>").div
    for module in wrapper.select(".detail-module"):
        heading = module.select_one(".dm-tit")
        content = module.select_one(".dm-cont")
        if content and heading and re.search(r"招聘简章|岗位介绍|职位列表|招聘岗位|招聘职位|职位详情", heading.get_text()):
            body.append(soup(str(content)))
    for link in body.select("a[href*='/detail/job?']"):
        query = parse_qs(urlsplit(link["href"]).query)
        if query.get("career_id") and query["career_id"] != [identity]:
            item = link.find_parent(class_="dm-text")
            if item:
                item.decompose()
    text = body.get_text("\n", strip=True)
    full_text = wrapper.get_text("\n", strip=True)
    event = candidate["date_basis"] == "event"
    if event:
        schedule = labeled(full_text, ["宣讲时间", "举办时间"])
        if schedule and (value := parse_date(schedule)):
            set_observation(patch, candidate, "event_date", value, material, ".main-inner .dm-text [宣讲时间]", schedule)
        start, end = parse_times(schedule or "")
        # An explicitly disclosed single start is valid; never invent its end.
        single = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", schedule or "")
        start = start or (f"{int(single[1]):02}:{single[2]}" if single else None)
        for name, value in (("start_time", start), ("end_time", end)):
            if value:
                set_observation(patch, candidate, name, value, material, ".main-inner .dm-text [宣讲时间]", schedule)
        venue = labeled(full_text, ["宣讲地点", "举办地点"])
        if venue:
            set_observation(patch, candidate, "event_venue", venue, material, ".main-inner .dm-text [宣讲地点]", venue)
            if key := campus_key(school_key, venue):
                patch["campus_key"] = key
    for item in wrapper.select(".dm-text, .dm-time"):
        value = clean(item.get_text())
        if re.match(r"^(?:发布时间|发布于)\s*[:：]", value) and (date_value := parse_date(value)):
            set_observation(patch, candidate, "published_date", date_value, material, ".main-inner [发布时间]", value)
            break
    if text:
        material["scope"]["coverage"] = "partial" if unread_materials(body) else "complete_for_material"
        location_groups = workplace_blocks(body)
        if location_groups:
            location_groups = location_groups[:16]
            values = list(dict.fromkeys(value for group, _, _ in location_groups for value in group))[:30]
            proof = [evidence(material, '.detail-module [招聘内容] .dm-cont ' + locator, excerpt)
                     for _, locator, excerpt in location_groups[:16]]
            patch['work_locations'] = values
            patch['work_locations_scope'] = 'partial_disclosed' if len(location_groups) > 1 or any('table序号' in locator for _, locator, _ in location_groups) else 'this_announcement'
            patch['field_observations']['work_locations'] = observation('known', values, proof)
            if candidate.get('field_observations', {}).get('work_locations', {}).get('state') == 'known' and candidate.get('work_locations') != values:
                retained = candidate['field_observations']['work_locations'].get('evidence', [])[:8]
                patch['field_observations']['work_locations'] = observation('conflict', None, [*retained, *proof[:16 - len(retained)]])
                patch.pop('work_locations', None)
        cutoff, cutoff_text = deadline(text, ordinary=not event)
        if cutoff:
            set_observation(patch, candidate, "deadline", cutoff, material, ".detail-module [招聘简章] .dm-cont", cutoff_text)
        if related := related_evidence(text):
            patch["relevance"] = "related"
            patch["field_observations"]["relevance"] = observation("known", "related", [
                evidence(material, ".detail-module [招聘简章] .dm-cont", related)])
        patch["job_fragments"] = job_fragments(body, material, ".detail-module [招聘简章] .dm-cont")
        patch["attachments"] = attachments(body, response["url"], material)
        fill_missing(patch, candidate, material, body, ".detail-module [招聘简章] .dm-cont", event_semantics=event)
    else:
        material["parsing_status"] = "partial"
        warnings.append("招聘正文未取得；仅补充同页明确活动安排，不宣称材料齐全")
    return {"patch": patch, "material_refs": [material], "warnings": warnings}


class HnuAdapter:
    @staticmethod
    def discover(config, fetcher, cursor=None):
        return cloud_discover(config, fetcher, cursor, school_key="hnu", host="scc.hnu.edu.cn")

    @staticmethod
    def enrich(candidate, fetcher):
        return cloud_enrich(candidate, fetcher, school_key="hnu", host="scc.hnu.edu.cn")
