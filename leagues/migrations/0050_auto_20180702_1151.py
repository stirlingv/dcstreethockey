# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2018-07-02 15:51
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0049_auto_20180702_1146'),
    ]

    operations = [
        migrations.RenameField(
            model_name='homepage',
            old_name='winer_champ_announcement',
            new_name='winter_champ_announcement',
        ),
    ]
