from __future__ import unicode_literals

from django.db import models
import datetime



YEAR_CHOICES = []
for r in range(1980, (datetime.datetime.now().year+2)):
	YEAR_CHOICES.append((r,r))

class Player(models.Model):
	first_name = models.CharField(max_length=30)
	last_name = models.CharField(max_length=30)
	email = models.EmailField(null=True, blank=True)
	photo = models.ImageField(null=True, blank=True)

	class Meta:
		ordering = ('last_name',)
		unique_together = ('first_name', 'last_name',)

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
	season_type = models.PositiveIntegerField(choices=SEASON_TYPE, null=True)
	year = models.IntegerField(choices=YEAR_CHOICES, default=datetime.datetime.now().year)
	is_current_season = models.NullBooleanField()

	def __unicode__(self):
		return u"%s: %s" % (self.get_season_type_display(), self.year)

	def __str__(self):
		return self.__unicode__()

class Division(models.Model):
	DIVISION_TYPE = (
	(1, 'Sunday D1'),
	(2, 'Sunday D2'),
	(3, 'Wednesday Draft League')
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
	(2, 'West')
	)
	team_name = models.CharField(max_length=30)
	team_color = models.CharField(max_length=30)
	division = models.ForeignKey(Division, null=True)
	season = models.ForeignKey(Season, null=True)
	conference = models.PositiveIntegerField(choices=CONFERENCE_TYPE, null=True, blank=True)
	team_photo = models.ForeignKey(TeamPhoto, null=True)
	is_active = models.BooleanField()

	class Meta:
		unique_together = ('team_name', 'season',)

	def __unicode__(self):
		return u"%s, %s" % (self.team_name, self.season)

	def __str__(self):
		return self.__unicode__()

class Team_Stat(models.Model):
	division = models.ForeignKey(Division, null=True)
	season = models.ForeignKey(Season, null=True)
	team = models.ForeignKey(Team, null=True)
	win = models.PositiveSmallIntegerField(default=0)
	loss = models.PositiveSmallIntegerField(default=0)
	tie = models.PositiveSmallIntegerField(default=0)
	goals_for = models.PositiveSmallIntegerField(default=0)
	goals_against = models.PositiveSmallIntegerField(default=0)

	class Meta:
		ordering = ('team__team_name',)

	def __unicode__(self):
		return u"%s: %s - %s - %s" % (self.team, self.win, self.loss, self.tie)

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
	team = models.ForeignKey(Team, null=True)
	position1 = models.PositiveIntegerField(choices=POSITION_TYPE)
	position2 = models.PositiveIntegerField(choices=POSITION_TYPE, null=True, blank=True)

	class Meta:
		ordering = ('team','player__last_name')

	def __unicode__(self):
		return u"%s: %s" % (self.team, str(self.player))

	def __str__(self):
		return self.__unicode__()

class Week(models.Model):
	game_number = models.PositiveIntegerField(default=1)
	division = models.ForeignKey(Division, null=True)
	season = models.ForeignKey(Season)
	date = models.DateField()

	def __unicode__(self):
		return u"Week: %s %s %s" % (self.game_number, self.division, self.season)

	def __str__(self):
		return self.__unicode__()

class MatchUp(models.Model):
	week = models.ForeignKey(Week, null=True)
	time = models.TimeField()
	awayteam = models.ForeignKey(Team, related_name="+")
	hometeam = models.ForeignKey(Team, related_name="+")
	ref1 = models.ForeignKey('Ref', related_name="+", null=True, blank=True, default=None)
	ref2 = models.ForeignKey('Ref', related_name="+", null=True, blank=True, default=None)
	notes = models.CharField(max_length=500, null=True, blank=True, default=None)
	is_postseason = models.BooleanField(default=False)

	class Meta:
		ordering = ('week','time',)

	def __unicode__(self):
		return u"Game %s: %s vs %s on %s" % (self.week.game_number, self.awayteam, self.hometeam, self.week.date)

	def __str__(self):
		return self.__unicode__()

class Stat(models.Model):
	player = models.ForeignKey(Player)
	team = models.ForeignKey(Team, null=True, blank=True)
	matchup = models.ForeignKey(MatchUp, null=True, blank=True)
	goals = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
	assists = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
	goals_against = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
	empty_net = models.PositiveSmallIntegerField(null=True, blank=True, default=0)

	class Meta:
		ordering = ('matchup__week__date','matchup__time','team__team_name','player__last_name',)

	def __unicode__(self):
		return u"%s - %s %s: G:%s A:%s " % (self.matchup.week.date, self.team.team_name, str(self.player), self.goals, self.assists)

	def __str__(self):
		return self.__unicode__()

class Ref(models.Model):
	player = models.ForeignKey(Player)

	def __unicode__(self):
		return u"%s" % (self.player)

	def __str__(self):
		return self.__unicode__()


class HomePage(models.Model):
	logo = models.ImageField(upload_to='homepage', null=True)
	d1_champ_photo = models.ImageField(upload_to='homepage', null=True)
	d2_champ_photo = models.ImageField(upload_to='homepage', null=True)
	announcement = models.CharField(max_length=1000, null=True, blank=True)
	announcement1 = models.CharField(max_length=1000, null=True, blank=True)
	announcement2 = models.CharField(max_length=1000, null=True, blank=True)
	twitter_posts = models.PositiveSmallIntegerField(null=False, blank=False, default=2)
	alt_photo1 = models.ImageField(upload_to='homepage', null=True, blank=True)
	alt_photo2 = models.ImageField(upload_to='homepage', null=True, blank=True)
	alt_title1 = models.CharField(max_length=1000, null=True, blank=True)
	alt_title2 = models.CharField(max_length=1000, null=True, blank=True)
	alt_announcement1 = models.CharField(max_length=1000, null=True, blank=True)
	alt_announcement2 = models.CharField(max_length=1000, null=True, blank=True)
	wed_champ_photo = models.ImageField(upload_to='homepage', null=True, blank=True)
	wed_champ_announcement = models.CharField(max_length=1000, null=True, blank=True)
	winter_champ_photo = models.ImageField(upload_to='homepage', null=True, blank=True)
	winter_champ_announcement = models.CharField(max_length=1000, null=True, blank=True)

