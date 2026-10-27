from __future__ import unicode_literals

from django.apps import AppConfig


class LeaguesConfig(AppConfig):
    name = "leagues"

    def ready(self):
        from . import signals  # noqa: F401  (connects the receivers)
