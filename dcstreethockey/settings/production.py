from .base import *
from .aws_settings import *
import dj_database_url

DATABASES = {'default': dj_database_url.config()}
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True