"""Public SCUT college announcements; the authenticated main portal stays restricted."""

from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

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
    if response["url"] != url:
        raise FetchError("学院栏目最终响应不属于本页游标，已停止解析", material_ref=response)
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
    if response["url"] != candidate["source_url"]:
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material], "warnings": ["学院详情跳转至其他材料，未补充本条字段"]}
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


# Public school-source identifier returned by NCSS's source-name directory.
# It is a public catalogue identity, not a credential or authentication token.
NCSS_SCHOOL_ID = "nlienp69uztxk4q8ikyu61issohbja7h"
NCSS_OWNER_URL = "https://www.ncss.cn/student/m/api/jobs/findJobOutsiteNames?type=1"
NCSS_LIST_URL = "https://www.ncss.cn/student/jobs/jobslist/ajax/"
NCSS_JOB = re.compile(r"https://www\.ncss\.cn/student/jobs/([A-Za-z0-9]{8,80})/detail\.html")


def ncss_list_url(offset=1):
    return NCSS_LIST_URL + "?" + urlencode({"sourcesName": NCSS_SCHOOL_ID,
        "sourcesType": "1", "jobName": "电气", "offset": str(offset), "limit": "10"})


def _ncss_cursor(url):
    parts = urlsplit(url)
    values = parse_qs(parts.query, keep_blank_values=True)
    expected = parse_qs(urlsplit(ncss_list_url()).query)
    if (parts.scheme != "https" or parts.netloc != "www.ncss.cn"
            or parts.path != "/student/jobs/jobslist/ajax/" or parts.fragment
            or set(values) != set(expected)
            or any(values[key] != expected[key] for key in expected if key != "offset")
            or len(values["offset"]) != 1 or not re.fullmatch(r"[1-9]\d{0,3}", values["offset"][0])):
        raise FetchError("华工平台游标必须保留已核验的学校来源与公开查询范围")
    return int(values["offset"][0])


def _ncss_json(response):
    try:
        value = json.loads(response["text"])
    except (TypeError, ValueError) as exc:
        raise FetchError("公开平台未返回可解析的数据材料", material_ref=response) from exc
    if (isinstance(value, dict) and value.get("flag") is False
            and isinstance(value.get("global"), list)
            and any(isinstance(item, dict) and item.get("des") == "请登录后查看"
                    for item in value["global"])):
        raise FetchError("公开平台明确要求登录，已停止该路径", restricted=True, material_ref=response)
    if not isinstance(value, dict) or value.get("flag") is not True:
        raise FetchError("公开平台未确认返回学校来源材料", material_ref=response)
    return value.get("data")


