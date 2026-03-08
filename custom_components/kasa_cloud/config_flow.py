"""Config flow for Kasa Cloud integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class KasaCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kasa Cloud."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                from tplinkcloud import TPLinkDeviceManager

                # login() is synchronous (uses requests), run in executor
                dm = await self.hass.async_add_executor_job(
                    TPLinkDeviceManager,
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )
                # get_devices() is async
                await dm.get_devices()
            except Exception:
                _LOGGER.exception("Failed to authenticate with TP-Link cloud")
                errors["base"] = "invalid_auth"
            else:
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Kasa Cloud ({user_input[CONF_EMAIL]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
