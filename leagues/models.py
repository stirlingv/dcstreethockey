from __future__ import unicode_literals

from django.db import models
import datetime

class Player(models.Model):
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    email = models.EmailField(null=True, blank=True)
    photo = models.ImageField(null=True, blank=True)

    def __unicode__(self): 
        return u"%s, %s" % (self.last_name, self.first_name)

class Team(models.Model):
    team_name = models.CharField(max_length=30)
    team_color = models.CharField(max_length=30)
    is_active = models.BooleanField()

    def __unicode__(self): 
        return u"%s" % (self.team_name)

class Roster(models.Model):
    POSITION_TYPE = (
    (1, 'Center'),
    (2, 'Wing'),
    (3, 'Defense'),
    (4, 'Goalie')
    )
    player = models.ForeignKey(Player, related_name="+", null=True)
    team = models.ForeignKey(Team)
    position1 = models.PositiveIntegerField(choices=POSITION_TYPE)
    position2 = models.PositiveIntegerField(choices=POSITION_TYPE)

    def __unicode__(self): 
        return u"%s: %s" % (self.team, str(self.player))
 # first_name = models.ForeignKey(Player, db_column='first_name', null=True, related_name="+")
 #    last_name = models.ForeignKey(Player, db_column='last_name', null=True, related_name="+")
    
YEAR_CHOICES = []
for r in range(1980, (datetime.datetime.now().year+1)):
    YEAR_CHOICES.append((r,r))

class Season(models.Model):
    SEASON_TYPE = (
    (1, 'Spring'),
    (2, 'Summer'),
    (3, 'Fall'),
    (4, 'Winter')
    )
    team = models.ForeignKey(Team)
    is_champion = models.NullBooleanField()
    season_type = models.PositiveIntegerField(choices=SEASON_TYPE, null=True)
    year = models.IntegerField(choices=YEAR_CHOICES, default=datetime.datetime.now().year)
    is_current_season = models.NullBooleanField()

    def __unicode__(self): 
        return u"%s: %s" % (self.get_season_type_display(), self.year)

class League(models.Model):
    DIVISION_TYPE = (
    (1, 'Sunday D1'),
    (2, 'Sunday D2'),
    (3, 'Wednesday Draft League')
    )
    season = models.ForeignKey(Season)
    team = models.ForeignKey(Team)
    division = models.IntegerField(choices=DIVISION_TYPE, null=True)
    win = models.PositiveSmallIntegerField(default=0)
    loss = models.PositiveSmallIntegerField(default=0)
    tie = models.PositiveSmallIntegerField(default=0)
    goals_for = models.PositiveSmallIntegerField(default=0)
    goals_against = models.PositiveSmallIntegerField(default=0)

    def __unicode__(self): 
        return u"%s: %s" % (self.season, self.get_division_display())

class Game(models.Model):
    season = models.ForeignKey(Season)
    league = models.ForeignKey(League, null=True)
    date = models.DateField()
    time = models.TimeField()
    awayteam = models.ForeignKey(Team, related_name="+")
    hometeam = models.ForeignKey(Team, related_name="+")
    ref1 = models.ForeignKey('Ref', related_name="+", null=True, blank=True, default=None)
    ref2 = models.ForeignKey('Ref', related_name="+", null=True, blank=True, default=None)
    notes = models.CharField(max_length=500, null=True, blank=True, default=None)
    is_postseason = models.BooleanField(default=False)

    def __unicode__(self): 
        return u"%s vs %s" % (self.awayteam, self.hometeam)

class Stat(models.Model):
    season = models.ForeignKey(Season)
    league = models.ForeignKey(League, null=True)
    player = models.ForeignKey(Player)
    game = models.ForeignKey(Game)
    assists = models.PositiveSmallIntegerField()
    goals_against = models.PositiveSmallIntegerField()
    en = models.PositiveSmallIntegerField()

class Ref(models.Model):
    first_name = models.CharField(max_length=30, null=True)
    last_name = models.CharField(max_length=30, null=True)
    player = models.ForeignKey(Player)
    
    def __unicode__(self): 
        return u"%s, %s" % (self.last_name, self.first_name)


