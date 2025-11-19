print("Loaded aws_settings.py, using S3 storage backend")
import os

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
AWS_S3_REGION_NAME = "us-east-1"  # or your region
AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
AWS_QUERYSTRING_AUTH = False

DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/"

# Optional: Raise a clear error if any variable is missing
missing = []
if not AWS_ACCESS_KEY_ID:
    missing.append("AWS_ACCESS_KEY")
if not AWS_SECRET_ACCESS_KEY:
    missing.append("AWS_SECRET_ACCESS_KEY")
if not AWS_STORAGE_BUCKET_NAME:
    missing.append("S3_BUCKET_NAME")
if missing:
    raise Exception(f"Missing required AWS environment variables: {', '.join(missing)}")
