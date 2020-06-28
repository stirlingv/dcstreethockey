# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-03-27 18:13
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0055_team_stat_otl'),
    ]

    operations = [
        migrations.AddField(
            model_name='roster',
            name='is_captain',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='team',
            name='is_champ',
            field=models.BooleanField(default=False),
        ),
    ]