def _ncss_pagination(data, offset):
    pagination = data.get("pagenation")
    if not isinstance(pagination, dict):
        return None
    if any(type(pagination.get(key)) is not int for key in ("count", "total", "limit", "offset")):
        return None
    count, total, limit = (pagination[key] for key in ("count", "total", "limit"))
    if (limit != 10 or count < 0 or not 0 <= total <= 9999
            or total != (count + limit - 1) // limit or pagination["offset"] != offset):
        return None
    if total == 0:
        return pagination if offset == 1 and not data["list"] else None
    if not 1 <= offset <= total:
        return None
    expected_rows = min(limit, count - (offset - 1) * limit)
    if len(data["list"]) != expected_rows:
        return None
    return pagination


def ncss_discover(source_config, fetcher, cursor=None):
    if source_config["school_key"] != "scut":
        raise FetchError("平台学校来源归属不一致")
    url = cursor or source_config["official_entry_url"]
    offset = _ncss_cursor(url)
    owner_response = fetcher.get(NCSS_OWNER_URL)
    if owner_response["url"] != NCSS_OWNER_URL:
        raise FetchError("学校来源目录最终响应身份不一致", material_ref=owner_response)
    directory = _ncss_json(owner_response)
    owners = ([item for item in directory
               if isinstance(item, dict) and item.get("id") == NCSS_SCHOOL_ID]
              if isinstance(directory, list) else [])
    if len(owners) != 1 or owners[0].get("name") != "华南理工大学":
        raise FetchError("公开目录未确认华南理工大学来源身份", material_ref=owner_response)
    response = fetcher.get(url)
    if _ncss_cursor(response["url"]) != offset:
        raise FetchError("平台列表最终响应改变分页身份，已停止解析", material_ref=response)
    data = _ncss_json(response)
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        raise FetchError("平台学校来源列表结构未可靠取得", material_ref=response)
    material = material_reference(response, source_config["source_key"], scope={
        "type": "source_list", "coverage": "complete_for_page", "page_url": response["url"],
        "school_source_id": NCSS_SCHOOL_ID,
    })
    records, warnings, seen = [], [], set()
    rows = data["list"]
    if len(rows) > 10:
        warnings.append("公开列表超出登记分页大小，不能确认完整范围")
    for row in rows[:10]:
        if not isinstance(row, dict):
            warnings.append("列表包含无法核验的记录，不能确认完整范围")
            continue
        identity = str(row.get("jobId") or "")
        if (row.get("sourcesName") != NCSS_SCHOOL_ID or row.get("sourcesNameCh") != "华南理工大学"
                or str(row.get("sourcesType")) != "12"):
            warnings.append("列表混入未经学校来源归属校验的记录，未收录")
            continue
        title = clean(row.get("jobName"))
        if not re.fullmatch(r"[A-Za-z0-9]{8,80}", identity) or not title or identity in seen:
            warnings.append("列表记录身份、标题或唯一性未核实，不能确认完整范围")
            continue
        seen.add(identity)
        item = candidate_base(source_config, identity, title,
            f"https://www.ncss.cn/student/jobs/{identity}/detail.html", "announcement",
            "华南理工大学来源的官方平台招聘岗位", "publication")
        # Full timestamp belongs to this jobId's list item. A detail's month/day
        # update label is never used to invent the publication year.
        stamp = row.get("publishDate")
        if type(stamp) in (int, float) and 946684800000 <= stamp < 4102444800000:
            date_value = datetime.fromtimestamp(stamp / 1000, timezone(timedelta(hours=8))).date().isoformat()
            set_known(item, "published_date", date_value, material,
                f"JSON $.data.list[?(@.jobId=='{identity}')].publishDate", f"publishDate={stamp}")
        records.append(item)
    pagination = _ncss_pagination(data, offset)
    valid_rows = len(rows) <= 10 and len(records) == len(rows) and not warnings
    if pagination is not None:
        next_cursor = ncss_list_url(offset + 1) if offset < pagination["total"] else None
    else:
        # Missing metadata may still yield reliable records, but not a verified
        # terminal. Malformed supplied metadata cannot direct further requests.
        next_cursor = (ncss_list_url(offset + 1)
                       if "pagenation" not in data and len(rows) == 10 else None)
        warnings.append("公开分页元数据或实际条数与声明范围不符，已停止续页；不能确认完整范围"
                        if "pagenation" in data else "公开分页元数据未核实，不能确认完整范围")
    page = page_result(source_config, response, records, next_cursor,
        warnings, scope_note="国家大学生就业服务平台中明确归属华南理工大学的电气查询；有限分页，不代表就业中心自动源或全校覆盖")
    if pagination is not None and valid_rows:
        # Every page matches the advertised count before its records can be
        # trusted for completion. Completion is only this registered query.
        page["scope"].update({"school_wide": False, "query_keyword": "电气",
            "pagination": {key: pagination[key] for key in ("count", "total", "limit", "offset")}})
        if not rows:
            page["material_refs"][0]["parsing_status"] = "success"
            page["material_refs"][0]["scope"]["coverage"] = "verified_empty"
            page["warnings"] = []
        if next_cursor is None:
            page["completeness"] = "complete_for_channel"
    elif "pagenation" in data:
        # The orchestrator must not continue past a malformed page and later
        # report only its clean terminal as a complete check. Old facts remain.
        page["material_refs"][0]["parsing_status"] = "failed"
    page["material_refs"].append(material_reference(owner_response, source_config["source_key"], scope={
        "type": "source_owner", "coverage": "complete_for_material", "school_source_id": NCSS_SCHOOL_ID,
        "note": "公开来源目录确认学校来源ID；不是认证材料",
    }))
    return page


def ncss_enrich(candidate, fetcher):
    match = NCSS_JOB.fullmatch(candidate["source_url"])
    if candidate["school_key"] != "scut" or not match or match[1] != candidate["source_identity"]:
        raise FetchError("平台详情必须对应本条学校来源岗位身份")
    response = fetcher.get(candidate["source_url"])
    document = soup(response["text"])
    material = material_reference(response, candidate["source_key"], candidate["source_identity"])
    final_identity = NCSS_JOB.fullmatch(response["url"])
    if not final_identity or final_identity[1] != candidate["source_identity"]:
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material], "warnings": ["平台详情最终响应属于其他岗位，未补充本条字段"]}
    marker = document.select_one(".source-sp")
    source = document.select_one("#sourcesName")
    body = document.select_one(".mainContent-geshi")
    source_id = (source.get("value") if source and source.name == "input"
                 else clean(source.get_text()) if source else None)
    if (source is None or source_id != NCSS_SCHOOL_ID or marker is None
            or len(document.select("#sourcesName")) != 1 or len(document.select(".source-sp")) != 1
            or clean(marker.get_text()) != "华南理工大学"
            or str(marker.get("data-sourcestype")) != "12" or body is None):
        material["parsing_status"] = "failed"
        return {"patch": {}, "material_refs": [material],
            "warnings": ["详情缺少本条华工来源标记或正文，已停止补充；不收全国任意平台岗位"]}
    material["scope"]["coverage"] = "partial" if unread_materials(body) else "complete_for_material"
    text = body.get_text("\n", strip=True)
    patch = {"field_observations": {}}
    title = document.select_one(".job-title")
    if title and clean(title.get_text()):
        patch["title"] = clean(title.get_text())
    locations = explicit_locations(text)
    if locations:
        set_observation(patch, candidate, "work_locations", locations, material, ".mainContent-geshi", "、".join(locations))
    cutoff, cutoff_text = deadline(text, ordinary=True)
    if cutoff:
        set_observation(patch, candidate, "deadline", cutoff, material, ".mainContent-geshi", cutoff_text)
    related = related_evidence(text)
    related_locator = ".job-title / .mainContent-geshi"
    if not related:
        paragraphs = body.find_all(["p", "h2", "h3"])
        for index, paragraph in enumerate(paragraphs):
            heading = clean(paragraph.get_text(" ", strip=True))
            if not re.fullmatch(r"(?:[一二三四五六七八九十]+[、.．]\s*)?我们的招聘岗位\s*[:：]?", heading):
                continue
            for item in paragraphs[index + 1:index + 5]:
                value = clean(item.get_text(" ", strip=True))
                if re.match(r"[一二三四五六七八九十]+[、.．]", value):
                    break
                if "涵盖" in value and re.search(r"电气类|自动化类", value):
                    related = heading + "；" + value
                    related_locator = ".mainContent-geshi [我们的招聘岗位章节] p [专业涵盖段]"
                    break
            if related:
                break
    # The actual job title is an explicit role, rather than employer background.
    if not related and title and re.search(r"电气.{0,12}(?:工程师|岗|技术员)", clean(title.get_text())):
        related = clean(title.get_text())
    if related:
        patch["relevance"] = "related"
        patch["field_observations"]["relevance"] = observation("known", "related", [
            evidence(material, related_locator, related)])
    patch["attachments"] = attachments(body, response["url"], material)
    patch["job_fragments"] = job_fragments(body, material, ".mainContent-geshi")
    fill_missing(patch, candidate, material, body, ".mainContent-geshi", event_semantics=False)
    return {"patch": patch, "material_refs": [material], "warnings": []}


class ScutNcssAdapter:
    discover = staticmethod(ncss_discover)
    enrich = staticmethod(ncss_enrich)
