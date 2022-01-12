# Generated by Django 3.1.8 on 2021-09-09 19:21

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0068_auto_20210909_1458'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='player',
            name='player_photo',
        ),
        migrations.AddField(
            model_name='player',
            name='player_photo',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='leagues.playerphoto'),
        ),
    ]