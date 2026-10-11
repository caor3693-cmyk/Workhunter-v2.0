"""Finite HTML helpers. These functions know no database or API objects."""

import base64
import binascii
from datetime import date
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
import zlib

from bs4 import BeautifulSoup

from .transport import DEFAULT_HOSTS

PARSER_VERSION = "school-html-1"
CORE_FIELDS = ("published_date", "event_date", "start_time", "end_time", "deadline", "event_venue", "work_locations")
COMPRESSED = re.compile(
    r'\$\("#(?P<slot>content\d+)"\)\.each\(function\(\)\s*\{\s*\$\(this\)\.'
    r'(?P<mode>replaceWith|parent\(\)\.html)\('
    r'Base64\.decode\(unzip\("(?P<payload>[A-Za-z0-9+/=]+)"\)\.substr\((?P<inner>\d+)\)\)'
    r'\.substr\((?P<outer>\d+)\)\);', re.S
)


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalized(text):
    return clean(text).replace("：", ":").replace("－", "-").replace("—", "-").replace("–", "-")


def soup(text):
    return BeautifulSoup(text, "html.parser")


def safe_url(value, base=None):
    if not isinstance(value, str):
        return None
    value = urljoin(base or "", value.strip())
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme != "https" or parts.hostname not in DEFAULT_HOSTS
            or parts.username or parts.password or port not in (None, 443)):
        return None
    if re.search(r"/(?:user/login|default/ulogin|frontend_static/frontend/login|cas/|search)", parts.path, re.I):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def material_reference(response, source_key, official_record_id=None, *, scope=None, parsing_status="success"):
    return {
        "reference_key": response["reference_key"], "source_key": source_key,
        "source_url": response["url"], "official_record_id": official_record_id,
        "material_hash": response["material_hash"], "fetched_at": response["fetched_at"],
        "raw_reference": response["raw_reference"], "acquisition_status": "success",
        "parsing_status": parsing_status, "parser_version": PARSER_VERSION,
        "scope": scope or {"type": "this_announcement", "coverage": "partial"},
    }


def evidence(material, locator, excerpt, *, scope="this_announcement"):
    return {
        "material_ref": material["reference_key"], "source_url": material["source_url"],
        "locator": locator, "excerpt": clean(excerpt)[:500], "scope": scope,
        "observed_at": material["fetched_at"], "parser_version": PARSER_VERSION,
    }


def observation(state="not_collected", value=None, evidence_items=None):
    return {"state": state, "value": value if state == "known" else None, "evidence": evidence_items or []}


def candidate_base(config, official_id, title, source_url, kind, original_kind, date_basis):
    result = {
        "school_key": config["school_key"], "source_key": config["source_key"],
        "source_identity": str(official_id), "title": clean(title), "kind": kind,
        "original_kind": original_kind, "date_basis": date_basis, "source_url": source_url,
        "published_date": None, "event_date": None, "start_time": None, "end_time": None,
        "deadline": None, "event_venue": None, "work_locations": [],
        "work_locations_scope": "this_announcement", "relevance": "unknown",
        "event_status": "unknown" if date_basis == "event" else "not_applicable",
        "recruitment_status": "unknown", "field_observations": {},
        "roster_fragments": [], "job_fragments": [], "attachments": [],
    }
    for name in CORE_FIELDS:
        result["field_observations"][name] = observation(value=[] if name == "work_locations" else None)
    return result


def set_known(candidate, name, value, material, locator, excerpt):
    candidate[name] = value
    candidate["field_observations"][name] = observation("known", value, [evidence(material, locator, excerpt)])


def set_observation(patch, candidate, name, value, material, locator, excerpt, *, state="known"):
    item = evidence(material, locator, excerpt)
    previous = candidate.get("field_observations", {}).get(name, {})
    if (state == "known" and previous.get("state") == "known"
            and candidate.get(name) != value):
        patch.setdefault("field_observations", {})[name] = observation(
            "conflict", None, [*previous.get("evidence", []), item],
        )
        return
    # Missing or failed detail cannot erase a reliable observation from the list.
    if state != "known" and previous.get("state") in ("known", "conflict"):
        return
    patch[name] = value
    patch.setdefault("field_observations", {})[name] = observation(state, value, [item])


