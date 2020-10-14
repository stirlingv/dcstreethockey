import os

AWS_QUERYSTRING_AUTH = False
AWS_ACCESS_KEY_ID = os.environ['AWS_ACCESS_KEY']
AWS_SECRET_ACCESS_KEY = os.environ['AWS_SECRET_ACCESS_KEY']
AWS_STORAGE_BUCKET_NAME = os.environ['S3_BUCKET_NAME']
MEDIA_URL = 'https://%s.s3.amazonaws.com/' % AWS_STORAGE_BUCKET_NAME

DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
STATICFILES_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

# S3DIRECT_ENDPOINT = 's3.amazonaws.com'  # http://docs.aws.amazon.com/general/latest/gr/rande.html#s3_region
# S3DIRECT_DIR = 's3direct'  # (optional, default is 's3direct', location within the bucket to upload files)
# S3DIRECT_UNIQUE_RENAME = False # (optional, default is 'False', gives the uploaded file a unique filename)