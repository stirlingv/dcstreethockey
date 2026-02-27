from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError


GROUP_NAME = "Quick Cancel Operators"
QUICK_CANCEL_PERMISSION = "can_quick_cancel_games"


class Command(BaseCommand):
    help = (
        "Create or update the Quick Cancel Operators group and a staff user "
        "that can only run the quick-cancel admin workflow."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            required=False,
            help="Username to create/update and add to Quick Cancel Operators.",
        )
        parser.add_argument(
            "--password",
            required=False,
            help="Password for the user (do not pass on the command line in production; "
            "use the QUICK_CANCEL_PASS environment variable via build.sh instead).",
        )
        parser.add_argument(
            "--email",
            default="",
            help="Optional email for the user.",
        )
        parser.add_argument(
            "--no-user",
            action="store_true",
            help="Only create/update the group and permissions.",
        )

    def handle(self, *args, **options):
        group, created = Group.objects.get_or_create(name=GROUP_NAME)
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created group: {GROUP_NAME}"))
        else:
            self.stdout.write(f"Group exists: {GROUP_NAME}")

        permission = self._get_quick_cancel_permission()
        group.permissions.set([permission])
        self.stdout.write(
            self.style.SUCCESS(
                f"Group permissions updated: leagues.{QUICK_CANCEL_PERMISSION}"
            )
        )

        if options.get("no_user"):
            return

        username = options["username"]
        password = options["password"]
        email = options["email"]
        if not username:
            raise CommandError(
                "Provide --username, or use --no-user to skip user creation."
            )
        if not password:
            raise CommandError(
                "Provide --password, or use --no-user to skip user creation. "
                "Never hardcode the password; pass it via an environment variable."
            )

        user = self._create_or_update_user(
            username=username,
            password=password,
            email=email,
            group=group,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"User '{user.username}' is staff and assigned to {GROUP_NAME}."
            )
        )

    def _get_quick_cancel_permission(self):
        try:
            return Permission.objects.get(
                content_type__app_label="leagues",
                codename=QUICK_CANCEL_PERMISSION,
            )
        except Permission.DoesNotExist as exc:
            raise CommandError(
                "Permission 'leagues.can_quick_cancel_games' was not found. "
                "Run migrations first."
            ) from exc

    def _create_or_update_user(self, username, password, email, group):
        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username=username, defaults={"email": email}
        )
        if email and user.email != email:
            user.email = email

        user.is_staff = True
        user.is_superuser = False
        user.set_password(password)
        user.save()

        # Keep this user limited to quick-cancel workflow only.
        user.groups.set([group])
        user.user_permissions.clear()
        return user
