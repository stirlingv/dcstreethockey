from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leagues", "0090_signup_position_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="draftpick",
            name="traded",
            field=models.BooleanField(
                default=False,
                help_text="Check if this pick was acquired via a trade. Original draft slot is preserved for reference.",
            ),
        ),
        migrations.AddField(
            model_name="draftpick",
            name="trade_note",
            field=models.CharField(
                blank=True,
                default="",
                max_length=200,
                help_text="Optional note describing the trade (e.g. 'Swapped with Smith from Team B').",
            ),
        ),
    ]
