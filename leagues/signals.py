"""
Keep the computed standings in step with the games.

Every change to a stat row or a game refreshes the record of the teams in
that game's season and division. Only seasons with ``standings_from_games``
are touched; the recompute is a no-op for seasons kept by hand.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from leagues.models import MatchUp, Stat
from leagues.results import recompute_for_week_id


@receiver(post_save, sender=Stat)
@receiver(post_delete, sender=Stat)
def _stat_changed(sender, instance, **kwargs):
    week_id = (
        MatchUp.objects.filter(pk=instance.matchup_id)
        .values_list("week_id", flat=True)
        .first()
    )
    if week_id:
        recompute_for_week_id(week_id)


@receiver(post_save, sender=MatchUp)
@receiver(post_delete, sender=MatchUp)
def _matchup_changed(sender, instance, **kwargs):
    if instance.week_id:
        recompute_for_week_id(instance.week_id)
    # A game moved to a week in another season or division leaves the old
    # standings behind, so refresh those too.
    previous = getattr(instance, "_loaded_week_id", None)
    if previous and previous != instance.week_id:
        recompute_for_week_id(previous)
