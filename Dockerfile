FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY README.md ./
COPY comment_data ./comment_data
COPY main.py ./

RUN pip install --no-cache-dir .

ENTRYPOINT ["comment-data"]
