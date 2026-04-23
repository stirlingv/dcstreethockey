"""
Tests for player photo upload and admin approval workflow.
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
    PendingPlayerPhotoAdmin,
    approve_pending_photos,
    reject_pending_photos,
)
from leagues.models import PendingPlayerPhoto, Player, PlayerPhoto


# Use local filesystem storage during tests so uploads don't hit S3.
_TEST_STORAGE = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
_TEST_MEDIA = "/tmp/test_media_player_photo/"


def _make_player(**kwargs):
    defaults = {
        "first_name": "Alex",
        "last_name": "Smith",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Player.objects.create(**defaults)


def _fake_image(name="photo.jpg"):
    """Return a real 1×1 JPEG produced by Pillow so ImageField validation passes."""
    buf = io.BytesIO()
    img = PilImage.new("RGB", (1, 1), (255, 255, 255))
    img.save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=_TEST_MEDIA, STORAGES=_TEST_STORAGE)
class UploadPlayerPhotoViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.player = _make_player()
        self.url = reverse("upload_player_photo", args=[self.player.id])

    def test_get_renders_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload a photo")
        self.assertContains(response, self.player.first_name)
        self.assertContains(response, self.player.last_name)

    def test_get_unknown_player_returns_404(self):
        response = self.client.get(reverse("upload_player_photo", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_post_valid_creates_pending_record(self):
        self.assertEqual(PendingPlayerPhoto.objects.count(), 0)
        response = self.client.post(
            self.url,
            {
                "photo": _fake_image(),
                "submitter_email": "alex@example.com",
                "submitter_note": "From team photo",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Photo submitted")
        self.assertEqual(PendingPlayerPhoto.objects.count(), 1)
        pending = PendingPlayerPhoto.objects.get()
        self.assertEqual(pending.player, self.player)
        self.assertEqual(pending.submitter_email, "alex@example.com")
        self.assertEqual(pending.submitter_note, "From team photo")

    def test_post_without_email_or_note_is_valid(self):
        response = self.client.post(self.url, {"photo": _fake_image()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Photo submitted")
        self.assertEqual(PendingPlayerPhoto.objects.count(), 1)
        pending = PendingPlayerPhoto.objects.get()
        self.assertEqual(pending.submitter_email, "")
        self.assertEqual(pending.submitter_note, "")

    def test_post_without_photo_shows_error(self):
        response = self.client.post(self.url, {"submitter_email": "x@x.com"})
        self.assertEqual(response.status_code, 200)
        # Form re-renders with an error; success state is absent
        self.assertNotContains(response, "Photo submitted")
        self.assertContains(response, "Submit photo")
        # No pending record should be created
        self.assertEqual(PendingPlayerPhoto.objects.count(), 0)

    def test_pending_photo_does_not_go_live(self):
        self.client.post(self.url, {"photo": _fake_image()})
        self.player.refresh_from_db()
        self.assertIsNone(self.player.player_photo)

    def test_resubmission_replaces_previous_pending(self):
        # First submission.
        self.client.post(self.url, {"photo": _fake_image("first.jpg")})
        self.assertEqual(
            PendingPlayerPhoto.objects.filter(player=self.player).count(), 1
        )
        first_pk = PendingPlayerPhoto.objects.get(player=self.player).pk

        # Second submission should replace the first.
        self.client.post(self.url, {"photo": _fake_image("second.jpg")})
        pending = PendingPlayerPhoto.objects.filter(player=self.player)
        self.assertEqual(pending.count(), 1)
        self.assertNotEqual(pending.first().pk, first_pk)


@override_settings(MEDIA_ROOT=_TEST_MEDIA, STORAGES=_TEST_STORAGE)
class ApprovePendingPhotoAdminActionTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin = PendingPlayerPhotoAdmin(PendingPlayerPhoto, self.site)
        self.player = _make_player()
        self.pending = PendingPlayerPhoto.objects.create(
            player=self.player,
            photo=_fake_image("pending.jpg"),
            submitter_email="p@example.com",
        )
        self.superuser = User.objects.create_superuser("admin", "a@a.com", "pw")

    def _make_request(self):
        request = self.factory.post("/admin/")
        request.user = self.superuser
        setattr(request, "session", "session")
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)
        return request

    def test_approve_creates_live_photo_and_links_player(self):
        request = self._make_request()
        queryset = PendingPlayerPhoto.objects.filter(pk=self.pending.pk)
        approve_pending_photos(self.admin, request, queryset)

        # Pending record is gone
        self.assertFalse(PendingPlayerPhoto.objects.filter(pk=self.pending.pk).exists())

        # Player now has a live photo
        self.player.refresh_from_db()
        self.assertIsNotNone(self.player.player_photo)
        live_photo = self.player.player_photo
        self.assertIsInstance(live_photo, PlayerPhoto)

    def test_approve_multiple(self):
        player2 = _make_player(first_name="Jordan", last_name="Lee")
        pending2 = PendingPlayerPhoto.objects.create(
            player=player2,
            photo=_fake_image("pending2.jpg"),
        )
        request = self._make_request()
        queryset = PendingPlayerPhoto.objects.filter(
            pk__in=[self.pending.pk, pending2.pk]
        )
        approve_pending_photos(self.admin, request, queryset)

        self.assertEqual(PendingPlayerPhoto.objects.count(), 0)
        self.player.refresh_from_db()
        player2.refresh_from_db()
        self.assertIsNotNone(self.player.player_photo)
        self.assertIsNotNone(player2.player_photo)

    def test_approve_replaces_existing_live_photo(self):
        # Give the player an existing live photo.
        old_live = PlayerPhoto.objects.create(photo=_fake_image("old_live.jpg"))
        self.player.player_photo = old_live
        self.player.save()
        old_live_pk = old_live.pk

        request = self._make_request()
        queryset = PendingPlayerPhoto.objects.filter(pk=self.pending.pk)
        approve_pending_photos(self.admin, request, queryset)

        # Old PlayerPhoto record is deleted.
        self.assertFalse(PlayerPhoto.objects.filter(pk=old_live_pk).exists())
        # Player now points to the new live photo.
        self.player.refresh_from_db()
        self.assertIsNotNone(self.player.player_photo)
        self.assertNotEqual(self.player.player_photo.pk, old_live_pk)

    def test_reject_deletes_record_and_file(self):
        file_name = self.pending.photo.name
        request = self._make_request()
        queryset = PendingPlayerPhoto.objects.filter(pk=self.pending.pk)
        reject_pending_photos(self.admin, request, queryset)

        self.assertFalse(PendingPlayerPhoto.objects.filter(pk=self.pending.pk).exists())
        # File should no longer exist in storage.
        from django.core.files.storage import default_storage

        self.assertFalse(default_storage.exists(file_name))

    def test_reject_does_not_affect_live_photo(self):
        # Player has an approved live photo — rejection of a pending photo
        # must not touch it.
        live = PlayerPhoto.objects.create(photo=_fake_image("live.jpg"))
        self.player.player_photo = live
        self.player.save()

        request = self._make_request()
        queryset = PendingPlayerPhoto.objects.filter(pk=self.pending.pk)
        reject_pending_photos(self.admin, request, queryset)

        self.player.refresh_from_db()
        self.assertEqual(self.player.player_photo.pk, live.pk)


@override_settings(MEDIA_ROOT=_TEST_MEDIA, STORAGES=_TEST_STORAGE)
class SingleItemApproveRejectViewTest(TestCase):
    """Inline Approve / Reject buttons hit single-item admin views."""

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser("admin", "a@a.com", "pw")
        self.client.force_login(self.superuser)
        self.player = _make_player()
        self.pending = PendingPlayerPhoto.objects.create(
            player=self.player,
            photo=_fake_image("pending.jpg"),
        )

    def test_approve_single_makes_photo_live(self):
        url = f"/admin/leagues/pendingplayerphoto/{self.pending.pk}/approve/"
        response = self.client.get(url)
        self.assertRedirects(response, "/admin/leagues/pendingplayerphoto/")
        self.assertFalse(PendingPlayerPhoto.objects.filter(pk=self.pending.pk).exists())
        self.player.refresh_from_db()
        self.assertIsNotNone(self.player.player_photo)

    def test_approve_single_cleans_up_old_live_photo(self):
        old_live = PlayerPhoto.objects.create(photo=_fake_image("old.jpg"))
        self.player.player_photo = old_live
        self.player.save()

        url = f"/admin/leagues/pendingplayerphoto/{self.pending.pk}/approve/"
        self.client.get(url)

        self.assertFalse(PlayerPhoto.objects.filter(pk=old_live.pk).exists())
        self.player.refresh_from_db()
        self.assertNotEqual(self.player.player_photo.pk, old_live.pk)

    def test_reject_single_deletes_record_and_file(self):
        file_name = self.pending.photo.name
        url = f"/admin/leagues/pendingplayerphoto/{self.pending.pk}/reject/"
        response = self.client.get(url)
        self.assertRedirects(response, "/admin/leagues/pendingplayerphoto/")
        self.assertFalse(PendingPlayerPhoto.objects.filter(pk=self.pending.pk).exists())
        from django.core.files.storage import default_storage

        self.assertFalse(default_storage.exists(file_name))

    def test_approve_single_requires_login(self):
        self.client.logout()
        url = f"/admin/leagues/pendingplayerphoto/{self.pending.pk}/approve/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_approve_single_404_for_missing_pk(self):
        url = "/admin/leagues/pendingplayerphoto/99999/approve/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_change_form_shows_approve_and_reject_buttons(self):
        url = f"/admin/leagues/pendingplayerphoto/{self.pending.pk}/change/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        approve_url = f"/admin/leagues/pendingplayerphoto/{self.pending.pk}/approve/"
        reject_url = f"/admin/leagues/pendingplayerphoto/{self.pending.pk}/reject/"
        self.assertContains(response, approve_url)
        self.assertContains(response, reject_url)
        self.assertContains(response, "Approve")
        self.assertContains(response, "Reject")


@override_settings(MEDIA_ROOT=_TEST_MEDIA, STORAGES=_TEST_STORAGE)
class AdminPendingPhotoBannerTest(TestCase):
    """Admin pages show a review banner when pending photos exist."""

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser("admin", "a@a.com", "pw")
        self.client.force_login(self.superuser)
        self.player = _make_player()

    def test_no_banner_when_no_pending_photos(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "to review")

    def test_banner_appears_when_pending_photo_exists(self):
        PendingPlayerPhoto.objects.create(
            player=self.player,
            photo=_fake_image("pending.jpg"),
        )
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 photo to review")
        self.assertContains(response, "/admin/leagues/pendingplayerphoto/")

    def test_banner_shows_correct_count(self):
        player2 = _make_player(first_name="Jordan", last_name="Lee")
        PendingPlayerPhoto.objects.create(
            player=self.player, photo=_fake_image("p1.jpg")
        )
        PendingPlayerPhoto.objects.create(player=player2, photo=_fake_image("p2.jpg"))
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 photos to review")


class PlayerProfileAvatarTest(TestCase):
    """Player profile page shows avatar when photo exists, placeholder otherwise."""

    def setUp(self):
        self.client = Client()
        self.player = _make_player()
        self.url = reverse("player", args=[self.player.id])

    def test_no_photo_shows_placeholder_and_upload_link(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "player-avatar-placeholder")
        self.assertContains(response, "Add photo")
        upload_url = reverse("upload_player_photo", args=[self.player.id])
        self.assertContains(response, upload_url)

    @override_settings(MEDIA_ROOT=_TEST_MEDIA, STORAGES=_TEST_STORAGE)
    def test_approved_photo_shows_img_and_change_link(self):
        live_photo = PlayerPhoto.objects.create(photo=_fake_image("live.jpg"))
        self.player.player_photo = live_photo
        self.player.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "player-avatar")
        self.assertContains(response, "<img")
        self.assertContains(response, "Change photo")
        upload_url = reverse("upload_player_photo", args=[self.player.id])
        self.assertContains(response, upload_url)
