"""Check Azure WebSocket upgrade and session readiness without sending microphone audio."""

import asyncio
import json

import aiohttp

from auth import AzureCliTokenProvider
from live import LiveSessionError, live_session_url
from server import (SessionConfiguration, connect_voice, describe_connection_error,
                    load_settings, lookup_configured_agent)


async def check_live(client, cfg, headers, version):
    params = {"api-version": cfg.api_version, "x-agent-version-override": version}
    started = False
    events = []
    async with client.ws_connect(live_session_url(cfg).replace("https://", "wss://", 1),
                                 headers=headers, params=params) as ws:
        async for message in ws:
            if message.type != aiohttp.WSMsgType.TEXT:
                continue
            event = json.loads(message.data)
            kind = event.get("type")
            events.append(kind)
            if kind == "session.started":
                audio = (event.get("session") or {}).get("audio") or {}
                if audio.get("format") != {"type": "audio/pcm", "rate": 24000}:
                    raise LiveSessionError("GPT Live did not negotiate PCM16 at 24 kHz.")
                started = True
                await ws.send_json({"type": "session.close"})
            elif kind == "session.closed":
                print(json.dumps({"ok": started and event.get("reason") != "connection_lost",
                                  "stage": "session_closed", "events": events,
                                  "usage": event.get("usage"),
                                  "note": "GPT Live startup and graceful close checked; no microphone audio was sent."}))
                return 0 if started and event.get("reason") != "connection_lost" else 1
            elif kind == "error":
                break
    raise LiveSessionError("GPT Live diagnostic ended without a successful startup and graceful close.")


async def check():
    cfg = load_settings()
    if not cfg.configured:
        print(json.dumps({"ok": False, "stage": "configuration", "issues": cfg.setup_issues,
                          "message": "Set the project endpoint in .env, then sign in with az login. Create the Agent through the demo UI before running this diagnostic."}))
        return 1
    events = []
    stage = "azure_cli_authentication"
    try:
        async with asyncio.timeout(50):
            async with aiohttp.ClientSession() as client:
                provider = AzureCliTokenProvider()
                token = await provider.get_token(client)
                headers = {"Authorization": f"Bearer {token}", "Foundry-Features": cfg.features}
                stage = "agent_lookup"
                latest = await lookup_configured_agent(client, cfg, headers, include_version=True)
                if latest is not None and latest["definition"].get("sub_protocol") == "live":
                    stage = "live_startup"
                    return await check_live(client, cfg, headers, latest["version"])
                stage = "websocket_upgrade"
                async with connect_voice(client, cfg, {"Authorization": f"Bearer {token}",
                        "Foundry-Features": cfg.features}, "websocket") as ws:
                    print(json.dumps({"stage": "websocket_upgrade", "ok": True}), flush=True)
                    stage = "session_startup"
                    configuration = SessionConfiguration()
                    async for message in ws:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            continue
                        event = json.loads(message.data)
                        events.append(event.get("type"))
                        if await configuration.observe(event, ws):
                            print(json.dumps({"ok": True, "stage": "session_ready", "events": events,
                                              "note": "Model-specific interruption settings acknowledged; no microphone audio or user turn was sent."}))
                            return 0
                        if event.get("type") == "error":
                            print(json.dumps({"ok": False, "stage": "service_error", "events": events}))
                            return 1
        print(json.dumps({"ok": False, "stage": "closed_before_ready", "events": events}))
    except Exception as error:
        os_error = getattr(error, "os_error", error)
        print(json.dumps({"ok": False, "stage": stage, "error_type": type(error).__name__,
                          "message": describe_connection_error(error),
                          "http_status": getattr(error, "status", None),
                          "errno": getattr(os_error, "errno", None),
                          "winerror": getattr(os_error, "winerror", None), "events": events}))
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check()))
