"""Loopback web cockpit; Azure credentials and simulated tools stay server-side."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from vehicle import Dispatcher, configure_console
from vehicle_voice_agent import Session, definition, project_endpoint, receive

ROOT = Path(__file__).parent
logger = logging.getLogger(__name__)


@dataclass
class Settings:
    demo: bool
    port: int
    dispatcher: Dispatcher = field(default_factory=Dispatcher)
    voice_active: bool = False
    client: Any = None
    agent_name: str | None = None
    agent_enabled: bool = False


SETTINGS = web.AppKey("settings", Settings)


def snapshot(dispatcher: Dispatcher) -> dict[str, Any]:
    return dispatcher.vehicle.execute("get_vehicle_status", {})["state"]


@web.middleware
async def local_only(request: web.Request, handler):
    port = request.app[SETTINGS].port
    if request.host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
        raise web.HTTPForbidden(text="Use the loopback address printed by the server.")
    origin = request.headers.get("Origin")
    if origin and origin != f"{request.scheme}://{request.host}":
        raise web.HTTPForbidden(text="Cross-origin requests are not allowed.")
    if request.method != "GET" and not origin:
        raise web.HTTPForbidden(text="Browser actions require a same-origin request.")
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


async def index(_request):
    return web.FileResponse(ROOT / "static" / "index.html")


async def asset(request):
    name = request.match_info["name"]
    if name not in {"app.js", "style.css", "pcm-worklet.js", "playback.js", "car.svg"}:
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT / "static" / name)


async def state(request):
    return web.json_response({
        "mode": "offline" if request.app[SETTINGS].demo else "cloud",
        "state": snapshot(request.app[SETTINGS].dispatcher), "simulated": True,
    })


async def manual_tool(request):
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="Expected a JSON tool request.")
    if not isinstance(body, dict) or set(body) != {"name", "arguments"}:
        raise web.HTTPBadRequest(text="Expected name and arguments.")
    if not isinstance(body["name"], str):
        raise web.HTTPBadRequest(text="Tool name must be a string.")
    if len(request.app[SETTINGS].dispatcher.completed) >= 1000:
        return web.json_response({"ok": False, "error": "Tool limit reached. Restart the simulator."}, status=429)
    result = request.app[SETTINGS].dispatcher.dispatch({
        "call_id": uuid.uuid4().hex, "name": body["name"],
        "arguments": json.dumps(body["arguments"]),
    })
    return web.json_response(result, status=200 if result["ok"] else 400)


class BrowserAudio:
    requires_ack = True

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self.generation = 0

    def output(self, delta: Any, event: dict[str, Any]) -> None:
        pcm = delta if isinstance(delta, bytes) else base64.b64decode(delta, validate=True)
        if len(pcm) % 2:
            raise RuntimeError("Incomplete output PCM frames.")
        if not isinstance(event.get("item_id"), str) or not isinstance(event.get("response_id"), str):
            raise RuntimeError("Output audio must identify its response and conversation item.")
        try:
            self.queue.put_nowait({
                "type": "audio", "generation": self.generation,
                "item_id": event["item_id"], "content_index": event.get("content_index", 0),
                "response_id": event["response_id"], "pcm": base64.b64encode(pcm).decode("ascii"),
            })
        except asyncio.QueueFull as error:
            raise RuntimeError("Browser audio transport cannot keep up.") from error

    async def send(self, socket):
        while True:
            event = await self.queue.get()
            if event["generation"] == self.generation:
                await socket.send_json(event)

    def interrupt(self) -> int:
        self.generation += 1
        while not self.queue.empty():
            self.queue.get_nowait()
        return self.generation


async def cloud_resources(app):
    from azure.ai.projects.aio import AIProjectClient
    from azure.identity.aio import AzureCliCredential, DefaultAzureCredential

    settings = app[SETTINGS]
    if settings.demo:
        yield
        return
    endpoint = project_endpoint(os.getenv("AZURE_VOICE_AGENTS_ENDPOINT", ""))
    mode = os.getenv("AZURE_CREDENTIAL_MODE", "cli")
    if mode not in {"cli", "default"}:
        raise ValueError("AZURE_CREDENTIAL_MODE must be cli or default.")
    credential = AzureCliCredential() if mode == "cli" else DefaultAzureCredential()
    async with credential, AIProjectClient(
        endpoint=endpoint, credential=credential, allow_preview=True,
    ) as client:
        settings.client = client
        try:
            yield
        finally:
            settings.client = None


async def ensure_agent(settings: Settings, socket) -> str:
    from azure.ai.projects.models import VoiceAgentDefinition

    started = asyncio.get_running_loop().time()
    if settings.agent_name is None:
        await socket.send_json({"type": "progress", "message": "Signing in to Azure and creating the cockpit agent (first connection only)…"})
        name = f"vehicle-cockpit-{uuid.uuid4().hex[:12]}"
        async with asyncio.timeout(60):
            await settings.client.agents.create_version(
                agent_name=name,
                definition=VoiceAgentDefinition(definition(
                    os.getenv("AZURE_VOICE_AGENTS_MODEL", "gpt-realtime"),
                    os.getenv("AZURE_VOICE_AGENTS_VOICE", "en-US-AvaNeural"), False,
                )),
            )
        settings.agent_name = name
        logger.info("Agent creation took %.1fs: %s", asyncio.get_running_loop().time() - started, name)
    if not settings.agent_enabled:
        await socket.send_json({"type": "progress", "message": "Enabling the cockpit agent…"})
        async with asyncio.timeout(30):
            await settings.client.agents.enable(settings.agent_name)
        settings.agent_enabled = True
    logger.info("Agent ready after %.1fs: %s", asyncio.get_running_loop().time() - started, settings.agent_name)
    return settings.agent_name


async def cloud_session(request, socket, incoming):
    settings = request.app[SETTINGS]
    name = await ensure_agent(settings, socket)
    await socket.send_json({"type": "agent", "name": name})
    await socket.send_json({"type": "progress", "message": "Opening the realtime voice connection…"})
    started = asyncio.get_running_loop().time()
    async with AsyncExitStack() as stack:
        async with asyncio.timeout(45):
            connection = await stack.enter_async_context(
                settings.client.beta.voice_agents.realtime.connect(agent_name=name),
            )
            while True:
                event = await receive(connection)
                if event.get("type") == "session.updated":
                    config = event.get("session") or {}
                    vad = ((config.get("audio") or {}).get("input") or {}).get(
                        "turn_detection", config.get("turn_detection"),
                    )
                    if not isinstance(vad, dict) or vad.get("create_response") is not False:
                        raise RuntimeError("Client-controlled VAD responses were not configured.")
                    break
        logger.info("Realtime session ready in %.1fs", asyncio.get_running_loop().time() - started)
        audio = BrowserAudio()

        async def notify(event):
            event["state"] = snapshot(settings.dispatcher)
            await socket.send_json(event)

        session = Session(
            connection, Dispatcher(vehicle=settings.dispatcher.vehicle, discovery=True), audio, notify,
        )
        session_events: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)

        async def cloud_events():
            while True:
                await session_events.put(await receive(connection))

        async def events():
            while True:
                deadlines = [
                    value for value in (
                        session.deadline if session.responding else None,
                        session.playback_ack_deadline,
                    ) if value is not None
                ]
                async with asyncio.timeout_at(min(deadlines) if deadlines else None):
                    await session.handle(await session_events.get())

        async def inputs():
            while True:
                packet = await incoming.get()
                if isinstance(packet, bytes):
                    await connection.input_audio_buffer.append(audio=packet)
                else:
                    await session_events.put(packet)

        await socket.send_json({"type": "ready"})
        tasks = [
            asyncio.create_task(cloud_events()), asyncio.create_task(events()),
            asyncio.create_task(inputs()), asyncio.create_task(audio.send(socket)),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def read_browser(socket, incoming) -> None:
    # Read immediately, including during Azure setup, so heartbeat PONGs are processed.
    async for message in socket:
        if message.type == WSMsgType.BINARY:
            if not message.data or len(message.data) > 4800 or len(message.data) % 2:
                raise ValueError("Expected small 24 kHz PCM16 microphone chunks.")
            try:
                incoming.put_nowait(message.data)
            except asyncio.QueueFull as error:
                raise RuntimeError("Browser microphone upload is falling behind.") from error
        elif message.type == WSMsgType.TEXT:
            try:
                packet = json.loads(message.data)
            except json.JSONDecodeError as error:
                raise ValueError("Invalid browser playback acknowledgement.") from error
            if not isinstance(packet, dict) or packet.get("type") != "playback_interrupted":
                raise ValueError("Only PCM and playback acknowledgements are accepted.")
            try:
                incoming.put_nowait(packet)
            except asyncio.QueueFull as error:
                raise RuntimeError("Browser input queue is full.") from error
        elif message.type == WSMsgType.ERROR:
            raise RuntimeError("Browser voice socket failed.")


async def voice(request):
    settings = request.app[SETTINGS]
    if settings.demo:
        raise web.HTTPBadRequest(text="Offline mode has no cloud voice connection.")
    if settings.voice_active:
        raise web.HTTPConflict(text="Another voice session is active.")
    socket = web.WebSocketResponse(max_msg_size=32768, heartbeat=20)
    settings.voice_active = True
    tasks = []
    try:
        await socket.prepare(request)
        try:
            incoming: asyncio.Queue[bytes | dict[str, Any]] = asyncio.Queue(maxsize=200)
            tasks = [
                asyncio.create_task(read_browser(socket, incoming)),
                asyncio.create_task(cloud_session(request, socket, incoming)),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except Exception:
            # Azure exceptions can contain endpoint/request details; keep those server-side.
            logger.exception("Cloud voice session failed")
            if not socket.closed:
                try:
                    await socket.send_json({
                        "type": "error",
                        "message": "Cloud voice failed. Check the server log, Azure login, and model configuration.",
                    })
                except ConnectionResetError:
                    logger.info("Browser disconnected before the error could be delivered.")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await socket.close()
    finally:
        settings.voice_active = False
    return socket


def create_app(demo: bool, port: int) -> web.Application:
    configure_console()
    app = web.Application(middlewares=[local_only], client_max_size=8192)
    app[SETTINGS] = Settings(demo, port)
    app.cleanup_ctx.append(cloud_resources)
    app.add_routes([
        web.get("/", index), web.get("/static/{name}", asset),
        web.get("/api/state", state), web.post("/api/tool", manual_tool), web.get("/ws", voice),
    ])
    return app


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Offline cockpit; no Azure calls, microphone, or AI.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535.")
    print(f"SIMULATED VEHICLE ONLY. Open http://127.0.0.1:{args.port}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    web.run_app(create_app(args.demo, args.port), host="127.0.0.1", port=args.port)
