import datetime
import os
from zoneinfo import ZoneInfo

import requests
from django.core.cache import cache
from django.shortcuts import render

from leagues.models import HomePage, MatchUp

_WEATHER_FULL_TTL = 60 * 30  # 30 minutes
_WEATHER_ERROR_TTL = 60 * 5  # retry after 5 minutes on API failure
_WEATHER_FETCH_TIMEOUT = 8  # seconds — NWS can be slightly slower than commercial APIs

_EASTERN = ZoneInfo("America/New_York")

# NWS grid coordinates for Alexandria, VA (LWX office, never changes).
# Derived from: GET https://api.weather.gov/points/38.8048,-77.0469
_NWS_HOURLY_URL = "https://api.weather.gov/gridpoints/LWX/97,67/forecast/hourly"
_NWS_HEADERS = {
    "User-Agent": "dcstreethockey.com (weather forecast for game planning)",
    "Accept": "application/geo+json",
}

# Sentinel stored in cache when the API fetch fails so we don't hammer it.
_WEATHER_FETCH_FAILED = {"_failed": True}

# Used for comparing and combining playability values
_PLAYABILITY_ORDER = {"good": 0, "uncertain": 1, "likely_cancelled": 2}


def _compute_playability(pop_pct, short_forecast):
    """
    Determine game playability from a single NWS hourly forecast period.
    Returns one of: "good" | "uncertain" | "likely_cancelled"

    pop_pct: 0–100 integer or None (NWS probabilityOfPrecipitation.value)
    short_forecast: NWS shortForecast string, e.g. "Chance Rain Showers"

    NWS qualifying language maps to PoP ranges:
      "Slight Chance" = 10–20 %   "Chance" = 30–50 %
      "Likely"        = 60–70 %   no qualifier = > 70 %
    """
    short = short_forecast.lower()
    pop = pop_pct or 0

    # Thunderstorms — dangerous regardless of probability
    if "thunder" in short:
        return "likely_cancelled"

    # More likely to precipitate than not (>= 50 % or NWS "Likely" qualifier)
    if pop >= 50 or "likely" in short:
        return "likely_cancelled"

    # Moderate chance or any precipitation keyword in the forecast text
    precip_keywords = ("rain", "shower", "snow", "sleet", "drizzle", "flurr", "hail")
    if pop >= 20 or any(k in short for k in precip_keywords):
        return "uncertain"

    return "good"


def _worse_playability(a, b):
    """Return the more pessimistic of two playability values."""
    return a if _PLAYABILITY_ORDER[a] >= _PLAYABILITY_ORDER[b] else b


