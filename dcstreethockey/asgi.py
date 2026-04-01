import os
import sys
import types

# dal_select2 imports django.utils.itercompat which was removed in Django 4.0.
if "django.utils.itercompat" not in sys.modules:
    _compat = types.ModuleType("django.utils.itercompat")
    _compat.is_iterable = lambda x: hasattr(x, "__iter__")
    sys.modules["django.utils.itercompat"] = _compat

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dcstreethockey.settings")

django_asgi_app = get_asgi_application()

from leagues.routing import websocket_urlpatterns  # noqa: E402 — must be after setup

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
