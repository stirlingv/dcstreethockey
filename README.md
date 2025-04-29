# dcstreethockey

## Clone and run using docker

1. [install_docker](https://docs.docker.com/engine/installation/)
1. [install_docker-compose](https://docs.docker.com/compose/install/)
1. [fork](https://help.github.com/articles/fork-a-repo/) and [clone](https://help.github.com/articles/cloning-a-repository/) repo
1. docker-compose up
1. Stop that process Ctrl+c
1. Download test data set
1. docker-compose run --rm web python manage.py loaddata working-herokudump.json
1. docker-compose up

## Clone and Run in localhost

1. [download postgres](https://www.enterprisedb.com/downloads/postgres-postgresql-downloads#linux)
   - [generic instructions here](https://www.postgresql.org/download/linux/)
   - if using homebrew: 
      - ```brew instal postgresql```
1. [fork](https://help.github.com/articles/fork-a-repo/) and [clone](https://help.github.com/articles/cloning-a-repository/) repo
1. activate virtual environment 
   - ```venv``` is part of python3 base image.
   - cd to dcstreethockey folder
   - ```python3 -m venv [path to virtual environment folder]``` (first time only)
   - ```source [path to virtual environment]/bin/activate```
1. pip install -r requirements.txt
1. Make sure postgres is running and Database exists
   - ```brew services start postgresql```
   - ```psql -l```
      - if dcstreethockey doesn't exist continue
   - ```createdb dcstreethockey```
   - ```createuser user```
1. ```uvicorn dcstreethockey.asgi:application --host 0.0.0.0 --port 8000```

## Deploy - keeps dev and  in sync

1. ```./manage.py makemigrations```
1. ```./manage.py migrate```
1. ```git push origin main```

## [OUTDATED] Ensure DJANGO_SETTINGS_MODULE is set for production deployments

1. ```heroku config:set DJANGO_SETTINGS_MODULE=dcstreethockey.settings.production```

## Create backup of render database and restore in local postgres instance

1. Run pg_dump to generate an export of the database on render: 

    ```bash
    pg_dump -d <<external render DB connection>> > ~/Downloads/<<file_name>>.sql 
    ```

1. Delete local postgres db

    ```bash
    dropdb dcstreethockey
    ```

1. Create local db

    ```bash
    createdb dcstreethockey
    ```

1. Run restore:

    ```bash
    psql -U user -d dcstreethockey < ~/Downloads/<<file_name>>.sql
    ```

1. Update db permissions to empower the dcstreethockey user:

    ```sql
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO dcstreethockey;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO dcstreethockey;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO dcstreethockey;
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO dcstreethockey;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO dcstreethockey;
    GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO dcstreethockey;
    ```

## Run local database to render

1. Get Connection Details:
   - Log in to your Render dashboard and navigate to your PostgreSQL service. Copy the connection string provided, which will be in the format:

    ```sql
    postgres://<username>:<password>@<host>:<port>/<database>
    ```

1. Save your SQL script locally, e.g., db_migration_scripts/insert_matchup.sql.
1. Run the following command in your terminal, replacing <connection_string> with the actual connection string and path/to/your/script.sql with the path to your SQL script:

    ```bash
    psql postgres://<username>:<password>@<host>:<port>/<database> -f path/to/your/script.sql
    ```
