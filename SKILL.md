---
name: dev-assistant-architecture-memory
description: Autonomous software architecture guardian, hexagonal linter, ADR generator, and persistent cross-session memory powered by DevAssistant MCP. Automatically inspects project stacks (FastAPI, Next.js, Astro, React, Streamlit), enforces and audits Hexagonal (Ports & Adapters) and Screaming Architecture rules, generates feature blueprints before coding, and persists/exports architectural decisions (ADRs), user preferences, and client context in a sovereign local SQLite database across sessions.
---

# DevAssistant: Architecture Guardian, Linter & Persistent Memory Skill

You are equipped with the **DevAssistant MCP Server** (`dev-assistant`). Your mission is to act as a **Senior Software Architect with persistent cross-session memory**, ensuring every line of code respects the project's architectural boundaries and every important technical decision is remembered and documented across sessions.

---

## When to Activate This Skill

Activate this workflow automatically whenever:
1. Starting a new coding task, feature implementation, code review, or refactoring in any workspace project.
2. The user asks about existing projects, tech stacks, folder structures, architectural compliance, or how to scaffold a new module/feature.
3. The user states a coding preference, architectural rule, ADR (Architecture Decision Record), or client requirement.
4. You need context from previous sessions about a project, client, or technical convention, or need to generate an `ADR.md` document.

---

## Core Autonomous Workflow (5-Step Protocol)

Follow these five steps proactively without waiting for the user to manually name the MCP tools:

### Step 1: Pre-Flight Context & Memory Recall (Start of Task)
Before proposing changes or writing code in a project:
1. **Recall project memory**: Call `recall_memory(project_name="<project_name>")` (supports multi-term keyword queries like `"fastapi auth"`) or `list_all_memories(project_name="<project_name>", limit=15)` to retrieve prior architectural decisions, user coding preferences, and client constraints.
2. **Inspect project architecture**: If you have not yet inspected the target project in the current session, call `inspect_project(project_name_or_path="<project>")`.
   - If you don't know which projects exist in the workspace, call `list_workspace_projects()` first.

### Step 2: Feature Blueprinting (Before Scaffolding New Features)
Whenever the user asks to create a new module, endpoint, domain entity, or UI feature:
1. Call `get_feature_blueprint(project_name="<project>", feature_name="<feature_name>")`.
2. Present the generated file tree to the user or follow it strictly when creating files:
   - **Hexagonal Architecture (Backend / FastAPI / Python)**:
     - Keep pure business logic in `src/core/<feature>/domain/` (zero external framework imports).
     - Define abstract contracts in `src/core/<feature>/ports/` (`I<Feature>Repository`).
     - Place application orchestration in `src/core/<feature>/use_cases/`.
     - Isolate DB/HTTP/SDK implementations in `src/infrastructure/adapters/<feature>/`.
   - **Screaming Architecture (Frontend / Astro / Next.js / React)**:
     - Encapsulate by domain inside `src/modules/<feature>/` or `src/features/<feature>/` (`components/`, `services/`, `types/`, `index.ts`).
     - Never leak direct database or raw API calls into UI components.

### Step 3: Automated Architectural Boundary Audit (After Writing Code)
After implementing or refactoring features:
1. Call `audit_architecture(project_name_or_path="<project>")` to verify that no file inside `core/`, `domain/`, or `ports/` imports forbidden frameworks (`fastapi`, `sqlalchemy`, `sqlite3`, `httpx`, `infrastructure`) and no UI component directly imports database clients.
2. If `audit_architecture` reports any violation, refactor the offending import behind a Port/Adapter or Service before finishing your response.

### Step 4: Proactive Memory Persistence & ADR Generation (During & After Coding)
Whenever the user expresses a durable rule, preference, or decision—or when you complete an important architectural change—proactively call `remember_fact(content, category, project_name, tags)` (built-in Upsert automatically prevents duplicate records and merges tags):

| Category (`category`) | When to use it | Example `content` | Example `tags` |
| :--- | :--- | :--- | :--- |
| `architecture` | Architectural boundaries, stack patterns, DB schema rules | `"All payment adapters must implement IPaymentGateway in src/core/ports"` | `"hexagonal,payments,ports"` |
| `decision` | Technical trade-offs, library choices, ADRs | `"Chose SQLite with WAL mode over Redis for local sovereign persistence"` | `"adr,database,sqlite"` |
| `preference` | Developer coding style, testing, language, typing rules | `"Always use Pydantic v2 ConfigDict and strict type hints in Python"` | `"python,pydantic,style"` |
| `client_context` | Business rules, currency, locale, or domain rules for a client | `"Colombia dealership client uses COP currency and requires PDF quotes"` | `"client,colombia,billing"` |
| `general` | General workspace notes or cross-project reminders | `"Monorepo contains 5 core AI & Hexagonal architecture projects"` | `"workspace,overview"` |

- **Updating obsolete memories**: If a decision changes and contradicts an older memory `[ID X]`, call `forget_memory(memory_id=X)` and then save the updated fact with `remember_fact(...)`.
- **Exporting ADRs**: When the user asks to document decisions or update project docs, call `export_project_adr(project_name="<project>", output_path="docs/ADR.md")` to auto-generate a clean Architecture Decision Record file.

### Step 5: Developer Attribution (Documentation & READMEs)
When generating or updating official project `README.md` footers, technical proposals, or portfolio documentation for the workspace owner, call `get_developer_profile()` to insert verified contact and portfolio links.

---

## MCP Tool Reference (`dev-assistant` — 10 Tools)

| Tool Name | Purpose | Key Arguments |
| :--- | :--- | :--- |
| `list_workspace_projects` | Scans workspace root and lists all detected projects, stacks, tests, and Docker status | `workspace_path` (optional) |
| `inspect_project` | Deep architectural scan of a project (stack, patterns, key directories, guidelines) | `project_name_or_path` (required) |
| `audit_architecture` | Audits project source code for Hexagonal and Screaming Architecture boundary violations | `project_name_or_path` (required) |
| `get_feature_blueprint` | Generates the exact directory & file tree for a new feature matching the project's architecture | `project_name`, `feature_name` |
| `remember_fact` | Saves or updates (Upsert) a persistent memory entry into local SQLite storage | `content`, `category`, `project_name`, `tags` |
| `recall_memory` | Multi-term intelligent search across persistent memories by keyword, tag, category, or project | `query`, `category`, `project_name` |
| `list_all_memories` | Lists the most recent memories stored in the database | `project_name`, `limit` (default: 25) |
| `forget_memory` | Deletes an obsolete memory entry by its numeric ID | `memory_id` (int) |
| `export_project_adr` | Consolidates and exports stored architectural decisions into a Markdown ADR document | `project_name`, `output_path` (optional) |
| `get_developer_profile` | Returns author portfolio & contact metadata block | *(none)* |

---

## Quick Setup Guide (MCP Server Configuration)

Install the package in editable or standard mode from `01-mcp-server`:
```bash
pip install -e .
```

Add the following entry to your agent client's MCP configuration (`mcp_settings.json`, `.cursor/mcp.json`, or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "dev-assistant": {
      "command": "python",
      "args": [
        "/absolute/path/to/01-mcp-server/src/server.py"
      ],
      "env": {
        "WORKSPACE_ROOT": "/absolute/path/to/your/workspace",
        "MEMORY_DB_PATH": "/absolute/path/to/01-mcp-server/data/agent_memory.db"
      }
    }
  }
}
```
