import { z } from "zod";

/** One cart line as sent to the API. */
export const CartItemSchema = z.object({
  sku: z.string().min(1),
  quantity: z.number().int().positive().max(20),
  unit_price: z.number().positive(),
});

/** Body of POST /orders. At most 50 lines; the discount code is optional. */
export const OrderRequestSchema = z.object({
  items: z.array(CartItemSchema).min(1).max(50),
  discount_code: z.string().max(32).optional(),
});

export type CartItem = z.infer<typeof CartItemSchema>;
export type OrderRequest = z.infer<typeof OrderRequestSchema>;
