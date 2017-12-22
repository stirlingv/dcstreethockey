# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2017-12-22 19:55
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0043_auto_20171222_1445'),
    ]

    operations = [
        migrations.CreateModel(
            name='PhotoMod',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('photo', models.ImageField(blank=True, upload_to='teams')),
            ],
        ),
        migrations.RemoveField(
            model_name='team',
            name='photo',
        ),
        migrations.AddField(
            model_name='team',
            name='photoref',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='leagues.PhotoMod'),
        ),
    ]
