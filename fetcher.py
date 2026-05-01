"""날씨 및 주식 데이터 fetch — 네트워크 I/O 전담.

주식: yfinance 대신 야후 파이낸스 chart API 직접 호출 (yfinance 1.3.0 의
curl_cffi 백엔드가 PyQt 스레드와 충돌해 access violation 일으키는 이슈 회피).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Optional

import requests


GEO_URL   = "https://geocoding-api.open-meteo.com/v1/search"
WX_URL    = "https://api.open-meteo.com/v1/forecast"
YF_URL    = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
UA_HEADER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

WEATHER_ICONS = {
    "sunny": "☀️", "clear": "☀️",
    "partly cloudy": "⛅", "cloudy": "☁️", "overcast": "☁️",
    "mist": "🌫️", "fog": "🌫️",
    "rain": "🌧️", "drizzle": "🌦️", "shower": "🌦️",
    "snow": "❄️", "sleet": "🌨️", "blizzard": "❄️",
    "thunder": "⛈️", "storm": "⛈️",
    "wind": "💨",
}

# WMO weather codes (Open-Meteo) → 영문 description (icons.py 매핑용)
_WMO_DESC = {
    0:  "clear",          1:  "partly cloudy",  2:  "partly cloudy",  3:  "cloudy",
    45: "fog",            48: "fog",
    51: "drizzle",        53: "drizzle",        55: "drizzle",
    56: "drizzle",        57: "drizzle",
    61: "rain",           63: "rain",           65: "rain",
    66: "rain",           67: "rain",
    71: "snow",           73: "snow",           75: "snow",  77: "snow",
    80: "shower",         81: "shower",         82: "shower",
    85: "snow",           86: "snow",
    95: "thunder",        96: "thunder",        99: "thunder",
}

# 도시 → (lat, lon, display_name) 캐시
_geo_cache: dict = {}


@dataclass
class HourlySlot:
    dt: datetime
    temp_c: float
    desc: str
    rain_pct: int


@dataclass
class WeatherData:
    city: str
    temp_c: float
    feels_like_c: float
    condition: str
    icon: str
    humidity: int
    wind_kmh: float
    temp_max_c: float = 0.0      # 오늘 최고
    temp_min_c: float = 0.0      # 오늘 최저
    rain_pct: int = 0            # 오늘 강수확률 최대치
    desc: str = ""
    hourly: list = field(default_factory=list)


@dataclass
class StockData:
    ticker: str
    name: str
    price: float
    change: float        # 절대값
    change_pct: float    # %
    currency: str = "USD"
    error: Optional[str] = None


def _condition_icon(desc: str) -> str:
    low = desc.lower()
    for keyword, icon in WEATHER_ICONS.items():
        if keyword in low:
            return icon
    return "🌡️"


def weather_mood(d: "WeatherData") -> str:
    """현재 날씨 데이터로부터 한국어 한 줄 코멘트 생성 (최소 7글자)."""
    cond  = (d.condition or "").lower()
    swing = d.temp_max_c - d.temp_min_c

    # 1순위: 위험·강수 조건
    if "thunder" in cond or "storm" in cond:
        return "천둥번개 치는 험한 날씨 ⚡"
    if "snow" in cond or "blizzard" in cond or "sleet" in cond:
        return "눈길 미끄러우니 조심하세요 ❄"
    if "rain" in cond or "shower" in cond or "drizzle" in cond:
        return "비가 와요, 우산 꼭 챙기세요 ☂"
    if d.rain_pct >= 70:
        return "비 올 가능성 높아요. 우산 챙기세요"
    if d.rain_pct >= 50:
        return "비 올 수 있으니 우산 챙기세요"
    if "fog" in cond or "mist" in cond:
        return "안개 짙어요, 운전 시 주의하세요"

    # 2순위: 극단 기온
    if d.temp_c >= 33:
        return "폭염주의보 수준, 야외활동 자제하세요"
    if d.temp_c >= 30:
        return "한낮 무더위, 수분 섭취 잊지 마세요"
    if d.temp_c <= -5:
        return "한파에요, 외출 시 단단히 입으세요"
    if d.temp_c <= 3:
        return "쌀쌀한 날씨, 따뜻하게 입으세요"

    # 3순위: 일교차
    if swing >= 12:
        return "일교차 큰 날, 겉옷 꼭 챙기세요"

    # 4순위: 강풍
    if d.wind_kmh >= 30:
        return "바람이 거세니 주의하세요"

    # 5순위: 쾌적도
    if "clear" in cond or "sunny" in cond:
        if 18 <= d.temp_c <= 25:
            return "피크닉 가기 딱 좋은 날씨 🌳"
        if 10 <= d.temp_c < 18:
            return "선선하고 햇살 좋은 하루"
        if 25 < d.temp_c < 30:
            return "맑지만 살짝 더운 하루"
        if d.temp_c < 10:
            return "맑지만 쌀쌀한 하루"
        return "구름 한 점 없는 화창한 날 ☀"
    if "partly cloudy" in cond:
        if 18 <= d.temp_c <= 25:
            return "구름 약간, 활동하기 좋은 날"
        if d.temp_c < 10:
            return "구름 사이로 햇살, 쌀쌀해요"
        return "구름 적당한 무난한 하루"
    if "cloudy" in cond or "overcast" in cond:
        if d.temp_c < 10:
            return "흐리고 쌀쌀한 하루"
        if d.temp_c > 25:
            return "흐리고 후텁지근한 하루"
        return "구름 가득한 흐린 하루"

    return "평범하고 무난한 하루입니다"


def _geocode(city: str) -> tuple:
    """도시명 → (lat, lon, display_name). 메모리 캐시."""
    if city in _geo_cache:
        return _geo_cache[city]
    resp = requests.get(GEO_URL,
                        params={"name": city, "count": 1, "language": "ko"},
                        timeout=10)
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        raise ValueError(f"도시를 찾을 수 없음: {city}")
    r = results[0]
    name_parts = [r.get("name", city)]
    if r.get("country") and r["country"] != name_parts[0]:
        name_parts.insert(0, r["country"])
    out = (float(r["latitude"]), float(r["longitude"]), ", ".join(name_parts))
    _geo_cache[city] = out
    return out


def fetch_weather(city: str) -> WeatherData:
    lat, lon, display = _geocode(city)

    params = {
        "latitude":  lat,
        "longitude": lon,
        "current":   "temperature_2m,relative_humidity_2m,apparent_temperature,"
                     "weather_code,wind_speed_10m",
        "hourly":    "temperature_2m,weather_code,precipitation_probability",
        "daily":     "temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max",
        "timezone":  "auto",
        "forecast_days": 2,
    }
    resp = requests.get(WX_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    cur = data["current"]
    cur_code = int(cur.get("weather_code", 0))
    desc = _WMO_DESC.get(cur_code, "clear")

    # 1시간 간격 hourly — 현재 시각 이후만, 5개
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    codes = hourly.get("weather_code", [])
    rains = hourly.get("precipitation_probability", [])
    now = datetime.now()
    slots: list = []
    for i, t_str in enumerate(times):
        try:
            dt = datetime.fromisoformat(t_str)
        except Exception:
            continue
        if dt <= now:
            continue
        slots.append(HourlySlot(
            dt=dt,
            temp_c=float(temps[i]) if i < len(temps) else 0.0,
            desc=_WMO_DESC.get(int(codes[i]) if i < len(codes) else 0, "clear"),
            rain_pct=int(rains[i]) if i < len(rains) and rains[i] is not None else 0,
        ))
        if len(slots) >= 5:
            break

    daily = data.get("daily", {})
    def _today(key, default=0):
        arr = daily.get(key, [])
        return arr[0] if arr else default

    return WeatherData(
        city=display,
        temp_c=float(cur["temperature_2m"]),
        feels_like_c=float(cur.get("apparent_temperature", cur["temperature_2m"])),
        condition=desc,
        icon=_condition_icon(desc),
        humidity=int(cur.get("relative_humidity_2m", 0)),
        wind_kmh=float(cur.get("wind_speed_10m", 0)),
        temp_max_c=float(_today("temperature_2m_max", cur["temperature_2m"])),
        temp_min_c=float(_today("temperature_2m_min", cur["temperature_2m"])),
        rain_pct=int(_today("precipitation_probability_max", 0) or 0),
        desc=desc,
        hourly=slots,
    )


def _fetch_one_stock(ticker: str) -> StockData:
    resp = requests.get(
        YF_URL.format(ticker=ticker),
        headers=UA_HEADER,
        params={"interval": "1d", "range": "5d"},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    chart = payload.get("chart", {})
    err = chart.get("error")
    if err:
        raise RuntimeError(err.get("description", str(err)))
    result = chart["result"][0]
    meta = result["meta"]
    price = float(meta.get("regularMarketPrice") or 0)
    prev  = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
    change = price - prev
    pct    = (change / prev * 100) if prev else 0.0
    currency = meta.get("currency", "USD") or "USD"
    return StockData(ticker, ticker, price, change, pct, currency)


def fetch_stocks(tickers: list) -> list:
    results: list = []
    for t in tickers:
        try:
            results.append(_fetch_one_stock(t))
        except Exception as e:
            results.append(StockData(t, t, 0, 0, 0, error=str(e)))
    return results