def _find_best_forecast_slot(periods, game_date, game_time):
    """
    Return the NWS hourly period whose start time is closest to game start.
    Used for display info (temp, description, pop_pct).
    """
    if not periods:
        return None

    if game_time is not None:
        target_dt = datetime.datetime.combine(game_date, game_time).replace(
            tzinfo=_EASTERN
        )
    else:
        target_dt = datetime.datetime.combine(game_date, datetime.time(19, 0)).replace(
            tzinfo=_EASTERN
        )

    best_period = None
    best_diff = None
    for period in periods:
        start = datetime.datetime.fromisoformat(period["startTime"])
        diff = abs((start - target_dt).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_period = period

    return best_period


def _compute_window_max_pop(periods, game_date, game_time):
    """Return the highest precipitation probability across the pre-game window, or None."""
    if game_time is not None:
        target_dt = datetime.datetime.combine(game_date, game_time).replace(
            tzinfo=_EASTERN
        )
    else:
        target_dt = datetime.datetime.combine(game_date, datetime.time(19, 0)).replace(
            tzinfo=_EASTERN
        )

    max_pop = None
    for period in periods:
        start = datetime.datetime.fromisoformat(period["startTime"])
        diff_seconds = (start - target_dt).total_seconds()
        if -4 * 3600 <= diff_seconds <= 3600:
            pop = (period.get("probabilityOfPrecipitation") or {}).get("value")
            if pop is not None:
                max_pop = pop if max_pop is None else max(max_pop, pop)
    return max_pop


def _compute_window_playability(periods, game_date, game_time):
    """
    Check every NWS hourly period from 4 hours before game time through
    1 hour after and return the worst playability found.

    A 4-hour pre-game window catches rain that would leave the rink wet by
    game time even if the forecast at the exact game hour looks clear.

    Returns None if no periods fall within the window (e.g. game is beyond
    the 7-day forecast horizon).
    """
    if game_time is not None:
        target_dt = datetime.datetime.combine(game_date, game_time).replace(
            tzinfo=_EASTERN
        )
    else:
        target_dt = datetime.datetime.combine(game_date, datetime.time(19, 0)).replace(
            tzinfo=_EASTERN
        )

    worst = None
    for period in periods:
        start = datetime.datetime.fromisoformat(period["startTime"])
        diff_seconds = (start - target_dt).total_seconds()
        # Window: 4 h before game through 1 h after
        if -4 * 3600 <= diff_seconds <= 3600:
            pop_pct = (period.get("probabilityOfPrecipitation") or {}).get("value") or 0
            p = _compute_playability(pop_pct, period["shortForecast"])
            worst = p if worst is None else _worse_playability(worst, p)

    return worst


def _fetch_weather(api_key, game_times):
    """
    Fetch hourly forecast from the NWS API and return the weather_data dict.
    Returns None on any network or API error so the caller can cache a failure
    sentinel and show a graceful unavailable state.

    api_key is accepted for interface compatibility but is unused — NWS
    requires no API key.

    game_times: dict mapping datetime.date -> datetime.time (or None) for the
    earliest game on that date, used to select the right forecast window.
    """
    weather_data = {}

    try:
        response = requests.get(
            _NWS_HOURLY_URL,
            headers=_NWS_HEADERS,
            timeout=_WEATHER_FETCH_TIMEOUT,
        )

        if response.status_code != 200:
            return None

        periods = response.json()["properties"]["periods"]

        for game_date, game_time in game_times.items():
            game_date_str = game_date.strftime("%Y-%m-%d")

            # Display info: period closest to game start time
            display_period = _find_best_forecast_slot(periods, game_date, game_time)

            # Playability: worst condition in the 4-hour pre-game window
            window_play = _compute_window_playability(periods, game_date, game_time)

            # Max PoP across the window — used for display so the shown percentage
            # matches the warning badge, which is window-based not game-time-only.
            window_max_pop = _compute_window_max_pop(periods, game_date, game_time)

            # Fall back to single-period assessment if window is outside the
            # 7-day forecast horizon.
            if window_play is None and display_period:
                fallback_pop = (
                    display_period.get("probabilityOfPrecipitation") or {}
                ).get("value") or 0
                window_play = _compute_playability(
                    fallback_pop, display_period["shortForecast"]
                )

            if display_period:
                display_pop = (
                    display_period.get("probabilityOfPrecipitation") or {}
                ).get("value")
                # Show the window's max PoP so the displayed % matches the warning.
                pop_pct = window_max_pop if window_max_pop is not None else display_pop
                short = display_period["shortForecast"]
                weather_data[game_date_str] = {
                    "temp": display_period["temperature"],
                    "description": short,
                    "pop_pct": pop_pct,
                    "humidity": (display_period.get("relativeHumidity") or {}).get(
                        "value"
                    ),
                    "playability": window_play or "good",
                    # Distinguish thunderstorm cancellations from plain rain so
                    # the template can show a more specific label.
                    "thunder": "thunder" in short.lower(),
                }

    except Exception as e:
        print(f"Error fetching NWS weather data: {e}")
        return None

    return weather_data


def home(request):
    today = datetime.date.today()
    next_week = today + datetime.timedelta(days=6)

    # select_related eliminates per-matchup FK queries in the template.
    matchups = (
        MatchUp.objects.filter(week__date__range=(today, next_week))
        .select_related("week", "hometeam", "awayteam")
        .order_by("time")
    )
    # One row per date, ordered by date then time so distinct picks the
    # earliest game — used for weather window targeting and template date headers.
    one_row = list(
        MatchUp.objects.filter(week__date__range=(today, next_week))
        .select_related("week")
        .order_by("week__date", "time")
        .distinct("week__date")
    )

    cache_key = f"weather_data_{today}"
    cached = cache.get(cache_key)

    weather_unavailable = False

    if cached is None:
        game_times = {row.week.date: row.time for row in one_row}
        result = _fetch_weather(None, game_times)
        if result is None:
            cache.set(cache_key, _WEATHER_FETCH_FAILED, _WEATHER_ERROR_TTL)
            weather_unavailable = True
            weather_data = {}
        else:
            cache.set(cache_key, result, _WEATHER_FULL_TTL)
            weather_data = result
    elif cached is _WEATHER_FETCH_FAILED or cached.get("_failed"):
        weather_unavailable = True
        weather_data = {}
    else:
        weather_data = cached

    context = {
        "weather_data": weather_data,
        "weather_unavailable": weather_unavailable,
        "matchup": matchups,
        "one_row": one_row,
        "homepage": HomePage.objects.last(),
    }
    return render(request, "core/home.html", context=context)


def leagues(request):
    return render(request, "leagues/index.html")