def parse_date(text):
    text = normalized(text)
    match = re.search(r"(?<!\d)(20\d{2})\s*(?:-|年)\s*(\d{1,2})\s*(?:-|月)\s*(\d{1,2})(?:日)?(?!\d)", text)
    if not match:
        return None
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError:
        return None


def parse_times(text):
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})\s*[-~至]\s*(\d{1,2}):(\d{2})(?!\d)", normalized(text))
    if not match:
        return None, None
    h1, m1, h2, m2 = map(int, match.groups())
    if max(h1, h2) > 23 or max(m1, m2) > 59:
        return None, None
    return f"{h1:02}:{m1:02}", f"{h2:02}:{m2:02}"


def labeled(text, labels):
    expression = r"(?:" + "|".join(re.escape(label) for label in labels) + r")\s*[:：]\s*"
    match = re.search(expression, text)
    if not match:
        return None
    tail = text[match.end():]
    return clean(re.split(r"\n|(?:宣讲地点|举办地点|工作地点|宣讲时间|举办时间|投递截止|报名截止)\s*[:：]", tail, maxsplit=1)[0])[:500]


def campus_key(school_key, venue):
    aliases = {
        "scut": {"五山校区": "wushan", "大学城校区": "university_city"},
        "gdut": {"大学城校区": "university_city", "龙洞校区": "longdong", "东风路校区": "dongfenglu"},
    }
    hits = {key for phrase, key in aliases.get(school_key, {}).items() if phrase in (venue or "")}
    return next(iter(hits)) if len(hits) == 1 else None


def decode_public_slots(text, *, max_decoded_bytes=8_000_000):
    """Decode only the exact public compression expression, never evaluate JS."""
    document = soup(text)
    warnings = []
    slots = 0
    for match in COMPRESSED.finditer(text):
        target = document.find(id=match["slot"])
        if target is None:
            warnings.append("公开正文槽不存在，保留已取得的基础字段")
            continue
        try:
            compressed = base64.b64decode(match["payload"], validate=True)
            decompressor = zlib.decompressobj()
            inflated = decompressor.decompress(compressed, max_decoded_bytes + 1)
            if len(inflated) > max_decoded_bytes or not decompressor.eof or decompressor.unused_data:
                raise ValueError("Compressed material exceeded its finite bound")
            first = inflated.decode("utf-8")[int(match["inner"]):]
            decoded = base64.b64decode(first, validate=True)
            if len(decoded) > max_decoded_bytes:
                raise ValueError("Decoded material exceeded its finite bound")
            content = decoded.decode("utf-8")[int(match["outer"]):]
            fragment = soup(content)
            # Evidence uses CSS/text locators into the raw response's public slot.
            if match["mode"] == "parent().html":
                parent = target.parent
                parent.clear()
                parent.append(fragment)
            else:
                target.replace_with(fragment)
            slots += 1
        except (ValueError, UnicodeDecodeError, binascii.Error, zlib.error):
            warnings.append("公开压缩正文解析失败，保留已取得的基础字段")
    if "Base64.decode(unzip(" in text and not slots:
        warnings.append("公开正文尚未可靠取得")
    return document, warnings


def next_page(document, page_url):
    for link in document.select("a[href]"):
        if "下一页" not in clean(link.get_text()):
            continue
        classes = set(link.get("class", [])) | set(link.parent.get("class", []))
        if classes & {"disabled", "disable"}:
            return None, []
        target = safe_url(link["href"], page_url)
        if not target:
            return None, []
        if target == safe_url(page_url):
            return None, ["分页下一页指向本页，停止续跑；不能据此宣称完整覆盖"]
        return target, []
    return None, []


