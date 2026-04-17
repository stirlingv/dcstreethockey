from __future__ import unicode_literals

from django.db import models
import datetime
import uuid

from django.db.models import indexes


YEAR_CHOICES = []
for r in range(2000, (datetime.datetime.now().year + 2)):
    YEAR_CHOICES.append((r, r))


class PlayerPhoto(models.Model):
    photo = models.ImageField(upload_to="players", blank=True)

    def __unicode__(self):
        return "Photo: %s" % (self.photo)

    def __str__(self):
        return self.__unicode__()


class Player(models.Model):
    GENDER_CHOICES = (
        (
            "F",
            "Female",
        ),
        (
            "M",
            "Male",
        ),
        (
            "NB",
            "Non-Binary",
        ),
        (
            "NA",
            "Prefer not to say",
        ),
    )
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(db_index=True, max_length=30)
    email = models.EmailField(null=True, blank=True)
    player_photo = models.ForeignKey(
        PlayerPhoto, null=True, blank=True, on_delete=models.SET_NULL
    )
    gender = models.CharField(
        max_length=2, choices=GENDER_CHOICES, default="M", null=True, blank=True
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive players won't appear in goalie dropdowns",
    )
    exclude_from_auto_deactivation = models.BooleanField(
        default=False,
        help_text="If checked, this player won't be auto-deactivated by the cleanup command (e.g., available subs not on a roster)",
    )

    class Meta:
        ordering = ("last_name",)
        unique_together = (
            "first_name",
            "last_name",
        )
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
        ]

    def __unicode__(self):
        return "%s, %s" % (self.last_name, self.first_name)

    def __str__(self):
        return self.__unicode__()


class Season(models.Model):
    SEASON_TYPE = ((1, "Spring"), (2, "Summer"), (3, "Fall"), (4, "Winter"))
    season_type = models.PositiveIntegerField(
        db_index=True, choices=SEASON_TYPE, null=True
    )
    year = models.IntegerField(
        db_index=True, choices=YEAR_CHOICES, default=datetime.datetime.now().year
    )
    is_current_season = models.BooleanField(null=True)

    class Meta:
        ordering = [
            "-year",
        ]

    def __unicode__(self):
        return "%s: %s" % (self.get_season_type_display(), self.year)

    def __str__(self):
        return self.__unicode__()


class Division(models.Model):
    DIVISION_TYPE = (
        (1, "Sunday D1"),
        (2, "Sunday D2"),
        (3, "Wednesday Draft League"),
        (4, "Monday A League"),
        (5, "Monday B League"),
    )
    division = models.IntegerField(choices=DIVISION_TYPE, null=True, unique=True)

    def __unicode__(self):
        return "%s" % (self.get_division_display())

    def __str__(self):
        return self.__unicode__()


class TeamPhoto(models.Model):
    photo = models.ImageField(upload_to="teams", blank=True)

    def __unicode__(self):
        return "Photo: %s" % (self.photo)

    def __str__(self):
        return self.__unicode__()


class Team(models.Model):
    CONFERENCE_TYPE = ((1, "East"), (2, "West"), (3, "A League"), (4, "B League"))
    team_name = models.CharField(db_index=True, max_length=55)
    team_color = models.CharField(max_length=30)
    division = models.ForeignKey(Division, null=True, on_delete=models.PROTECT)
    season = models.ForeignKey(Season, null=True, on_delete=models.PROTECT)
    conference = models.PositiveIntegerField(
        choices=CONFERENCE_TYPE, null=True, blank=True
    )
    team_photo = models.ForeignKey(TeamPhoto, null=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField()
    captain_access_code = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True
    )

    class Meta:
        unique_together = (
            "team_name",
            "season",
        )
        ordering = [
            "-season__year",
        ]
        indexes = [
            models.Index(fields=["team_name"]),
            models.Index(fields=["-season"]),
        ]

    def __unicode__(self):
        return "%s, %s" % (self.team_name, self.season)

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
        ordering = ("team__team_name", "-season__year")

    def __unicode__(self):
        return "%s: %s - %s - %s" % (self.team, self.win, self.loss, self.tie)

    def __str__(self):
        return self.__unicode__()


