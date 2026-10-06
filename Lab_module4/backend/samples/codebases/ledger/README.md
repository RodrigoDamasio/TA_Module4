# Ledger

A small bookkeeping service: a TypeScript API built with **Hono** (`src/`) records debit and
credit entries, and a Python worker (`worker/`) reconciles them with the bank's daily CSV.

## Running

- API: `npm install && npm run dev` (port 8787). Every request needs the `x-api-key`
  header; keys are listed in `LEDGER_API_KEYS` (comma-separated).
- Worker: `python -m worker.reconcile statement.csv` — prints entries that are missing on
  either side.

## Money

Amounts are stored as integer **cents** to avoid floating-point errors.
