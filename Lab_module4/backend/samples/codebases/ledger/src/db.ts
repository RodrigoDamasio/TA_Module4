import type { Entry } from "./entries";

/** In-memory storage for the demo. A real deployment would use a database. */
export const store: { entries: Entry[] } = { entries: [] };
