# -*- coding: utf-8 -*-
# Generated by Django 1.11.21 on 2019-07-17 02:40
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0052_auto_20190120_1113'),
    ]

    operations = [
        migrations.AlterField(
            model_name='player',
            name='photo',
            field=models.ImageField(blank=True, null=True, upload_to=''),
        ),
    ]
