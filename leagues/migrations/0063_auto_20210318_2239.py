# Generated by Django 3.1.6 on 2021-03-19 02:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0062_auto_20210318_2235'),
    ]

    operations = [
        migrations.AlterField(
            model_name='season',
            name='is_current_season',
            field=models.BooleanField(null=True),
        ),
    ]
