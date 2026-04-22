import datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, Client
from django.urls import reverse

from core.views.home import (
    _compute_playability,
    _compute_window_playability,
    _find_best_forecast_slot,
    _worse_playability,
)


def _make_period(start_iso, pop_pct=0, short_forecast="Sunny", temp=70, humidity=50):
    """Build a minimal NWS hourly period dict."""
    return {
        "startTime": start_iso,
        "endTime": start_iso,  # not used in logic
        "temperature": temp,
        "temperatureUnit": "F",
        "shortForecast": short_forecast,
        "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": pop_pct},
        "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": humidity},
    }


class ComputePlayabilityTest(TestCase):
    """Unit tests for _compute_playability(pop_pct, short_forecast)."""

    def test_clear_skies_is_good(self):
        self.assertEqual(_compute_playability(0, "Sunny"), "good")

    def test_mostly_cloudy_low_pop_is_good(self):
        self.assertEqual(_compute_playability(10, "Mostly Cloudy"), "good")

    def test_slight_chance_rain_is_uncertain(self):
        # "Slight Chance" = NWS 10–20 % PoP; still worth flagging
        self.assertEqual(
            _compute_playability(13, "Slight Chance Rain Showers"), "uncertain"
        )

    def test_chance_rain_is_uncertain(self):
        # "Chance" = NWS 30–50 % PoP
        self.assertEqual(_compute_playability(43, "Chance Rain Showers"), "uncertain")

    def test_pop_20_no_precip_keyword_is_uncertain(self):
        self.assertEqual(_compute_playability(20, "Mostly Cloudy"), "uncertain")

    def test_pop_19_no_precip_keyword_is_good(self):
        self.assertEqual(_compute_playability(19, "Mostly Cloudy"), "good")

    def test_rain_likely_is_cancelled(self):
        # "Likely" = NWS 60–70 % PoP
        self.assertEqual(
            _compute_playability(59, "Rain Showers Likely"), "likely_cancelled"
        )

    def test_pop_50_is_cancelled(self):
        self.assertEqual(
            _compute_playability(50, "Chance Rain Showers"), "likely_cancelled"
        )

    def test_high_pop_no_precip_keyword_is_cancelled(self):
        self.assertEqual(_compute_playability(60, "Mostly Cloudy"), "likely_cancelled")

    def test_thunderstorm_is_cancelled_regardless_of_pop(self):
        self.assertEqual(
            _compute_playability(5, "Slight Chance Thunderstorms"), "likely_cancelled"
        )

    def test_thunderstorm_high_pop_is_cancelled(self):
        self.assertEqual(_compute_playability(80, "Thunderstorms"), "likely_cancelled")

    def test_snow_showers_likely_is_cancelled(self):
        self.assertEqual(
            _compute_playability(60, "Snow Showers Likely"), "likely_cancelled"
        )

    def test_slight_chance_snow_is_uncertain(self):
        self.assertEqual(
            _compute_playability(15, "Slight Chance Snow Showers"), "uncertain"
        )

    def test_drizzle_low_pop_is_uncertain(self):
        self.assertEqual(_compute_playability(10, "Drizzle"), "uncertain")

    def test_null_pop_treated_as_zero(self):
        self.assertEqual(_compute_playability(None, "Sunny"), "good")

    def test_fog_is_good(self):
        # Fog is not a cancellation condition for floor hockey
        self.assertEqual(_compute_playability(0, "Dense Fog"), "good")


class FindBestForecastSlotTest(TestCase):
    """Unit tests for _find_best_forecast_slot()."""

    def test_returns_none_for_empty_list(self):
        result = _find_best_forecast_slot([], datetime.date(2025, 6, 15), None)
        self.assertIsNone(result)

    def test_finds_closest_period_to_7pm_eastern_default(self):
        # No game_time → defaults to 7pm ET.
        # On 2025-06-15 (EDT, UTC-4): 7pm ET = 23:00 UTC = "2025-06-15T23:00:00-04:00"
        # Period at 5pm ET (2h before) vs 8pm ET (1h after) → 8pm is closer.
        game_date = datetime.date(2025, 6, 15)
        periods = [
            _make_period("2025-06-15T17:00:00-04:00"),  # 5pm ET — 2h before
            _make_period("2025-06-15T20:00:00-04:00"),  # 8pm ET — 1h after
        ]
        result = _find_best_forecast_slot(periods, game_date, None)
        self.assertEqual(result["startTime"], "2025-06-15T20:00:00-04:00")

    def test_finds_closest_period_to_explicit_game_time(self):
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 30)  # 7:30pm
        periods = [
            _make_period("2025-06-15T14:00:00-04:00"),  # 2pm — far
            _make_period("2025-06-15T17:00:00-04:00"),  # 5pm — moderate
            _make_period("2025-06-15T19:00:00-04:00"),  # 7pm — closest to 7:30
            _make_period("2025-06-15T22:00:00-04:00"),  # 10pm — farther
        ]
        result = _find_best_forecast_slot(periods, game_date, game_time)
        self.assertEqual(result["startTime"], "2025-06-15T19:00:00-04:00")

    def test_handles_single_period(self):
        game_date = datetime.date(2025, 4, 20)
        periods = [_make_period("2025-04-20T21:00:00-04:00")]
        result = _find_best_forecast_slot(periods, game_date, None)
        self.assertEqual(result["startTime"], "2025-04-20T21:00:00-04:00")


