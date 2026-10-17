"""MQTT must not keep reconnecting with a stale access token.

The hub's MQTT broker authenticates with the HTTP access token, which expires
and is invalidated when the hub restarts. These tests drive the paho callbacks
the way paho's network thread does and check that reconnects use a fresh token.
"""
import asyncio
import importlib.util
import pathlib
import sys
import threading
from unittest.mock import MagicMock

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "yolocal" / "api" / "mqtt.py"
spec = importlib.util.spec_from_file_location("yolocal_mqtt", ROOT)
mqtt_mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mqtt_mod
spec.loader.exec_module(mqtt_mod)
YoLinkMQTTClient = mqtt_mod.YoLinkMQTTClient


def _make(provider):
    c = YoLinkMQTTClient("hub", "net", "client-id", "stale-token", token_provider=provider)
    c._client = MagicMock()
    c._loop = asyncio.get_running_loop()
    return c


def _from_paho_thread(fn, *args):
    t = threading.Thread(target=fn, args=args)
    t.start()
    t.join()


def test_auth_failure_forces_new_token():
    async def run():
        calls = []

        async def provider(force):
            calls.append(force)
            return "fresh-token"

        c = _make(provider)
        _from_paho_thread(c._on_connect, c._client, None, None, 5)  # 5 = not authorized
        await asyncio.sleep(0.05)
        assert calls == [True]
        c._client.username_pw_set.assert_called_with("client-id", "fresh-token")

    asyncio.run(run())


def test_disconnect_refreshes_expired_token_before_reconnect():
    async def run():
        async def provider(force):
            assert force is False
            return "renewed-token"

        c = _make(provider)
        _from_paho_thread(c._on_disconnect, c._client, None, None, 7)
        await asyncio.sleep(0.05)
        c._client.username_pw_set.assert_called_with("client-id", "renewed-token")

    asyncio.run(run())


def test_forced_refresh_is_rate_limited():
    async def run():
        calls = []

        async def provider(force):
            calls.append(force)
            return "fresh-token"

        c = _make(provider)
        for _ in range(5):
            _from_paho_thread(c._on_connect, c._client, None, None, 5)
        await asyncio.sleep(0.05)
        assert calls == [True]

    asyncio.run(run())


def test_unchanged_token_does_not_reset_credentials():
    async def run():
        async def provider(force):
            return "stale-token"

        c = _make(provider)
        _from_paho_thread(c._on_disconnect, c._client, None, None, 7)
        await asyncio.sleep(0.05)
        c._client.username_pw_set.assert_not_called()

    asyncio.run(run())


def test_provider_failure_is_tolerated():
    async def run():
        async def provider(force):
            raise ConnectionError("hub unreachable")

        c = _make(provider)
        _from_paho_thread(c._on_connect, c._client, None, None, 5)
        await asyncio.sleep(0.05)
        c._client.username_pw_set.assert_not_called()

    asyncio.run(run())
