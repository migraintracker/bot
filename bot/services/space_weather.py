import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

NOAA_KP_URL = "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json"
NOAA_SOLAR_WIND_URL = "https://services.swpc.noaa.gov/products/summary/solar-wind-mag-field.json"
NOAA_STORM_URL = "https://services.swpc.noaa.gov/products/alerts.json"


class SpaceWeatherService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0)

    async def close(self):
        await self.client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5))
    async def _fetch_json(self, url: str) -> list[dict] | dict | None:
        try:
            r = await self.client.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    async def get_kp_data(self) -> list[dict]:
        """Get planetary K-index data (last ~24h real-time + ~3d forecast)."""
        data = await self._fetch_json(NOAA_KP_URL)
        return data or []

    async def get_daily_kp_summary(self, target_date: date | None = None) -> dict | None:
        """Get Kp summary for a specific date using real-time data only."""
        kp_data = await self.get_kp_data()
        if not kp_data:
            return None

        target = target_date or date.today()

        kp_values = []
        for entry in kp_data:
            try:
                ts = datetime.fromisoformat(entry["time"].rstrip("Z")).replace(tzinfo=timezone.utc)
                if ts.date() == target and ts <= datetime.now(timezone.utc):
                    val = float(entry["kp_index"])
                    kp_values.append(val)
            except (KeyError, ValueError, TypeError):
                continue

        if not kp_values:
            return None

        return {
            "kp_index": sum(kp_values) / len(kp_values),
            "kp_max": max(kp_values),
            "kp_min": min(kp_values),
            "geomagnetic_storm": max(kp_values) >= 5,
            "storm_level": self._storm_level(max(kp_values)),
        }

    async def get_current_kp(self) -> dict | None:
        """Get the latest (most recent) Kp reading."""
        kp_data = await self.get_kp_data()
        if not kp_data:
            return None
        try:
            latest = kp_data[-1]
            ts = datetime.fromisoformat(latest["time"].rstrip("Z")).replace(tzinfo=timezone.utc)
            val = float(latest["kp_index"])
            return {
                "kp_current": val,
                "time": ts,
                "storm": val >= 5,
                "storm_level": self._storm_level(val),
            }
        except (KeyError, ValueError, TypeError, IndexError):
            return None

    def _storm_level(self, kp: float) -> str:
        if kp < 5:
            return "none"
        elif kp < 6:
            return "G1"
        elif kp < 7:
            return "G2"
        elif kp < 8:
            return "G3"
        elif kp < 9:
            return "G4"
        else:
            return "G5"

    async def get_solar_wind(self) -> dict | None:
        """Get current solar wind data."""
        data = await self._fetch_json(NOAA_SOLAR_WIND_URL)
        if not data:
            return None

        result = {}
        try:
            for line in data:
                if isinstance(line, list) and len(line) >= 3:
                    if line[0] == "Wind Speed":
                        result["solar_wind_speed"] = float(line[2]) if line[2] != "--" else None
                    elif line[0] == "Wind Dens":
                        result["solar_wind_density"] = float(line[2]) if line[2] != "--" else None
                    elif line[0] == "Bz":
                        result["bz_component"] = float(line[2]) if line[2] != "--" else None
        except (ValueError, TypeError, IndexError):
            pass

        return result if result else None

    async def get_today_summary(self) -> dict | None:
        """Get combined space weather data for today."""
        kp = await self.get_daily_kp_summary()
        wind = await self.get_solar_wind()
        alerts = await self.get_storm_alerts()

        if not kp:
            return None

        result = {
            "kp_index": kp["kp_index"],
            "kp_max": kp["kp_max"],
            "kp_min": kp["kp_min"],
            "geomagnetic_storm": kp["geomagnetic_storm"],
            "storm_level": kp["storm_level"],
        }
        if wind:
            result.update(wind)
        if alerts:
            result["alerts"] = alerts
            if not result["geomagnetic_storm"] and any(
                a.get("severity") in ("G3", "G4", "G5") for a in alerts
            ):
                result["geomagnetic_storm"] = True
        result["source"] = "noaa"
        return result

    async def get_storm_alerts(self) -> list[dict]:
        """Get current NOAA storm alerts."""
        data = await self._fetch_json(NOAA_STORM_URL)
        if not data:
            return []
        alerts = []
        for entry in data if isinstance(data, list) else []:
            try:
                alerts.append({
                    "type": entry.get("type", ""),
                    "severity": entry.get("severity", ""),
                    "issue_time": entry.get("issue_time", ""),
                    "message": entry.get("message", ""),
                })
            except Exception:
                continue
        return alerts

    async def get_kp_forecast(self) -> list[dict]:
        """Get Kp forecast for next few days. NOAA provides up to 3 days."""
        data = await self._fetch_json(NOAA_KP_URL)
        if not data:
            return []

        today = date.today()
        now = datetime.now(timezone.utc)
        forecast: dict[date, list[float]] = {}

        for entry in data:
            try:
                ts = datetime.fromisoformat(entry["time"].rstrip("Z")).replace(tzinfo=timezone.utc)
                entry_date = ts.date()
                if entry_date > today or (entry_date == today and ts > now):
                    val = float(entry["kp_index"])
                    forecast.setdefault(entry_date, []).append(val)
            except (KeyError, ValueError, TypeError):
                continue

        result = []
        for d in sorted(forecast.keys())[:7]:
            vals = forecast[d]
            result.append({
                "date": d.isoformat(),
                "kp_avg": sum(vals) / len(vals),
                "kp_max": max(vals),
                "kp_min": min(vals),
                "storm_risk": max(vals) >= 5,
                "storm_level": self._storm_level(max(vals)),
            })

        return result


space_weather_service = SpaceWeatherService()
