# Architecture

## Components

- **Web client** (`web/`): React components, a cart kept in memory, and `processOrder`,
  which validates the cart and calls the API.
- **API** (`backend/app/`): FastAPI routers for auth, orders and stock.
- **Payment gateway**: an external HTTP service, wrapped by `PaymentClient`.
- **Database**: any SQLAlchemy database (SQLite in development, PostgreSQL in production).

## Order flow

1. The customer clicks **Checkout** (`CheckoutButton`), which calls `processOrder`.
2. `processOrder` validates the cart with Zod and sends `POST /orders` with the bearer token.
3. The `create_order` route calls `OrderService.place_order`.
4. `place_order` reserves stock, applies any discount code, and charges the card with
   `PaymentClient.charge`. If the charge fails, the stock is released and the order is
   marked `payment_failed`.
5. On success the order is saved as `paid` and a confirmation email is sent.

## Authentication

Users log in with email and password. Passwords are hashed with bcrypt. A successful login
returns a JWT access token signed with `JWT_SECRET`; protected routes read it from the
`Authorization: Bearer` header through the `get_current_user` dependency.
