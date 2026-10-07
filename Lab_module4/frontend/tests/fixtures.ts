/** Real responses recorded from the API (local fake backend, and production for the stored
 * reports and one cached real answer). See FRONTEND_PLAN §11. */
import chunks from "./fixtures/chunks.json";
import codebaseDetail from "./fixtures/codebase-detail.json";
import codebases from "./fixtures/codebases.json";
import config from "./fixtures/config.json";
import dataset from "./fixtures/dataset.json";
import evaluations from "./fixtures/evaluations.json";
import health from "./fixtures/health.json";
import jobEvaluate from "./fixtures/job-evaluate.json";
import jobIndex from "./fixtures/job-index.json";
import problemReadonly from "./fixtures/problem-readonly.json";
import problemValidation from "./fixtures/problem-validation.json";
import queryDebug from "./fixtures/query-debug.json";
import queryReal from "./fixtures/query-real.json";
import reportFull from "./fixtures/report-full.json";
import reportGrid from "./fixtures/report-grid.json";
import reportRetrieval from "./fixtures/report-retrieval.json";
import searchDebug from "./fixtures/search-debug.json";
import stats from "./fixtures/stats.json";
import {
  ChunkSchema,
  CodebaseDetailSchema,
  CodebaseSchema,
  ConfigSchema,
  ExampleSchema,
  GridReportSchema,
  HealthSchema,
  JobSchema,
  QueryResultSchema,
  ReportSchema,
  SearchResultSchema,
  StatsSchema,
} from "@/lib/schemas";

export const raw = {
  chunks, codebaseDetail, codebases, config, dataset, evaluations, health, jobEvaluate, jobIndex,
  problemReadonly, problemValidation, queryDebug, queryReal, reportFull, reportGrid,
  reportRetrieval, searchDebug, stats,
};

export const fx = {
  config: ConfigSchema.parse(config),
  health: HealthSchema.parse(health),
  codebases: CodebaseSchema.array().parse(codebases),
  codebaseDetail: CodebaseDetailSchema.parse(codebaseDetail),
  chunks: ChunkSchema.array().parse(chunks),
  dataset: ExampleSchema.array().parse(dataset),
  queryDebug: QueryResultSchema.parse(queryDebug),
  queryReal: QueryResultSchema.parse(queryReal),
  searchDebug: SearchResultSchema.parse(searchDebug),
  jobIndex: JobSchema.parse(jobIndex),
  jobEvaluate: JobSchema.parse(jobEvaluate),
  reportFull: ReportSchema.parse(reportFull),
  reportRetrieval: ReportSchema.parse(reportRetrieval),
  grid: GridReportSchema.parse(reportGrid),
  stats: StatsSchema.parse(stats),
};
