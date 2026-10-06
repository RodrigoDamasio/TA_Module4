import type { CartItem } from "../orders/schemas";

/** In-memory shopping cart. Quantities of the same SKU are merged. */
export class Cart {
  items: CartItem[] = [];
  coupon: string | null = null;

  add(item: CartItem): void {
    const existing = this.items.find((i) => i.sku === item.sku);
    if (existing) existing.quantity += item.quantity;
    else this.items.push({ ...item });
  }

  remove(sku: string): void {
    this.items = this.items.filter((i) => i.sku !== sku);
  }

  /** Sum of unit price × quantity, before discounts and shipping. */
  subtotal(): number {
    return this.items.reduce((sum, i) => sum + i.unit_price * i.quantity, 0);
  }

  /**
   * Remembers a coupon code for checkout. Codes are upper-cased; the server decides
   * whether the code is valid (see apply_discount in the backend).
   */
  applyCoupon(code: string): void {
    this.coupon = code.trim().toUpperCase() || null;
  }

  clear(): void {
    this.items = [];
    this.coupon = null;
  }
}
