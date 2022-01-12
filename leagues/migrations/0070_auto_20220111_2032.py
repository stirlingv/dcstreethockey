# Generated by Django 3.1.13 on 2022-01-12 01:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0069_auto_20210909_1521'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='week',
            options={'ordering': ['-season__year', '-date']},
        ),
        migrations.RemoveIndex(
            model_name='week',
            name='leagues_wee_game_nu_b321e6_idx',
        ),
        migrations.RemoveField(
            model_name='week',
            name='game_number',
        ),
        migrations.AlterField(
            model_name='season',
            name='year',
            field=models.IntegerField(choices=[(2000, 2000), (2001, 2001), (2002, 2002), (2003, 2003), (2004, 2004), (2005, 2005), (2006, 2006), (2007, 2007), (2008, 2008), (2009, 2009), (2010, 2010), (2011, 2011), (2012, 2012), (2013, 2013), (2014, 2014), (2015, 2015), (2016, 2016), (2017, 2017), (2018, 2018), (2019, 2019), (2020, 2020), (2021, 2021), (2022, 2022), (2023, 2023)], db_index=True, default=2022),
        ),
        migrations.AddIndex(
            model_name='week',
            index=models.Index(fields=['-date'], name='leagues_wee_date_9ecc97_idx'),
        ),
    ]
