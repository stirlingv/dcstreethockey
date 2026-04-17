from .base import *
from .aws_settings import *
import dj_database_url

DEBUG = False

DATABASES = {"default": dj_database_url.config()}
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True

# Static files: content-hashed filenames enable long-term browser caching
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
