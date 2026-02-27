# Security API (Express + PostgreSQL)

## Install

```bash
npm install
```

## Configure

1. Copy `.env.example` to `.env`.
2. Set `DATABASE_URL` and `JWT_SECRET`.
3. Apply schema:

```bash
psql "$DATABASE_URL" -f sql/schema.sql
```

## Run

```bash
npm start
```

## Endpoints

- `POST /api/login` (rate-limited, creates tracked session, flags suspicious IPs)
- `POST /api/logout` (requires JWT, closes active session)
- `GET /api/director/suspicious` (requires JWT + Director role)
- `GET /api/health`