class Roster(models.Model):
    POSITION_TYPE = ((1, "Center"), (2, "Wing"), (3, "Defense"), (4, "Goalie"))
    player = models.ForeignKey(Player, null=True, on_delete=models.SET_NULL)
    team = models.ForeignKey(Team, null=True, on_delete=models.SET_NULL)
    position1 = models.PositiveIntegerField(choices=POSITION_TYPE, db_index=True)
    position2 = models.PositiveIntegerField(
        choices=POSITION_TYPE, null=True, blank=True
    )
    is_captain = models.BooleanField(default=False)
    is_substitute = models.BooleanField(default=False, db_index=True)
    is_primary_goalie = models.BooleanField(
        default=False,
        db_index=True,
        help_text="If checked, this goalie will be the default for goalie status pages. Only one goalie per team should be marked as primary.",
    )
    player_number = models.PositiveSmallIntegerField(blank=True, null=True)

    class Meta:
        ordering = ("team", "player__last_name")
        indexes = [
            models.Index(fields=["team", "position1"]),
            models.Index(fields=["team", "is_primary_goalie"]),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        # Validate: only one primary goalie per team
        if self.is_primary_goalie and self.team_id:
            existing_primary = Roster.objects.filter(
                team_id=self.team_id,
                is_primary_goalie=True,
            ).exclude(pk=self.pk)
            if existing_primary.exists():
                raise ValidationError(
                    {
                        "is_primary_goalie": f"This team already has a primary goalie: {existing_primary.first().player}. Uncheck their primary status first."
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __unicode__(self):
        return "%s: %s" % (self.team, str(self.player))

    def __str__(self):
        return self.__unicode__()


class Week(models.Model):
    division = models.ForeignKey(Division, null=True, on_delete=models.PROTECT)
    season = models.ForeignKey(Season, on_delete=models.PROTECT)
    date = models.DateField()
    is_cancelled = models.BooleanField(
        default=False,
        help_text="Check to mark all games for this division/date as cancelled. A banner will appear on the home page until the date passes.",
    )

    class Meta:
        ordering = [
            "-season__year",
            "-date",
        ]
        permissions = [
            (
                "can_quick_cancel_games",
                "Can quick-cancel games from admin dashboard",
            )
        ]
        indexes = [
            models.Index(fields=["-date"]),
        ]

    def __unicode__(self):
        return "Week: %s %s %s" % (self.date, self.division, self.season)

    def __str__(self):
        return self.__unicode__()


class MatchUp(models.Model):
    GOALIE_STATUS_CHOICES = (
        (1, "Confirmed"),
        (2, "Sub Needed"),
        (3, "Unconfirmed"),
    )
    week = models.ForeignKey(Week, null=True, on_delete=models.CASCADE, db_index=True)
    time = models.TimeField(db_index=True)
    awayteam = models.ForeignKey(
        Team, related_name="+", on_delete=models.PROTECT, db_index=True
    )
    hometeam = models.ForeignKey(
        Team, related_name="+", on_delete=models.PROTECT, db_index=True
    )
    ref1 = models.ForeignKey(
        "Ref",
        related_name="+",
        null=True,
        blank=True,
        default=None,
        on_delete=models.SET_NULL,
    )
    ref2 = models.ForeignKey(
        "Ref",
        related_name="+",
        null=True,
        blank=True,
        default=None,
        on_delete=models.SET_NULL,
    )
    notes = models.CharField(max_length=500, null=True, blank=True, default=None)
    is_postseason = models.BooleanField(default=False)
    is_championship = models.BooleanField(default=False)
    # Goalie status fields
    away_goalie = models.ForeignKey(
        "Player",
        related_name="away_goalie_matchups",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Leave blank to use team's roster goalie",
    )
    away_goalie_status = models.PositiveIntegerField(
        choices=GOALIE_STATUS_CHOICES, default=3
    )
    home_goalie = models.ForeignKey(
        "Player",
        related_name="home_goalie_matchups",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Leave blank to use team's roster goalie",
    )
    home_goalie_status = models.PositiveIntegerField(
        choices=GOALIE_STATUS_CHOICES, default=3
    )

    class Meta:
        ordering = (
            "-hometeam__season__year",
            "week",
            "time",
        )

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.away_goalie_status == 2 and self.away_goalie_id:
            errors["away_goalie"] = "Clear the away goalie when status is 'Sub Needed'."
        if self.home_goalie_status == 2 and self.home_goalie_id:
            errors["home_goalie"] = "Clear the home goalie when status is 'Sub Needed'."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.awayteam} vs {self.hometeam} on {self.week.date}"


class MatchUpGoalieStatus(MatchUp):
    """
    Proxy model for managing goalie status separately from general matchup administration.
    This allows for a dedicated admin interface focused on goalie assignments.
    """

    class Meta:
        proxy = True
        verbose_name = "Goalie Status"
        verbose_name_plural = "Goalie Statuses"


class Stat(models.Model):
    player = models.ForeignKey(Player, on_delete=models.PROTECT, db_index=True)
    team = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.PROTECT, db_index=True
    )
    matchup = models.ForeignKey(
        MatchUp, null=True, blank=True, on_delete=models.PROTECT, db_index=True
    )
    goals = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
    assists = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
    goals_against = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
    empty_net = models.PositiveSmallIntegerField(null=True, blank=True, default=0)

    class Meta:
        ordering = (
            "matchup__week__date",
            "matchup__time",
            "team__team_name",
            "player__last_name",
        )
        indexes = [
            models.Index(fields=["player", "team", "matchup"]),
        ]

    def __str__(self):
        return f"{self.matchup.week.date} - {self.team.team_name} {self.player.last_name}: G:{self.goals} A:{self.assists}"


class Ref(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)

    def __unicode__(self):
        return "%s" % (self.player)

    def __str__(self):
        return self.__unicode__()


# ---------------------------------------------------------------------------
# Wednesday Draft League – Signup & Draft Board
# ---------------------------------------------------------------------------


class SeasonSignup(models.Model):
    """A player's signup for a Wednesday Draft League season."""

    # Positions match Roster.POSITION_TYPE (1-4) so stats queries stay consistent.
    POSITION_CENTER = 1
    POSITION_WING = 2
    POSITION_DEFENSE = 3
    POSITION_GOALIE = 4
    POSITION_ONE_THING = 0  # secondary-only: "I only do one thing, period!"

    PRIMARY_POSITION_CHOICES = (
        (POSITION_CENTER, "Center"),
        (POSITION_WING, "Wing"),
        (POSITION_DEFENSE, "Defense"),
        (POSITION_GOALIE, "Goalie"),
    )
    SECONDARY_POSITION_CHOICES = (
        (POSITION_CENTER, "Center"),
        (POSITION_WING, "Wing"),
        (POSITION_DEFENSE, "Defense"),
        (POSITION_GOALIE, "Goalie"),
        (POSITION_ONE_THING, "I only do one thing, period!"),
    )

    CAPTAIN_YES = 1
    CAPTAIN_OVERDUE = 2
    CAPTAIN_LAST_RESORT = 3
    CAPTAIN_NO = 4
    CAPTAIN_INTEREST_CHOICES = (
        (CAPTAIN_YES, "Yes for sure please so I control who I play with"),
        (CAPTAIN_OVERDUE, "I can as I'm overdue to captain/help out"),
        (CAPTAIN_LAST_RESORT, "Only if you can't find 8"),
        (CAPTAIN_NO, "Nope, lazy or don't know enough"),
    )

    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name="signups")
    # Entered at signup time; may or may not match an existing Player record
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    email = models.EmailField()
    primary_position = models.PositiveIntegerField(
        choices=PRIMARY_POSITION_CHOICES,
    )
    secondary_position = models.PositiveIntegerField(
        choices=SECONDARY_POSITION_CHOICES,
    )
    captain_interest = models.PositiveIntegerField(
        choices=CAPTAIN_INTEREST_CHOICES,
        null=True,
        blank=True,
    )
    notes = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="Notes for the season",
        help_text="Out for travel, etc. beyond a random week or 2 that most miss.",
    )
    # Admin-only: set by commissioner after matching to an existing Player record
    is_returning = models.BooleanField(
        default=False,
        verbose_name="Returning player?",
        help_text="Set by commissioner. Has this player played in the Wednesday Draft League before?",
    )
    # Optionally linked to an existing Player for historical stats lookup
    linked_player = models.ForeignKey(
        Player,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="draft_signups",
        help_text="Link to existing player record to pull historical stats.",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("last_name", "first_name")

    def __str__(self):
        return f"{self.last_name}, {self.first_name} ({self.season})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def is_goalie(self):
        return self.primary_position == self.POSITION_GOALIE


class DraftSession(models.Model):
    """Configuration and state for a single Wednesday Draft League draft."""

    STATE_SETUP = "setup"
    STATE_DRAW = "draw"
    STATE_ACTIVE = "active"
    STATE_PAUSED = "paused"
    STATE_COMPLETE = "complete"
    STATE_CHOICES = (
        (STATE_SETUP, "Setup"),
        (STATE_DRAW, "Draw Phase"),
        (STATE_ACTIVE, "Active"),
        (STATE_PAUSED, "Paused"),
        (STATE_COMPLETE, "Complete"),
    )

    season = models.OneToOneField(
        Season, on_delete=models.PROTECT, related_name="draft_session"
    )
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=STATE_SETUP)
    num_teams = models.PositiveIntegerField(default=0)
    num_rounds = models.PositiveIntegerField(default=0)
    signups_open = models.BooleanField(
        default=False,
        help_text="When checked, the public signup form is active for this season.",
    )
    # Token for the commissioner control URL
    commissioner_token = models.UUIDField(default=uuid.uuid4, unique=True)
    # Spectator URL uses the session pk — no token needed (read-only)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when commissioner triggers "Finalize Draft" to create real Team/Roster records
    finalized_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Draft – {self.season} ({self.get_state_display()})"

    @property
    def current_pick(self):
        """Return (round_number, pick_index) of the next pick to be made."""
        picks = self.picks.order_by("round_number", "pick_number")
        total_picks = picks.count()
        expected = self.num_rounds * self.num_teams
        if total_picks >= expected:
            return None  # draft complete
        pick_in_round = total_picks % self.num_teams
        round_number = (total_picks // self.num_teams) + 1
        return round_number, pick_in_round

    def pick_order_for_round(self, round_number):
        """
        Return ordered list of DraftTeam PKs for a given round.
        Randomized: teams are shuffled deterministically using a seeded RNG.
        Snake: direction alternates, but randomized rounds are excluded from
        the parity count so the snake continues uninterrupted after them.
        """
        import random as _random

        teams = list(
            self.teams.exclude(draft_position__isnull=True).order_by("draft_position")
        )
        try:
            round_obj = self.rounds.get(round_number=round_number)
        except DraftRound.DoesNotExist:
            round_obj = None

        if round_obj and round_obj.order_type == DraftRound.ORDER_RANDOMIZED:
            rng = _random.Random(f"{self.pk}-{round_number}")
            rng.shuffle(teams)
            return [t.pk for t in teams]

        # Snake parity: count only non-randomized rounds before this one so
        # a randomized round doesn't break the snake direction.
        randomized_before = self.rounds.filter(
            round_number__lt=round_number,
            order_type=DraftRound.ORDER_RANDOMIZED,
        ).count()
        effective_round = round_number - randomized_before

        if effective_round % 2 == 0:
            return [t.pk for t in reversed(teams)]
        return [t.pk for t in teams]


class DraftRound(models.Model):
    """Per-round configuration. Defaults to snake; can be overridden to randomized."""

    ORDER_SNAKE = "snake"
    ORDER_RANDOMIZED = "randomized"
    ORDER_CHOICES = (
        (ORDER_SNAKE, "Snake (reverse of previous round)"),
        (ORDER_RANDOMIZED, "Re-randomized"),
    )

    session = models.ForeignKey(
        DraftSession, on_delete=models.CASCADE, related_name="rounds"
    )
    round_number = models.PositiveIntegerField()
    order_type = models.CharField(
        max_length=20, choices=ORDER_CHOICES, default=ORDER_SNAKE
    )

    class Meta:
        ordering = ("round_number",)
        unique_together = ("session", "round_number")

    def __str__(self):
        return f"Round {self.round_number} – {self.get_order_type_display()}"


class DraftTeam(models.Model):
    """A team/captain slot within a draft session."""

    session = models.ForeignKey(
        DraftSession, on_delete=models.CASCADE, related_name="teams"
    )
    captain = models.ForeignKey(
        SeasonSignup,
        on_delete=models.PROTECT,
        related_name="captained_teams",
    )
    team_name = models.CharField(
        max_length=55,
        blank=True,
        help_text="Defaults to '{First Name}'s Team' if left blank.",
    )
    # Set during draw phase; null until then
    draft_position = models.PositiveIntegerField(null=True, blank=True)
    # Round in which the captain is auto-drafted onto their own team.
    # When the draft reaches this round for this team, the captain is automatically
    # inserted as a pick and skipped for manual selection.
    captain_draft_round = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Round number in which this captain is automatically drafted onto their team. Leave blank if not applicable.",
    )
    # Unique URL token for captain to make picks
    captain_token = models.UUIDField(default=uuid.uuid4, unique=True)
    # Set after "Finalize Draft" creates the real Team record for this slot
    league_team = models.ForeignKey(
        "Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="draft_team",
        help_text="The real Team record created when this draft was finalized.",
    )

    class Meta:
        ordering = ("draft_position", "pk")
        unique_together = ("session", "captain")

    def save(self, *args, **kwargs):
        if not self.team_name:
            self.team_name = f"{self.captain.first_name}'s Team"
        super().save(*args, **kwargs)

    def __str__(self):
        pos = self.draft_position or "TBD"
        return f"{self.team_name} (Pick #{pos})"

    @property
    def picks(self):
        return self.draft_picks.order_by("round_number", "pick_number")


