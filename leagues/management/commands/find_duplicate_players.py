from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count

from leagues.models import Player, Roster


# Common nickname mappings
NICKNAME_MAP = {
    "richard": ["rich", "rick", "ricky", "dick"],
    "michael": ["mike", "mikey", "mick"],
    "william": ["will", "bill", "billy", "willy"],
    "robert": ["rob", "bob", "bobby", "robbie"],
    "james": ["jim", "jimmy", "jamie"],
    "joseph": ["joe", "joey"],
    "thomas": ["tom", "tommy"],
    "christopher": ["chris", "cj"],
    "matthew": ["matt", "matty"],
    "anthony": ["tony", "ant"],
    "daniel": ["dan", "danny"],
    "david": ["dave", "davey"],
    "edward": ["ed", "eddie", "ted", "teddy"],
    "patrick": ["pat", "patty", "paddy"],
    "stephen": ["steve", "stevie"],
    "steven": ["steve", "stevie"],
    "andrew": ["andy", "drew"],
    "nicholas": ["nick", "nicky"],
    "jonathan": ["jon", "jonny", "john"],
    "john": ["jon", "johnny", "jack"],
    "benjamin": ["ben", "benny"],
    "alexander": ["alex", "al"],
    "timothy": ["tim", "timmy"],
    "charles": ["charlie", "chuck", "chas"],
    "kenneth": ["ken", "kenny"],
    "gregory": ["greg", "gregg"],
    "jeffrey": ["jeff", "geoff"],
    "ronald": ["ron", "ronnie"],
    "donald": ["don", "donnie"],
    "raymond": ["ray"],
    "lawrence": ["larry", "lars"],
    "gerald": ["gerry", "jerry"],
    "samuel": ["sam", "sammy"],
    "peter": ["pete", "petey"],
    "henry": ["hank", "harry"],
    "douglas": ["doug", "dougie"],
    "dennis": ["denny"],
    "harold": ["hal", "harry"],
    "eugene": ["gene"],
    "phillip": ["phil"],
    "vincent": ["vince", "vinny"],
    "walter": ["walt", "wally"],
    "frederick": ["fred", "freddy", "freddie"],
    "albert": ["al", "bert", "bertie"],
    "arthur": ["art", "artie"],
    "nathan": ["nate", "nat"],
    "zachary": ["zach", "zack"],
    "jacob": ["jake"],
    "joshua": ["josh"],
    "brian": ["bri"],
    "kevin": ["kev"],
    "jason": ["jay"],
    "justin": ["just"],
    "brandon": ["brand"],
    "jessica": ["jess", "jessie"],
    "jennifer": ["jen", "jenny"],
    "elizabeth": ["liz", "lizzy", "beth", "betty", "eliza"],
    "katherine": ["kate", "kathy", "katie", "kat"],
    "catherine": ["kate", "cathy", "katie", "cat"],
    "margaret": ["maggie", "meg", "peggy", "marge"],
    "patricia": ["pat", "patty", "trish"],
    "rebecca": ["becky", "becca"],
    "christine": ["chris", "chrissy", "tina"],
    "christina": ["chris", "chrissy", "tina"],
    "stephanie": ["steph", "stephie"],
    "samantha": ["sam", "sammy"],
    "alexandra": ["alex", "lexi"],
    "victoria": ["vicky", "tori"],
    "natalie": ["nat"],
    "nicholas": ["nick", "nicky", "nico"],
}


def get_name_variants(first_name):
    """Get all possible variants of a first name."""
    name_lower = first_name.lower().strip()
    variants = {name_lower}

    # Check if this name is a full name with nicknames
    if name_lower in NICKNAME_MAP:
        variants.update(NICKNAME_MAP[name_lower])

    # Check if this name is a nickname of a full name
    for full_name, nicknames in NICKNAME_MAP.items():
        if name_lower in nicknames:
            variants.add(full_name)
            variants.update(nicknames)

    return variants


class Command(BaseCommand):
    help = "Find potential duplicate players based on similar names"

    def add_arguments(self, parser):
        parser.add_argument(
            "--last-name",
            type=str,
            help="Filter to a specific last name",
        )
        parser.add_argument(
            "--show-rosters",
            action="store_true",
            help="Show roster history for each potential duplicate",
        )

    def handle(self, *args, **options):
        last_name_filter = options.get("last_name")
        show_rosters = options["show_rosters"]

        players = Player.objects.all().order_by("last_name", "first_name")
        if last_name_filter:
            players = players.filter(last_name__iexact=last_name_filter)

        # Group players by last name
        by_last_name = defaultdict(list)
        for player in players:
            by_last_name[player.last_name.lower().strip()].append(player)

        # Find potential duplicates
        duplicate_groups = []

        for last_name, group in by_last_name.items():
            if len(group) < 2:
                continue

            # Check for exact first name matches
            first_names = defaultdict(list)
            for player in group:
                first_names[player.first_name.lower().strip()].append(player)

            for first_name, exact_matches in first_names.items():
                if len(exact_matches) > 1:
                    duplicate_groups.append(("EXACT MATCH", last_name, exact_matches))

            # Check for nickname matches
            processed = set()
            for i, player1 in enumerate(group):
                if player1.id in processed:
                    continue

                variants1 = get_name_variants(player1.first_name)
                matches = [player1]

                for player2 in group[i + 1 :]:
                    if player2.id in processed:
                        continue

                    name2_lower = player2.first_name.lower().strip()
                    if name2_lower in variants1 or any(
                        v in get_name_variants(player2.first_name) for v in variants1
                    ):
                        # Don't double-count exact matches
                        if player1.first_name.lower() != player2.first_name.lower():
                            matches.append(player2)
                            processed.add(player2.id)

                if len(matches) > 1:
                    processed.add(player1.id)
                    duplicate_groups.append(("NICKNAME MATCH", last_name, matches))

        # Output results
        if not duplicate_groups:
            self.stdout.write(self.style.SUCCESS("No potential duplicates found!"))
            return

        self.stdout.write(
            self.style.WARNING(
                f"\nFound {len(duplicate_groups)} potential duplicate groups:\n"
            )
        )

        for match_type, last_name, players in duplicate_groups:
            self.stdout.write(
                self.style.HTTP_INFO(f"\n[{match_type}] {last_name.title()}:")
            )

            for player in players:
                roster_count = Roster.objects.filter(player=player).count()
                status = "ACTIVE" if player.is_active else "inactive"
                self.stdout.write(
                    f"  • ID {player.id}: {player.first_name} {player.last_name} "
                    f"({roster_count} roster entries, {status})"
                )

                if show_rosters:
                    rosters = (
                        Roster.objects.filter(player=player)
                        .select_related("team", "team__season")
                        .order_by("-team__season__year")
                    )
                    for roster in rosters[:5]:  # Show last 5
                        season = roster.team.season
                        self.stdout.write(
                            f"      - {season.year} {season.get_season_type_display()}: "
                            f"{roster.team.team_name}"
                        )
                    if rosters.count() > 5:
                        self.stdout.write(f"      ... and {rosters.count() - 5} more")

        self.stdout.write(
            self.style.WARNING(
                f"\n\nTo merge duplicates, update Roster/Stat records to point to "
                f"the correct player ID, then delete the duplicate Player record."
            )
        )
