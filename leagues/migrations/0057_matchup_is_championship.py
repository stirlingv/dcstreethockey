# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-03-27 21:20
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0056_auto_20200327_1413'),
    ]

    operations = [
        migrations.AddField(
            model_name='matchup',
            name='is_championship',
            field=models.BooleanField(default=False),
        ),
    ]