class DraftPick(models.Model):
    """A single pick made during the draft."""

    session = models.ForeignKey(
        DraftSession, on_delete=models.CASCADE, related_name="picks"
    )
    team = models.ForeignKey(
        DraftTeam, on_delete=models.CASCADE, related_name="draft_picks"
    )
    signup = models.ForeignKey(
        SeasonSignup,
        on_delete=models.PROTECT,
        related_name="draft_pick",
    )
    round_number = models.PositiveIntegerField()
    pick_number = models.PositiveIntegerField(
        help_text="Pick index within the round (0-based)."
    )
    picked_at = models.DateTimeField(auto_now_add=True)
    is_auto_captain = models.BooleanField(
        default=False,
        help_text="Set automatically when a captain is auto-drafted onto their own team.",
    )
    traded = models.BooleanField(
        default=False,
        help_text="Check if this pick was acquired via a trade. Original draft slot is preserved for reference.",
    )
    trade_note = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Optional note describing the trade (e.g. 'Swapped with Smith from Team B').",
    )

    class Meta:
        ordering = ("round_number", "pick_number")
        unique_together = (
            ("session", "signup"),  # player can only be picked once
            ("session", "round_number", "pick_number"),  # one pick per slot
        )

    def __str__(self):
        traded_marker = " [TRADED]" if self.traded else ""
        return (
            f"R{self.round_number}P{self.pick_number + 1} – "
            f"{self.team.team_name} picks {self.signup.full_name}{traded_marker}"
        )


