from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("leagues", "0092_captain_draft_round"),
    ]

    operations = [
        migrations.AddField(
            model_name="draftsession",
            name="finalized_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="draftteam",
            name="league_team",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="draft_team",
                to="leagues.team",
                help_text="The real Team record created when this draft was finalized.",
            ),
        ),
    ]
