from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("leagues", "0099_add_shootout_winner_is_home_to_matchup"),
    ]

    operations = [
        migrations.CreateModel(
            name="PendingTeamPhoto",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("photo", models.ImageField(upload_to="teams/pending")),
                ("submitter_email", models.EmailField(blank=True, max_length=254)),
                ("submitter_note", models.CharField(blank=True, max_length=500)),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pending_photos",
                        to="leagues.team",
                    ),
                ),
            ],
            options={
                "ordering": ("submitted_at",),
            },
        ),
    ]
