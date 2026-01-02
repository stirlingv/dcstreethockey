from __future__ import annotations

from getpass import getpass

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Create or update the 'Goalie Managers' group and optionally add a user to it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            help="Username to create/update and add to the Goalie Managers group.",
        )
        parser.add_argument("--email", help="Email for the user (optional).")
        parser.add_argument(
            "--password",
            help="Password for the user. If omitted, you'll be prompted.",
        )
        parser.add_argument(
            "--no-user",
            action="store_true",
            help="Only create/update the group and permissions.",
        )

    def handle(self, *args, **options):
        group, created = Group.objects.get_or_create(name="Goalie Managers")
        if created:
            self.stdout.write(self.style.SUCCESS("Created group: Goalie Managers"))
        else:
            self.stdout.write("Group exists: Goalie Managers")

        permissions = self._get_permissions()
        group.permissions.set(permissions)
        self.stdout.write(self.style.SUCCESS("Group permissions updated."))

        if options.get("no_user"):
            return

        username = options.get("username")
        if not username:
            raise CommandError("--username is required unless --no-user is set.")

        email = options.get("email") or ""
        password = options.get("password")
        if not password:
            password = getpass("Password for user: ")
        if not password:
            raise CommandError("Password cannot be empty.")

        user = self._create_or_update_user(username, email, password, group)
        self.stdout.write(
            self.style.SUCCESS(
                f"User '{user.username}' is staff and in Goalie Managers group."
            )
        )

    def _get_permissions(self):
        matchup_ct = ContentType.objects.get_for_model(
            apps.get_model("leagues", "MatchUp")
        )
        team_ct = ContentType.objects.get_for_model(apps.get_model("leagues", "Team"))
        player_ct = ContentType.objects.get_for_model(
            apps.get_model("leagues", "Player")
        )

        codenames = [
            (matchup_ct, "view_matchup"),
            (matchup_ct, "change_matchup"),
            (team_ct, "view_team"),
            (player_ct, "view_player"),
        ]

        permissions = []
        for content_type, codename in codenames:
            perm = Permission.objects.get(content_type=content_type, codename=codename)
            permissions.append(perm)
        return permissions

    def _create_or_update_user(self, username, email, password, group):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username, defaults={"email": email}
        )
        if not created and email:
            user.email = email
        user.is_staff = True
        user.set_password(password)
        user.save()
        user.groups.add(group)
        return user
