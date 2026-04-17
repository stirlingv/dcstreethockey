# context_processors.py
from django.core.cache import cache

from leagues.models import HomePage

_HOMEPAGE_LOGO_CACHE_KEY = "homepage_logo_ctx"
_HOMEPAGE_LOGO_TTL = 60 * 5  # 5 minutes — logo changes rarely


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
