# Generated by Django 3.0.7 on 2020-09-04 18:29

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0058_remove_team_is_champ'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='team',
            options={'ordering': ['-season__year']},
        ),
        migrations.AlterField(
            model_name='matchup',
            name='awayteam',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='leagues.Team'),
        ),
        migrations.AlterField(
            model_name='matchup',
            name='hometeam',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='leagues.Team'),
        ),
        migrations.AlterField(
            model_name='matchup',
            name='ref1',
            field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='leagues.Ref'),
        ),
        migrations.AlterField(
            model_name='matchup',
            name='ref2',
            field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='leagues.Ref'),
        ),
        migrations.AlterField(
            model_name='roster',
            name='team',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='leagues.Team'),
        ),
        migrations.AlterField(
            model_name='stat',
            name='matchup',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='leagues.MatchUp'),
        ),
        migrations.AlterField(
            model_name='stat',
            name='player',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='leagues.Player'),
        ),
        migrations.AlterField(
            model_name='stat',
            name='team',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='leagues.Team'),
        ),
        migrations.AlterField(
            model_name='team',
            name='division',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='leagues.Division'),
        ),
        migrations.AlterField(
            model_name='team',
            name='season',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='leagues.Season'),
        ),
        migrations.AlterField(
            model_name='team',
            name='team_name',
            field=models.CharField(max_length=55),
        ),
        migrations.AlterField(
            model_name='team',
            name='team_photo',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='leagues.TeamPhoto'),
        ),
        migrations.AlterField(
            model_name='team_stat',
            name='division',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='leagues.Division'),
        ),
        migrations.AlterField(
            model_name='team_stat',
            name='season',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='leagues.Season'),
        ),
        migrations.AlterField(
            model_name='team_stat',
            name='team',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='leagues.Team'),
        ),
        migrations.AlterField(
            model_name='week',
            name='division',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to='leagues.Division'),
        ),
        migrations.AlterField(
            model_name='week',
            name='season',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='leagues.Season'),
        ),
    ]
