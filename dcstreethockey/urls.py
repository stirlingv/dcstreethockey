"""dcstreethockey URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.9/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""
from django.conf.urls import include, url
from django.contrib import admin
import core.views as core_view
from django.conf.urls.static import static
from django.conf import settings
import debug_toolbar
from django.urls import include, path
import leagues

urlpatterns = [
	url(r'^$', core_view.home, name='home'),
    url(r'^admin/', admin.site.urls),
    path('__debug__/', include(debug_toolbar.urls)),
    url(r'^leagues/', include('leagues.urls', namespace='leagues')),
]  + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

app_name="leagues"