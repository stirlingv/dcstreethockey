from __future__ import unicode_literals

from django.db import models

class Player(models.Model):
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    email = models.EmailField()
    photo = models.ImageField(null=True)

    def __unicode__(self): 
        return "%s, %s" % (self.last_name, self.first_name)

class Team(models.Model):
    team_name = models.CharField(max_length=30)
    team_color = models.CharField(max_length=30)
    is_active = models.BooleanField()

    def __unicode__(self): 
        return "%s" % (self.team_name)

class Roster(models.Model):
    POSITION_TYPE = (
    	(1, 'Center'),
    	(2, 'Wing'),
    	(3, 'Defense'),
    	(4, 'Goalie')
    	)
    player = models.ForeignKey(Player)
    team = models.ForeignKey(Team)
    position1 = models.PositiveIntegerField(choices=POSITION_TYPE)
    position2 = models.PositiveIntegerField(choices=POSITION_TYPE)
    
class Season(models.Model):
	SEASON_TYPE = (
        (1, 'Spring'),
        (2, 'Summer'),
        (3, 'Fall'),
        (4, 'Winter')
    )
    team = models.ForeignKey(Team)
    is_champion = models.NullBooleanField()
    season_type = models.PositiveIntegerField(choices=SEASON_TYPE)
    year = models.CharField(max_length=4)
    is_current_season = models.BooleanField()

    def __unicode__(self): 
        return "%s: %s" % (self.season_type, self.year)

class League(models.Model):
    season = models.ForeignKey(Season)
    team = models.ForeignKey(Team)
    division = models.PositiveSmallIntegerField()
    win = models.PositiveSmallIntegerField()
    loss = models.PositiveSmallIntegerField()
    tie = models.PositiveSmallIntegerField()
    goals_for = models.PositiveSmallIntegerField()
    goals_against = models.PositiveSmallIntegerField()

class Game(models.Model):
    season = models.ForeignKey(Season)
    league = models.ForeignKey(League)
    date = models.DateField()
    time = models.TimeField()
    awayteam = models.ForeignKey(Team, related_name="+")
    hometeam = models.ForeignKey(Team, related_name="+")
    ref1 = models.CharField(max_length=50)
    ref2 = models.CharField(max_length=50)
    notes = models.CharField(max_length=500)
    is_regularseasion = models.BooleanField()

    def __unicode__(self): 
        return "%s vs %s" % (self.awayteam, self.hometeam)

class Stat(models.Model):
    season = models.ForeignKey(Season)
    league = models.ForeignKey(League)
    player = models.ForeignKey(Player)
    game = models.ForeignKey(Game)
    assists = models.PositiveSmallIntegerField()
    goals_against = models.PositiveSmallIntegerField()
    en = models.PositiveSmallIntegerField()

class Ref(models.Model):
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    player = models.ForeignKey(Player)