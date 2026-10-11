"""Bounded reads of registered public sources, with exact-byte material archives."""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx
import httpcore

from backend.domain.source_policy import approved_hosts, validate_url, validate_public_addresses

DEFAULT_HOSTS = approved_hosts()
RESTRICTED_CODES = frozenset({401, 403, 412, 429, 483})
AUTH_PATH = re.compile(r"/(?:cas(?:/|$)|authserver(?:/|$)|user/login|default/ulogin|frontend_static/frontend/login)", re.I)


class PublicDNSResolver:
    """Resolve registered names, rejecting the entire answer on a private IP.

    The explicit DoH mode supports local fake-IP networks. It never authorizes a
    fake/private address, and the source transport connects to the checked IPs.
    """

    def __init__(self, hosts, *, mode='system', client=None, monotonic=time.monotonic):
        if mode not in {'system', 'cloudflare-doh'}:
            raise ValueError('来源 DNS 模式只接受 system 或 cloudflare-doh。')
        self.hosts = frozenset(hosts)
        self.mode = mode
        self.cache = {}
        self.monotonic = monotonic
        self.client = client
        self.owns_client = False
        if mode == 'cloudflare-doh' and client is None:
            self.client = httpx.Client(verify=True, trust_env=False, follow_redirects=False, timeout=8)
            self.owns_client = True

    def close(self):
        if self.owns_client:
            self.client.close()

    def __call__(self, hostname):
        hostname = hostname.decode('ascii') if isinstance(hostname, bytes) else hostname
        if hostname not in self.hosts:
            raise ValueError('DNS 查询只能用于已批准来源域名。')
        cached = self.cache.get(hostname)
        if cached and cached[0] > self.monotonic():
            return cached[1]
        ttl = 30
        if self.mode == 'system':
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
        else:
            try:
                dns_deadline = self.monotonic() + 8
                # Fixed provider; no caller-controlled endpoint, redirects or TLS override.
                with self.client.stream('GET', 'https://cloudflare-dns.com/dns-query',
                        params={'name': hostname, 'type': 'A'}, headers={'Accept': 'application/dns-json'}) as response:
                    if response.status_code != 200 or response.headers.get('content-type', '').split(';', 1)[0] not in {'application/dns-json', 'application/json'}:
                        raise ValueError('可信公开 DNS 响应不可用。')
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if self.monotonic() >= dns_deadline:
                            raise ValueError('可信公开 DNS 响应总时限已耗尽。')
                        body.extend(chunk)
                        if len(body) > 32768:
                            raise ValueError('可信公开 DNS 响应超过上限。')
                import json
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError('可信公开 DNS 回答格式无效。')
                questions = data.get('Question', [])
                if data.get('Status') != 0 or data.get('TC') or not isinstance(questions, list) or len(questions) != 1 or not isinstance(questions[0], dict) or questions[0].get('name', '').rstrip('.').lower() != hostname or questions[0].get('type') != 1:
                    raise ValueError('可信公开 DNS 回答与请求不一致。')
                records = data.get('Answer', [])
                if not isinstance(records, list) or len(records) > 32 or not all(isinstance(a, dict) for a in records):
                    raise ValueError('可信公开 DNS 回答格式或数量无效。')
                aliases = {hostname}
                alias_ttls = []
                for _ in range(8):
                    links = [a for a in records if a.get('type') == 5 and a.get('name', '').rstrip('.').lower() in aliases]
                    if any(type(a.get('TTL')) is not int or not 0 <= a['TTL'] <= 2147483647 for a in links):
                        raise ValueError('可信公开 DNS 别名 TTL 无效。')
                    alias_ttls.extend(a['TTL'] for a in links)
                    found = {a['data'].rstrip('.').lower() for a in links}
                    if found <= aliases:
                        break
                    aliases.update(found)
                answers = [a for a in records if a.get('type') == 1]
                if not 1 <= len(answers) <= 16:
                    raise ValueError('可信公开 DNS 未取得有界地址回答。')
                if any(a.get('name', '').rstrip('.').lower() not in aliases or type(a.get('TTL')) is not int or not 0 <= a['TTL'] <= 2147483647 for a in answers):
                    raise ValueError('可信公开 DNS 地址未绑定请求域名或有效 TTL。')
                addresses = {a['data'] for a in answers}
                ttl = min([60, *(a['TTL'] for a in answers), *alias_ttls])
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
                raise ValueError('可信公开 DNS 校验失败，不回退到私网或代理地址。') from exc
        checked = tuple(sorted(validate_public_addresses(addresses)))
        self.cache[hostname] = (self.monotonic() + ttl, checked)
        return checked


class PinnedPublicBackend(httpcore.SyncBackend):
    """TCP uses checked IPs; HTTP origin and TLS server_hostname remain unchanged."""

    def __init__(self, resolver):
        self.resolver = resolver

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port != 443:
            raise httpcore.ConnectError('公开来源仅允许 HTTPS 端口。')
        try:
            addresses = validate_public_addresses(self.resolver(host))
        except (ValueError, OSError) as exc:
            raise httpcore.ConnectError('来源公开地址校验失败。') from exc
        started = time.monotonic()
        last = None
        for address in addresses:
            remaining = None if timeout is None else timeout - (time.monotonic() - started)
            if remaining is not None and remaining <= 0:
                raise httpcore.ConnectTimeout('来源连接预算已耗尽。')
            try:
                return super().connect_tcp(address, port, remaining, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        raise last or httpcore.ConnectError('公开来源没有可用地址。')


class PinnedPublicTransport(httpx.HTTPTransport):
    """The locked HTTPX transport with HTTPcore's supported network backend."""

    def __init__(self, resolver):
        super().__init__(verify=True, trust_env=False, retries=0)
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            network_backend=PinnedPublicBackend(resolver), retries=0,
        )


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
                 max_retries=1, client=None, monotonic=time.monotonic, school_key=None, resolver=None):
        self.material_root = Path(material_root)
        self.allowed_hosts = frozenset(allowed_hosts)
        self.school_key = school_key
        self._owned_resolver = None
        if client is None and resolver is None:
            self._owned_resolver = PublicDNSResolver(self.allowed_hosts, mode=os.environ.get('WH_SOURCE_DNS_MODE', 'system'))
            resolver = self._owned_resolver
        self.resolver = resolver
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
        self.client = client or httpx.Client(transport=PinnedPublicTransport(self.resolver),
            verify=True, trust_env=False, follow_redirects=False, timeout=self.timeout_seconds)
        self._owns_client = client is None

    def close(self):
        if self._owns_client:
            self.client.close()
        if self._owned_resolver:
            self._owned_resolver.close()

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

        try:
            validate_url(url,self.school_key,fetch=True)
            if self.resolver is not None:
                validate_public_addresses(self.resolver(parts.hostname))
        except (ValueError,OSError) as exc:
            raise FetchError('来源策略或公开地址校验失败') from exc

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
            content_type = material['content_type'].split(';',1)[0].strip().lower()
            if content_type and content_type not in {'text/html','application/xhtml+xml','text/plain','application/json'}:
                raise FetchError('响应类型不是批准的公开正文',status='invalid_content_type',material_ref=material)
            return material
