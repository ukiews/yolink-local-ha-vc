"""Optional YoLink Cloud client used only for hub diagnostics."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from .auth import AuthenticationError
from .client import ApiError

CLOUD_BASE_URL = "https://api.yosmart.com"
TOKEN_REFRESH_BUFFER = 300


@dataclass
class CloudHub:
    """Cloud device credentials for a YoLink hub."""

    device_id: str
    token: str
    name: str
    model: str | None = None


class YoLinkCloudClient:
    """Minimal cloud client for read-only hub diagnostics."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        session: aiohttp.ClientSession,
        hub_device_id: str | None = None,
    ) -> None:
        """Initialize the optional cloud diagnostics client."""
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session
        self._preferred_hub_id = hub_device_id.casefold() if hub_device_id else None
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._hub: CloudHub | None = None

    @property
    def hub(self) -> CloudHub | None:
        """Return the selected cloud hub, when discovered."""
        return self._hub

    async def async_get_hub_state(self) -> dict[str, Any]:
        """Return the selected hub's cloud state."""
        if self._hub is None:
            await self._async_discover_hub()

        if self._hub is None:
            raise ApiError("No YoLink Hub was found in the cloud account")

        try:
            return await self._async_request(
                {
                    "method": "Hub.getState",
                    "targetDevice": self._hub.device_id,
                    "token": self._hub.token,
                    "params": {},
                }
            )
        except ApiError as err:
            # Refresh the device token once in case YoLink rotated it.
            if "000103" not in str(err):
                raise
            self._hub = None
            await self._async_discover_hub()
            if self._hub is None:
                raise
            return await self._async_request(
                {
                    "method": "Hub.getState",
                    "targetDevice": self._hub.device_id,
                    "token": self._hub.token,
                    "params": {},
                }
            )

    async def _async_discover_hub(self) -> None:
        """Discover and cache the requested hub and its cloud Net Token."""
        data = await self._async_request({"method": "Home.getDeviceList"})
        devices = data.get("devices", data.get("list", []))
        hubs = [device for device in devices if device.get("type") == "Hub"]

        selected: dict[str, Any] | None = None
        if self._preferred_hub_id:
            selected = next(
                (
                    hub
                    for hub in hubs
                    if str(hub.get("deviceId", "")).casefold()
                    == self._preferred_hub_id
                ),
                None,
            )
            if selected is None:
                raise ApiError(
                    "The configured Hub Device EUI was not found in the cloud account"
                )
        elif len(hubs) == 1:
            selected = hubs[0]
        elif not hubs:
            raise ApiError("No YoLink Hub was found in the cloud account")
        else:
            raise ApiError(
                "Multiple YoLink Hubs were found; configure the Hub Device EUI"
            )

        token = selected.get("token")
        device_id = selected.get("deviceId")
        if not token or not device_id:
            raise ApiError("The cloud Hub record did not include device credentials")

        self._hub = CloudHub(
            device_id=str(device_id),
            token=str(token),
            name=str(selected.get("name") or "YoLink Hub"),
            model=(
                str(selected["modelName"])
                if selected.get("modelName") is not None
                else None
            ),
        )

    async def _async_get_access_token(self) -> str:
        """Return a valid cloud access token."""
        if (
            self._access_token is not None
            and time.time() < self._expires_at - TOKEN_REFRESH_BUFFER
        ):
            return self._access_token

        async with self._session.post(
            f"{CLOUD_BASE_URL}/open/yolink/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        ) as response:
            response.raise_for_status()
            result = await response.json()

        access_token = result.get("access_token")
        if not access_token:
            raise AuthenticationError("YoLink Cloud authentication failed")

        self._access_token = str(access_token)
        self._expires_at = time.time() + int(result.get("expires_in", 7200))
        return self._access_token

    async def _async_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a read-only request to the YoLink Cloud API."""
        token = await self._async_get_access_token()
        request = {**payload, "time": int(time.time() * 1000)}
        async with self._session.post(
            f"{CLOUD_BASE_URL}/open/yolink/v2/api",
            json=request,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        ) as response:
            response.raise_for_status()
            result = await response.json()

        if result.get("code") != "000000":
            raise ApiError(
                f"YoLink Cloud API error {result.get('code')}: "
                f"{result.get('desc', 'unknown error')}"
            )
        return result.get("data", {})
