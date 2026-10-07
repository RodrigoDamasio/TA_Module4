import { z } from "zod";
import {
  type Chunk,
  ChunkSchema,
  type Codebase,
  type CodebaseDetail,
  CodebaseDetailSchema,
  CodebaseSchema,
  type Config,
  ConfigSchema,
  type Example,
  ExampleSchema,
  type GridReport,
  GridReportSchema,
  type Health,
  HealthSchema,
  type Job,
  JobSchema,
  ProblemSchema,
  type QueryResult,
  QueryResultSchema,
  type Report,
  type ReportListItem,
  ReportListItemSchema,
  ReportSchema,
  type SearchMode,
  type SearchResult,
  SearchResultSchema,
  type Stats,
  StatsSchema,
} from "./schemas";

export type ApiErrorKind =
  | "validation"
  | "unsupported"
  | "empty"
  | "too_large"
  | "not_found"
  | "read_only"
  | "full"
  | "rate_limited"
  | "quota"
  | "busy"
  | "loading"
  | "bad_answer"
  | "timeout"
  | "server"
  | "network"
  | "invalid_response";

export class ApiError extends Error {
  constructor(
    public kind: ApiErrorKind,
    message: string,
    public retryAfter?: number,
    public fieldErrors: string[] = [],
    public slug = "",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// /query waits for Gemini (server timeout 90 s); a retrieval evaluation takes a few seconds.
export const TIMEOUTS = { query: 120_000, evaluate: 60_000, default: 30_000 } as const;

export function apiUrl(): string {
  // Referenced directly so Next.js inlines the value at build time.
  return (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
}

const FIELD_LABELS: Record<string, string> = {
  question: "Question",
  query: "Search text",
  codebases: "Codebases",
  codebase: "Codebase name",
  k: "K",
  mode: "Mode",
  examples: "Examples",
  dataset: "Dataset",
};

/** "#/question" → "Question"; "#/files/3/path" → "File 4 path"; "#/examples/0" → "Example 1". */
export function fieldLabel(pointer: string): string {
  const parts = pointer.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts.length === 0) return "Request";
  const [head, index, field] = parts;
  if ((head === "files" || head === "examples") && index !== undefined) {
    const n = Number(index);
    const noun = head === "files" ? "File" : "Example";
    if (Number.isInteger(n)) return `${noun} ${n + 1}${field ? ` ${field}` : ""}`;
  }
  return FIELD_LABELS[head] ?? head.charAt(0).toUpperCase() + head.slice(1).replaceAll("_", " ");
}

async function toApiError(res: Response): Promise<ApiError> {
  const retryHeader = Number(res.headers.get("Retry-After"));
  const retryAfter = Number.isFinite(retryHeader) && retryHeader > 0 ? retryHeader : undefined;
  let detail: string | undefined;
  let title: string | undefined;
  let slug = "";
  let fieldErrors: string[] = [];
  try {
    const problem = ProblemSchema.safeParse(await res.json());
    if (problem.success) {
      detail = problem.data.detail;
      title = problem.data.title;
      slug = problem.data.type?.split("/").pop() ?? "";
      fieldErrors = (problem.data.errors ?? []).map((e) => `${fieldLabel(e.pointer)}: ${e.detail}`);
    }
  } catch {
    // Not JSON (e.g. a proxy error page): fall back to the generic messages below.
  }
  const err = (kind: ApiErrorKind, message: string, fields: string[] = []) =>
    new ApiError(kind, message, retryAfter, fields, slug);

  switch (slug) {
    case "validation-error":
    case "malformed-request":
      return err("validation", detail ?? "The request is not valid.", fieldErrors);
    case "unsupported-file-type":
      return err("unsupported", detail ?? "This file type is not supported.");
    case "empty-index":
      return err("empty", "Nothing is indexed in the selected codebases yet.");
    case "input-too-large":
      return err("too_large", detail ?? "Too much code for one request.");
    case "codebase-not-found":
      return err(
        "not_found",
        "This codebase no longer exists. Uploaded codebases expire after 24 hours.",
      );
    case "job-not-found":
      return err("not_found", "This job no longer exists.");
    case "evaluation-not-found":
      return err("not_found", "This evaluation report no longer exists.");
    case "codebase-read-only":
      return err("read_only", "Sample codebases can't be changed. Choose another name.");
    case "too-many-codebases":
      return err("full", detail ?? "The demo holds a limited number of uploaded codebases.");
    case "rate-limited":
      return err("rate_limited", "Too many requests in a short time.");
    case "llm-quota-exhausted":
      return err("quota", "Today's free AI quota is used up. Search still works.");
    case "llm-unavailable":
    case "busy":
      return err("busy", "The service is busy right now.");
    case "models-loading":
      return err("loading", "The search models are starting.");
    case "llm-bad-response":
      return err("bad_answer", "The model's answer wasn't usable. Try again or rephrase.");
    case "wait-timeout":
      return err("timeout", "The job is still running.");
  }
  if (res.status === 400 || res.status === 422) {
    return err("validation", detail ?? "The request is not valid.", fieldErrors);
  }
  if (res.status === 429) return err("rate_limited", "Too many requests in a short time.");
  if (res.status === 503) return err("busy", "The service is busy right now.");
  return err("server", title ?? "Something went wrong on the server. Please try again.");
}

interface Options extends RequestInit {
  timeout?: number;
}

async function send(path: string, init: Options = {}): Promise<Response> {
  const { timeout = TIMEOUTS.default, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(`${apiUrl()}${path}`, { ...rest, signal: AbortSignal.timeout(timeout) });
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new ApiError("timeout", "The server took too long to answer. Please try again.");
    }
    throw new ApiError("network", "Can't reach the service. Check your connection.");
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

async function request<T>(path: string, schema: z.ZodType<T>, init?: Options): Promise<T> {
  const res = await send(path, init);
  const parsed = schema.safeParse(await res.json().catch(() => undefined));
  if (!parsed.success) {
    throw new ApiError("invalid_response", "Unexpected response from the server.");
  }
  return parsed.data;
}

const post = (body: unknown, timeout?: number): Options => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
  timeout,
});

const enc = encodeURIComponent;

export const health = (): Promise<Health> => request("/health", HealthSchema);
export const config = (): Promise<Config> => request("/config", ConfigSchema);

export const listCodebases = (): Promise<Codebase[]> =>
  request("/codebases", z.array(CodebaseSchema));
export const getCodebase = (id: string): Promise<CodebaseDetail> =>
  request(`/codebases/${enc(id)}`, CodebaseDetailSchema);
export const listChunks = (id: string, path: string): Promise<Chunk[]> =>
  request(`/codebases/${enc(id)}/chunks?path=${enc(path)}`, z.array(ChunkSchema));

export async function deleteCodebase(id: string): Promise<void> {
  await send(`/codebases/${enc(id)}`, { method: "DELETE" });
}

export interface UploadFile {
  path: string;
  content: string;
}

/** Starts an index job (202). The caller follows it with getJob(). */
export const indexFiles = (codebase: string, files: UploadFile[]): Promise<Job> =>
  request("/index/files", JobSchema, post({ codebase, files }));
export const getJob = (id: string): Promise<Job> => request(`/jobs/${enc(id)}`, JobSchema);

export interface QueryParams {
  codebases: string[];
  k: number;
  mode: SearchMode;
}

export const query = (question: string, p: QueryParams): Promise<QueryResult> =>
  request("/query?debug=true", QueryResultSchema, post({ question, ...p }, TIMEOUTS.query));
export const search = (text: string, p: QueryParams): Promise<SearchResult> =>
  request("/search?debug=true", SearchResultSchema, post({ query: text, ...p }));

export const builtinDataset = (): Promise<Example[]> =>
  request("/datasets/builtin", z.array(ExampleSchema));
export const listEvaluations = (): Promise<ReportListItem[]> =>
  request("/evaluations", z.array(ReportListItemSchema));
export const getReport = (id: string): Promise<Report> =>
  request(`/evaluations/${enc(id)}`, ReportSchema);
export const getGrid = (): Promise<GridReport> => request("/evaluations/grid", GridReportSchema);

export interface RetrievalRun {
  k?: number;
  search_mode?: SearchMode;
  examples?: unknown[]; // custom dataset; omitted = the built-in one
}

export const runRetrieval = ({ examples, ...rest }: RetrievalRun): Promise<Report> =>
  request(
    "/evaluate",
    ReportSchema,
    post(
      { mode: "retrieval", dataset: examples ? "custom" : "builtin", examples, ...rest },
      TIMEOUTS.evaluate,
    ),
  );

/** Starts a full evaluation job (202). In production it replays cached answers only. */
export const runFull = (): Promise<Job> =>
  request("/evaluate", JobSchema, post({ mode: "full" }, TIMEOUTS.evaluate));

export const stats = (): Promise<Stats> => request("/stats", StatsSchema);
