"""Offline checks for permitted origins and public assets."""

import unittest
import xml.etree.ElementTree as ET

from aiohttp.test_utils import TestClient, TestServer

from server import Settings, create_app, origin_allowed


class OriginTests(unittest.TestCase):
    def test_local_origin_is_allowed(self):
        self.assertTrue(origin_allowed("127.0.0.1:8080", "http",
                                       "http://127.0.0.1:8080"))

    def test_unconfigured_public_origin_is_rejected(self):
        self.assertFalse(origin_allowed("voice.example.com", "https",
                                        "https://voice.example.com"))

    def test_configured_public_origin_is_allowed(self):
        self.assertTrue(origin_allowed("voice.example.com", "http",
                                       "https://voice.example.com",
                                       "https://voice.example.com"))

    def test_mismatched_public_host_is_rejected(self):
        self.assertFalse(origin_allowed("attacker.example", "http",
                                        "https://voice.example.com",
                                        "https://voice.example.com"))


class AssetTests(unittest.IsolatedAsyncioTestCase):
    async def test_returned_cost_module_is_served_without_local_pricing(self):
        async with TestClient(TestServer(create_app(Settings("", "")))) as client:
            config = await (await client.get("/api/config")).json()
            self.assertNotIn("callPricing", config)
            module = await client.get("/call-cost.mjs")
            self.assertEqual(module.status, 200)
            self.assertIn("export function returnedCallCost", await module.text())
            self.assertEqual((await client.get("/call-prices.json")).status, 404)

    async def test_page_links_to_a_served_svg_favicon(self):
        async with TestClient(TestServer(create_app(Settings("", "")))) as client:
            page = await client.get("/")
            self.assertIn('<link rel="icon" type="image/svg+xml" href="/favicon.svg">', await page.text())
            icon = await client.get("/favicon.svg")
            self.assertEqual(icon.status, 200)
            self.assertEqual(icon.content_type, "image/svg+xml")
            svg = ET.fromstring(await icon.text())
            self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
            self.assertEqual(svg.attrib["viewBox"], "0 0 64 64")
            private_file = await client.get("/server.py")
            self.assertEqual(private_file.status, 404)


if __name__ == "__main__":
    unittest.main()
