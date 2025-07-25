from __future__ import unicode_literals

from django.db import models
import datetime

from django.db.models import indexes



YEAR_CHOICES = []
for r in range(2000, (datetime.datetime.now().year+2)):
    YEAR_CHOICES.append((r,r))

class PlayerPhoto(models.Model):
    photo = models.ImageField(upload_to='players', blank=True)

    def __unicode__(self):
        return u"Photo: %s" % (self.photo)

    def __str__(self):
        return self.__unicode__()

class Player(models.Model):
    GENDER_CHOICES = (
        ('F', 'Female',),
        ('M', 'Male',),
        ('NB', 'Non-Binary',),
        ('NA', 'Prefer not to say',)
    )
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(db_index=True, max_length=30)
    email = models.EmailField(null=True, blank=True)
    player_photo = models.ForeignKey(PlayerPhoto, null=True, blank=True, on_delete=models.SET_NULL)
    gender = models.CharField(max_length=2,choices=GENDER_CHOICES, default='M', null=True, blank=True)

    class Meta:
        ordering = ('last_name',)
        unique_together = ('first_name', 'last_name',)
        indexes = [
            models.Index(fields=['last_name', 'first_name']),
        ]

    def __unicode__(self):
        return u"%s, %s" % (self.last_name, self.first_name)

    def __str__(self):
        return self.__unicode__()

class Season(models.Model):
    SEASON_TYPE = (
    (1, 'Spring'),
    (2, 'Summer'),
    (3, 'Fall'),
    (4, 'Winter')
    )
    season_type = models.PositiveIntegerField(db_index=True, choices=SEASON_TYPE, null=True)
    year = models.IntegerField(db_index=True, choices=YEAR_CHOICES, default=datetime.datetime.now().year)
    is_current_season = models.BooleanField(null=True)

    class Meta:
        ordering = ['-year',]
    def __unicode__(self):
        return u"%s: %s" % (self.get_season_type_display(), self.year)

    def __str__(self):
        return self.__unicode__()

class Division(models.Model):
    DIVISION_TYPE = (
    (1, 'Sunday D1'),
    (2, 'Sunday D2'),
    (3, 'Wednesday Draft League'),
    (4, 'Monday A League'),
    (5, 'Monday B League')
    )
    division = models.IntegerField(choices=DIVISION_TYPE, null=True, unique=True)

    def __unicode__(self):
        return u"%s" % (self.get_division_display())

    def __str__(self):
        return self.__unicode__()

class TeamPhoto(models.Model):
    photo = models.ImageField(upload_to='teams', blank=True)

    def __unicode__(self):
        return u"Photo: %s" % (self.photo)

    def __str__(self):
        return self.__unicode__()

