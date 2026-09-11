FROM python:3.13-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY shortener/requirements.txt ./shortener/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    -r shortener/requirements.txt \
    && addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --home /nonexistent --no-create-home app \
    && mkdir -p /data/instance \
    && chown app:app /data/instance

COPY --chown=app:app shortener ./shortener

USER 10001:10001
EXPOSE 5000

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--worker-tmp-dir", "/tmp", "--no-control-socket", "--bind", "0.0.0.0:5000", "--access-logfile", "-", "--error-logfile", "-", "shortener.app:create_app()"]
