"""Config flow for YoLink Local integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ApiError, AuthenticationError, YoLinkCloudClient, create_client
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_CLOUD_CLIENT_ID,
    CONF_CLOUD_CLIENT_SECRET,
    CONF_CLOUD_HUB_ID,
    CONF_HUB_IP,
    CONF_NET_ID,
    DOMAIN,
)

CLOUD_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CLOUD_CLIENT_ID): str,
        vol.Optional(CONF_CLOUD_CLIENT_SECRET): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_CLOUD_HUB_ID): str,
    }
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HUB_IP): str,
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_CLIENT_SECRET): str,
        vol.Required(CONF_NET_ID): str,
    }
)


class YoLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for YoLink Local."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> YoLocalOptionsFlow:
        """Create the optional cloud diagnostics flow."""
        return YoLocalOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                client, _, session = await create_client(
                    host=user_input[CONF_HUB_IP],
                    client_id=user_input[CONF_CLIENT_ID],
                    client_secret=user_input[CONF_CLIENT_SECRET],
                )
                await session.close()
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"YoLink Hub ({user_input[CONF_HUB_IP]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class YoLocalOptionsFlow(OptionsFlowWithReload):
    """Configure optional YoLink Cloud hub diagnostics."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure or disable cloud diagnostics."""
        errors: dict[str, str] = {}

        if user_input is not None:
            options = {
                key: str(user_input.get(key, "")).strip()
                for key in (
                    CONF_CLOUD_CLIENT_ID,
                    CONF_CLOUD_CLIENT_SECRET,
                    CONF_CLOUD_HUB_ID,
                )
            }
            cloud_client_id = options[CONF_CLOUD_CLIENT_ID]
            cloud_client_secret = options[CONF_CLOUD_CLIENT_SECRET]

            if bool(cloud_client_id) != bool(cloud_client_secret):
                errors["base"] = "cloud_credentials_incomplete"
            elif cloud_client_id and cloud_client_secret:
                session = aiohttp.ClientSession()
                try:
                    cloud = YoLinkCloudClient(
                        client_id=cloud_client_id,
                        client_secret=cloud_client_secret,
                        session=session,
                        hub_device_id=options[CONF_CLOUD_HUB_ID] or None,
                    )
                    async with asyncio.timeout(15):
                        await cloud.async_get_hub_state()
                except AuthenticationError:
                    errors["base"] = "invalid_cloud_auth"
                except ApiError:
                    errors["base"] = "invalid_cloud_hub"
                except Exception:
                    _LOGGER.exception("Unable to validate YoLink Cloud diagnostics")
                    errors["base"] = "cannot_connect_cloud"
                finally:
                    await session.close()

            if not errors:
                return self.async_create_entry(data=options)

        suggested = user_input if user_input is not None else self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                CLOUD_OPTIONS_SCHEMA, suggested
            ),
            errors=errors,
        )
