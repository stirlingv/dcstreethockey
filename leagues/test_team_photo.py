"""
Tests for team photo upload and admin approval workflow.
"""

import io

from PIL import Image as PilImage

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.test.client import Client
from django.urls import reverse

from leagues.admin import (
    PendingTeamPhotoAdmin,
    approve_pending_team_photos,
    reject_pending_team_photos,
)
from leagues.models import Division, PendingTeamPhoto, Season, Team, TeamPhoto


_TEST_STORAGE = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
_TEST_MEDIA = "/tmp/test_media_team_photo/"


def _make_season(year=2024):
    return Season.objects.get_or_create(
        year=year, defaults={"season_type": 1, "is_current_season": True}
    )[0]


def _make_division(division=1):
    return Division.objects.get_or_create(division=division)[0]


def _make_team(**kwargs):
    season = kwargs.pop("season", None) or _make_season()
    division = kwargs.pop("division", None) or _make_division()
    defaults = {
        "team_name": "Red Dragons",
        "team_color": "Red",
        "is_active": True,
        "season": season,
        "division": division,
    }
    defaults.update(kwargs)
    return Team.objects.create(**defaults)


def _fake_image(name="photo.jpg"):
    """Return a real 1×1 JPEG so ImageField validation passes."""
    buf = io.BytesIO()
    img = PilImage.new("RGB", (1, 1), (255, 255, 255))
    img.save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=_TEST_MEDIA, STORAGES=_TEST_STORAGE)
class UploadTeamPhotoViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.team = _make_team()
        self.url = reverse("upload_team_photo", args=[self.team.id])

    def test_get_renders_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a team photo")
        self.assertContains(response, self.team.team_name)

    def test_get_unknown_team_returns_404(self):
        response = self.client.get(reverse("upload_team_photo", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_post_valid_creates_pending_record(self):
        self.assertEqual(PendingTeamPhoto.objects.count(), 0)
        response = self.client.post(
            self.url,
            {
                "photo": _fake_image(),
                "submitter_email": "captain@example.com",
                "submitter_note": "Team photo Fall 2024",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Photo submitted")
        self.assertEqual(PendingTeamPhoto.objects.count(), 1)
        pending = PendingTeamPhoto.objects.get()
        self.assertEqual(pending.team, self.team)
        self.assertEqual(pending.submitter_email, "captain@example.com")
        self.assertEqual(pending.submitter_note, "Team photo Fall 2024")

    def test_post_without_email_or_note_is_valid(self):
        response = self.client.post(self.url, {"photo": _fake_image()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Photo submitted")
        self.assertEqual(PendingTeamPhoto.objects.count(), 1)
        pending = PendingTeamPhoto.objects.get()
        self.assertEqual(pending.submitter_email, "")
        self.assertEqual(pending.submitter_note, "")

    def test_post_without_photo_shows_error(self):
        response = self.client.post(self.url, {"submitter_email": "x@x.com"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Photo submitted")
        self.assertContains(response, "Submit photo")
        self.assertEqual(PendingTeamPhoto.objects.count(), 0)

    def test_pending_photo_does_not_go_live(self):
        self.client.post(self.url, {"photo": _fake_image()})
        self.team.refresh_from_db()
        self.assertIsNone(self.team.team_photo)

    def test_resubmission_replaces_previous_pending(self):
        self.client.post(self.url, {"photo": _fake_image("first.jpg")})
        self.assertEqual(PendingTeamPhoto.objects.filter(team=self.team).count(), 1)
        first_pk = PendingTeamPhoto.objects.get(team=self.team).pk

        self.client.post(self.url, {"photo": _fake_image("second.jpg")})
        pending = PendingTeamPhoto.objects.filter(team=self.team)
        self.assertEqual(pending.count(), 1)
        self.assertNotEqual(pending.first().pk, first_pk)


@override_settings(MEDIA_ROOT=_TEST_MEDIA, STORAGES=_TEST_STORAGE)
class ApprovePendingTeamPhotoAdminActionTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin = PendingTeamPhotoAdmin(PendingTeamPhoto, self.site)
        self.team = _make_team()
        self.pending = PendingTeamPhoto.objects.create(
            team=self.team,
            photo=_fake_image("pending.jpg"),
            submitter_email="cap@example.com",
        )
        self.superuser = User.objects.create_superuser("admin", "a@a.com", "pw")

    def _make_request(self):
        request = self.factory.post("/admin/")
        request.user = self.superuser
        setattr(request, "session", "session")
        msgs = FallbackStorage(request)
        setattr(request, "_messages", msgs)
        return request

    def test_approve_creates_live_photo_and_links_team(self):
        request = self._make_request()
        queryset = PendingTeamPhoto.objects.filter(pk=self.pending.pk)
        approve_pending_team_photos(self.admin, request, queryset)

        self.assertFalse(PendingTeamPhoto.objects.filter(pk=self.pending.pk).exists())
        self.team.refresh_from_db()
        self.assertIsNotNone(self.team.team_photo)
        self.assertIsInstance(self.team.team_photo, TeamPhoto)

    def test_approve_multiple(self):
        season = _make_season()
        division = _make_division(division=2)
        team2 = _make_team(team_name="Blue Hawks", season=season, division=division)
        pending2 = PendingTeamPhoto.objects.create(
            team=team2,
            photo=_fake_image("pending2.jpg"),
        )
        request = self._make_request()
        queryset = PendingTeamPhoto.objects.filter(
            pk__in=[self.pending.pk, pending2.pk]
        )
        approve_pending_team_photos(self.admin, request, queryset)

        self.assertEqual(PendingTeamPhoto.objects.count(), 0)
        self.team.refresh_from_db()
        team2.refresh_from_db()
        self.assertIsNotNone(self.team.team_photo)
        self.assertIsNotNone(team2.team_photo)

    def test_approve_replaces_existing_live_photo(self):
        old_live = TeamPhoto.objects.create(photo=_fake_image("old_live.jpg"))
        self.team.team_photo = old_live
        self.team.save()
        old_live_pk = old_live.pk

        request = self._make_request()
        queryset = PendingTeamPhoto.objects.filter(pk=self.pending.pk)
        approve_pending_team_photos(self.admin, request, queryset)

        self.assertFalse(TeamPhoto.objects.filter(pk=old_live_pk).exists())
        self.team.refresh_from_db()
        self.assertIsNotNone(self.team.team_photo)
        self.assertNotEqual(self.team.team_photo.pk, old_live_pk)

    def test_reject_deletes_record_and_file(self):
        file_name = self.pending.photo.name
        request = self._make_request()
        queryset = PendingTeamPhoto.objects.filter(pk=self.pending.pk)
        reject_pending_team_photos(self.admin, request, queryset)

        self.assertFalse(PendingTeamPhoto.objects.filter(pk=self.pending.pk).exists())
        from django.core.files.storage import default_storage

        self.assertFalse(default_storage.exists(file_name))

    def test_reject_does_not_affect_live_photo(self):
        live = TeamPhoto.objects.create(photo=_fake_image("live.jpg"))
        self.team.team_photo = live
        self.team.save()

        request = self._make_request()
        queryset = PendingTeamPhoto.objects.filter(pk=self.pending.pk)
        reject_pending_team_photos(self.admin, request, queryset)

        self.team.refresh_from_db()
        self.assertEqual(self.team.team_photo.pk, live.pk)


@override_settings(MEDIA_ROOT=_TEST_MEDIA, STORAGES=_TEST_STORAGE)
class SingleItemApproveRejectTeamPhotoViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser("admin", "a@a.com", "pw")
        self.client.force_login(self.superuser)
        self.team = _make_team()
        self.pending = PendingTeamPhoto.objects.create(
            team=self.team,
            photo=_fake_image("pending.jpg"),
        )

    def test_approve_single_makes_photo_live(self):
        url = f"/admin/leagues/pendingteamphoto/{self.pending.pk}/approve/"
        response = self.client.get(url)
        self.assertRedirects(response, "/admin/leagues/pendingteamphoto/")
        self.assertFalse(PendingTeamPhoto.objects.filter(pk=self.pending.pk).exists())
        self.team.refresh_from_db()
        self.assertIsNotNone(self.team.team_photo)

    def test_approve_single_cleans_up_old_live_photo(self):
        old_live = TeamPhoto.objects.create(photo=_fake_image("old.jpg"))
        self.team.team_photo = old_live
        self.team.save()

        url = f"/admin/leagues/pendingteamphoto/{self.pending.pk}/approve/"
        self.client.get(url)

        self.assertFalse(TeamPhoto.objects.filter(pk=old_live.pk).exists())
        self.team.refresh_from_db()
        self.assertNotEqual(self.team.team_photo.pk, old_live.pk)

    def test_reject_single_deletes_record_and_file(self):
        file_name = self.pending.photo.name
        url = f"/admin/leagues/pendingteamphoto/{self.pending.pk}/reject/"
        response = self.client.get(url)
        self.assertRedirects(response, "/admin/leagues/pendingteamphoto/")
        self.assertFalse(PendingTeamPhoto.objects.filter(pk=self.pending.pk).exists())
        from django.core.files.storage import default_storage

        self.assertFalse(default_storage.exists(file_name))

    def test_approve_single_requires_login(self):
        self.client.logout()
        url = f"/admin/leagues/pendingteamphoto/{self.pending.pk}/approve/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_approve_single_404_for_missing_pk(self):
        url = "/admin/leagues/pendingteamphoto/99999/approve/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_change_form_shows_approve_and_reject_buttons(self):
        url = f"/admin/leagues/pendingteamphoto/{self.pending.pk}/change/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        approve_url = f"/admin/leagues/pendingteamphoto/{self.pending.pk}/approve/"
        reject_url = f"/admin/leagues/pendingteamphoto/{self.pending.pk}/reject/"
        self.assertContains(response, approve_url)
        self.assertContains(response, reject_url)
        self.assertContains(response, "Approve")
        self.assertContains(response, "Reject")


@override_settings(MEDIA_ROOT=_TEST_MEDIA, STORAGES=_TEST_STORAGE)
class AdminPendingTeamPhotoBannerTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser("admin", "a@a.com", "pw")
        self.client.force_login(self.superuser)
        self.team = _make_team()

    def test_no_banner_when_no_pending_team_photos(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "team photos to review")

    def test_banner_appears_when_pending_team_photo_exists(self):
        PendingTeamPhoto.objects.create(
            team=self.team,
            photo=_fake_image("pending.jpg"),
        )
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 team photo to review")
        self.assertContains(response, "/admin/leagues/pendingteamphoto/")

    def test_banner_shows_plural_count(self):
        season = _make_season()
        division = _make_division(division=2)
        team2 = _make_team(team_name="Blue Hawks", season=season, division=division)
        PendingTeamPhoto.objects.create(team=self.team, photo=_fake_image("p1.jpg"))
        PendingTeamPhoto.objects.create(team=team2, photo=_fake_image("p2.jpg"))
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 team photos to review")
