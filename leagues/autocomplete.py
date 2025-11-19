# leagues/autocomplete.py
from dal import autocomplete
from .models import Player
from django.db.models import Q
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
