import datetime
import os

import requests
from django.core.cache import cache
from django.shortcuts import render

from leagues.models import HomePage, MatchUp, Season


def home(request):
    # Filter matchups for the next 7 days
    today = datetime.date.today()
    next_week = today + datetime.timedelta(days=6)
    matchups = MatchUp.objects.filter(week__date__range=(today, next_week)).order_by(
        "time"
    )
    one_row = (
        MatchUp.objects.filter(week__date__range=(today, next_week))
        .select_related("week")
        .order_by("week__date")
        .distinct("week__date")
    )

    # Fetch weather data, cached for 30 minutes to avoid blocking the page on
    # every request. Cache key is per-day so it refreshes naturally at midnight.
    cache_key = f"weather_data_{today}"
    weather_data = cache.get(cache_key)

    if weather_data is None:
        weather_data = {}
        api_key = os.environ.get("OPENWEATHERMAP_API_KEY")

        if not api_key:
            print("Warning: OPENWEATHERMAP_API_KEY is not set.")
        else:
            forecast_url = "https://api.openweathermap.org/data/2.5/forecast"
            current_weather_url = "https://api.openweathermap.org/data/2.5/weather"

            try:
                forecast_params = {
                    "q": "Alexandria,VA,US",
                    "appid": api_key,
                    "units": "imperial",
                }
                forecast_response = requests.get(forecast_url, params=forecast_params)
                if forecast_response.status_code == 200:
                    forecast = forecast_response.json()
                    for row in one_row:
                        game_date = row.week.date.strftime("%Y-%m-%d")
                        total_rain_mm = 0
                        weather_found = False

                        for item in forecast["list"]:
                            if game_date in item["dt_txt"]:
                                rain_mm = item.get("rain", {}).get("3h", 0)
                                total_rain_mm += rain_mm
                                if game_date not in weather_data:
                                    weather_data[game_date] = {
                                        "temp": item["main"].get("temp", "N/A"),
                                        "wind_speed": item["wind"].get("speed", "N/A"),
                                        "description": item["weather"][0].get(
                                            "description", "N/A"
                                        ),
                                        "rain": total_rain_mm * 0.0393701,
                                    }
                                    weather_found = True
                                    break

                        if not weather_found and row.week.date == today:
                            current_params = {
                                "q": "Alexandria,VA,US",
                                "appid": api_key,
                                "units": "imperial",
                            }
                            current_response = requests.get(
                                current_weather_url, params=current_params
                            )
                            if current_response.status_code == 200:
                                current_weather = current_response.json()
                                weather_data[game_date] = {
                                    "temp": current_weather["main"].get("temp", "N/A"),
                                    "wind_speed": current_weather["wind"].get(
                                        "speed", "N/A"
                                    ),
                                    "description": current_weather["weather"][0].get(
                                        "description", "N/A"
                                    ),
                                    "rain": current_weather.get("rain", {}).get("1h", 0)
                                    * 0.0393701,
                                }

            except Exception as e:
                print(f"Error fetching weather data: {e}")

        cache.set(cache_key, weather_data, 60 * 30)  # cache for 30 minutes

    # Add weather data and other context variables
    context = {
        "weather_data": weather_data,
        "season": Season.objects.all(),
        "matchup": matchups,
        "one_row": one_row,
        "homepage": HomePage.objects.last(),
    }
    return render(request, "core/home.html", context=context)


def leagues(request):
    return render(request, "leagues/index.html")