class WorsePlayabilityTest(TestCase):
    """Unit tests for _worse_playability()."""

    def test_good_vs_good_returns_good(self):
        self.assertEqual(_worse_playability("good", "good"), "good")

    def test_good_vs_uncertain_returns_uncertain(self):
        self.assertEqual(_worse_playability("good", "uncertain"), "uncertain")

    def test_uncertain_vs_good_returns_uncertain(self):
        self.assertEqual(_worse_playability("uncertain", "good"), "uncertain")

    def test_good_vs_cancelled_returns_cancelled(self):
        self.assertEqual(
            _worse_playability("good", "likely_cancelled"), "likely_cancelled"
        )

    def test_cancelled_vs_good_returns_cancelled(self):
        self.assertEqual(
            _worse_playability("likely_cancelled", "good"), "likely_cancelled"
        )

    def test_uncertain_vs_cancelled_returns_cancelled(self):
        self.assertEqual(
            _worse_playability("uncertain", "likely_cancelled"), "likely_cancelled"
        )

    def test_cancelled_vs_uncertain_returns_cancelled(self):
        self.assertEqual(
            _worse_playability("likely_cancelled", "uncertain"), "likely_cancelled"
        )

    def test_cancelled_vs_cancelled_returns_cancelled(self):
        self.assertEqual(
            _worse_playability("likely_cancelled", "likely_cancelled"),
            "likely_cancelled",
        )


class ComputeWindowPlayabilityTest(TestCase):
    """Unit tests for _compute_window_playability()."""

    def test_returns_none_when_no_periods_in_window(self):
        # Period 6h before game — outside the 4h window
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)  # 7pm ET
        periods = [_make_period("2025-06-15T13:00:00-04:00")]  # 1pm ET — 6h before
        result = _compute_window_playability(periods, game_date, game_time)
        self.assertIsNone(result)

    def test_good_when_all_window_periods_are_clear(self):
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        periods = [
            _make_period("2025-06-15T17:00:00-04:00", pop_pct=5),  # 5pm — 2h before
            _make_period("2025-06-15T19:00:00-04:00", pop_pct=10),  # 7pm — at game
        ]
        result = _compute_window_playability(periods, game_date, game_time)
        self.assertEqual(result, "good")

    def test_cancelled_when_one_period_has_rain(self):
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        periods = [
            _make_period(
                "2025-06-15T17:00:00-04:00", pop_pct=70, short_forecast="Rain"
            ),
            _make_period(
                "2025-06-15T19:00:00-04:00", pop_pct=5, short_forecast="Sunny"
            ),
        ]
        result = _compute_window_playability(periods, game_date, game_time)
        self.assertEqual(result, "likely_cancelled")

    def test_uncertain_when_moderate_pop(self):
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        periods = [
            _make_period(
                "2025-06-15T17:00:00-04:00",
                pop_pct=30,
                short_forecast="Chance Rain Showers",
            ),
        ]
        result = _compute_window_playability(periods, game_date, game_time)
        self.assertEqual(result, "uncertain")

    def test_period_1h_after_game_is_included(self):
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)  # 7pm ET; 1h after = 8pm ET
        periods = [
            _make_period(
                "2025-06-15T20:00:00-04:00", pop_pct=80, short_forecast="Rain"
            ),
        ]
        result = _compute_window_playability(periods, game_date, game_time)
        self.assertEqual(result, "likely_cancelled")

    def test_period_2h_after_game_is_excluded(self):
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)  # 7pm ET; 2h after = 9pm ET
        periods = [
            _make_period(
                "2025-06-15T21:00:00-04:00", pop_pct=90, short_forecast="Rain"
            ),
        ]
        result = _compute_window_playability(periods, game_date, game_time)
        self.assertIsNone(result)

    def test_defaults_to_7pm_when_no_game_time(self):
        game_date = datetime.date(2025, 6, 15)
        periods = [
            _make_period(
                "2025-06-15T17:00:00-04:00", pop_pct=5, short_forecast="Sunny"
            ),
        ]
        result = _compute_window_playability(periods, game_date, None)
        self.assertEqual(result, "good")

    def test_worst_of_multiple_window_periods(self):
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        periods = [
            _make_period(
                "2025-06-15T17:00:00-04:00", pop_pct=5, short_forecast="Sunny"
            ),
            _make_period(
                "2025-06-15T18:00:00-04:00",
                pop_pct=35,
                short_forecast="Chance Rain Showers",
            ),
            _make_period(
                "2025-06-15T19:00:00-04:00",
                pop_pct=75,
                short_forecast="Rain Showers Likely",
            ),
        ]
        result = _compute_window_playability(periods, game_date, game_time)
        self.assertEqual(result, "likely_cancelled")


class WeatherIntegrationTest(TestCase):
    """
    Integration smoke test: home view produces playability data when the
    NWS API returns a forecast.
    """

    def _make_nws_response(self, periods):
        return {"properties": {"periods": periods}}

    def _get_home_with_forecast(self, periods):
        with patch("core.views.home.MatchUp") as MockMatchUp, patch(
            "core.views.home.requests.get"
        ) as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = self._make_nws_response(periods)
            cache.clear()
            response = self.client.get(reverse("home"))
        return response

    def test_home_view_returns_200(self):
        periods = [_make_period("2025-06-15T19:00:00-04:00", pop_pct=5)]
        response = self._get_home_with_forecast(periods)
        self.assertEqual(response.status_code, 200)

    def test_weather_unavailable_on_api_failure(self):
        with patch("core.views.home.MatchUp") as MockMatchUp, patch(
            "core.views.home.requests.get"
        ) as mock_get:
            mock_get.return_value.status_code = 500
            cache.clear()
            response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["weather_unavailable"])
