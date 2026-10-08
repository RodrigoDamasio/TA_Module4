# TA_Module4

Module 4: **RAG (Retrieval-Augmented Generation) & Evaluation** — lab: **Codebase RAG System**, a Q&A system that indexes code files, retrieves the relevant chunks, answers questions grounded in them, and measures retrieval and answer quality.

Assignment: [Lab4_RAG_System_with_Evaluation.md](Lab_module4/Lab4_RAG_System_with_Evaluation.md).

All lab code and documents live in [Lab_module4/](Lab_module4/).

**Live app:** https://taller-codebase-rag.vercel.app (Vercel, [frontend/DEPLOY.md](Lab_module4/frontend/DEPLOY.md))

**Live API:** https://backend-production-cf2a.up.railway.app ([docs](https://backend-production-cf2a.up.railway.app/docs)) — Railway, [backend/DEPLOY.md](Lab_module4/backend/DEPLOY.md)

## Documents

| Document | What it explains |
|---|---|
| [PLAN.md](Lab_module4/PLAN.md) | The big picture: architecture, decisions, diagrams |
| [BACKEND_PLAN.md](Lab_module4/BACKEND_PLAN.md) · [FRONTEND_PLAN.md](Lab_module4/FRONTEND_PLAN.md) | Detailed designs, with what changed during implementation |
| [PIPELINE_WALKTHROUGH.md](Lab_module4/PIPELINE_WALKTHROUGH.md) | Indexing and retrieval step by step: what runs each step (Python, ONNX, ChromaDB, SQLite) and the code behind it |
| [EVALUATION.md](Lab_module4/EVALUATION.md) | Measured results: chunking strategies, search modes, embedding models, answer quality |
| [MEMORY_TUNING.md](Lab_module4/MEMORY_TUNING.md) | How the backend was fitted into Railway's free plan, and the trade-offs |
| [backend/DEPLOY.md](Lab_module4/backend/DEPLOY.md) · [frontend/DEPLOY.md](Lab_module4/frontend/DEPLOY.md) | Deploy steps actually run, post-deploy checks, known issues |
| [backend/README.md](Lab_module4/backend/README.md) · [frontend/README.md](Lab_module4/frontend/README.md) | How to run and test each part |
