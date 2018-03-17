FROM python:2.7
ENV PYTHONUNBUFFERED 1

ENV RUN_DOCKER "True"

RUN echo "deb http://apt.postgresql.org/pub/repos/apt/ jessie-pgdg main" >  /etc/apt/sources.list.d/pgdg.list
RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -
RUN apt-get update
RUN apt-get install -y postgresql-client-10 ipython
RUN mkdir -p /app
RUN wget -O /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
RUN python /tmp/get-pip.py
RUN wget https://cli-assets.heroku.com/heroku-cli/channels/stable/heroku-cli-linux-x64.tar.gz -O heroku.tar.gz && \
    tar -xvzf heroku.tar.gz && \
    mkdir -p /usr/local/lib /usr/local/bin && \
    mv heroku-cli-v6.* /usr/local/lib/heroku && \
    ln -s /usr/local/lib/heroku/bin/heroku /usr/local/bin/heroku
WORKDIR /app
ADD requirements.txt /app/
RUN pip install -r requirements.txt
ADD . /app/

CMD sh run_app.sh
