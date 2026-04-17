import datetime
import os
import threading

import requests
from django.core.cache import cache
from django.shortcuts import render

from leagues.models import HomePage, MatchUp

# Short TTL for the "fetch in progress" placeholder so that if the background
# thread fails (network error, bad API key, etc.) the next request after one
# minute will retry rather than serving empty weather for 30 minutes.
_WEATHER_PLACEHOLDER_TTL = 60  # seconds
_WEATHER_FULL_TTL = 60 * 30  # 30 minutes


def _fetch_and_cache_weather(cache_key, api_key, game_dates):
    """
    Fetch weather from OpenWeatherMap and write real data into the cache.
    Always runs in a background daemon thread — never called on the hot path.
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
            forecast = forecast_response.json()
            for game_date in game_dates:
                game_date_str = game_date.strftime("%Y-%m-%d")
                total_rain_mm = 0
                weather_found = False

                for item in forecast["list"]:
                    if game_date_str in item["dt_txt"]:
                        rain_mm = item.get("rain", {}).get("3h", 0)
                        total_rain_mm += rain_mm
                        if game_date_str not in weather_data:
                            weather_data[game_date_str] = {
                                "temp": item["main"].get("temp", "N/A"),
                                "wind_speed": item["wind"].get("speed", "N/A"),
                                "description": item["weather"][0].get(
                                    "description", "N/A"
                                ),
                                "rain": total_rain_mm * 0.0393701,
                            }
                            weather_found = True
                            break

                if not weather_found and game_date == today:
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
                        current_weather = current_response.json()
                        weather_data[game_date_str] = {
                            "temp": current_weather["main"].get("temp", "N/A"),
                            "wind_speed": current_weather["wind"].get("speed", "N/A"),
                            "description": current_weather["weather"][0].get(
                                "description", "N/A"
                            ),
                            "rain": current_weather.get("rain", {}).get("1h", 0)
                            * 0.0393701,
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
            game_dates = [row.week.date for row in one_row]
            threading.Thread(
                target=_fetch_and_cache_weather,
                args=(cache_key, api_key, game_dates),
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
