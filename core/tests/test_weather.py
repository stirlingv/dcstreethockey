import datetime
from unittest.mock import patch, MagicMock

from django.core.cache import cache
from django.test import TestCase, Client
from django.urls import reverse

from core.views.home import (
    _compute_playability,
    _compute_window_playability,
    _find_best_forecast_slot,
    _playability_from_current_weather,
    _worse_playability,
)


class ComputePlayabilityTest(TestCase):
    """Unit tests for _compute_playability()."""

    def test_clear_skies_is_good(self):
        # Condition 800 = Clear sky, no precip
        self.assertEqual(_compute_playability(800, 0.0, 0, 0), "good")

    def test_cloudy_no_precip_is_good(self):
        # Condition 803 = Broken clouds
        self.assertEqual(_compute_playability(803, 0.10, 0, 0), "good")

    def test_low_pop_is_good(self):
        self.assertEqual(_compute_playability(800, 0.20, 0, 0), "good")

    def test_pop_threshold_uncertain(self):
        # 30% pop with clear condition code → uncertain
        self.assertEqual(_compute_playability(800, 0.30, 0, 0), "uncertain")

    def test_high_pop_no_precipitation_condition_still_uncertain(self):
        # 70% pop but no precipitation in the window yet
        self.assertEqual(_compute_playability(801, 0.70, 0, 0), "uncertain")

    def test_rain_condition_code_is_cancelled(self):
        # 500 = Light rain
        self.assertEqual(_compute_playability(500, 0.0, 0, 0), "likely_cancelled")

    def test_heavy_rain_condition_code_is_cancelled(self):
        # 502 = Heavy intensity rain
        self.assertEqual(_compute_playability(502, 0.80, 5.0, 0), "likely_cancelled")

    def test_drizzle_condition_code_is_cancelled(self):
        # 300 = Light intensity drizzle
        self.assertEqual(_compute_playability(300, 0.10, 0, 0), "likely_cancelled")

    def test_snow_condition_code_is_cancelled(self):
        # 601 = Snow
        self.assertEqual(_compute_playability(601, 0.90, 0, 2.0), "likely_cancelled")

    def test_thunderstorm_condition_code_is_cancelled(self):
        # 211 = Thunderstorm
        self.assertEqual(_compute_playability(211, 0.95, 3.0, 0), "likely_cancelled")

    def test_measurable_rain_mm_is_cancelled_even_with_clear_code(self):
        # Clear condition code but actual rain in the window
        self.assertEqual(_compute_playability(800, 0.0, 0.5, 0), "likely_cancelled")

    def test_trace_rain_below_threshold_is_good(self):
        # Under 0.1 mm is trace/noise — does not cancel
        self.assertEqual(_compute_playability(800, 0.05, 0.05, 0), "good")

    def test_snow_mm_is_cancelled(self):
        # Any snow triggers cancellation
        self.assertEqual(_compute_playability(800, 0.0, 0, 0.1), "likely_cancelled")

    def test_boundary_condition_699_is_cancelled(self):
        # 699 is the last "bad" condition code (top of snow range)
        self.assertEqual(_compute_playability(699, 0.0, 0, 0), "likely_cancelled")

    def test_boundary_condition_700_is_not_precipitation(self):
        # 700-series is atmospheric (mist, fog) — not a cancellation condition
        self.assertEqual(_compute_playability(701, 0.0, 0, 0), "good")

    def test_fog_low_pop_is_good(self):
        # 741 = Fog — not a cancellation reason for floor hockey
        self.assertEqual(_compute_playability(741, 0.05, 0, 0), "good")


