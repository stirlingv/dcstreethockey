import datetime
import os
import threading
from zoneinfo import ZoneInfo

import requests
from django.core.cache import cache
from django.shortcuts import render

from leagues.models import HomePage, MatchUp

# Short TTL for the "fetch in progress" placeholder so that if the background
# thread fails (network error, bad API key, etc.) the next request after one
# minute will retry rather than serving empty weather for 30 minutes.
_WEATHER_PLACEHOLDER_TTL = 60  # seconds
_WEATHER_FULL_TTL = 60 * 30  # 30 minutes

_EASTERN = ZoneInfo("America/New_York")


def _compute_playability(condition_id, pop, rain_mm, snow_mm):
    """
    Determine game playability from OpenWeatherMap forecast data.

    Games are cancelled for rain, snow, or active rink condensation.
    Returns one of: "good" | "uncertain" | "likely_cancelled"

    OWM condition code ranges:
      2xx = Thunderstorm, 3xx = Drizzle, 5xx = Rain, 6xx = Snow
    """
    # Any active precipitation condition code → cancellation likely
    if 200 <= condition_id <= 699:
        return "likely_cancelled"
    # Measurable rain or snow in the forecast window
    if rain_mm > 0.1 or snow_mm > 0:
        return "likely_cancelled"
    # 30%+ probability of precipitation → watch closely
    if pop >= 0.30:
        return "uncertain"
    return "good"


def _find_best_forecast_slot(forecast_list, game_date, game_time):
    """
    Return the forecast slot (dict) whose timestamp is closest to game start.

    game_time is a datetime.time in local (Eastern) time, or None to default
    to 7:00 PM Eastern.
    """
    if not forecast_list:
        return None

    if game_time is not None:
        target_local = datetime.datetime.combine(game_date, game_time).replace(
            tzinfo=_EASTERN
        )
    else:
        target_local = datetime.datetime.combine(
            game_date, datetime.time(19, 0)
        ).replace(tzinfo=_EASTERN)

    target_utc = target_local.astimezone(datetime.timezone.utc)

    best_slot = None
    best_diff = None
    for item in forecast_list:
        slot_dt = datetime.datetime.strptime(
            item["dt_txt"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=datetime.timezone.utc)
        diff = abs((slot_dt - target_utc).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_slot = item

    return best_slot


def _fetch_and_cache_weather(cache_key, api_key, game_times):
    """
    Fetch weather from OpenWeatherMap and write real data into the cache.
    Always runs in a background daemon thread — never called on the hot path.

    game_times: dict mapping datetime.date -> datetime.time (or None) for the
    earliest game on that date, used to select the right forecast window.
    """
    today = datetime.date.today()
    weather_data = {}
    forecast_url = "https://api.openweathermap.org/data/2.5/forecast"
    current_weather_url = "https://api.openweathermap.org/data/2.5/weather"

    try:
        forecast_response = requests.get(
            forecast_url,
            params={"q": "Alexandria,VA,US", "appid": api_key, "units": "imperial"},
            timeout=10,
        )
        if forecast_response.status_code == 200:
            forecast_list = forecast_response.json()["list"]

            for game_date, game_time in game_times.items():
                game_date_str = game_date.strftime("%Y-%m-%d")

                slot = _find_best_forecast_slot(forecast_list, game_date, game_time)

                if slot:
                    condition_id = slot["weather"][0]["id"]
                    pop = slot.get("pop", 0)
                    rain_mm = slot.get("rain", {}).get("3h", 0)
                    snow_mm = slot.get("snow", {}).get("3h", 0)

                    weather_data[game_date_str] = {
                        "temp": slot["main"].get("temp", "N/A"),
                        "description": slot["weather"][0].get("description", "N/A"),
                        "pop_pct": round(pop * 100),
                        "rain": rain_mm * 0.0393701,
                        "snow": snow_mm * 0.0393701,
                        "humidity": slot["main"].get("humidity"),
                        "playability": _compute_playability(
                            condition_id, pop, rain_mm, snow_mm
                        ),
                    }
                elif game_date == today:
                    # Forecast doesn't reach today — fall back to current conditions.
                    current_response = requests.get(
                        current_weather_url,
                        params={
                            "q": "Alexandria,VA,US",
                            "appid": api_key,
                            "units": "imperial",
                        },
                        timeout=10,
                    )
                    if current_response.status_code == 200:
                        w = current_response.json()
                        condition_id = w["weather"][0]["id"]
                        rain_mm = w.get("rain", {}).get("1h", 0)
                        snow_mm = w.get("snow", {}).get("1h", 0)

                        weather_data[game_date_str] = {
                            "temp": w["main"].get("temp", "N/A"),
                            "description": w["weather"][0].get("description", "N/A"),
                            "pop_pct": None,
                            "rain": rain_mm * 0.0393701,
                            "snow": snow_mm * 0.0393701,
                            "humidity": w["main"].get("humidity"),
                            "playability": _compute_playability(
                                condition_id, 0, rain_mm, snow_mm
                            ),
                        }
    except Exception as e:
        print(f"Error fetching weather data: {e}")

    # Overwrite the short-TTL placeholder with real data (or empty dict on error).
    cache.set(cache_key, weather_data, _WEATHER_FULL_TTL)


def home(request):
    today = datetime.date.today()
    next_week = today + datetime.timedelta(days=6)

    # select_related eliminates per-matchup FK queries in the template.
    matchups = (
        MatchUp.objects.filter(week__date__range=(today, next_week))
        .select_related("week", "hometeam", "awayteam")
        .order_by("time")
    )
    # Evaluate once so the queryset isn't re-hit when we extract game_dates
    # and again when the template iterates it.
    one_row = list(
        MatchUp.objects.filter(week__date__range=(today, next_week))
        .select_related("week")
        .order_by("week__date")
        .distinct("week__date")
    )

    cache_key = f"weather_data_{today}"
    weather_data = cache.get(cache_key)

    if weather_data is None:
        # Serve the page immediately with no weather data.  A background thread
        # fetches real data and overwrites the cache; the next page load will
        # have weather.  A short placeholder TTL ensures we retry quickly if the
        # thread fails.
        weather_data = {}
        cache.set(cache_key, weather_data, _WEATHER_PLACEHOLDER_TTL)
        api_key = os.environ.get("OPENWEATHERMAP_API_KEY")
        if api_key:
            # Use the game time from one_row as the target forecast time so we
            # look at the weather window closest to when players are actually
            # on the rink.
            game_times = {row.week.date: row.time for row in one_row}
            threading.Thread(
                target=_fetch_and_cache_weather,
                args=(cache_key, api_key, game_times),
                daemon=True,
            ).start()

    context = {
        "weather_data": weather_data,
        "matchup": matchups,
        "one_row": one_row,
        "homepage": HomePage.objects.last(),
    }
    return render(request, "core/home.html", context=context)


def leagues(request):
    return render(request, "leagues/index.html")
