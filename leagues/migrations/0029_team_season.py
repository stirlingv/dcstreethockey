# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2017-05-10 10:43
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0028_auto_20170327_2114'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='season',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='leagues.Season'),
        ),
    ]
