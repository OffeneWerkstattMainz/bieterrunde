FROM python:3.11

RUN mkdir /app
WORKDIR /app

RUN pip install poetry

COPY poetry.lock /app
COPY pyproject.toml /app

# Install dependencies
RUN poetry install --with prod --without dev --no-directory

COPY . /app

# Install the application
RUN poetry install --with prod --without dev

EXPOSE 80
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["--env", "DJANGO_SETTINGS_MODULE=bieterrunde.settings_prod", "--forwarded-allow-ips", "*", "--bind", "0.0.0.0:80", "bieterrunde.wsgi"]
