# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-03-31 22:36
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0057_matchup_is_championship'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='team',
            name='is_champ',
        ),
    ]