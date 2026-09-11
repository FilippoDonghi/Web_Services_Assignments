# URL shortener services — security and reliability refactor

[![CI](https://github.com/FilippoDonghi/Web_Services_Assignments/actions/workflows/ci.yml/badge.svg)](https://github.com/FilippoDonghi/Web_Services_Assignments/actions/workflows/ci.yml)

This repository is a university assignment fork used as a focused refactoring case study. It contains a Flask authentication service, a Flask URL shortener, and an Nginx gateway. The goal is to make a small teaching project safer to clone, understand, test, and run—not to present it as a production platform.

## Attribution and scope

The original project is [`Nicholas-03/url-shortener-k8s`](https://github.com/Nicholas-03/url-shortener-k8s). Its public baseline is a single commit credited to `Nicholas-03`; it contains no Filippo-authored commits. Filippo's portfolio contribution is this later security and reliability refactor, and the original assignment implementation is not claimed as his work.

The refactor replaces the baseline's hard-coded, hand-rolled token scheme and plaintext password storage; removes references to a dead public demo; and adds deterministic tests and reproducible development tooling. Commit history remains the source of truth for individual changes.

## What this branch demonstrates

- application-factory Flask services with strict JSON schemas and consistent error bodies;
- JWTs issued through maintained `PyJWT`, signed with a required environment secret, and checked for issuer and expiry;
- scrypt password hashes via Werkzeug—passwords are never written to the JSON store;
- bounded service-to-service calls and strict `Authorization: Bearer <token>` parsing;
- validated HTTP/HTTPS destinations, random short IDs, real `302` responses with `Location`, ownership checks, and meaningful delete responses;
- in-process locking plus atomic file replacement for a deliberately single-process JSON demo;
- non-root containers, a loopback-only Compose gateway, health checks, exact direct-dependency versions, pytest, Ruff, dependency auditing, and least-privilege CI permissions.

## Architecture

```text
client -> Nginx :8080
           |-- /auth/*      -> auth :5001 -> auth/database.json
           `-- /shortener/* -> shortener :5000 -> shortener/database.json
                                      |
                                      `-> auth /validate (2 s timeout)
```

## Run with Docker Compose

Requirements: Docker with Compose v2 and Python 3 for generating a random secret.

From the repository root, this command builds the images, waits for health checks, and exposes only Nginx on `http://127.0.0.1:8080`:

```bash
JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  docker compose up --build --wait
```

The secret is supplied to that Compose process only; it is not committed or given an insecure default. Named volumes preserve the two JSON files across normal restarts. Stop the stack with `docker compose down`; add `--volumes` only when you intentionally want to delete the demo data.

### Try the main flow

```bash
curl --fail-with-body -X POST http://127.0.0.1:8080/auth/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"correct horse battery staple"}'

TOKEN="$(curl --fail-with-body -sS -X POST http://127.0.0.1:8080/auth/users/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"correct horse battery staple"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"

curl --fail-with-body -X POST http://127.0.0.1:8080/shortener/ \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/docs"}'

curl --fail-with-body http://127.0.0.1:8080/shortener/ \
  -H "Authorization: Bearer ${TOKEN}"
```

Open the `Location` returned by the create request, or request `/shortener/<id>` with `curl -i`, to observe the `302` redirect.

## API summary

Successful responses and common failure states are covered by the test suite. Errors use `{"error":{"code":"...","message":"..."}}`. The paths below are service-local; through Nginx, prepend `/auth` or `/shortener` as shown in the runnable examples.

| Service | Method | Path | Authentication | Result |
|---|---|---|---|---|
| Auth | `GET` | `/health` | No | Health status |
| Auth | `POST` | `/users` | No | Register a user |
| Auth | `POST` | `/users/login` | No | Return a Bearer access token |
| Auth | `PUT` | `/users/password` | Old password in body | Change a password |
| Auth | `POST` | `/validate` | Token in JSON body | Internal token validation |
| Shortener | `GET` | `/health` | No | Health status |
| Shortener | `GET` | `/` | Bearer | List the caller's links |
| Shortener | `POST` | `/` | Bearer | Create a link from `{"url":"..."}` |
| Shortener | `PUT` | `/<id>` | Bearer owner | Change the destination |
| Shortener | `DELETE` | `/<id>` | Bearer owner | Delete one link |
| Shortener | `DELETE` | `/` | Bearer | Delete all links owned by the caller |
| Shortener | `GET` | `/<id>` | No | Redirect to the destination |

## Local checks

Python 3.13 is the supported development version.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
ruff check .
ruff format --check .
pytest
pip-audit -r auth/requirements.txt
pip-audit -r shortener/requirements.txt
kubernetes-validate --strict k8s/namespace.yaml k8s/*_deployment.yaml
```

Tests use Flask's in-process client and temporary directories. They do not need running services, fixed ports, network access, or persistent test accounts. GitHub Actions repeats linting, tests, dependency audits, Compose validation, and image builds with read-only repository permissions.

## Persistence and limitations

The JSON stores are appropriate only for a single-process demonstration. Atomic replacement avoids partial files and locks coordinate threads in one process, but there is no cross-process or distributed lock. The containers therefore run one Gunicorn worker and the Kubernetes examples use one replica. Use a transactional database before attempting horizontal scaling.

This project also omits TLS termination, rate limiting, refresh/revocation flows, email verification, backups, metrics, and a deployment-specific secret manager. Those are intentional boundaries, not production-readiness claims.

The files in [`k8s/`](k8s/) are cleaned-up, declarative learning examples; they are not a supported or verified live deployment. See [`k8s/README.md`](k8s/README.md) for assumptions and safe secret creation.

## Licensing

The upstream assignment does not supply an open-source licence. This refactor preserves
its attribution and does not grant new rights to the original contributors' code;
contact the contributors before redistributing it.
