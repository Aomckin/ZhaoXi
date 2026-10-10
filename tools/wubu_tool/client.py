"""Local HTTP client; resume once after refused connection and on-demand startup."""
import json
import math
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class WubuError(Exception):
    def __init__(self, code, message, *, status=None, data=None, unknown=False, retryable=False):
        super().__init__(message)
        self.code, self.status, self.data = code, status, data
        self.unknown, self.retryable = unknown, retryable


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WubuClient:
    def __init__(self, base_url="http://127.0.0.1:8026", timeout=15, *, autostart=False,
                 project_dir=None, startup_timeout=8):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("物簿 base_url 必须是本机 HTTP 根地址。")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("物簿端口无效。")
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout_seconds 必须是有限正数。")
        self.starter = None
        if autostart:
            from tools.wubu_tool.autostart import WubuAutoStarter
            # The documented script starts the normal service on port 8026.
            if (parsed.port or 80) != 8026:
                raise ValueError("自动启动只支持物簿默认端口 8026；其他端口请关闭 autostart_enabled。")
            self.starter = WubuAutoStarter(self.base_url, project_dir, startup_timeout)

    def request(self, method, path, query=None, payload=None, key=None, *, read_only=False):
        # HTTP POST is also used for Wubu's documented pure-read prechecks.
        read_only = read_only or (method == "POST" and (
            path == "/api/v1/purchases/validate"
            or (path == "/api/v1/purchases" and (query or {}).get("dry_run") in (True, "true"))))
        options = {"read_only": True} if read_only else {}
        try:
            return self._request_once(method, path, query, payload, key, **options)
        except WubuError as exc:
            if self.starter is None or not getattr(exc, "refused", False):
                raise
        self.starter.ensure_ready()
        # Refusal proves the first request was unsent. Keep the identical key/DTO,
        # and never recursively trigger startup or retry after this second attempt.
        return self._request_once(method, path, query, payload, key, **options)

    def _request_once(self, method, path, query=None, payload=None, key=None, *, read_only=False):
        url = self.base_url + path
        if query:
            url += "?" + urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in query.items()})
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        request = Request(url, data=body, headers=headers, method=method)
        write = method != "GET" and not read_only
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=self.timeout) as response:
                raw = response.read()
                replayed = response.headers.get("Idempotency-Replayed", "").lower() == "true"
            return json.loads(raw), replayed
        except HTTPError as exc:
            try:
                data = json.loads(exc.read())
            except (ValueError, OSError, HTTPException):
                data = None
            finally:
                exc.close()
            error = data.get("error", {}) if isinstance(data, dict) else {}
            if not isinstance(error, dict):
                error = {}
            raise WubuError(error.get("code", f"http_{exc.code}"),
                            error.get("message", f"物簿返回 HTTP {exc.code}。"),
                            status=exc.code, data=data, unknown=write and (exc.code >= 500 or exc.code == 408),
                            retryable=(error["retryable"] if type(error.get("retryable")) is bool
                                       else exc.code >= 500 or exc.code in {408, 429})) from exc
        except (URLError, OSError, TimeoutError, HTTPException) as exc:
            from tools.wubu_tool.autostart import connection_refused
            refused = connection_refused(exc)
            error = WubuError("wubu_unavailable", "无法连接物簿或请求超时。",
                              unknown=write and not refused, retryable=True)
            error.refused = refused
            raise error from exc
        except (ValueError, UnicodeError) as exc:
            raise WubuError("invalid_response", "物簿返回了无效 JSON。", unknown=write, retryable=True) from exc
