# Changelog

All notable changes to **DevAssistant MCP Server** are documented in this file.

## [2.0.0] - 2026-11-05

### 🛡️ Security Hardening
- **`WorkspaceGuard` Multi-Root Boundary:** Enforces strict containment of all filesystem reads and writes inside `DEVASSISTANT_WORKSPACE_ROOTS`, blocking path traversal (`..`), symlink escapes, protected folders (`.git`, `.github`, `.vscode`), and non-Markdown file overwrites.
- **Automatic Secret Redaction:** Added pure domain service (`src/core/services/redaction.py`) that detects and redacts OpenAI/Anthropic keys, GitHub tokens, AWS keys, Google API keys, Slack tokens, JWTs, private keys, and generic credentials before SQLite persistence.
- **Prompt Injection Mitigations:** Wrapped recalled memories in `<stored_memory trust="data-not-instructions">` delimiters and stripped HTML comments from scanned `README.md` headers wrapped in `<project_readme trust="data-not-instructions">`.
- **MCP Tool Annotations:** Added `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint=False` metadata across all tools.

### 🏛️ Architecture Auditor v2 & CLI / SARIF
- **Module Dependency Graph + Python AST Extractor:** Replaced line regexes for Python with a full `ast.NodeVisitor` handling relative imports, `from . import submodule`, dynamic `importlib`, docstring immunity, and `TYPE_CHECKING` severity downgrade (`ERROR` -> `WARNING`).
- **Configurable Rules (`devassistant.toml` & `[tool.devassistant]`):** Added customizable layer definitions, external package allow/deny lists, presets (`hexagonal-python`, `screaming-ts`, `django`), and expiring `[[exceptions]]`.
- **Circular Dependency Detection:** Implemented Tarjan's Strongly Connected Components (SCC) algorithm (`no-cycles` rule).
- **CI CLI & SARIF 2.1.0 Export:** Added `dev-assistant-mcp audit . --format sarif --fail-on error` for GitHub Code Scanning PR annotations, while preserving `serve` stdio as default when invoked without arguments.
- **Scanner Fixes:** Pruned `node_modules`/`.venv` in-place during directory walks, fixed `"pg"` substring false positives on UI imports, separated scan vs. audit ignore lists (`src/data/` now audited), and added accurate `pyproject.toml`/`package.json` dependency parsing for monorepos.

### 🧠 Sovereign Memory v2 (SQLite FTS5 + Versioning)
- **Safe User-Scoped Storage:** Default DB path moved to `~/.dev-assistant/agent_memory.db` with automatic non-destructive copy migration from legacy `./data/agent_memory.db` and pre-migration `.bak-v{n}` backups (`PRAGMA user_version = 4`, WAL mode).
- **FTS5 + BM25 Ranking:** Added `memories_fts` with `unicode61 remove_diacritics 2` tokenizer (`decisión` matches `decision`), query sanitization, and automatic `LIKE` fallback.
- **Memory Versioning & Scope:** Added `supersedes` parameter on `remember_fact` (preserving `created_at` and tracking `updated_at` / `last_used_at`), `scope` (`project | global | all`), and `review_stale_memories`.

### 📄 MADR File Repository & ADR Drift
- **MADR ADRs (`docs/adr/NNNN-slug.md`):** Added `record_decision`, `list_adrs`, `update_adr_status`, and automatic `docs/adr/README.md` index generation.
- **ADR Drift Detection (`check_adr_drift`):** Cross-checks accepted ADRs (`enforced_by` rule IDs) against live architectural audit violations.
- **Safe Feature Scaffolding (`apply_blueprint`):** Previews (`dry_run=True`) or creates architecture-compliant feature files without overwriting existing files.
- **MCP Resources & Prompts:** Exposed `devassistant://projects`, `devassistant://rules/{project}`, `devassistant://adrs/{project}`, and guided prompts (`new-feature`, `architecture-review`, `record-decision`).

---

## [1.2.0] - 2026-11-04
- Initial commercial release on Agensi.io with `SKILL.md`, static import checks, SQLite upsert memory, and Markdown ADR export.
