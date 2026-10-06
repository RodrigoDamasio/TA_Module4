# Shopflow

Shopflow is a small online shop: a FastAPI backend (`backend/`) and a TypeScript web
client (`web/`). Customers register, fill a cart, and check out; the backend reserves stock,
charges the card through the payment gateway, and emails a confirmation.

## Setup

1. Create a virtual environment and install `backend/requirements.txt`.
2. Copy `.env.example` to `.env` and fill in the values below.
3. Run `uvicorn app.main:app --reload` from `backend/`.
4. In `web/`, run `npm install` and `npm run dev`.

## Configuration

All backend settings are environment variables read by `backend/app/config.py`:

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy URL of the main database | `sqlite:///./shopflow.db` |
| `JWT_SECRET` | Secret used to sign access tokens | none (required) |
| `JWT_TTL_MINUTES` | Access token lifetime | `60` |
| `PAYMENT_API_URL` | Base URL of the payment gateway | `https://payments.example.com` |
| `SMTP_HOST` / `SMTP_PORT` | Mail server for order confirmations | `localhost` / `25` |

The web client reads `VITE_API_BASE_URL` (see `web/src/api/client.ts`).

## Further reading

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit together.
