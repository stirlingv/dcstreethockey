# Generated by Django 3.1.8 on 2021-09-09 18:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0067_auto_20210816_1742'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='player',
            name='player_photo',
        ),
        migrations.AddField(
            model_name='player',
            name='player_photo',
            field=models.ManyToManyField(null=True, related_name='playerphoto', to='leagues.PlayerPhoto'),
        ),
    ]