class FindBestForecastSlotTest(TestCase):
    """Unit tests for _find_best_forecast_slot()."""

    def _make_slot(self, dt_txt, condition_id=800, pop=0.0, rain_mm=0, temp=70):
        """Build a minimal OWM forecast list item."""
        return {
            "dt_txt": dt_txt,
            "weather": [{"id": condition_id, "description": "clear sky"}],
            "main": {"temp": temp, "humidity": 50},
            "pop": pop,
            "rain": {"3h": rain_mm} if rain_mm else {},
            "snow": {},
        }

    def test_returns_none_for_empty_list(self):
        result = _find_best_forecast_slot([], datetime.date(2025, 6, 15), None)
        self.assertIsNone(result)

    def test_finds_closest_slot_to_7pm_eastern_default(self):
        # For a summer date (EDT = UTC-4), 7pm ET = 23:00 UTC
        # Slots at 21:00 UTC (5pm ET) and 00:00 UTC next day (8pm ET) — 00:00 is closer
        game_date = datetime.date(2025, 6, 15)  # Summer (EDT)
        slots = [
            self._make_slot("2025-06-15 21:00:00"),  # 5pm EDT — 2h before target
            self._make_slot("2025-06-16 00:00:00"),  # 8pm EDT — 1h after target
        ]
        result = _find_best_forecast_slot(slots, game_date, None)
        self.assertEqual(result["dt_txt"], "2025-06-16 00:00:00")

    def test_finds_closest_slot_to_explicit_game_time(self):
        # 7:30pm ET game on a summer date; 23:00 UTC slot (7pm ET) is closest
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 30)
        slots = [
            self._make_slot("2025-06-15 18:00:00"),  # 2pm ET — far
            self._make_slot("2025-06-15 21:00:00"),  # 5pm ET — moderate
            self._make_slot("2025-06-15 23:00:00"),  # 7pm ET — closest to 7:30pm
            self._make_slot("2025-06-16 02:00:00"),  # 10pm ET — farther
        ]
        result = _find_best_forecast_slot(slots, game_date, game_time)
        self.assertEqual(result["dt_txt"], "2025-06-15 23:00:00")

    def test_handles_single_slot(self):
        game_date = datetime.date(2025, 4, 20)
        slots = [self._make_slot("2025-04-20 21:00:00")]
        result = _find_best_forecast_slot(slots, game_date, None)
        self.assertEqual(result["dt_txt"], "2025-04-20 21:00:00")


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

    def _make_slot(self, dt_txt, condition_id=800, pop=0.0, rain_mm=0, snow_mm=0):
        return {
            "dt_txt": dt_txt,
            "weather": [{"id": condition_id, "description": "clear sky"}],
            "main": {"temp": 70, "humidity": 50},
            "pop": pop,
            "rain": {"3h": rain_mm} if rain_mm else {},
            "snow": {"3h": snow_mm} if snow_mm else {},
        }

    def test_returns_none_when_no_slots_in_window(self):
        # Only slot is 6h before game — outside the 4h window
        # 7pm ET on 2025-06-15 (summer, EDT=UTC-4) → 23:00 UTC
        # 6h before = 17:00 UTC
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        slots = [self._make_slot("2025-06-15 17:00:00")]
        result = _compute_window_playability(slots, game_date, game_time)
        self.assertIsNone(result)

    def test_good_when_all_window_slots_are_clear(self):
        # 7pm ET game on 2025-06-15 → window is 15:00–00:00 UTC
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        slots = [
            self._make_slot("2025-06-15 21:00:00"),  # 5pm ET — 2h before
            self._make_slot("2025-06-15 23:00:00"),  # 7pm ET — at game time
        ]
        result = _compute_window_playability(slots, game_date, game_time)
        self.assertEqual(result, "good")

    def test_cancelled_when_one_slot_has_rain(self):
        # Slot 2h before game shows rain → whole window is cancelled
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        slots = [
            self._make_slot("2025-06-15 21:00:00", rain_mm=2.0),  # 5pm ET — rain
            self._make_slot("2025-06-15 23:00:00"),  # 7pm ET — clear
        ]
        result = _compute_window_playability(slots, game_date, game_time)
        self.assertEqual(result, "likely_cancelled")

    def test_uncertain_when_high_pop_no_actual_rain(self):
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        slots = [
            self._make_slot("2025-06-15 21:00:00", pop=0.5),  # 5pm ET, 50% PoP
        ]
        result = _compute_window_playability(slots, game_date, game_time)
        self.assertEqual(result, "uncertain")

    def test_slot_just_after_game_is_included(self):
        # Slot 1h after game start (within window) with rain
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        # 7pm ET = 23:00 UTC; 1h after = 00:00 UTC next day
        slots = [
            self._make_slot("2025-06-16 00:00:00", rain_mm=1.5),
        ]
        result = _compute_window_playability(slots, game_date, game_time)
        self.assertEqual(result, "likely_cancelled")

    def test_slot_more_than_1h_after_game_excluded(self):
        # Slot 2h after game should be outside the window
        # 7pm ET = 23:00 UTC; 2h after = 01:00 UTC next day
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        slots = [
            self._make_slot("2025-06-16 01:00:00", condition_id=500),
        ]
        result = _compute_window_playability(slots, game_date, game_time)
        self.assertIsNone(result)

    def test_defaults_to_7pm_when_no_game_time(self):
        # No game_time → defaults to 7pm ET; verify window still works
        game_date = datetime.date(2025, 6, 15)
        slots = [
            self._make_slot("2025-06-15 21:00:00"),  # 5pm ET — in window
        ]
        result = _compute_window_playability(slots, game_date, None)
        self.assertEqual(result, "good")

    def test_worst_of_multiple_window_slots(self):
        # Mix of good and cancelled slots in window — worst wins
        game_date = datetime.date(2025, 6, 15)
        game_time = datetime.time(19, 0)
        slots = [
            self._make_slot("2025-06-15 21:00:00"),  # good
            self._make_slot("2025-06-15 23:00:00", pop=0.4),  # uncertain
            self._make_slot(
                "2025-06-15 23:00:00", rain_mm=1.0
            ),  # cancelled (dup dt ok)
        ]
        result = _compute_window_playability(slots, game_date, game_time)
        self.assertEqual(result, "likely_cancelled")


