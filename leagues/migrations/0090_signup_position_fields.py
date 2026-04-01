from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("leagues", "0089_draft_session_signups_open"),
    ]

    operations = [
        # Remove the old single position_preference field
        migrations.RemoveField(
            model_name="seasonsignup",
            name="position_preference",
        ),
        # Remove old is_returning (will be re-added below with updated help_text)
        migrations.RemoveField(
            model_name="seasonsignup",
            name="is_returning",
        ),
        # Make email non-nullable (table is empty so no one-time default needed)
        migrations.AlterField(
            model_name="seasonsignup",
            name="email",
            field=models.EmailField(max_length=254),
        ),
        # Add primary_position
        migrations.AddField(
            model_name="seasonsignup",
            name="primary_position",
            field=models.PositiveIntegerField(
                choices=[
                    (1, "Center"),
                    (2, "Wing"),
                    (3, "Defense"),
                    (4, "Goalie"),
                ],
                default=1,
            ),
            preserve_default=False,
        ),
        # Add secondary_position
        migrations.AddField(
            model_name="seasonsignup",
            name="secondary_position",
            field=models.PositiveIntegerField(
                choices=[
                    (1, "Center"),
                    (2, "Wing"),
                    (3, "Defense"),
                    (4, "Goalie"),
                    (0, "I only do one thing, period!"),
                ],
                default=0,
            ),
            preserve_default=False,
        ),
        # Add captain_interest (nullable — not everyone will answer)
        migrations.AddField(
            model_name="seasonsignup",
            name="captain_interest",
            field=models.PositiveIntegerField(
                blank=True,
                choices=[
                    (1, "Yes for sure please so I control who I play with"),
                    (2, "I can as I'm overdue to captain/help out"),
                    (3, "Only if you can't find 8"),
                    (4, "Nope, lazy or don't know enough"),
                ],
                null=True,
            ),
        ),
        # Re-add is_returning as admin-only field
        migrations.AddField(
            model_name="seasonsignup",
            name="is_returning",
            field=models.BooleanField(
                default=False,
                help_text="Set by commissioner. Has this player played in the Wednesday Draft League before?",
                verbose_name="Returning player?",
            ),
        ),
    ]
