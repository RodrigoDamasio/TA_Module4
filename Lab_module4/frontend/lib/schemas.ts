/** Zod schemas mirroring the backend views (app/api/schemas.py, app/api/routes.py).
 * Every API response is parsed; invalid data is never rendered. Unknown keys are dropped,
 * except on spans and candidates, whose attributes vary by step. */
import { z } from "zod";

export const SEARCH_MODES = ["hybrid", "vector", "bm25", "hybrid_rerank"] as const;
export const SearchModeSchema = z.enum(SEARCH_MODES);
export type SearchMode = z.infer<typeof SearchModeSchema>;

const num = z.number();
const nullableNum = z.number().nullable();

// ---- problems (RFC 9457) ----------------------------------------------------------------

export const ProblemSchema = z.object({
  type: z.string().optional(),
  title: z.string().optional(),
  status: z.number().optional(),
  detail: z.string().optional(),
  instance: z.string().nullable().optional(),
  errors: z.array(z.object({ pointer: z.string(), detail: z.string() })).nullable().optional(),
});

// ---- server info -------------------------------------------------------------------------

export const HealthSchema = z.object({
  status: z.string(),
  models: z.string(),
  reranker: z.string().optional(),
  samples: z.string(),
});

export const ConfigSchema = z.object({
  limits: z.object({
    max_files_per_request: num,
    max_bytes_per_request: num,
    max_files_per_codebase: num,
    max_bytes_per_codebase: num,
    max_user_codebases: num,
    codebase_ttl_hours: num,
    max_k: num,
    question_max_chars: num,
    max_path_chars: num,
    minified_line_chars: num,
    max_custom_examples: num,
  }),
  files: z.object({
    extensions: z.array(z.string()),
    extra_names: z.array(z.string()),
    skipped_dirs: z.array(z.string()),
    lockfiles: z.array(z.string()),
    codebase_id_pattern: z.string(),
  }),
  defaults: z.object({ k: num, mode: SearchModeSchema }),
  modes: z.array(
    z.object({ id: SearchModeSchema, available: z.boolean(), reason: z.string().nullable() }),
  ),
  pipeline_debug: z.boolean(),
  rate_limits: z.object({ query_per_minute: num, query_per_day: num }),
});

// ---- codebases and chunks ----------------------------------------------------------------

export const CodebaseSchema = z.object({
  id: z.string(),
  kind: z.enum(["sample", "user"]),
  read_only: z.boolean(),
  file_count: num,
  chunk_count: num,
  bytes: num,
  languages: z.record(z.string(), num),
  created_at: z.string(),
  updated_at: z.string(),
  expires_at: z.string().nullable(),
});

export const FileRecordSchema = z.object({
  path: z.string(),
  language: z.string(),
  chunk_count: num,
  bytes: num,
  fallback: z.boolean(),
  indexed_at: z.string(),
});

export const CodebaseDetailSchema = CodebaseSchema.extend({ files: z.array(FileRecordSchema) });

export const ChunkSchema = z.object({
  chunk_id: z.string(),
  codebase: z.string(),
  path: z.string(),
  language: z.string(),
  kind: z.string(),
  symbol: z.string().nullable(),
  signature: z.string().nullable(),
  start_line: num,
  end_line: num,
  part: z.tuple([num, num]).nullable(),
  code: z.string(),
});

export const SourceSchema = ChunkSchema.extend({
  n: num,
  scores: z.object({
    vector: nullableNum,
    bm25: nullableNum,
    rrf: nullableNum,
    rerank: nullableNum,
    ranks: z.record(z.string(), num),
  }),
});

// ---- trace, meta, pipeline -----------------------------------------------------------------

export const SpanSchema = z
  .object({ name: z.string(), ms: num, ok: z.boolean() })
  .catchall(z.unknown());

export const TraceSchema = z.object({
  request_id: z.string(),
  total_ms: num,
  spans: z.array(SpanSchema),
  mode: z.string().optional(),
  k: num.optional(),
  cache: z
    .object({ llm: z.boolean().nullable(), query_embedding: z.boolean().nullable() })
    .optional(),
});

export const MetaSchema = z.object({
  mode: SearchModeSchema,
  k: num,
  embedder: z.string(),
  reranker: z.string(),
  chunker_version: z.string(),
  model: z.string(),
  prompt_version: z.string(),
  debug: z.enum(["enabled", "disabled"]).optional(),
});

export const CandidateSchema = z
  .object({
    rank: num,
    chunk_id: z.string(),
    codebase: z.string().optional(),
    path: z.string().optional(),
    symbol: z.string().nullable().optional(),
    start_line: num.optional(),
    end_line: num.optional(),
  })
  .catchall(z.unknown());