class PlayabilityFromCurrentWeatherTest(TestCase):
    """Unit tests for _playability_from_current_weather()."""

    def _make_current(self, condition_id, rain_1h=0, rain_3h=0, snow_1h=0):
        return {
            "weather": [{"id": condition_id, "description": "test"}],
            "main": {"temp": 60, "humidity": 70},
            "rain": {
                **({"1h": rain_1h} if rain_1h else {}),
                **({"3h": rain_3h} if rain_3h else {}),
            },
            "snow": {"1h": snow_1h} if snow_1h else {},
        }

    def test_clear_sky_is_good(self):
        self.assertEqual(
            _playability_from_current_weather(self._make_current(800)), "good"
        )

    def test_broken_clouds_is_good(self):
        self.assertEqual(
            _playability_from_current_weather(self._make_current(803)), "good"
        )

    def test_active_rain_condition_is_cancelled(self):
        # 500 = Light rain — actively precipitating
        self.assertEqual(
            _playability_from_current_weather(self._make_current(500)),
            "likely_cancelled",
        )

    def test_active_thunderstorm_is_cancelled(self):
        self.assertEqual(
            _playability_from_current_weather(self._make_current(211)),
            "likely_cancelled",
        )

    def test_active_snow_is_cancelled(self):
        self.assertEqual(
            _playability_from_current_weather(self._make_current(601)),
            "likely_cancelled",
        )

    def test_recent_rain_1h_is_uncertain(self):
        # Stopped raining but rained in the last hour → rink may still be wet
        self.assertEqual(
            _playability_from_current_weather(self._make_current(800, rain_1h=0.5)),
            "uncertain",
        )

    def test_trace_rain_1h_below_threshold_is_good(self):
        # ≤ 0.1 mm/h is negligible
        self.assertEqual(
            _playability_from_current_weather(self._make_current(800, rain_1h=0.1)),
            "good",
        )

    def test_meaningful_rain_3h_is_uncertain(self):
        # Hasn't rained in last hour but significant rain in last 3h
        self.assertEqual(
            _playability_from_current_weather(self._make_current(800, rain_3h=0.6)),
            "uncertain",
        )

    def test_light_rain_3h_below_threshold_is_good(self):
        # Under 0.5 mm in last 3h is negligible
        self.assertEqual(
            _playability_from_current_weather(self._make_current(800, rain_3h=0.5)),
            "good",
        )

    def test_recent_snow_1h_is_uncertain(self):
        # Snow in last hour — rink is likely wet/slushy
        self.assertEqual(
            _playability_from_current_weather(self._make_current(800, snow_1h=0.1)),
            "uncertain",
        )

    def test_fog_with_no_recent_precip_is_good(self):
        # Fog (741) is not a cancellation reason
        self.assertEqual(
            _playability_from_current_weather(self._make_current(741)),
            "good",
        )


class WeatherPlayabilityIntegrationTest(TestCase):
    """
    Integration smoke test: home view produces playability data when the
    OWM API returns a rainy forecast.
    """

    def _get_home_with_forecast(self, condition_id, pop, rain_mm=0):
        """Hit the home view with a mocked OWM response."""
        fake_slot = {
            "dt_txt": "2025-06-15 23:00:00",
            "weather": [{"id": condition_id, "description": "light rain"}],
            "main": {"temp": 65, "humidity": 80},
            "pop": pop,
            "rain": {"3h": rain_mm} if rain_mm else {},
            "snow": {},
        }
        fake_forecast = {"list": [fake_slot]}

        with patch("core.views.home.MatchUp") as MockMatchUp, patch(
            "core.views.home.requests.get"
        ) as mock_get, patch.dict("os.environ", {"OPENWEATHERMAP_API_KEY": "fake"}):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = fake_forecast
            cache.clear()
            response = self.client.get(reverse("home"))
        return response

    def test_home_view_returns_200(self):
        response = self._get_home_with_forecast(800, 0.0)
        self.assertEqual(response.status_code, 200)
