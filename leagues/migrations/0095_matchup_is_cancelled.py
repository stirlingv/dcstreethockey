from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leagues", "0094_remove_seasonsignup_unique_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="matchup",
            name="is_cancelled",
            field=models.BooleanField(
                default=False,
                help_text="Mark this individual game as cancelled.",
            ),
        ),
    ]