class DraftChatMessage(models.Model):
    """A chat message posted during a draft session."""

    SENDER_COMMISSIONER = "commissioner"
    SENDER_CAPTAIN = "captain"
    SENDER_SPECTATOR = "spectator"
    SENDER_SYSTEM = "system"
    SENDER_TYPE_CHOICES = [
        (SENDER_COMMISSIONER, "Commissioner"),
        (SENDER_CAPTAIN, "Captain"),
        (SENDER_SPECTATOR, "Spectator"),
        (SENDER_SYSTEM, "System"),
    ]

    session = models.ForeignKey(
        DraftSession, on_delete=models.CASCADE, related_name="chat_messages"
    )
    sender_name = models.CharField(max_length=50)
    sender_type = models.CharField(max_length=20, choices=SENDER_TYPE_CHOICES)
    body = models.CharField(max_length=500)
    sent_at = models.DateTimeField(auto_now_add=True)
    deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["sent_at"]

    def __str__(self):
        return f"[{self.sender_name}] {self.body[:60]}"


class DraftChatReaction(models.Model):
    """An emoji reaction from one participant on a chat message."""

    message = models.ForeignKey(
        DraftChatMessage, on_delete=models.CASCADE, related_name="reactions"
    )
    emoji = models.CharField(max_length=10)
    sender_name = models.CharField(max_length=50)

    class Meta:
        unique_together = [("message", "emoji", "sender_name")]

    def __str__(self):
        return f"{self.sender_name} reacted {self.emoji} to message {self.message_id}"


