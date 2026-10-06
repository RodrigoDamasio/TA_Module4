import { ApiError, apiFetch } from "../api/client";
import type { Cart } from "../cart/cart";
import { OrderRequestSchema } from "./schemas";

export type OrderResult =
  | { ok: true; orderId: number; total: string }
  | { ok: false; reason: "invalid-cart" | "out-of-stock" | "payment-declined" | "error"; message: string };

/**
 * Turns the cart into an order.
 *
 * 1. Validates the cart with OrderRequestSchema (Zod) before any network call.
 * 2. Sends POST /orders with the user's bearer token.
 * 3. Maps API errors to user-facing reasons: 409 → out of stock, 402 → payment declined.
 * On success the cart is emptied.
 */
export async function processOrder(cart: Cart, token: string, discountCode?: string): Promise<OrderResult> {
  const parsed = OrderRequestSchema.safeParse({ items: cart.items, discount_code: discountCode });
  if (!parsed.success) {
    return { ok: false, reason: "invalid-cart", message: parsed.error.issues[0].message };
  }
  try {
    const order = await apiFetch<{ id: number; total: string }>(
      "/orders",
      { method: "POST", body: JSON.stringify(parsed.data) },
      token,
    );
    cart.clear();
    return { ok: true, orderId: order.id, total: order.total };
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      return { ok: false, reason: "out-of-stock", message: err.message };
    }
    if (err instanceof ApiError && err.status === 402) {
      return { ok: false, reason: "payment-declined", message: "Your card was declined." };
    }
    return { ok: false, reason: "error", message: "Something went wrong. Please try again." };
  }
}
