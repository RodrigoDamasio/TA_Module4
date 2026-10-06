import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import type { Cart } from "../cart/cart";
import { processOrder } from "../orders/processOrder";

/** Places the order for the current cart and shows the outcome. */
export function CheckoutButton({ cart }: { cart: Cart }) {
  const { token } = useAuth();
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function checkout() {
    if (!token) {
      setMessage("Please log in first.");
      return;
    }
    setBusy(true);
    const result = await processOrder(cart, token, cart.coupon ?? undefined);
    setBusy(false);
    setMessage(result.ok ? `Order #${result.orderId} placed (${result.total} USD).` : result.message);
  }

  return (
    <div>
      <button onClick={checkout} disabled={busy || cart.items.length === 0}>
        {busy ? "Placing order…" : "Checkout"}
      </button>
      {message && <p role="status">{message}</p>}
    </div>
  );
}