class HomePage(models.Model):
    logo = models.ImageField(upload_to="homepage", null=True)
    announcement = models.CharField(max_length=1000, null=True, blank=True)
    d1_champ_photo = models.ImageField(upload_to="homepage", null=True)
    announcement1 = models.CharField(max_length=1000, null=True, blank=True)
    d2_champ_photo = models.ImageField(upload_to="homepage", null=True)
    announcement2 = models.CharField(max_length=1000, null=True, blank=True)
    twitter_posts = models.PositiveSmallIntegerField(null=False, blank=False, default=2)
    alt_title1 = models.CharField(max_length=1000, null=True, blank=True)
    alt_photo1 = models.ImageField(upload_to="homepage", null=True, blank=True)
    alt_announcement1 = models.CharField(max_length=1000, null=True, blank=True)
    alt_title2 = models.CharField(max_length=1000, null=True, blank=True)
    alt_photo2 = models.ImageField(upload_to="homepage", null=True, blank=True)
    alt_announcement2 = models.CharField(max_length=1000, null=True, blank=True)
    wed_champ_photo = models.ImageField(upload_to="homepage", null=True, blank=True)
    wed_champ_announcement = models.CharField(max_length=1000, null=True, blank=True)
    winter_title = models.CharField(max_length=1000, null=True, blank=True)
    winter_champ_photo = models.ImageField(upload_to="homepage", null=True, blank=True)
    winter_champ_announcement = models.CharField(max_length=1000, null=True, blank=True)
    alt_title3 = models.CharField(max_length=1000, null=True, blank=True)
    alt_photo3 = models.ImageField(upload_to="homepage", null=True, blank=True)
    alt_announcement3 = models.CharField(max_length=1000, null=True, blank=True)
    alt_title4 = models.CharField(max_length=1000, null=True, blank=True)
    alt_photo4 = models.ImageField(upload_to="homepage", null=True, blank=True)
    alt_announcement4 = models.CharField(max_length=1000, null=True, blank=True)
