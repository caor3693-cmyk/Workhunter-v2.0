"""Bounded reads of registered public sources, with exact-byte material archives."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit

import httpx

DEFAULT_HOSTS = frozenset({"cnsba.scut.edu.cn", "career.gdut.edu.cn", "jyzx.scut.edu.cn"})
RESTRICTED_CODES = frozenset({401, 403, 412, 429, 483})
AUTH_PATH = re.compile(r"/(?:cas(?:/|$)|authserver(?:/|$)|user/login|default/ulogin|frontend_static/frontend/login)", re.I)


class FetchError(RuntimeError):
    """An attempt failed; any obtained response remains available as material."""

    def __init__(self, message, *, status="failed", status_code=None, restricted=False, material_ref=None):
        super().__init__(message)
        self.status = "restricted" if restricted else status
        self.status_code = status_code
        self.restricted = restricted
        self.material_ref = material_ref


class Fetcher:
    def __init__(self, material_root=".runtime/materials", *, allowed_hosts=DEFAULT_HOSTS,
                 max_requests=30, max_seconds=90, timeout_seconds=15, max_bytes=8_000_000,
                 max_retries=1, client=None, monotonic=time.monotonic):
        self.material_root = Path(material_root)
        self.allowed_hosts = frozenset(allowed_hosts)
        self.max_requests = int(max_requests)
        self.max_seconds = float(max_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self.max_bytes = int(max_bytes)
        self.max_retries = int(max_retries)
        if min(self.max_requests, self.max_bytes) < 1 or self.max_seconds <= 0 or self.timeout_seconds <= 0 or not 0 <= self.max_retries <= 2:
            raise ValueError("Invalid source request budget")
        self.requests = 0
        self.monotonic = monotonic
        self.started = monotonic()
        self.client = client or httpx.Client(follow_redirects=False, timeout=self.timeout_seconds)
        self._owns_client = client is None

    def close(self):
        if self._owns_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _validate(self, url):
        try:
            parts = urlsplit(url)
            port = parts.port
        except (ValueError, TypeError) as exc:
            raise FetchError("来源链接格式无效") from exc
        if AUTH_PATH.search(parts.path) or (parts.hostname and parts.hostname.startswith(("sso.", "authserver."))):
            raise FetchError("来源要求统一认证，已停止该路径", restricted=True)
        if (parts.scheme != "https" or parts.hostname not in self.allowed_hosts
                or parts.username or parts.password or port not in (None, 443)):
            raise FetchError("链接不属于已核验的公开 HTTPS 来源")
        if parts.hostname == "career.gdut.edu.cn" and (
                parts.path.startswith("/search") or re.search(r"(?:^|&)(?:keyword|title)=", parts.query)):
            raise FetchError("广工关键词搜索路径不在本轮公开采集范围", restricted=True)

    def _budget(self):
        elapsed = self.monotonic() - self.started
        if self.requests >= self.max_requests or elapsed >= self.max_seconds:
            raise FetchError("来源请求预算已耗尽", status="budget_exhausted")
        self.requests += 1
        return min(self.timeout_seconds, self.max_seconds - elapsed)

    def _archive(self, url, body, content_type, status_code):
        digest = hashlib.sha256(body).hexdigest()
        self.material_root.mkdir(parents=True, exist_ok=True)
        target = self.material_root / digest
        if not target.exists():
            # Exclusive creation makes concurrent identical material writes harmless.
            try:
                with target.open("xb") as stream:
                    stream.write(body)
            except FileExistsError:
                pass
        elif target.read_bytes() != body:
            raise FetchError("材料归档校验失败")
        match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type or "", re.I)
        encoding = match.group(1) if match else "utf-8"
        try:
            text = body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            text = body.decode("utf-8", errors="replace")
        return {
            "url": url, "body": body, "text": text, "reference_key": hashlib.sha256((url + "\n" + digest).encode("utf-8")).hexdigest(),
            "material_hash": digest, "fetched_at": datetime.now(timezone.utc).isoformat(),
            "raw_reference": target.as_posix(), "content_type": content_type,
            "status_code": status_code,
        }

    @staticmethod
    def _restricted_body(text):
        # Public pages may show "登录后查看联系方式"; that alone is not a restriction.
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        return bool(
            "统一认证中心跳转中" in text
            or (title and re.search(r"统一认证|用户登录|访问验证|验证码|captcha|access denied", title.group(1), re.I))
            or (re.search(r"<input[^>]+type=[\"']password", text, re.I)
                and re.search(r"登录|login|认证", text, re.I))
        )

    def get(self, url):
        self._validate(url)
        current = url
        redirects = 0
        retries = 0
        while True:
            self._validate(current)
            timeout = self._budget()
            try:
                with self.client.stream("GET", current, follow_redirects=False, timeout=timeout) as response:
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        if self.monotonic() - self.started >= self.max_seconds:
                            raise FetchError("来源时限预算已耗尽", status="budget_exhausted")
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise FetchError("来源响应超过大小限制", status="response_too_large")
                        chunks.append(chunk)
                    material = self._archive(str(response.url), b"".join(chunks),
                                             response.headers.get("content-type", ""), response.status_code)
                    status = response.status_code
                    location = response.headers.get("location")
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if retries < self.max_retries:
                    retries += 1
                    continue
                raise FetchError("来源请求超时或连接失败", status="network_failed") from exc
            if status in RESTRICTED_CODES or self._restricted_body(material["text"]):
                raise FetchError("来源有访问限制，已停止该路径", status_code=status,
                                 restricted=True, material_ref=material)
            if 300 <= status < 400:
                if not location:
                    raise FetchError("来源重定向缺少目标", status_code=status, material_ref=material)
                target = urljoin(current, location)
                try:
                    self._validate(target)
                except FetchError as exc:
                    raise FetchError(str(exc), status_code=status, restricted=exc.restricted,
                                     material_ref=material) from exc
                redirects += 1
                if redirects > 3:
                    raise FetchError("来源重定向过多", status_code=status, material_ref=material)
                current = target
                continue
            if status >= 500 and retries < self.max_retries:
                retries += 1
                continue
            if status != 200:
                raise FetchError("来源未返回可用公开页面", status_code=status, material_ref=material)
            return material
