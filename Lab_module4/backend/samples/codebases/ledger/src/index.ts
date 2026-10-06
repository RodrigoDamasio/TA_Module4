import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { requireApiKey } from "./auth";
import { computeBalance } from "./balance";
import { createEntry, listEntries } from "./entries";

/** The Ledger HTTP API, built with Hono. All routes require an API key. */
const app = new Hono();
app.use("*", requireApiKey);

app.post("/entries", async (c) => {
  const result = createEntry(await c.req.json());
  return result.ok ? c.json(result.entry, 201) : c.json({ errors: result.errors }, 422);
});

app.get("/entries", (c) => c.json(listEntries(c.req.query("account"))));

app.get("/balance/:account", (c) => c.json(computeBalance(listEntries(c.req.param("account")))));

serve({ fetch: app.fetch, port: Number(process.env.PORT ?? 8787) });
