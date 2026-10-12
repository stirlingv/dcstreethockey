"""
Seed an empty database with the small league used by the smoke tests.

CI runs this against a throwaway PostgreSQL database before crawling the
site with scripts/smoke_crawl.py. It refuses to touch a database that
already has league data, so it can't pollute production or a local copy.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dcstreethockey.smoke_data import build_smoke_data
from leagues.models import Player, Season, Team


class Command(BaseCommand):
    help = "Seed an EMPTY database with smoke-test league data."

    def handle(self, *args, **options):
        if Season.objects.exists() or Team.objects.exists() or Player.objects.exists():
            raise CommandError(
                "This database already has league data. seed_smoke_data only "
                "runs against an empty database."
            )
        with transaction.atomic():
            data = build_smoke_data()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded smoke data: season {data['season']}, "
                f"{Team.objects.count()} teams, {Player.objects.count()} players."
            )
        )
