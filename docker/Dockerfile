FROM python:3.13

RUN mkdir /app
WORKDIR /app

RUN pip install uv

COPY uv.lock /app
COPY pyproject.toml /app

# Install dependencies
RUN uv sync --group prod --no-group dev --no-install-project

COPY . /app

# Install the application
RUN uv sync --group prod --no-group dev

ENV DJANGO_SETTINGS_MODULE=bieterrunde.settings_prod
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web", "--forwarded-allow-ips", "*", "--bind", "0.0.0.0:8000", "bieterrunde.wsgi"]
