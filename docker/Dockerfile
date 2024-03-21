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

ENV DJANGO_SETTINGS_MODULE=bieterrunde.settings_prod
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["--forwarded-allow-ips", "*", "--bind", "0.0.0.0:8000", "bieterrunde.wsgi"]
