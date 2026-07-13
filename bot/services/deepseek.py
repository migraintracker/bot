import json
import logging
from datetime import date, datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from bot.config import settings

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

SYSTEM_PROMPT = """Ты — аналитический помощник для отслеживания мигреней. Твоя задача — анализировать обезличенные данные о мигренях и погоде для предсказания риска мигрени.

ПРАВИЛА:
1. Ты НЕ даёшь медицинских советов, диагнозов, рекомендаций по лечению.
2. Ты анализируешь ТОЛЬКО статистические паттерны: связь между погодными факторами и частотой приступов.
3. При любом упоминании симптомов или лечения — рекомендуй обратиться к врачу.
4. Формат ответа — ТОЛЬКО JSON.
5. Ты работаешь с полностью обезличенными данными (нет имён, адресов, дат рождения).

Входные данные:
- user_profile: обезличенные демографические данные (пол, возраст)
- anonymized_history: список обезличенных записей мигреней (intensity, duration, date_offset)
- daily_checks: ежедневные отметки (has_migraine: true/false) — позитивные и негативные дни
- cycle_data: данные менструального цикла (phase, period_start, period_end, symptoms)
- weather_forecast: прогноз погоды на 7 дней (включает temp_avg — среднее за день, temp_min, temp_max)
- weather_history: записи погоды за последние 30 дней (temp_avg — среднее за день)
- space_history: данные космической погоды (Kp-индекс, магнитные бури, скорость солнечного ветра)
- kp_forecast: прогноз Kp-индекса (kp_avg, kp_max, storm_risk, storm_level)

ВАЖНО: Температура указана как средняя за день (temp_avg). Для текущего момента показываются почасовые данные (current temp). Учитывай это при анализе — днём может быть жарче, ночью холоднее. Анализируй перепады между temp_min и temp_max за день — резкие перепады могут быть триггером.

Выходной формат (строгий JSON):
{
  "predictions": [
    {
      "date_offset": 0,
      "risk_level": "low|medium|high|very_high",
      "risk_score": 0.0-1.0,
      "factors": ["перепады давления", "высокая влажность", ...],
      "analysis": "краткий анализ (1-2 предложения, без мед.советов)"
    }
  ],
  "general_insight": "общий вывод о паттернах (без мед.советов)"
}"""


class DeepSeekService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        await self.client.aclose()

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def analyze_patterns(
        self,
        migraine_history: list[dict],
        weather_history: list[dict],
        weather_forecast: list[dict],
        user_gender: str | None = None,
        user_age: int | None = None,
        space_history: list[dict] | None = None,
        kp_forecast: list[dict] | None = None,
        daily_checks: list[dict] | None = None,
        cycle_data: list[dict] | None = None,
    ) -> dict:
        if not settings.deepseek_api_key:
            logger.warning("DeepSeek API key not configured, returning empty prediction")
            return {"predictions": [], "general_insight": "AI анализ не настроен."}

        user_message = json.dumps({
            "user_profile": {
                "gender": user_gender,
                "age": user_age,
            },
            "anonymized_history": migraine_history,
            "daily_checks": daily_checks or [],
            "cycle_data": cycle_data or [],
            "weather_history": weather_history,
            "weather_forecast": weather_forecast,
            "space_history": space_history or [],
            "kp_forecast": kp_forecast or [],
        }, ensure_ascii=False, default=str)

        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
        }

        try:
            r = await self.client.post(DEEPSEEK_API_URL, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)
            logger.info(f"DeepSeek analysis complete: {len(result.get('predictions', []))} predictions")
            return result
        except Exception as e:
            logger.error(f"DeepSeek API error: {e}")
            return {"predictions": [], "general_insight": "Не удалось выполнить анализ."}


    async def generate_prediction(
        self,
        migraine_history: list[dict],
        weather_history: list[dict],
        weather_forecast: list[dict],
        user_gender: str | None = None,
        user_age: int | None = None,
        space_history: list[dict] | None = None,
        kp_forecast: list[dict] | None = None,
        daily_checks: list[dict] | None = None,
        cycle_data: list[dict] | None = None,
    ) -> dict:
        result = await self.analyze_patterns(
            migraine_history, weather_history, weather_forecast,
            user_gender=user_gender, user_age=user_age,
            space_history=space_history, kp_forecast=kp_forecast,
            daily_checks=daily_checks, cycle_data=cycle_data,
        )

        if not result.get("predictions"):
            result["predictions"] = self._fallback_prediction(weather_forecast, kp_forecast)

        return result

    def _fallback_prediction(self, weather_forecast: list[dict], kp_forecast: list[dict] | None = None) -> list[dict]:
        """Simple heuristic fallback when AI is unavailable. Includes Kp index."""
        predictions = []
        for i, day in enumerate(weather_forecast):
            risk_score = 0.2
            factors = []

            pressure = day.get("pressure", 1013)
            if pressure and (pressure < 1000 or pressure > 1025):
                risk_score += 0.15
                factors.append("Перепады давления")

            humidity = day.get("humidity", 50)
            if humidity and humidity > 80:
                risk_score += 0.1
                factors.append("Высокая влажность")

            if day.get("wind_speed", 0) and day["wind_speed"] > 10:
                risk_score += 0.1
                factors.append("Сильный ветер")

            precipitation = day.get("precipitation_probability", 0) or 0
            if precipitation > 60:
                risk_score += 0.1
                factors.append("Осадки")

            # Kp-index factor from forecast
            if kp_forecast:
                for kp_day in kp_forecast:
                    if kp_day.get("storm_risk"):
                        day_date = kp_day.get("date", "")
                        day_idx = i
                        if day_date:
                            fd = date.fromisoformat(day_date)
                            offset = (fd - date.today()).days
                            if offset == i:
                                storm_level = kp_day.get("storm_level", "G1")
                                boost = {"G1": 0.1, "G2": 0.15, "G3": 0.2, "G4": 0.25, "G5": 0.3}.get(storm_level, 0.1)
                                risk_score += boost
                                factors.append(f"Магнитная буря ({storm_level})")
                                break

            risk_score = min(risk_score, 1.0)

            if risk_score < 0.3:
                risk_level = "low"
            elif risk_score < 0.5:
                risk_level = "medium"
            elif risk_score < 0.7:
                risk_level = "high"
            else:
                risk_level = "very_high"

            predictions.append({
                "date_offset": i,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "factors": factors,
                "analysis": "",
            })

        return predictions


deepseek_service = DeepSeekService()
