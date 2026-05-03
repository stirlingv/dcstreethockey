# context_processors.py
from django.core.cache import cache
from django.urls import reverse

from leagues.models import DraftSession, HomePage

_HOMEPAGE_LOGO_CACHE_KEY = "homepage_logo_ctx"
_HOMEPAGE_LOGO_TTL = 60 * 5  # 5 minutes — logo changes rarely

_DRAFT_SIGNUP_CACHE_KEY = "draft_signup_url_ctx"
_DRAFT_SIGNUP_TTL = 60 * 5  # 5 minutes


def homepage_logo(request):
    result = cache.get(_HOMEPAGE_LOGO_CACHE_KEY)
    if result is None:
        try:
            homepage = HomePage.objects.first()
            logo = homepage.logo if homepage else None
        except HomePage.DoesNotExist:
            logo = None
        result = {"homepage_logo": logo}
        cache.set(_HOMEPAGE_LOGO_CACHE_KEY, result, _HOMEPAGE_LOGO_TTL)
    return result


def draft_signup_url(request):
    """Provides the signup URL for the currently open draft season, or None."""
    result = cache.get(_DRAFT_SIGNUP_CACHE_KEY)
    if result is None:
        session = (
            DraftSession.objects.filter(signups_open=True)
            .select_related("season")
            .first()
        )
        url = reverse("draft_signup", args=[session.season_id]) if session else None
        result = {"draft_signup_url": url}
        cache.set(_DRAFT_SIGNUP_CACHE_KEY, result, _DRAFT_SIGNUP_TTL)
    return result
