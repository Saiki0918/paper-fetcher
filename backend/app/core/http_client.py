"""集中管理各论文平台的异步 HTTP 客户端和请求默认值。"""

from collections.abc import Mapping
from typing import Any

import httpx

from app.core.config import settings


# 所有平台默认使用 JSON 响应和可识别的客户端标识；平台可按需覆盖。
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "PaperSearch/0.4 (academic-paper-search)",
}


# 创建带有统一超时、User-Agent 和 Accept 的异步 HTTP 客户端。
def create_http_client(
    *,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
) -> httpx.AsyncClient:
    """Build an AsyncClient while allowing a platform to override defaults."""
    request_headers = dict(DEFAULT_HEADERS)
    if headers:
        request_headers.update(headers)
    return httpx.AsyncClient(
        timeout=timeout if timeout is not None else settings.http_timeout_seconds,
        headers=request_headers,
        # 部分论文平台会将 API 地址重定向到区域或版本化地址。
        follow_redirects=True,
    )


# 发起 GET 请求并解析 JSON，同时统一执行 HTTP 状态检查。
async def request_json(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> Any:
    """获得 JSON 响应，支持自定义客户端、超时和头。"""
    if client is not None:
        request_kwargs: dict[str, Any] = {"params": params}
        if headers:
            request_kwargs["headers"] = headers
        response = await client.get(url, **request_kwargs)
        response.raise_for_status()
        return response.json()

    async with create_http_client(timeout=timeout, headers=headers) as request_client:
        response = await request_client.get(url, params=params)
        response.raise_for_status()
        return response.json()


# 发起 GET 请求并返回原始响应字节，适用于 XML 等非 JSON 接口。
async def request_content(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """获得非 JSON 响应，支持自定义客户端、超时和头。"""
    if client is not None:
        request_kwargs: dict[str, Any] = {"params": params}
        if headers:
            request_kwargs["headers"] = headers
        response = await client.get(url, **request_kwargs)
        response.raise_for_status()
        return response.content

    async with create_http_client(timeout=timeout, headers=headers) as request_client:
        response = await request_client.get(url, params=params)
        response.raise_for_status()
        return response.content
