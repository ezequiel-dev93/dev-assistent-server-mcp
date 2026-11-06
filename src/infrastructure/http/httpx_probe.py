import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict

from ...core.models import EndpointRequestSpec, HttpProbeRawResponse
from ...core.ports import IHttpProbe

MAX_RESPONSE_BYTES = 65_536


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevents automatic HTTP redirect following so 3xx responses cannot bypass SSRF validation."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _append_query_params(url: str, params: Dict[str, str]) -> str:
    if not params:
        return url
    parsed = urllib.parse.urlsplit(url)
    existing = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    merged = existing + [(str(k), str(v)) for k, v in params.items()]
    new_query = urllib.parse.urlencode(merged)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment)
    )


class HttpxClientProbe(IHttpProbe):
    """
    Driven HTTP adapter implementing `IHttpProbe`.
    Uses `httpx` as primary transport with automatic stdlib `urllib.request` fallback.
    """

    def send(
        self,
        spec: EndpointRequestSpec,
        resolved_headers: Dict[str, str],
    ) -> HttpProbeRawResponse:
        try:
            import httpx  # type: ignore

            return self._send_with_httpx(httpx, spec, resolved_headers)
        except ModuleNotFoundError:
            return self._send_with_urllib(spec, resolved_headers)

    def _send_with_httpx(
        self,
        httpx_mod: Any,
        spec: EndpointRequestSpec,
        resolved_headers: Dict[str, str],
    ) -> HttpProbeRawResponse:
        start = time.perf_counter()
        try:
            with httpx_mod.Client(
                timeout=spec.timeout_seconds,
                follow_redirects=False,
            ) as client:
                with client.stream(
                    method=spec.method.value,
                    url=spec.url,
                    headers=resolved_headers,
                    params=spec.query_params or None,
                    json=spec.json_payload if spec.json_payload is not None else None,
                ) as response:
                    chunks = []
                    total_read = 0
                    for chunk in response.iter_bytes():
                        total_read += len(chunk)
                        if total_read <= MAX_RESPONSE_BYTES:
                            chunks.append(chunk)
                        else:
                            overflow = total_read - MAX_RESPONSE_BYTES
                            keep = len(chunk) - overflow
                            if keep > 0:
                                chunks.append(chunk[:keep])
                            break
                    elapsed_ms = (time.perf_counter() - start) * 1000.0
                    raw_bytes = b"".join(chunks)
                    encoding = response.encoding or "utf-8"
                    body_text = raw_bytes.decode(encoding, errors="replace")
                    headers_dict = {str(k).lower(): str(v) for k, v in response.headers.items()}
                    return HttpProbeRawResponse(
                        status_code=int(response.status_code),
                        response_time_ms=round(elapsed_ms, 2),
                        headers=headers_dict,
                        content_type=headers_dict.get("content-type", ""),
                        body_text=body_text,
                        size_bytes=total_read,
                        transport_used="httpx",
                    )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return HttpProbeRawResponse(
                response_time_ms=round(elapsed_ms, 2),
                transport_used="httpx",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _send_with_urllib(
        self,
        spec: EndpointRequestSpec,
        resolved_headers: Dict[str, str],
    ) -> HttpProbeRawResponse:
        target_url = _append_query_params(spec.url, spec.query_params)
        req_headers = dict(resolved_headers)
        body_bytes = None
        if spec.json_payload is not None:
            body_bytes = json.dumps(spec.json_payload).encode("utf-8")
            if not any(k.lower() == "content-type" for k in req_headers):
                req_headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url=target_url,
            data=body_bytes,
            headers=req_headers,
            method=spec.method.value,
        )
        opener = urllib.request.build_opener(_NoRedirectHandler)
        start = time.perf_counter()
        try:
            with opener.open(request, timeout=spec.timeout_seconds) as resp:
                raw_bytes = resp.read(MAX_RESPONSE_BYTES)
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                headers_dict = {str(k).lower(): str(v) for k, v in resp.headers.items()}
                return HttpProbeRawResponse(
                    status_code=int(resp.status),
                    response_time_ms=round(elapsed_ms, 2),
                    headers=headers_dict,
                    content_type=headers_dict.get("content-type", ""),
                    body_text=raw_bytes.decode("utf-8", errors="replace"),
                    size_bytes=len(raw_bytes),
                    transport_used="urllib",
                )
        except urllib.error.HTTPError as http_err:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            raw_bytes = http_err.read(MAX_RESPONSE_BYTES) if http_err.fp else b""
            headers_dict = (
                {str(k).lower(): str(v) for k, v in http_err.headers.items()}
                if http_err.headers
                else {}
            )
            return HttpProbeRawResponse(
                status_code=int(http_err.code),
                response_time_ms=round(elapsed_ms, 2),
                headers=headers_dict,
                content_type=headers_dict.get("content-type", ""),
                body_text=raw_bytes.decode("utf-8", errors="replace"),
                size_bytes=len(raw_bytes),
                transport_used="urllib",
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return HttpProbeRawResponse(
                response_time_ms=round(elapsed_ms, 2),
                transport_used="urllib",
                error=f"{type(exc).__name__}: {exc}",
            )
