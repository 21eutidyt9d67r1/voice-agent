"""Weather assets must be served under the application's actual CSP."""

import unittest

from aiohttp.test_utils import TestClient, TestServer
from server import Settings, create_app


class WeatherAssetsTests(unittest.IsolatedAsyncioTestCase):
    async def test_weather_module_and_csp(self):
        async with TestClient(TestServer(create_app(Settings(endpoint="", agent="")))) as client:
            response = await client.get("/weather.mjs")
            self.assertEqual(response.status, 200)
            self.assertIn("javascript", response.content_type)
            self.assertIn(
                "connect-src 'self' https://api.open-meteo.com;",
                response.headers["Content-Security-Policy"],
            )
            self.assertIn("export function parseWeather", await response.text())
            response = await client.get("/city-scenes.mjs")
            self.assertEqual(response.status, 200)
            self.assertIn("javascript", response.content_type)
            self.assertIn("export function drawCityScene", await response.text())
            response = await client.get("/city-nature.mjs")
            self.assertEqual(response.status, 200)
            self.assertIn("javascript", response.content_type)
            self.assertIn("export function cityNature", await response.text())
            response = await client.get("/")
            html = await response.text()
            self.assertIn('id="weather-scene"', html)
            self.assertIn('label for="scene-city"', html)
            for city in ("seattle", "mumbai", "tokyo", "paris", "beijing", "new-york"):
                self.assertIn(f'<option value="{city}">', html)


if __name__ == "__main__":
    unittest.main()
