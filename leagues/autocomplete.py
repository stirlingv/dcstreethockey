# leagues/autocomplete.py
from dal import autocomplete
from .models import Player
from django.db.models import Q
from datetime import date
import logging

logger = logging.getLogger(__name__)


class PlayerAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Player.objects.none()
        qs = Player.objects.all()
        if self.q:
            qs = qs.filter(
                Q(first_name__icontains=self.q) | Q(last_name__icontains=self.q)
            )
        return qs

    def get(self, request, *args, **kwargs):
        try:
            response = super().get(request, *args, **kwargs)
            return response
        except Exception as e:
            logger.error(f"Error in PlayerAutocomplete: {e}")
            raise e


class GoalieAutocomplete(autocomplete.Select2QuerySetView):
    """
    Optimized autocomplete for goalie selection.
    Returns active goalies and recently played goalies.
    """

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Player.objects.none()

        current_year = date.today().year
        recent_years = [current_year, current_year - 1, current_year - 2]

        # Active goalies OR recently played goalies (even if inactive)
        qs = (
            Player.objects.filter(
                Q(roster__position1=4) | Q(roster__position2=4),
            )
            .filter(Q(is_active=True) | Q(roster__team__season__year__in=recent_years))
            .distinct()
            .order_by("last_name", "first_name")
        )

        if self.q:
            qs = qs.filter(
                Q(first_name__icontains=self.q) | Q(last_name__icontains=self.q)
            )

        return qs
