FROM python:2.7
ENV PYTHONUNBUFFERED 1

ENV RUN_DOCKER "True"

RUN apt-get update
RUN apt-get install -y python-psycopg2 postgresql-client ipython
RUN mkdir -p /app
RUN wget -O /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
RUN python /tmp/get-pip.py
WORKDIR /app
ADD requirements.txt /app/
RUN pip install -r requirements.txt
ADD . /app/

CMD sh run_app.sh
