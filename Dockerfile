# Basic Dockerfile for the USASpendingAPI

## 1) Build:
#        docker build . -t usaspending-api-image --build-arg DATABASE_URL=<postgres://user:pass@host:port/db_name>

## 2) Run:
#        docker run --name=usaspending-api -p 127.0.0.1:8000:8000 usaspending-api-image

# This will forward port 8000 of the container to your localhost:8000 and start a new container for the API.
# Rebuild and run when code in /usaspending-api changes

FROM python:3.5.6

WORKDIR /usaspending-api

RUN apt-get update -y

ADD requirements/requirements.txt /usaspending-api/requirements/requirements.txt

RUN pip install -r requirements/requirements.txt

ADD . /usaspending-api

ARG DATABASE_URL
ENV DATABASE_URL=$DATABASE_URL

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
