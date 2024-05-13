# Generated by Django 3.1.14 on 2024-05-10 19:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0074_auto_20230703_1530'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='gender',
            field=models.CharField(blank=True, choices=[('F', 'Female'), ('M', 'Male'), ('NB', 'Non-Binary'), ('NA', 'Prefer not to say')], max_length=2, null=True),
        ),
        migrations.AlterField(
            model_name='roster',
            name='player_number',
            field=models.PositiveSmallIntegerField(blank=True, default='', null=True),
        ),
        migrations.AlterField(
            model_name='season',
            name='year',
            field=models.IntegerField(choices=[(2000, 2000), (2001, 2001), (2002, 2002), (2003, 2003), (2004, 2004), (2005, 2005), (2006, 2006), (2007, 2007), (2008, 2008), (2009, 2009), (2010, 2010), (2011, 2011), (2012, 2012), (2013, 2013), (2014, 2014), (2015, 2015), (2016, 2016), (2017, 2017), (2018, 2018), (2019, 2019), (2020, 2020), (2021, 2021), (2022, 2022), (2023, 2023), (2024, 2024), (2025, 2025)], db_index=True, default=2024),
        ),
    ]
