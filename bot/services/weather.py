import logging
from datetime import date, datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from bot.config import settings

logger = logging.getLogger(__name__)


class WeatherService:
    OWM_BASE = "https://api.openweathermap.org/data/3.0/onecall"
    OWM_GEO_BASE = "https://api.openweathermap.org/geo/1.0/direct"
    WA_BASE = "https://api.weatherapi.com/v1"
    OM_BASE = "https://api.open-meteo.com/v1/forecast"
    OM_GEO_BASE = "https://geocoding-api.open-meteo.com/v1/search"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0)

    async def get_current_weather(self, lat: float, lon: float) -> dict | None:
        """Get current (hourly) weather data from Open-Meteo."""
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index",
            "timezone": "auto",
        }
        try:
            r = await self.client.get(self.OM_BASE, params=params)
            r.raise_for_status()
            data = r.json().get("current", {})
            if not data:
                return None
            return {
                "temp_current": data.get("temperature_2m"),
                "feels_like": data.get("apparent_temperature"),
                "humidity": data.get("relative_humidity_2m"),
                "pressure": data.get("pressure_msl"),
                "wind_speed": data.get("wind_speed_10m"),
                "wind_gust": data.get("wind_gusts_10m"),
                "wind_direction": data.get("wind_direction_10m"),
                "cloudiness": data.get("cloud_cover"),
                "weather_code": data.get("weather_code"),
                "precipitation_mm": data.get("precipitation"),
                "uv_index": data.get("uv_index"),
                "source": "openmeteo_current",
            }
        except Exception as e:
            logger.warning(f"Open-Meteo current failed for ({lat},{lon}): {e}")
        return None

    async def close(self):
        await self.client.aclose()

    async def _get_coordinates(self, city: str) -> tuple[float, float] | None:
        # Open-Meteo geocoding (free, no key)
        try:
            params = {"name": city, "count": 1, "language": "ru", "format": "json"}
            r = await self.client.get(self.OM_GEO_BASE, params=params)
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            if results:
                return float(results[0]["latitude"]), float(results[0]["longitude"])
        except Exception as e:
            logger.warning(f"Open-Meteo geocoding failed for {city}: {e}")

        # OWM geocoding fallback
        if settings.openweathermap_api_key:
            try:
                params = {"q": city, "limit": 1, "appid": settings.openweathermap_api_key}
                r = await self.client.get(self.OWM_GEO_BASE, params=params)
                r.raise_for_status()
                data = r.json()
                if data:
                    return float(data[0]["lat"]), float(data[0]["lon"])
            except Exception as e:
                logger.warning(f"OWM geocoding failed for {city}: {e}")

        return None

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def get_weather_owm(self, lat: float, lon: float, target_date: date | None = None) -> dict | None:
        if not settings.openweathermap_api_key:
            return None

        params = {
            "lat": lat,
            "lon": lon,
            "appid": settings.openweathermap_api_key,
            "units": "metric",
            "exclude": "minutely,hourly,alerts",
        }

        try:
            r = await self.client.get(self.OWM_BASE, params=params)
            r.raise_for_status()
            data = r.json()

            daily = data.get("daily", [])
            if not daily:
                return None

            if target_date:
                target_days = (target_date - date.today()).days
                if 0 <= target_days < len(daily):
                    day_data = daily[target_days]
                else:
                    day_data = daily[0]
            else:
                day_data = daily[0]

            return {
                "temp_min": day_data.get("temp", {}).get("min"),
                "temp_max": day_data.get("temp", {}).get("max"),
                "temp_avg": day_data.get("temp", {}).get("day"),
                "feels_like": day_data.get("feels_like", {}).get("day"),
                "pressure": day_data.get("pressure"),
                "humidity": day_data.get("humidity"),
                "wind_speed": day_data.get("wind_speed"),
                "wind_gust": day_data.get("wind_gust"),
                "wind_direction": day_data.get("wind_deg"),
                "cloudiness": day_data.get("clouds"),
                "weather_condition": day_data.get("weather", [{}])[0].get("description"),
                "weather_code": day_data.get("weather", [{}])[0].get("id"),
                "visibility": day_data.get("visibility"),
                "uv_index": day_data.get("uvi"),
                "precipitation_mm": day_data.get("rain") or day_data.get("snow"),
                "precipitation_probability": int(day_data.get("pop", 0) * 100) if day_data.get("pop") else None,
                "source": "openweathermap",
            }
        except Exception as e:
            logger.warning(f"OpenWeatherMap failed for ({lat},{lon}): {e}")
            return None

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def get_weather_wa(self, city: str, target_date: date | None = None) -> dict | None:
        if not settings.weatherapi_key:
            return None

        try:
            if target_date:
                params = {
                    "key": settings.weatherapi_key,
                    "q": city,
                    "dt": target_date.isoformat(),
                }
                r = await self.client.get(f"{self.WA_BASE}/history.json", params=params)
            else:
                params = {
                    "key": settings.weatherapi_key,
                    "q": city,
                    "days": 1,
                    "aqi": "no",
                }
                r = await self.client.get(f"{self.WA_BASE}/forecast.json", params=params)

            r.raise_for_status()
            data = r.json()

            if target_date:
                day_data = data.get("forecast", {}).get("forecastday", [{}])[0].get("day", {})
            else:
                day_data = data.get("forecast", {}).get("forecastday", [{}])[0].get("day", {})

            if not day_data:
                return None

            return {
                "temp_min": day_data.get("mintemp_c"),
                "temp_max": day_data.get("maxtemp_c"),
                "temp_avg": day_data.get("avgtemp_c"),
                "feels_like": day_data.get("avgtemp_c"),
                "pressure": day_data.get("pressure_mb") or (float(day_data.get("pressure_in", 0)) * 33.8639 if day_data.get("pressure_in") else None),
                "humidity": day_data.get("avghumidity"),
                "wind_speed": float(day_data.get("maxwind_kph", 0)) / 3.6 if day_data.get("maxwind_kph") else None,
                "wind_gust": None,
                "wind_direction": None,
                "cloudiness": None,
                "weather_condition": day_data.get("condition", {}).get("text"),
                "weather_code": day_data.get("condition", {}).get("code"),
                "visibility": float(day_data.get("avgvis_km", 0)) * 1000 if day_data.get("avgvis_km") else None,
                "uv_index": day_data.get("uv"),
                "precipitation_mm": day_data.get("totalprecip_mm"),
                "precipitation_probability": day_data.get("daily_chance_of_rain"),
                "source": "weatherapi",
            }
        except Exception as e:
            logger.warning(f"WeatherAPI failed for {city}: {e}")
            return None

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def get_weather_om(self, lat: float, lon: float, target_date: date | None = None) -> dict | None:
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": (
                "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
                "apparent_temperature_max,pressure_msl_hPa,"
                "wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,"
                "precipitation_sum,precipitation_probability_max,"
                "relative_humidity_2m,uv_index_max,cloud_cover_mean"
            ),
            "timezone": "auto",
            "forecast_days": 1,
        }
        if target_date:
            params["start_date"] = target_date.isoformat()
            params["end_date"] = target_date.isoformat()

        try:
            r = await self.client.get(self.OM_BASE, params=params)
            r.raise_for_status()
            data = r.json()
            daily = data.get("daily", {})
            if not daily:
                return None
            return {
                "temp_min": _first(daily, "temperature_2m_min"),
                "temp_max": _first(daily, "temperature_2m_max"),
                "temp_avg": _first(daily, "temperature_2m_mean"),
                "feels_like": _first(daily, "apparent_temperature_max"),
                "pressure": _first(daily, "pressure_msl_hPa"),
                "humidity": _first(daily, "relative_humidity_2m"),
                "wind_speed": _first(daily, "wind_speed_10m_max"),
                "wind_gust": _first(daily, "wind_gusts_10m_max"),
                "wind_direction": _first(daily, "wind_direction_10m_dominant"),
                "cloudiness": _first(daily, "cloud_cover_mean"),
                "weather_condition": None,
                "weather_code": None,
                "visibility": None,
                "uv_index": _first(daily, "uv_index_max"),
                "precipitation_mm": _first(daily, "precipitation_sum"),
                "precipitation_probability": _first(daily, "precipitation_probability_max"),
                "source": "openmeteo",
            }
        except Exception as e:
            logger.warning(f"Open-Meteo failed for ({lat},{lon}): {e}")
            return None

    async def get_daily_weather(self, city: str, lat: float, lon: float, target_date: date | None = None) -> dict | None:
        result = await self.get_weather_om(lat, lon, target_date)
        if result:
            return result

        result = await self.get_weather_wa(city, target_date)
        if result:
            return result

        result = await self.get_weather_owm(lat, lon, target_date)
        if result:
            return result

        logger.error(f"All weather sources failed for {city} ({lat},{lon})")
        return None

    async def get_forecast(self, lat: float, lon: float, days: int = 7) -> list[dict]:
        result = await self._get_forecast_om(lat, lon, days)
        if result:
            return result
        result = await self._get_forecast_wa(lat, lon, days)
        if result:
            return result
        return await self._get_forecast_owm(lat, lon, days)

    async def _get_forecast_om(self, lat: float, lon: float, days: int = 7) -> list[dict]:
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": (
                "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
                "pressure_msl_hPa,precipitation_sum,precipitation_probability_max,"
                "wind_speed_10m_max,relative_humidity_2m,uv_index_max,"
                "weather_code,cloud_cover_mean"
            ),
            "timezone": "auto",
            "forecast_days": min(days, 16),
        }
        try:
            r = await self.client.get(self.OM_BASE, params=params)
            r.raise_for_status()
            data = r.json()
            daily = data.get("daily", {})
            forecasts = []
            count = len(daily.get("time", []))
            for i in range(min(count, days)):
                forecasts.append({
                    "temp_min": _at(daily, "temperature_2m_min", i),
                    "temp_max": _at(daily, "temperature_2m_max", i),
                    "temp_avg": _at(daily, "temperature_2m_mean", i),
                    "pressure": _at(daily, "pressure_msl_hPa", i),
                    "humidity": _at(daily, "relative_humidity_2m", i),
                    "wind_speed": _at(daily, "wind_speed_10m_max", i),
                    "cloudiness": _at(daily, "cloud_cover_mean", i),
                    "weather_condition": None,
                    "weather_code": _at(daily, "weather_code", i),
                    "uv_index": _at(daily, "uv_index_max", i),
                    "precipitation_mm": _at(daily, "precipitation_sum", i),
                    "precipitation_probability": _at(daily, "precipitation_probability_max", i),
                })
            return forecasts
        except Exception as e:
            logger.error(f"Open-Meteo forecast failed: {e}")
            return []

    async def _get_forecast_wa(self, lat: float, lon: float, days: int = 7) -> list[dict]:
        if not settings.weatherapi_key:
            return []

        params = {
            "key": settings.weatherapi_key,
            "q": f"{lat},{lon}",
            "days": min(days, 3),
            "aqi": "no",
        }
        try:
            r = await self.client.get(f"{self.WA_BASE}/forecast.json", params=params)
            r.raise_for_status()
            data = r.json()
            forecasts = []
            for day_data in data.get("forecast", {}).get("forecastday", [])[:days]:
                d = day_data.get("day", {})
                forecasts.append({
                    "temp_min": d.get("mintemp_c"),
                    "temp_max": d.get("maxtemp_c"),
                    "temp_avg": d.get("avgtemp_c"),
                    "pressure": d.get("pressure_mb"),
                    "humidity": d.get("avghumidity"),
                    "wind_speed": float(d.get("maxwind_kph", 0)) / 3.6 if d.get("maxwind_kph") else None,
                    "cloudiness": None,
                    "weather_condition": d.get("condition", {}).get("text"),
                    "weather_code": d.get("condition", {}).get("code"),
                    "uv_index": d.get("uv"),
                    "precipitation_mm": d.get("totalprecip_mm"),
                    "precipitation_probability": d.get("daily_chance_of_rain"),
                })
            return forecasts[:days]
        except Exception as e:
            logger.error(f"WeatherAPI forecast failed: {e}")
            return []

    async def _get_forecast_owm(self, lat: float, lon: float, days: int = 7) -> list[dict]:
        if not settings.openweathermap_api_key:
            return []

        params = {
            "lat": lat,
            "lon": lon,
            "appid": settings.openweathermap_api_key,
            "units": "metric",
            "exclude": "current,minutely,hourly,alerts",
        }
        try:
            r = await self.client.get(self.OWM_BASE, params=params)
            r.raise_for_status()
            data = r.json()
            forecasts = []
            for day_data in data.get("daily", [])[:days]:
                forecasts.append({
                    "temp_min": day_data.get("temp", {}).get("min"),
                    "temp_max": day_data.get("temp", {}).get("max"),
                    "temp_avg": day_data.get("temp", {}).get("day"),
                    "pressure": day_data.get("pressure"),
                    "humidity": day_data.get("humidity"),
                    "wind_speed": day_data.get("wind_speed"),
                    "cloudiness": day_data.get("clouds"),
                    "weather_condition": day_data.get("weather", [{}])[0].get("description"),
                    "weather_code": day_data.get("weather", [{}])[0].get("id"),
                    "uv_index": day_data.get("uvi"),
                    "precipitation_mm": day_data.get("rain") or day_data.get("snow"),
                    "precipitation_probability": int(day_data.get("pop", 0) * 100) if day_data.get("pop") else None,
                })
            return forecasts
        except Exception as e:
            logger.error(f"OWM forecast failed: {e}")
            return []

    async def resolve_city(self, city: str) -> tuple[float, float] | None:
        return await self._get_coordinates(city)

    async def resolve_timezone(self, lat: float, lon: float) -> int | None:
        """Get UTC offset in hours from Open-Meteo forecast API."""
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max",
                "timezone": "auto",
                "forecast_days": 1,
            }
            r = await self.client.get(self.OM_BASE, params=params)
            r.raise_for_status()
            data = r.json()
            tz_abbr = data.get("timezone_abbreviation", "")
            offset_str = data.get("utc_offset_seconds", 0)
            return int(offset_str) // 3600
        except Exception:
            return None


def _first(data: dict, key: str):
    vals = data.get(key)
    return vals[0] if vals else None


def _at(data: dict, key: str, idx: int):
    vals = data.get(key)
    return vals[idx] if vals and idx < len(vals) else None


weather_service = WeatherService()
