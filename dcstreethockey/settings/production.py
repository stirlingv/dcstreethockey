from .base import *
from .aws_settings import *
import dj_database_url

DEBUG = False

DATABASES = {"default": dj_database_url.config()}
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True

# Static files: WhiteNoise's compressed manifest storage content-hashes
# filenames for long-term browser caching AND precompresses assets to gzip +
# brotli at collectstatic time, so CSS/JS are served compressed. This cuts
# outbound bandwidth (now metered in 1GB increments on Render's Hobby plan).
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
