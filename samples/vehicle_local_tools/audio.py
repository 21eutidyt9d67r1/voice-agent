"""Bounded 24 kHz mono PCM microphone and playback transport."""

from __future__ import annotations

import asyncio
import base64
import queue
from typing import Any

RATE = 24000
FRAMES = 1200


class Audio:
    def __init__(self, playback: bool) -> None:
        try:
            import pyaudio
        except ImportError as error:
            raise RuntimeError("Install requirements.txt to use microphone audio.") from error
        self.module = pyaudio
        self.device = pyaudio.PyAudio()
        self.playback = playback
        self.input_stream = None
        self.output_stream = None
        self.incoming: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self.outgoing: queue.Queue[bytes] = queue.Queue(maxsize=1200)
        self.remaining = b""
        self.failure: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    def fail(self, message: str) -> None:
        if not self.failure.done():
            self.failure.set_exception(RuntimeError(message))

    def start(self) -> None:
        loop = asyncio.get_running_loop()

        def enqueue(pcm, status):
            if status:
                self.fail("Microphone reported audio loss. Restart the session.")
                return
            try:
                self.incoming.put_nowait(pcm)
            except asyncio.QueueFull:
                self.fail("Audio upload is falling behind. Restart the session.")

        def capture(data, _frames, _time, status):
            loop.call_soon_threadsafe(enqueue, data, status)
            return None, self.module.paContinue

        def render(_data, frames, _time, _status):
            wanted = frames * 2
            output = self.remaining[:wanted]
            self.remaining = self.remaining[wanted:]
            while len(output) < wanted:
                try:
                    pcm = self.outgoing.get_nowait()
                except queue.Empty:
                    break
                take = wanted - len(output)
                output += pcm[:take]
                self.remaining = pcm[take:]
            return output + bytes(wanted - len(output)), self.module.paContinue

        if self.playback:
            self.output_stream = self.device.open(
                format=self.module.paInt16, channels=1, rate=RATE, output=True,
                frames_per_buffer=FRAMES, stream_callback=render,
            )
        self.input_stream = self.device.open(
            format=self.module.paInt16, channels=1, rate=RATE, input=True,
            frames_per_buffer=FRAMES, stream_callback=capture,
        )

    async def send(self, connection: Any) -> None:
        while True:
            await connection.input_audio_buffer.append(audio=await self.incoming.get())

    def output(self, delta: Any, _event: Any = None) -> None:
        pcm = delta if isinstance(delta, bytes) else base64.b64decode(delta, validate=True)
        if len(pcm) % 2:
            raise RuntimeError("Received incomplete PCM audio frames.")
        if self.playback:
            try:
                self.outgoing.put_nowait(pcm)
            except queue.Full:
                self.fail("Playback is falling behind. Restart with --no-playback.")

    def close(self) -> None:
        try:
            for stream in (self.input_stream, self.output_stream):
                if stream is not None:
                    try:
                        stream.stop_stream()
                    finally:
                        stream.close()
        finally:
            self.device.terminate()
            if not self.failure.done():
                self.failure.cancel()
