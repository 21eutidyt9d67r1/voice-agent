"""Ordered, bounded PCM playback for the long-tool sample; no application TTS."""

from __future__ import annotations

import asyncio
import threading
from collections import deque

RATE = 24000
FRAMES = 1200


class Playback:
    def __init__(self):
        self.lock = threading.Lock()
        self.chunks = deque()
        self.queued_bytes = 0

    def output(self, pcm):
        if len(pcm) % 2:
            raise RuntimeError("Incomplete PCM16 frame received.")
        with self.lock:
            if self.queued_bytes + len(pcm) > RATE * 2 * 120:
                raise RuntimeError("Playback exceeded its 120-second limit. Reconnect.")
            self.chunks.append(pcm)
            self.queued_bytes += len(pcm)

    def render(self, frames):
        wanted = frames * 2
        output = bytearray()
        with self.lock:
            while self.chunks and len(output) < wanted:
                chunk = self.chunks.popleft()
                take = min(wanted - len(output), len(chunk))
                output.extend(chunk[:take])
                self.queued_bytes -= take
                if take < len(chunk):
                    self.chunks.appendleft(chunk[take:])
        return bytes(output) + bytes(wanted - len(output))

    def interrupt(self):
        with self.lock:
            self.chunks.clear()
            self.queued_bytes = 0


class Audio(Playback):
    def __init__(self):
        super().__init__()
        try:
            import pyaudio
        except ImportError as error:
            raise RuntimeError("Microphone mode requires PyAudio; install it or use --text.") from error
        self.module = pyaudio
        self.device = pyaudio.PyAudio()
        self.loop = asyncio.get_running_loop()
        self.incoming = asyncio.Queue(maxsize=200)
        self.failure = self.loop.create_future()
        self.streams = []

    def fail(self, message):
        if not self.failure.done():
            self.failure.set_result(message)

    def enqueue(self, data, status):
        if status:
            self.fail("Microphone audio was lost. Reconnect.")
        else:
            try:
                self.incoming.put_nowait(data)
            except asyncio.QueueFull:
                self.fail("Microphone upload fell behind. Reconnect.")

    def start(self):
        def capture(data, _frames, _time, status):
            self.loop.call_soon_threadsafe(self.enqueue, data, status)
            return None, self.module.paContinue

        def render(_data, frames, _time, status):
            if status:
                self.loop.call_soon_threadsafe(self.fail, "Speaker playback reported audio loss. Reconnect.")
            return self.render(frames), self.module.paContinue

        for direction, callback in (("output", render), ("input", capture)):
            self.streams.append(self.device.open(
                format=self.module.paInt16, channels=1, rate=RATE,
                frames_per_buffer=FRAMES, stream_callback=callback, **{direction: True},
            ))

    async def send(self, connection):
        while True:
            if self.failure.done():
                raise RuntimeError(self.failure.result())
            try:
                data = await asyncio.wait_for(self.incoming.get(), timeout=0.2)
            except TimeoutError:
                continue
            await connection.input_audio_buffer.append(audio=data)

    def close(self):
        try:
            for stream in self.streams:
                try:
                    stream.stop_stream()
                finally:
                    stream.close()
        finally:
            self.device.terminate()