class Team(models.Model):
    CONFERENCE_TYPE = (
    (1, 'East'),
    (2, 'West'),
    (3, 'A League'),
    (4, 'B League')
    )
    team_name = models.CharField(db_index=True, max_length=55)
    team_color = models.CharField(max_length=30)
    division = models.ForeignKey(Division, null=True, on_delete=models.PROTECT)
    season = models.ForeignKey(Season, null=True, on_delete=models.PROTECT)
    conference = models.PositiveIntegerField(choices=CONFERENCE_TYPE, null=True, blank=True)
    team_photo = models.ForeignKey(TeamPhoto, null=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField()

    class Meta:
        unique_together = ('team_name', 'season',)
        ordering = ['-season__year',]
        indexes = [
            models.Index(fields=['team_name']),
            models.Index(fields=['-season']),
        ]

    def __unicode__(self):
        return u"%s, %s" % (self.team_name, self.season)

    def __str__(self):
        return self.__unicode__()

class Team_Stat(models.Model):
    division = models.ForeignKey(Division, null=True, on_delete=models.PROTECT)
    season = models.ForeignKey(Season, null=True, on_delete=models.PROTECT)
    team = models.ForeignKey(Team, null=True, on_delete=models.PROTECT)
    win = models.PositiveSmallIntegerField(default=0)
    otw = models.PositiveSmallIntegerField(default=0)
    loss = models.PositiveSmallIntegerField(default=0)
    otl = models.PositiveSmallIntegerField(default=0)
    tie = models.PositiveSmallIntegerField(default=0)
    goals_for = models.PositiveSmallIntegerField(default=0)
    goals_against = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ('team__team_name', '-season__year')

    def __unicode__(self):
        return u"%s: %s - %s - %s" % (self.team, self.win, self.loss, self.tie )

    def __str__(self):
        return self.__unicode__()

class Roster(models.Model):
    POSITION_TYPE = (
    (1, 'Center'),
    (2, 'Wing'),
    (3, 'Defense'),
    (4, 'Goalie')
    )
    player = models.ForeignKey(Player, null=True, on_delete=models.SET_NULL)
    team = models.ForeignKey(Team, null=True, on_delete=models.SET_NULL)
    position1 = models.PositiveIntegerField(choices=POSITION_TYPE)
    position2 = models.PositiveIntegerField(choices=POSITION_TYPE, null=True, blank=True)
    is_captain = models.BooleanField(default=False)
    is_substitute = models.BooleanField(default=False)
    player_number = models.PositiveSmallIntegerField(blank=True, null=True, default="")

    class Meta:
        ordering = ('team','player__last_name')

    def __unicode__(self):
        return u"%s: %s" % (self.team, str(self.player))

    def __str__(self):
        return self.__unicode__()

class Week(models.Model):
    division = models.ForeignKey(Division, null=True, on_delete=models.PROTECT)
    season = models.ForeignKey(Season, on_delete=models.PROTECT)
    date = models.DateField()

    class Meta:
        ordering = ['-season__year','-date',]
        indexes=[
            models.Index(fields=['-date']),
        ]
    def __unicode__(self):
        return u"Week: %s %s %s" % (self.date, self.division, self.season)

    def __str__(self):
        return self.__unicode__()

class MatchUp(models.Model):
    week = models.ForeignKey(Week, null=True, on_delete=models.CASCADE, db_index=True)
    time = models.TimeField(db_index=True)
    awayteam = models.ForeignKey(Team, related_name="+", on_delete=models.PROTECT, db_index=True)
    hometeam = models.ForeignKey(Team, related_name="+", on_delete=models.PROTECT, db_index=True)
    ref1 = models.ForeignKey('Ref', related_name="+", null=True, blank=True, default=None, on_delete=models.SET_NULL)
    ref2 = models.ForeignKey('Ref', related_name="+", null=True, blank=True, default=None, on_delete=models.SET_NULL)
    notes = models.CharField(max_length=500, null=True, blank=True, default=None)
    is_postseason = models.BooleanField(default=False)
    is_championship = models.BooleanField(default=False)

    class Meta:
        ordering = ('-hometeam__season__year','week','time',)

    def __str__(self):
        return f"{self.awayteam} vs {self.hometeam} on {self.week.date}"

class Stat(models.Model):
    player = models.ForeignKey(Player, on_delete=models.PROTECT, db_index=True)
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.PROTECT, db_index=True)
    matchup = models.ForeignKey(MatchUp, null=True, blank=True, on_delete=models.PROTECT, db_index=True)
    goals = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
    assists = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
    goals_against = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
    empty_net = models.PositiveSmallIntegerField(null=True, blank=True, default=0)

    class Meta:
        ordering = ('matchup__week__date', 'matchup__time', 'team__team_name', 'player__last_name',)
        indexes = [
            models.Index(fields=['player', 'team', 'matchup']),
        ]

    def __str__(self):
        return f"{self.matchup.week.date} - {self.team.team_name} {self.player.last_name}: G:{self.goals} A:{self.assists}"

class Ref(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)

    def __unicode__(self):
        return u"%s" % (self.player)

    def __str__(self):
        return self.__unicode__()

class HomePage(models.Model):
    logo = models.ImageField(upload_to='homepage', null=True)
    announcement = models.CharField(max_length=1000, null=True, blank=True)
    d1_champ_photo = models.ImageField(upload_to='homepage', null=True)
    announcement1 = models.CharField(max_length=1000, null=True, blank=True)
    d2_champ_photo = models.ImageField(upload_to='homepage', null=True)
    announcement2 = models.CharField(max_length=1000, null=True, blank=True)
    twitter_posts = models.PositiveSmallIntegerField(null=False, blank=False, default=2)
    alt_title1 = models.CharField(max_length=1000, null=True, blank=True)
    alt_photo1 = models.ImageField(upload_to='homepage', null=True, blank=True)
    alt_announcement1 = models.CharField(max_length=1000, null=True, blank=True)
    alt_title2 = models.CharField(max_length=1000, null=True, blank=True)
    alt_photo2 = models.ImageField(upload_to='homepage', null=True, blank=True)
    alt_announcement2 = models.CharField(max_length=1000, null=True, blank=True)
    wed_champ_photo = models.ImageField(upload_to='homepage', null=True, blank=True)
    wed_champ_announcement = models.CharField(max_length=1000, null=True, blank=True)
    winter_title = models.CharField(max_length=1000, null=True, blank=True)
    winter_champ_photo = models.ImageField(upload_to='homepage', null=True, blank=True)
    winter_champ_announcement = models.CharField(max_length=1000, null=True, blank=True)
    alt_title3 = models.CharField(max_length=1000, null=True, blank=True)
    alt_photo3 = models.ImageField(upload_to='homepage', null=True, blank=True)
    alt_announcement3 = models.CharField(max_length=1000, null=True, blank=True)
    alt_title4 = models.CharField(max_length=1000, null=True, blank=True)
    alt_photo4 = models.ImageField(upload_to='homepage', null=True, blank=True)
    alt_announcement4 = models.CharField(max_length=1000, null=True, blank=True)
