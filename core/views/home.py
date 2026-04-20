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

# Used for comparing and combining playability values
_PLAYABILITY_ORDER = {"good": 0, "uncertain": 1, "likely_cancelled": 2}


def _compute_playability(condition_id, pop, rain_mm, snow_mm):
    """
    Determine game playability from a single OWM forecast slot.
    Returns one of: "good" | "uncertain" | "likely_cancelled"

    OWM condition code ranges:
      2xx = Thunderstorm, 3xx = Drizzle, 5xx = Rain, 6xx = Snow
    """
    if 200 <= condition_id <= 699:
        return "likely_cancelled"
    if rain_mm > 0.1 or snow_mm > 0:
        return "likely_cancelled"
    if pop >= 0.30:
        return "uncertain"
    return "good"


def _worse_playability(a, b):
    """Return the more pessimistic of two playability values."""
    return a if _PLAYABILITY_ORDER[a] >= _PLAYABILITY_ORDER[b] else b


def _find_best_forecast_slot(forecast_list, game_date, game_time):
    """
    Return the forecast slot whose UTC timestamp is closest to game start.
    Used for display info (temp, description, pop_pct).
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


def _compute_window_playability(forecast_list, game_date, game_time):
    """
    Check every forecast slot from 4 hours before game time through 1 hour
    after and return the worst playability found.

    A 4-hour pre-game window catches rain that would leave the rink wet by
    game time even if the forecast at the exact game hour looks clear.

    Returns None if no forecast slots fall within the window (e.g. game is
    beyond the 5-day forecast horizon).
    """
    if game_time is not None:
        target_local = datetime.datetime.combine(game_date, game_time).replace(
            tzinfo=_EASTERN
        )
    else:
        target_local = datetime.datetime.combine(
            game_date, datetime.time(19, 0)
        ).replace(tzinfo=_EASTERN)

    target_utc = target_local.astimezone(datetime.timezone.utc)

    worst = None
    for item in forecast_list:
        slot_dt = datetime.datetime.strptime(
            item["dt_txt"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=datetime.timezone.utc)
        diff_seconds = (slot_dt - target_utc).total_seconds()
        # Window: 4 h before game through 1 h after
        if -4 * 3600 <= diff_seconds <= 3600:
            cond_id = item["weather"][0]["id"]
            pop = item.get("pop", 0)
            rain = item.get("rain", {}).get("3h", 0)
            snow = item.get("snow", {}).get("3h", 0)
            p = _compute_playability(cond_id, pop, rain, snow)
            worst = p if worst is None else _worse_playability(worst, p)

    return worst


def _playability_from_current_weather(current_w):
    """
    Assess current on-the-ground conditions for today's games.

    Checks whether it is actively precipitating or has rained/snowed in the
    last 1–3 hours (OWM 'rain.1h' / 'rain.3h' fields).  Recent rain leaves
    the rink wet even after the sky clears, so this is factored in alongside
    the forward forecast.
    """
    cond_id = current_w["weather"][0]["id"]
    rain_1h = current_w.get("rain", {}).get("1h", 0)
    snow_1h = current_w.get("snow", {}).get("1h", 0)
    rain_3h = current_w.get("rain", {}).get("3h", 0)

    # Currently precipitating — rink is actively getting wet
    if 200 <= cond_id <= 699:
        return "likely_cancelled"

    # Rained or snowed in the past hour — rink is likely still wet
    if rain_1h > 0.1 or snow_1h > 0:
        return "uncertain"

    # Meaningful rain in the past 3 hours — rink may still be damp
    if rain_3h > 0.5:
        return "uncertain"

    return "good"


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

        # Always fetch current conditions when today has games — needed to
        # detect rain that fell in the last 1–3 hours even if the forecast
        # at game time now looks clear.
        current_w = None
        if today in game_times:
            current_response = requests.get(
                current_weather_url,
                params={"q": "Alexandria,VA,US", "appid": api_key, "units": "imperial"},
                timeout=10,
            )
            if current_response.status_code == 200:
                current_w = current_response.json()

        if forecast_response.status_code == 200:
            forecast_list = forecast_response.json()["list"]

            for game_date, game_time in game_times.items():
                game_date_str = game_date.strftime("%Y-%m-%d")

                # Display info uses the slot closest to game time.
                display_slot = _find_best_forecast_slot(
                    forecast_list, game_date, game_time
                )

                # Playability uses the worst condition in the pre-game window.
                window_play = _compute_window_playability(
                    forecast_list, game_date, game_time
                )

                # Fall back to single-slot assessment if no window data
                # (game is beyond the 5-day forecast or no matching slots).
                if window_play is None and display_slot:
                    cond_id = display_slot["weather"][0]["id"]
                    pop = display_slot.get("pop", 0)
                    rain_mm = display_slot.get("rain", {}).get("3h", 0)
                    snow_mm = display_slot.get("snow", {}).get("3h", 0)
                    window_play = _compute_playability(cond_id, pop, rain_mm, snow_mm)

                # For today, combine forecast with current on-the-ground conditions.
                if game_date == today and current_w:
                    current_play = _playability_from_current_weather(current_w)
                    final_play = _worse_playability(window_play or "good", current_play)
                    # Use current weather for display if no forecast slot
                    if not display_slot:
                        display_slot = {
                            "main": current_w["main"],
                            "weather": current_w["weather"],
                        }
                else:
                    final_play = window_play or "good"

                if display_slot:
                    pop = display_slot.get("pop")
                    rain_mm = display_slot.get("rain", {}).get("3h", 0)
                    snow_mm = display_slot.get("snow", {}).get("3h", 0)

                    weather_data[game_date_str] = {
                        "temp": display_slot["main"].get("temp", "N/A"),
                        "description": display_slot["weather"][0].get(
                            "description", "N/A"
                        ),
                        "pop_pct": round(pop * 100) if pop is not None else None,
                        "rain": rain_mm * 0.0393701,
                        "snow": snow_mm * 0.0393701,
                        "humidity": display_slot["main"].get("humidity"),
                        "playability": final_play,
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