def page_result(config, response, records, cursor, warnings, *, scope_note):
    return {
        "source_key": config["source_key"], "channel_key": config["channel_key"],
        "records": records, "next_cursor": cursor,
        "scope": {**(config.get("scope") if isinstance(config.get("scope"), dict) else {}),
                  "page_url": response["url"], "record_count": len(records), "note": scope_note},
        "completeness": "partial", "material_refs": [
            material_reference(response, config["source_key"], scope={
                "type": "source_list", "coverage": "complete_for_page" if records else "unknown",
                "page_url": response["url"], "note": scope_note,
            }, parsing_status="success" if records else "failed"),
        ],
        "warnings": warnings if records else [*warnings, "本页尚未取得可解析招聘记录，不能据此认定零招聘"],
    }


def unread_materials(content):
    return bool(content.select("img") or any(
        re.search(r"(?:/_upload/|/attachment/|\.(?:pdf|docx?|xlsx?|pptx?|zip)(?:$|\?))", a.get("href", ""), re.I)
        for a in content.select("a[href]")
    ))


def attachments(content, source_url, material):
    output = []
    for link in content.select("a[href]"):
        url = safe_url(link["href"], source_url)
        if url and re.search(r"(?:/_upload/|/attachment/|\.(?:pdf|docx?|xlsx?|pptx?|zip)(?:$|\?))", url, re.I):
            output.append({
                "label": clean(link.get_text()) or "官方附件", "url": url,
                "scope": "this_announcement",
                "evidence": [evidence(material, "announcement_body a[href]", link.get_text() or url)],
            })
    return output[:8]


def job_fragments(content, material, locator):
    output = []
    for row in content.select("table tbody tr"):
        if not row.select_one("a[href*='/job/view/id/']"):
            continue
        text = clean(row.get_text(" ", strip=True))
        if text:
            output.append({"text": text[:2000], "scope": "partial",
                           "evidence": [evidence(material, locator + " table tbody tr", text)]})
    if not output:
        for paragraph in content.find_all(["p", "li"]):
            text = clean(paragraph.get_text(" ", strip=True))
            if re.search(r"招聘岗位|任职要求|招聘对象|需求专业|(?:电气|电力|自动化).{0,12}(?:岗|工程师|专业)", text):
                # Do not promote contact details to public opportunity fragments.
                text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+|(?<!\d)1[3-9]\d{9}(?!\d)", "[联系方式见原文]", text)
                output.append({"text": text[:2000], "scope": "partial",
                               "evidence": [evidence(material, locator + " p/li", text)]})
                if len(output) == 8:
                    break
    return output[:8]


def related_evidence(text):
    match = re.search(r"电气|电力|电网|输变电|继电保护|\bPLC\b|(?<!机械设计制造及其)自动化", text, re.I)
    if not match:
        return None
    return text[max(0, match.start() - 50):match.end() + 100]


def explicit_locations(text):
    value = labeled(text, ["工作地点", "工作城市", "招聘地点", "招聘城市"])
    if not value:
        match = re.search(r"【(?:四大|招聘|工作)城市】([^【\n]+)", text)
        value = clean(match.group(1)) if match else None
    if not value:
        return []
    # Preserve official precision instead of inferring cities from company names.
    return list(dict.fromkeys(clean(part) for part in re.split(r"[、；;]|[,，](?=[^，]*[市省])", value) if clean(part)))[:30]


def deadline(text, *, ordinary=False):
    normalized_text = normalized(text)
    match = re.search(r"(?:简历投递|投递简历|网申|申请)([^。\n]{0,60}?截止[^。\n]{0,30})", normalized_text)
    if not match and ordinary:
        match = re.search(r"报名截止(?:时间)?\s*:\s*([^。\n]{0,40})", normalized_text)
    return (parse_date(match.group(0)), match.group(0)) if match else (None, None)


def fill_missing(patch, candidate, material, content, locator, *, event_semantics):
    complete = not unread_materials(content)
    text = clean(content.get_text(" ", strip=True))
    for name in CORE_FIELDS:
        if name in patch.get("field_observations", {}) or candidate.get("field_observations", {}).get(name, {}).get("state") in ("known", "conflict"):
            continue
        if not event_semantics and name in ("event_date", "start_time", "end_time", "event_venue"):
            state = "not_applicable"
        else:
            state = "not_disclosed" if complete else "not_collected"
        set_observation(patch, candidate, name, [] if name == "work_locations" else None,
                        material, locator, text[:300] or candidate["title"], state=state)
