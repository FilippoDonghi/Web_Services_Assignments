FROM python:3.13-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY auth/requirements.txt ./auth/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    -r auth/requirements.txt \
    && addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --home /nonexistent --no-create-home app \
    && mkdir -p /data/instance \
    && chown app:app /data/instance

COPY --chown=app:app auth ./auth

USER 10001:10001
EXPOSE 5001

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--worker-tmp-dir", "/tmp", "--no-control-socket", "--bind", "0.0.0.0:5001", "--access-logfile", "-", "--error-logfile", "-", "auth.app:create_app()"]
