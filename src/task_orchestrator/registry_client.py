"""PT 注册客户端:向中央注册中心登记/发现/申请/批准。

组长/组员 PT 实例通过它接入注册中心,实现跨环境发现与权限批准。
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("registry.client")


class RegistryClient:
    """单个注册中心的客户端封装。"""

    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self._httpx = httpx.AsyncClient(timeout=timeout)

    async def register(self, name: str, url: str, role: str, description: str = "") -> int:
        """登记本实例,返回 peer_id。"""
        r = await self._httpx.post(
            f"{self.base_url}/api/register",
            json={"name": name, "url": url, "role": role, "description": description},
        )
        r.raise_for_status()
        return r.json()["peer_id"]

    async def join_request(self, peer_id: int, peer_name: str, peer_url: str, leader_id: int) -> int:
        """组员向组长发起加入申请,返回 request_id。"""
        r = await self._httpx.post(
            f"{self.base_url}/api/join-request",
            json={"peer_id": peer_id, "peer_name": peer_name, "peer_url": peer_url, "leader_id": leader_id},
        )
        r.raise_for_status()
        return r.json()["request_id"]

    async def approved_peers(self, leader_id: int) -> list[dict]:
        """组长已批准的组员列表。"""
        r = await self._httpx.get(f"{self.base_url}/api/approved", params={"leader_id": leader_id})
        r.raise_for_status()
        return r.json()

    async def list_requests(self, leader_id: int, status: str | None = None) -> list[dict]:
        """组长查询收到的申请列表。"""
        params = {"leader_id": leader_id}
        if status:
            params["status"] = status
        r = await self._httpx.get(f"{self.base_url}/api/requests", params=params)
        r.raise_for_status()
        return r.json()

    async def approve(self, request_id: int, approve: bool = True) -> str:
        """批准/拒绝申请,返回新状态。"""
        r = await self._httpx.post(
            f"{self.base_url}/api/approve",
            json={"request_id": request_id, "approve": approve},
        )
        r.raise_for_status()
        return r.json()["status"]

    async def peers(self, role: str | None = None) -> list[dict]:
        """查询已注册的 PT 列表。"""
        params = {"role": role} if role else {}
        r = await self._httpx.get(f"{self.base_url}/api/peers", params=params)
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        await self._httpx.aclose()


async def register_instance(settings, url: str) -> int | None:
    """启动时向注册中心登记本实例。

    未配置 registry_url 时返回 None(不注册)。失败仅告警不阻塞启动。
    """
    if not settings.registry_url:
        return None
    client = RegistryClient(settings.registry_url)
    try:
        peer_id = await client.register(
            name=settings.instance_name,
            url=url,
            role=settings.a2a_role,
            description=settings.instance_description,
        )
        logger.info("已注册到注册中心", extra={"peer_id": peer_id, "url": settings.registry_url})
        return peer_id
    except Exception as exc:
        logger.warning("注册中心登记失败(继续本地运行)", extra={"error": str(exc)})
        return None
    finally:
        await client.close()
