from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leagues", "0091_draftpick_trade_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="draftteam",
            name="captain_draft_round",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text="Round number in which this captain is automatically drafted onto their team. Leave blank if not applicable.",
            ),
        ),
        migrations.AddField(
            model_name="draftpick",
            name="is_auto_captain",
            field=models.BooleanField(
                default=False,
                help_text="Set automatically when a captain is auto-drafted onto their own team.",
            ),
        ),
    ]