export const PipelineSchema = z.object({
  question: z.string(),
  query_rewrite: z.unknown().nullable(),
  query_embedding: z
    .object({ model: z.string(), dims: num, cached: z.boolean(), ms: num })
    .nullable(),
  vector_candidates: z.array(CandidateSchema),
  bm25_candidates: z.array(CandidateSchema),
  rrf_merged: z.array(CandidateSchema),
  reranked: z.array(CandidateSchema).nullable(),
  rerank_skipped: z.string().nullable(),
  prompt: z
    .object({
      prompt_version: z.string(),
      est_tokens: num,
      chunks_sent: num,
      chunks_dropped: num,
      system: z.string(),
      user: z.string(),
    })
    .optional(),
  llm: z
    .object({
      cached: z.boolean(),
      input_tokens: nullableNum,
      output_tokens: nullableNum,
      raw_output: z.string().nullable(),
      attempts: z.array(
        z.object({
          raw_output: z.string().nullable(),
          errors: z.array(z.string()),
          repair_message: z.string().nullable(),
        }),
      ),
    })
    .optional(),
});

export const QueryResultSchema = z.object({
  request_id: z.string(),
  answer: z.string(),
  found: z.boolean(),
  grounded: z.boolean(),
  citations: z.array(num),
  sources: z.array(SourceSchema),
  trace: TraceSchema,
  meta: MetaSchema,
  pipeline: PipelineSchema.optional(),
});

export const SearchResultSchema = z.object({
  request_id: z.string(),
  hits: z.array(SourceSchema),
  trace: TraceSchema,
  meta: MetaSchema,
  pipeline: PipelineSchema.optional(),
});

// ---- jobs ------------------------------------------------------------------------------------

export const JobSchema = z.object({
  id: z.string(),
  kind: z.enum(["index", "evaluate"]),
  status: z.enum(["queued", "running", "completed", "failed"]),
  request: z.record(z.string(), z.unknown()),
  progress: z.record(z.string(), z.unknown()),
  result: z.record(z.string(), z.unknown()).nullable(),
  error: z.object({ title: z.string(), detail: z.string() }).nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  status_url: z.string(),
});

export const IndexProgressSchema = z.object({
  files_done: num,
  files_total: num,
  chunks: num,
  cache_hits: num,
});

export const IndexResultSchema = z.object({
  codebase: z.string(),
  files_indexed: num,
  files_unchanged: num,
  skipped: z.array(z.object({ path: z.string(), reason: z.string() })),
  chunks_added: num,
  chunks_removed: num,
  by_language: z.record(z.string(), num),
  embedding_cache_hits: num,
  fallbacks: z.array(z.unknown()),
  duration_ms: num.optional(),
});

export const EvalProgressSchema = z.object({
  examples_done: num,
  examples_total: num,
  real_calls: num.optional(),
  cached_calls: num.optional(),
});

// ---- evaluation ------------------------------------------------------------------------------

export const ExampleSchema = z.object({
  id: z.string(),
  question: z.string(),
  category: z.string(),
  codebases: z.array(z.string()),
  expected_answer: z.string(),
  relevant: z.array(z.object({ target: z.string(), lines: z.array(num) })),
  expect_found: z.boolean(),
});

const RetrievalMetricsSchema = z.object({
  precision: nullableNum,
  recall: nullableNum,
  mrr: nullableNum,
  hit: nullableNum,
  ndcg: nullableNum,
  n: num.optional(),
});

const JudgeScoresSchema = z.object({
  faithfulness: nullableNum,
  relevance: nullableNum,
  correctness: nullableNum,
  n: num.optional(),
});

const PassTotalSchema = z.object({ passed: num, total: num });

export const ReportSummarySchema = z.object({
  retrieval: z.object({
    overall: RetrievalMetricsSchema,
    by_category: z.record(z.string(), RetrievalMetricsSchema),
  }),
  generation: z
    .object({
      overall: JudgeScoresSchema,
      by_category: z.record(z.string(), JudgeScoresSchema),
    })
    .optional(),
  checks: z.record(z.string(), PassTotalSchema).optional(),
  judge_sanity: PassTotalSchema.optional(),
  skipped: z.array(z.unknown()).optional(),
  latency_ms: z.object({ p50: nullableNum, p95: nullableNum }).optional(),
  calls: z.object({ real_calls: num, cached_calls: num }).optional(),
  n_examples: num,
});

