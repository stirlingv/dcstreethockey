from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/draft/(?P<session_pk>\d+)/$", consumers.DraftConsumer.as_asgi()),
]
