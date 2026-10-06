import type { MiddlewareHandler } from "hono";

const validKeys = new Set(
  (process.env.LEDGER_API_KEYS ?? "").split(",").map((k) => k.trim()).filter(Boolean),
);

/**
 * Hono middleware: rejects any request whose `x-api-key` header is not one of the keys in
 * LEDGER_API_KEYS. There are no users or sessions — each client system has its own key.
 */
export const requireApiKey: MiddlewareHandler = async (c, next) => {
  const key = c.req.header("x-api-key");
  if (!key || !validKeys.has(key)) {
    return c.json({ error: "invalid or missing API key" }, 401);
  }
  await next();
};
