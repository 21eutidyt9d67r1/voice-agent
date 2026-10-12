"""Offline validation of audio, metrics, failures, and thread ramp."""

import io
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import tts_load_test as load


def wav_data(frames=240):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setparams((1, 2, 24000, frames, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * frames)
    return buffer.getvalue()


class LoadTests(unittest.TestCase):
    def test_exact_voice_and_ssml(self):
        self.assertIn(load.VOICE.encode(), load.validate_ssml(Path(__file__).with_name("diya_turbo.ssml")))

    def test_valid_audio(self):
        self.assertEqual(load.audio_duration(wav_data()), .01)

    def test_invalid_audio(self):
        for data in [b"", b"not audio", wav_data()[:-2]]:
            with self.subTest(data=data[:8]), self.assertRaises((EOFError, wave.Error, ValueError)):
                load.audio_duration(data)

    def test_nearest_rank_percentile(self):
        self.assertIsNone(load.percentile([], .95))
        self.assertEqual(load.percentile([4, 1, 3, 2], .5), 2)
        self.assertEqual(load.percentile(list(range(1, 101)), .95), 95)

    def test_invalid_voice_is_not_substituted(self):
        original = Path(__file__).with_name("diya_turbo.ssml").read_text()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wrong.ssml"
            path.write_text(original.replace(load.VOICE, "en-IN-DiyaNeural"))
            with self.assertRaisesRegex(ValueError, "exact"):
                load.validate_ssml(path)

    def test_report_is_persistent_and_has_no_nan(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            load.save_report(path, {"completed": False, "failures": 1})
            self.assertIn('"completed": false', path.read_text())
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_silent_audio_is_rejected(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setparams((1, 2, 24000, 240, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 240)
        with self.assertRaisesRegex(ValueError, "silent"):
            load.audio_duration(buffer.getvalue())

    def test_request_validates_audio(self):
        response = MagicMock(status=200)
        data = wav_data()
        response.read.side_effect = [data[:1], data[1:]]
        connection = MagicMock(connect_count=1, sock=object())
        connection.getresponse.return_value = response
        tracker = load.Inflight()
        row, audio = load.synthesize(connection, "Bearer test", b"ssml", tracker, 0, 0)
        self.assertTrue(row["success"])
        self.assertEqual(audio, data)
        self.assertEqual(tracker.current, 0)

    def test_http_failure_not_counted_as_audio(self):
        connection = MagicMock(connect_count=1, sock=object())
        response = MagicMock(status=429, reason="Too Many Requests")
        response.read.side_effect = [b"x", b"error"]
        connection.getresponse.return_value = response
        row, audio = load.synthesize(connection, "Bearer test", b"ssml", load.Inflight(), 0, 0)
        self.assertFalse(row["success"])
        self.assertEqual(row["status"], 429)
        self.assertIsNone(row["first_byte_ms"])
        self.assertEqual(audio, b"")

    def test_transport_failure_cleans_up(self):
        connection = MagicMock(connect_count=1, sock=object())
        connection.request.side_effect = TimeoutError("timed out")
        tracker = load.Inflight()
        row, _ = load.synthesize(connection, "Bearer test", b"ssml", tracker, 0, 0)
        self.assertFalse(row["success"])
        self.assertEqual(tracker.current, 0)
        connection.close.assert_called_once()

    def test_stage_runs_exact_worker_count(self):
        def request(connection, authorization, ssml, tracker, worker, sequence, output_format):
            tracker.enter()
            time.sleep(.02)
            tracker.leave()
            return {
                "success": True, "status": 200, "first_byte_ms": 10,
                "total_ms": 20, "worker": worker, "sequence": sequence,
                "connection_reused": sequence >= 0, "new_connections": int(sequence < 0),
            }, b""
        with patch.object(load, "HttpClient"), patch.object(load, "synthesize", request):
            summary, rows = load.run_stage("host", "token", b"ssml", 4, 3, 30)
        self.assertEqual(summary["requests"], 12)
        self.assertEqual(summary["successes"], 12)
        self.assertEqual(summary["peak_inflight"], 4)
        self.assertEqual(summary["warmup_requests"], 4)
        self.assertEqual(summary["warmup_failures"], 0)
        self.assertEqual(summary["warmed_successes"], 12)
        self.assertEqual(summary["measured_new_connections"], 0)
        self.assertTrue(all(row["sequence"] >= 0 for row in rows))
        self.assertEqual({row["worker"] for row in rows}, {0, 1, 2, 3})
        self.assertEqual(load.LEVELS, [4, 8, 16, 24, 32, 40, 50])

    def test_failed_warmup_does_not_start_measurement(self):
        def request(connection, authorization, ssml, tracker, worker, sequence, output_format):
            self.assertEqual(sequence, -1)
            return {
                "worker": worker, "success": False, "status": 429,
                "error": "HTTP 429", "sequence": sequence,
            }, b""
        with patch.object(load, "HttpClient"), patch.object(load, "synthesize", request):
            summary, rows = load.run_stage("host", "token", b"ssml", 4, 3, 30)
        self.assertEqual(rows, [])
        self.assertEqual(summary["warmup_failures"], 4)
        self.assertEqual(summary["elapsed_seconds"], 0)

    def test_closed_warmup_socket_is_rejected(self):
        def request(connection, authorization, ssml, tracker, worker, sequence, output_format):
            connection.sock = None
            return {"worker": worker, "success": True}, b""
        with patch.object(load, "HttpClient"), patch.object(load, "synthesize", request):
            summary, rows = load.run_stage("host", "token", b"ssml", 4, 3, 30)
        self.assertEqual(rows, [])
        self.assertEqual(summary["warmup_failures"], 4)

    def test_reconnect_is_recorded(self):
        data = wav_data()
        response = MagicMock(status=200)
        response.read.side_effect = [data[:1], data[1:]]
        connection = MagicMock(connect_count=1, sock=object())
        connection.getresponse.return_value = response
        def reconnect(*args):
            connection.connect_count += 1
        connection.request.side_effect = reconnect
        row, _ = load.synthesize(connection, "test", b"ssml", load.Inflight(), 0, 0)
        self.assertTrue(row["success"])
        self.assertFalse(row["connection_reused"])
        self.assertEqual(row["new_connections"], 1)

    def test_cold_requests_are_excluded_from_warm_percentiles(self):
        def request(connection, authorization, ssml, tracker, worker, sequence, output_format):
            return {
                "worker": worker, "success": True, "status": 200,
                "first_byte_ms": 10 if sequence == 0 else 1000,
                "total_ms": 20 if sequence == 0 else 2000,
                "sequence": sequence, "connection_reused": sequence == 0,
                "new_connections": int(sequence != 0),
            }, b""
        with patch.object(load, "HttpClient"), patch.object(load, "synthesize", request):
            summary, _ = load.run_stage("host", "token", b"ssml", 4, 2, 30)
        self.assertEqual(summary["cold_successes"], 4)
        self.assertEqual(summary["warmed_successes"], 4)
        self.assertEqual(summary["first_byte_ms"]["p95"], 10)
        self.assertEqual(summary["total_ms"]["p95"], 20)

    def test_raw_duration_and_invalid_payloads(self):
        self.assertEqual(load.audio_duration(b"\x01\x00" * 240, load.RAW_FORMAT), .01)
        for data in [b"", b"\x01", b"\0\0", wav_data()]:
            with self.subTest(data=data[:8]), self.assertRaises(ValueError):
                load.audio_duration(data, load.RAW_FORMAT)

    def test_raw_first_sample_requires_two_bytes(self):
        response = MagicMock(status=200)
        response.read.side_effect = [b"\x01", b"\x00", b"\x02\x00"]
        connection = MagicMock(connect_count=1, sock=object())
        connection.getresponse.return_value = response
        with patch.object(load.time, "perf_counter", side_effect=[0, .1, .2, .3]):
            row, audio = load.synthesize(
                connection, "test", b"ssml", load.Inflight(), 0, 0, load.RAW_FORMAT,
            )
        self.assertTrue(row["success"])
        self.assertEqual(row["first_byte_ms"], 100)
        self.assertEqual(row["first_audio_sample_ms"], 200)
        self.assertEqual(row["total_ms"], 300)
        self.assertEqual(audio, b"\x01\x00\x02\x00")
        self.assertEqual(
            connection.request.call_args.args[3]["X-Microsoft-OutputFormat"], load.RAW_FORMAT,
        )

    def test_raw_partial_first_sample_fails(self):
        response = MagicMock(status=200)
        response.read.side_effect = [b"\x01", b""]
        connection = MagicMock(connect_count=1, sock=object())
        connection.getresponse.return_value = response
        row, _ = load.synthesize(
            connection, "test", b"ssml", load.Inflight(), 0, 0, load.RAW_FORMAT,
        )
        self.assertFalse(row["success"])
        self.assertIsNone(row["first_audio_sample_ms"])

    def test_raw_latency_population_excludes_reconnects(self):
        def request(connection, authorization, ssml, tracker, worker, sequence, output_format):
            self.assertEqual(output_format, load.RAW_FORMAT)
            return {
                "worker": worker, "sequence": sequence, "success": True, "status": 200,
                "first_byte_ms": 10, "total_ms": 100,
                "first_audio_sample_ms": 20 if sequence == 0 else 2000,
                "connection_reused": sequence == 0, "new_connections": int(sequence != 0),
            }, b""
        with patch.object(load, "HttpClient"), patch.object(load, "synthesize", request):
            summary, _ = load.run_stage("host", "token", b"ssml", 4, 2, 30, load.RAW_FORMAT)
        self.assertEqual(summary["first_audio_sample_ms"]["p95"], 20)


if __name__ == "__main__":
    unittest.main()
