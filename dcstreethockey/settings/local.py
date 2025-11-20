import os

# Define BASE_DIR for local settings
BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

from .base import *

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Override file storage for local development and CI
DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"
