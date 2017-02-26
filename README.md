# dcstreethockey

##Deploy - keeps dev and heroku in sync
1. ./manage.py makemigrations
1. ./manage.py migrate
1. git push heroku master
1. heroku run python ./manage.py migrate
1. git push origin master

##Ensure DJANGO_SETTINGS_MODULE is set for production deployments
1. heroku config:set DJANGO_SETTINGS_MODULE=dcstreethockey.settings.production