export const ReportExampleSchema = z.object({
  id: z.string(),
  category: z.string(),
  question: z.string(),
  retrieved: z.array(
    z.object({
      rank: num,
      codebase: z.string(),
      path: z.string(),
      symbol: z.string().nullable(),
      lines: z.tuple([num, num]),
      relevant: z.boolean(),
    }),
  ),
  targets: z.array(z.object({ target: z.string(), first_rank: nullableNum })),
  metrics: RetrievalMetricsSchema.optional(),
  mode_used: z.string().optional(),
  answer: z
    .object({
      text: z.string(),
      found: z.boolean(),
      citations: z.array(num),
      grounded: z.boolean(),
      cached: z.boolean(),
    })
    .optional(),
  checks: z.record(z.string(), z.boolean()).optional(),
  missing_mentions: z.array(z.string()).optional(),
  judge_scores: JudgeScoresSchema.optional(),
  judge_reasons: z.record(z.string(), z.string()).optional(),
});

export const ReportSchema = z.object({
  id: z.string(),
  kind: z.enum(["retrieval", "full"]),
  created_at: z.string(),
  config: z.record(z.string(), z.unknown()),
  summary: ReportSummarySchema,
  examples: z.array(ReportExampleSchema),
  judge_sanity: z
    .array(
      z.object({
        id: z.string(),
        kind: z.string(),
        example: z.string(),
        scores: JudgeScoresSchema,
        passed: z.boolean(),
        lenient_on: z.array(z.string()),
      }),
    )
    .optional(),
});

const CategoryMetricsSchema = z.object({ recall: nullableNum, mrr: nullableNum });

export const GridRowSchema = z.object({
  embedder: z.string(),
  strategy: z.string(),
  mode: z.string(),
  k: num,
  chunks: num,
  index_s: num,
  precision: num,
  recall: num,
  mrr: num,
  ndcg: num,
  latency_p50_ms: num,
  context_chars: num,
  by_category: z.record(z.string(), CategoryMetricsSchema),
});

export const GridReportSchema = z.object({
  id: z.string(),
  kind: z.literal("grid"),
  created_at: z.string(),
  rows: z.array(GridRowSchema),
  summary: z.object({
    best_at_5: z.object({
      embedder: z.string(),
      strategy: z.string(),
      mode: z.string(),
      recall: num,
      mrr: num,
    }),
  }),
  n_examples: num,
});

export const ReportListItemSchema = z.object({
  id: z.string(),
  kind: z.string(),
  created_at: z.string(),
  published: z.boolean(),
});

export const StatsSchema = z.object({
  window: z.string(),
  requests: z.record(z.string(), num),
  latency_ms: z.record(z.string(), z.object({ p50: nullableNum, p95: nullableNum })),
  llm: z.object({
    calls_today: num,
    cached_today: num,
    cache_hit_rate: nullableNum,
    daily_limit: num,
    left_today: num,
    input_tokens: num,
    output_tokens: num,
    paid_equivalent_usd: num,
  }),
  index: z.record(z.string(), nullableNum),
  quota: z.record(z.string(), z.unknown()),
});

export type Problem = z.infer<typeof ProblemSchema>;
export type Health = z.infer<typeof HealthSchema>;
export type Config = z.infer<typeof ConfigSchema>;
export type Codebase = z.infer<typeof CodebaseSchema>;
export type CodebaseDetail = z.infer<typeof CodebaseDetailSchema>;
export type FileRecord = z.infer<typeof FileRecordSchema>;
export type Chunk = z.infer<typeof ChunkSchema>;
export type Source = z.infer<typeof SourceSchema>;
export type Span = z.infer<typeof SpanSchema>;
export type Trace = z.infer<typeof TraceSchema>;
export type Meta = z.infer<typeof MetaSchema>;
export type Candidate = z.infer<typeof CandidateSchema>;
export type Pipeline = z.infer<typeof PipelineSchema>;
export type QueryResult = z.infer<typeof QueryResultSchema>;
export type SearchResult = z.infer<typeof SearchResultSchema>;
export type Job = z.infer<typeof JobSchema>;
export type IndexProgress = z.infer<typeof IndexProgressSchema>;
export type IndexResult = z.infer<typeof IndexResultSchema>;
export type EvalProgress = z.infer<typeof EvalProgressSchema>;
export type Example = z.infer<typeof ExampleSchema>;
export type Report = z.infer<typeof ReportSchema>;
export type ReportExample = z.infer<typeof ReportExampleSchema>;
export type ReportSummary = z.infer<typeof ReportSummarySchema>;
export type GridRow = z.infer<typeof GridRowSchema>;
export type GridReport = z.infer<typeof GridReportSchema>;
export type ReportListItem = z.infer<typeof ReportListItemSchema>;
export type Stats = z.infer<typeof StatsSchema>;
