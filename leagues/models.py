from __future__ import unicode_literals

from django.db import models
import datetime

    
YEAR_CHOICES = []
for r in range(1980, (datetime.datetime.now().year+1)):
    YEAR_CHOICES.append((r,r))

class Player(models.Model):
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    email = models.EmailField(null=True, blank=True)
    photo = models.ImageField(null=True, blank=True)

    def __unicode__(self): 
        return u"%s, %s" % (self.last_name, self.first_name)

class Season(models.Model):
    SEASON_TYPE = (
    (1, 'Spring'),
    (2, 'Summer'),
    (3, 'Fall'),
    (4, 'Winter')
    )
    season_type = models.PositiveIntegerField(choices=SEASON_TYPE, null=True)
    year = models.IntegerField(choices=YEAR_CHOICES, default=datetime.datetime.now().year)
    is_current_season = models.NullBooleanField()

    def __unicode__(self): 
        return u"%s: %s" % (self.get_season_type_display(), self.year)

class Division(models.Model):
    DIVISION_TYPE = (
    (1, 'Sunday D1'),
    (2, 'Sunday D2'),
    (3, 'Wednesday Draft League')
    )
    division = models.IntegerField(choices=DIVISION_TYPE, null=True, unique=True)

    def __unicode__(self): 
        return u"%s" % (self.get_division_display())

class Team(models.Model):
    team_name = models.CharField(max_length=30, unique=True)
    team_color = models.CharField(max_length=30)
    division = models.ForeignKey(Division, null=True)
    is_active = models.BooleanField()

    def __unicode__(self): 
        return u"%s" % (self.team_name)

class Team_Stat(models.Model):
    division = models.ForeignKey(Division, null=True)
    season = models.ForeignKey(Season, null=True)
    team = models.ForeignKey(Team, null=True)
    win = models.PositiveSmallIntegerField(default=0)
    loss = models.PositiveSmallIntegerField(default=0)
    tie = models.PositiveSmallIntegerField(default=0)
    goals_for = models.PositiveSmallIntegerField(default=0)
    goals_against = models.PositiveSmallIntegerField(default=0)

    def __unicode__(self): 
        return u"%s: %s" % (self.season, self.get_division_display())
        
class Roster(models.Model):
    POSITION_TYPE = (
    (1, 'Center'),
    (2, 'Wing'),
    (3, 'Defense'),
    (4, 'Goalie')
    )
    player = models.ForeignKey(Player, related_name="+", null=True)
    team = models.ForeignKey(Team, null=True)
    position1 = models.PositiveIntegerField(choices=POSITION_TYPE)
    position2 = models.PositiveIntegerField(choices=POSITION_TYPE, null=True, blank=True)

    def __unicode__(self): 
        return u"%s: %s" % (self.team, str(self.player))

class Game(models.Model):
    gamenumber = models.PositiveIntegerField(default=1)
    division = models.ForeignKey(Division, null=True)
    season = models.ForeignKey(Season)
    date = models.DateField()

    def __unicode__(self): 
        return u"Game: %s" % (self.gamenumber)

class MatchUp(models.Model):
    game = models.ForeignKey(Game, null=True)
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
    division = models.ForeignKey(Division, null=True)
    season = models.ForeignKey(Season)
    player = models.ForeignKey(Player)
    team = models.ForeignKey(Team, null=True)
    matchup = models.ForeignKey(MatchUp, null=True)
    assists = models.PositiveSmallIntegerField()
    goals_against = models.PositiveSmallIntegerField()
    en = models.PositiveSmallIntegerField()

class Ref(models.Model):
    player = models.ForeignKey(Player)
    
    def __unicode__(self): 
        return u"%s" % (self.player)


