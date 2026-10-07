import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "@/lib/api";
import { ApiError, fieldLabel } from "@/lib/api";
import { raw } from "./fixtures";

const params = { codebases: ["shopflow"], k: 5, mode: "hybrid" as const };

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(status === 204 ? null : typeof body === "string" ? body : JSON.stringify(body), { status, headers }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const problem = (slug: string, status: number, extra: object = {}) => ({
  type: `https://api.example/problems/${slug}`,
  title: "T",
  status,
  detail: `detail of ${slug}`,
  ...extra,
});

async function errorOf(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (err) {
    if (err instanceof ApiError) return err;
  }
  throw new Error("expected an ApiError");
}

afterEach(() => vi.unstubAllGlobals());

describe("requests", () => {
  it("sends a question with debug=true and the settings", async () => {
    const fetchMock = respond(200, raw.queryDebug);
    const result = await api.query("Where is the db?", params);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/query?debug=true");
    expect(JSON.parse(init.body)).toEqual({ question: "Where is the db?", ...params });
    expect(init.method).toBe("POST");
    expect(result.sources.length).toBeGreaterThan(0);
  });

  it("sends a search as `query`", async () => {
    const fetchMock = respond(200, raw.searchDebug);
    await api.search("discount", params);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).query).toBe("discount");
  });

  it("builds the other paths", async () => {
    let fetchMock = respond(200, raw.chunks);
    await api.listChunks("my code", "a b.py");
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/codebases/my%20code/chunks?path=a%20b.py");
    fetchMock = respond(204, "");
    await api.deleteCodebase("demo");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
    fetchMock = respond(200, raw.reportRetrieval);
    await api.runRetrieval({ k: 3, search_mode: "vector" });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ mode: "retrieval", dataset: "builtin", k: 3, search_mode: "vector" });
    fetchMock = respond(200, raw.reportRetrieval);
    await api.runRetrieval({ examples: [{ id: "x" }] });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).dataset).toBe("custom");
    fetchMock = respond(202, raw.jobEvaluate);
    expect((await api.runFull()).kind).toBe("evaluate");
    fetchMock = respond(202, raw.jobIndex);
    await api.indexFiles("demo", [{ path: "a.py", content: "x" }]);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ codebase: "demo", files: [{ path: "a.py", content: "x" }] });
  });

  it("uses NEXT_PUBLIC_API_URL without a trailing slash", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example/");
    const fetchMock = respond(200, raw.health);
    await api.health();
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.example/health");
  });
});

describe("errors (FRONTEND_PLAN §8)", () => {
  it.each([
    ["validation-error", 422, "validation"],
    ["malformed-request", 400, "validation"],
    ["unsupported-file-type", 422, "unsupported"],
    ["empty-index", 422, "empty"],
    ["input-too-large", 413, "too_large"],
    ["codebase-not-found", 404, "not_found"],
    ["job-not-found", 404, "not_found"],
    ["evaluation-not-found", 404, "not_found"],
    ["codebase-read-only", 409, "read_only"],
    ["too-many-codebases", 409, "full"],
    ["rate-limited", 429, "rate_limited"],
    ["llm-quota-exhausted", 503, "quota"],
    ["llm-unavailable", 503, "busy"],
    ["busy", 503, "busy"],
    ["models-loading", 503, "loading"],
    ["llm-bad-response", 502, "bad_answer"],
    ["wait-timeout", 504, "timeout"],
    ["internal-error", 500, "server"],
  ])("%s → %s", async (slug, status, kind) => {
    respond(status, problem(slug, status), { "Retry-After": "30" });
    const err = await errorOf(api.health());
    expect(err.kind).toBe(kind);
    expect(err.slug).toBe(slug);
    expect(err.retryAfter).toBe(30);
  });

  it("maps field errors with readable labels", async () => {
    respond(422, raw.problemValidation);
    const err = await errorOf(api.query("x", params));
    expect(err.kind).toBe("validation");
    expect(err.fieldErrors[0]).toMatch(/^Question: /);
  });

  it("falls back on the status when the body is not a problem", async () => {
    respond(429, "<html>busy</html>");
    expect((await errorOf(api.health())).kind).toBe("rate_limited");
    respond(503, "nope");
    expect((await errorOf(api.health())).kind).toBe("busy");
    respond(422, "nope");
    expect((await errorOf(api.health())).kind).toBe("validation");
    respond(500, "nope");
    const err = await errorOf(api.health());
    expect(err.kind).toBe("server");
    expect(err.retryAfter).toBeUndefined();
  });

  it("rejects responses that fail their schema", async () => {
    respond(200, { status: 1 });
    expect((await errorOf(api.health())).kind).toBe("invalid_response");
    respond(200, "not json");
    expect((await errorOf(api.health())).kind).toBe("invalid_response");
  });

  it("reports network failures and timeouts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect((await errorOf(api.health())).kind).toBe("network");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("t", "TimeoutError")));
    expect((await errorOf(api.health())).kind).toBe("timeout");
  });

  it("labels JSON pointers", () => {
    expect(fieldLabel("#/question")).toBe("Question");
    expect(fieldLabel("#/files/3/path")).toBe("File 4 path");
    expect(fieldLabel("#/examples/0")).toBe("Example 1");
    expect(fieldLabel("#")).toBe("Request");
    expect(fieldLabel("#/some_field")).toBe("Some field");
  });
});
