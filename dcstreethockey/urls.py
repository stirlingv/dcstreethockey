from django.contrib import admin
import core.views as core_view
from django.conf.urls.static import static
from django.conf import settings
import debug_toolbar
from django.urls import include, path
from django.urls import include, re_path
from django.urls import get_resolver

urlpatterns = [
    path('', core_view.home, name='home'),
    path('admin/', admin.site.urls),
    path('leagues/', include('leagues.urls', namespace='leagues')), 
    path('__debug__/', include(debug_toolbar.urls)),
]  + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


for url_pattern in get_resolver().url_patterns:
    print(url_pattern)