# 🧠 DevAssistant MCP Server v2.1: Guardián de Arquitectura, Linter AST, MADR, Memoria FTS5 & QA Freelance Toolkit

[![Version](https://img.shields.io/badge/Version-2.1.0-brightgreen.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Protocol](https://img.shields.io/badge/MCP-1.x%20%26%202.x%20Compatible-purple.svg)](https://modelcontextprotocol.io/)
[![Skill](https://img.shields.io/badge/Agent%20Skill-Available%20on%20Agensi-blue.svg)](https://www.agensi.io/r/EZEQUIELSUAREZ)
[![Architecture](https://img.shields.io/badge/Architecture-Hexagonal%20Self--Audited-green.svg)](devassistant.toml)
[![Storage](https://img.shields.io/badge/Storage-SQLite%20FTS5%20%2B%20MADR-orange.svg)](#-memoria-persistente-fts5--madr)
[![License](https://img.shields.io/badge/License-Proprietary%20%7C%20All%20Rights%20Reserved-critical.svg)](LICENSE)

Servidor bajo el estándar **Model Context Protocol (MCP)** + CLI para CI/CD + paquete **`SKILL.md`** desarrollado en **Python** con **Arquitectura Hexagonal pura** (auditado automáticamente por sí mismo en CI con **0 violaciones**).

Convierte a cualquier agente de código (**Claude Code, Cursor, Antigravity, Claude Desktop, Copilot, Windsurf**) en un **Principal Software Architect y Lead QA Automation Engineer**:

1. **🛡️ Auditor Estático de Arquitectura v2 (Grafo + AST + Ciclos + SARIF):** Construye el grafo de módulos resuelto (AST nativo para Python + extractor TypeScript/Astro/React), valida capas y paquetes externos según `devassistant.toml` o presets automáticos, detecta dependencias circulares (algoritmo de Tarjan SCC) y exporta reportes **SARIF 2.1.0** para Pull Requests en GitHub.
2. **🧠 Memoria Soberana v2 (SQLite FTS5 + BM25 + Versionado + Redacción de Secretos):** Persistencia local en `~/.dev-assistant/agent_memory.db` con búsqueda de texto completo sin tildes (`unicode61 remove_diacritics 2`), reemplazo evolutivo de decisiones (`supersedes`), combinación de alcance `project + global` y redacción automática de API Keys/Tokens antes de tocar disco.
3. **📄 Gestión de ADRs en Formato MADR & Detección de Drift (`check_adr_drift`):** Versiona decisiones formales en `docs/adr/NNNN-slug.md` vinculadas a IDs de reglas (`enforced_by`) y verifica en tiempo real si algún cambio de código contradice un ADR aceptado.
4. **🧪 Suite de Testing y QA Automatizado sin salir del Chat:** Prueba endpoints HTTP individuales o suites batch con inyección segura de credenciales locales (`auth_env_var`), auditoría estática de `.env` vs `docker-compose.yml`, inspección de salud de contenedores Docker y ejecución aislada de tests (`pytest`/`unittest`).
5. **🔒 Seguridad Endurecida (`WorkspaceGuard`):** Contención multi-raíz contra *path traversal* y symlinks, bloqueo de SSRF a Cloud Metadata (`169.254.169.254`), mitigación de indirect prompt injection con etiquetas delimitadoras `<stored_memory>` y `<http_response>`.

---

## 🏛️ Arquitectura del Servidor (Hexagonal)

<p align="center">
  <img src="docs/architecture.svg" alt="Arquitectura Hexagonal del Servidor MCP" width="100%" />
</p>

```text
01-mcp-server/
├── pyproject.toml                 # Empaquetado PEP 621 (dev-assistant-mcp) + Ruff + Pytest + Mypy
├── devassistant.toml              # Dogfooding: reglas con las que el servidor se audita a sí mismo
├── SKILL.md                       # Protocolo autónomo de 5 pasos para Agentes IA
├── CHANGELOG.md                   # Historial de versiones (v2.0.0)
├── src/
│   ├── __init__.py                # Versión y mapeo limpio de paquete
│   ├── __main__.py                # Soporte `python -m src` / `python -m dev_assistant_mcp`
│   ├── cli.py                     # Driving Adapter CLI (`serve` default | `audit` | `memory` | `adr`)
│   ├── settings.py                # Configuración de usuario sin side-effects + migración segura de DB
│   ├── server.py                  # Driving Adapter MCP (17 Tools, 3 Resources, 3 Prompts, Annotations)
│   ├── core/                      # DOMINIO PURO (Solo Python stdlib + Pydantic v2)
│   │   ├── errors.py
│   │   ├── models.py
│   │   ├── ports.py               # IProjectScanner, IMemoryRepository, IImportExtractor, IAdrRepository...
│   │   └── services/              # Lógica pura sin I/O: redaction, cycles (Tarjan), rules_engine, drift, blueprint
│   ├── tools/                     # Capa de Aplicación & Presentación Markdown
│   │   ├── workspace_guard.py     # Frontera de seguridad de archivos multi-raíz
│   │   ├── markdown_presenter.py  # Formateadores y delimitadores <stored_memory>
│   │   ├── project_tools.py
│   │   ├── memory_tools.py
│   │   └── adr_tools.py
│   └── infrastructure/            # DRIVEN ADAPTERS
│       ├── extractors/            # python_ast.py & typescript_regex.py
│       ├── resolvers/             # module_resolver.py
│       ├── config/                # toml_loader.py & presets (hexagonal, screaming, django)
│       ├── scanner/               # filesystem_scanner.py (con poda rápida de node_modules)
│       ├── storage/               # migrations.py (PRAGMA user_version=4) & sqlite_memory.py (FTS5)
│       ├── adr/                   # madr_filesystem.py (docs/adr/NNNN-slug.md)
│       └── reporting/             # sarif.py (SARIF 2.1.0)
└── tests/                         # 21 suites: Unit, Contract (SQLite + InMemory), Self-Audit & E2E MCP
```

---

## 🚀 Instalación y Configuración Rápida

Requisitos: **Python 3.10+** y **Git** instalado.

### Opción A: Instalación en 1 línea con `uvx` (Recomendada para Clientes MCP)

Agrega este bloque en tu `mcp_settings.json`, `.cursor/mcp.json` o `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dev-assistant": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/ezequiel-dev93/dev-assistent-server-mcp@v2.0.0",
        "dev-assistant-mcp"
      ],
      "env": {
        "DEVASSISTANT_WORKSPACE_ROOTS": "/ruta/absoluta/a/tu/workspace"
      }
    }
  }
}
```

### Opción B: Instalación Local Editable (`pip`)

```bash
git clone https://github.com/ezequiel-dev93/dev-assistent-server-mcp.git
cd dev-assistent-server-mcp
pip install -e ".[dev]"
```

> **Persistencia Segura:** Por defecto, la base de datos SQLite vive en `~/.dev-assistant/agent_memory.db` (fuera de la caché temporal de `uvx`), migrando automáticamente cualquier base de datos previa sin perder registros y creando backups `.bak-v{n}` antes de cada actualización de esquema.

---

## 🛠️ Catálogo Completo v2.1 (22 MCP Tools + Resources + Prompts)

### 📂 1. Exploración, Auditoría AST y Blueprints
* **`list_workspace_projects(workspace_path)`**: Escanea el workspace y detecta stacks (`FastAPI`, `Next.js`, `Astro`, `React`, `Django`, `NestJS`, `Streamlit`), tests y Docker.
* **`inspect_project(project_name_or_path)`**: Radiografía arquitectónica con directrices para el LLM y resumen de README sanitizado.
* **`audit_architecture(project_name_or_path)`**: Audita el grafo de módulos resuelto contra `devassistant.toml` o el preset autodetectado, reportando violaciones de capas, imports externos prohibidos y ciclos (Tarjan SCC).
* **`get_feature_blueprint(project_name, feature_name)`**: Genera el plano exacto de archivos según la arquitectura del proyecto.
* **`apply_blueprint(project_name, feature_name, dry_run=True)`**: Previsualiza o crea la estructura de una nueva feature sin sobrescribir archivos existentes.
* **`get_author_profile()`**: Retorna el bloque de firma del desarrollador configurado en `~/.dev-assistant/config.toml` o `DEVASSISTANT_AUTHOR_*`.

### 🧠 2. Memoria Persistente Soberana (SQLite FTS5)
* **`remember_fact(content, category, project_name, tags, supersedes)`**: Guarda o actualiza (Upsert por hash normalizado) memorias con **redacción automática de secretos** y soporte de versionado (`supersedes`).
* **`recall_memory(query, category, project_name, scope, include_history, limit)`**: Búsqueda **FTS5 + BM25** insensible a tildes combinando memorias del proyecto + globales (`scope="all"`).
* **`list_all_memories(project_name, scope, include_history, limit)`**: Lista memorias activas o históricas.
* **`review_stale_memories(days=180)`**: Sugiere recuerdos antiguos sin uso para revisión manual (nunca borra automáticamente).
* **`forget_memory(memory_id)`**: Elimina permanentemente un recuerdo por su ID.

### 📄 3. ADRs en Formato MADR & Detección de Drift
* **`record_decision(project_name, title, context, decision, consequences, status, supersedes, enforced_by, tags)`**: Crea `docs/adr/NNNN-slug.md` y regenera `docs/adr/README.md`.
* **`list_adrs(project_name)`**: Lista todos los ADRs del proyecto.
* **`update_adr_status(project_name, adr_number, status, superseded_by)`**: Actualiza el ciclo de vida de un ADR sincronizando archivos reemplazados.
* **`check_adr_drift(project_name)`**: Cruza los ADRs `accepted` y sus reglas `enforced_by` contra el auditor estático para detectar deriva arquitectónica.
* **`render_adr(project_name)`** / **`write_adr(output_path, project_name, overwrite)`**: Renderiza o exporta un resumen consolidado desde la memoria SQLite.

### 🧪 4. Testing, Diagnóstico Docker y QA Freelance
* **`test_api_endpoint(url, method, expected_status, ...)`**: Ejecuta peticiones HTTP/REST contra endpoints verificando status, latencia y JSON dot-paths, con inyección segura de variables de entorno locales (`auth_env_var`).
* **`run_api_test_suite(endpoints, base_url, ...)`**: Ejecuta una batería completa de pruebas API con tabla de diagnóstico consolidada.
* **`audit_env_and_docker(project_name_or_path)`**: Audita sincronización `.env` $\leftrightarrow$ `.env.example`, variables Compose sin fallback, credenciales hardcodeadas, directivas `Dockerfile` y exclusiones en `.dockerignore`.
* **`inspect_docker_stack(project_name_or_path, tail_logs)`**: Inspecciona estado en tiempo real de contenedores Docker, healthchecks y puertos publicados, extrayendo logs sanitizados de servicios caídos.
* **`run_project_tests(project_name_or_path, target_subpath, keyword, timeout_seconds)`**: Ejecuta la suite de pruebas del proyecto (`pytest` o `unittest discover`) en un subproceso aislado, retornando métricas y diagnóstico de fallos.

---

## ⚙️ Uso por Consola (CLI) e Integración CI / GitHub Actions

El binario `dev-assistant-mcp` sin argumentos inicia el servidor MCP `stdio`, pero también incluye subcomandos para desarrollo y pipelines de CI:

```bash
# Auditar arquitectura en consola (exit code 1 si hay errores)
dev-assistant-mcp audit . --fail-on error

# Exportar reporte SARIF 2.1.0 para GitHub Code Scanning en Pull Requests
dev-assistant-mcp audit . --format sarif --output audit.sarif

# Verificar que ningún ADR aceptado esté siendo violado
dev-assistant-mcp adr drift . --fail-on error

# Exportar / importar backup JSON de la memoria SQLite (solo disponible por CLI humano)
dev-assistant-mcp memory export --output backup.json
dev-assistant-mcp memory import backup.json

# Ejecutar auditoría estática de .env y Docker
dev-assistant-mcp qa env-docker . --fail-on error

# Probar endpoint HTTP con assertions y auth desde variable de entorno
dev-assistant-mcp qa endpoint http://localhost:8000/api/health --expect-status 200 --expect-keys status

# Ejecutar suite de pruebas en subproceso aislado
dev-assistant-mcp qa test . --timeout 60

# Diagnosticar estado de contenedores Docker y extraer logs de caídas
dev-assistant-mcp qa docker .
```

### Ejemplo de `devassistant.toml` por Proyecto

```toml
version = 1
preset = "hexagonal-python"

[layers]
domain         = ["src/core/**"]
application    = ["src/tools/**"]
infrastructure = ["src/infrastructure/**"]

[[rules]]
id = "domain-no-infra"
from = "domain"
disallow_layers = ["infrastructure", "application"]
severity = "error"

[[rules]]
id = "domain-no-frameworks"
from = "domain"
allow_external = ["pydantic"]
disallow_external = ["fastapi", "sqlalchemy", "sqlite3", "mcp"]
severity = "error"

[[rules]]
id = "no-cycles"
kind = "cycles"
severity = "warning"
```

---

## 🧪 Ejecutar Suite de Pruebas

```bash
python -m unittest discover -s tests -p "test_*.py" -v
# o con pytest:
pytest -v
```

---

## 👨‍💻 Autor y Contacto

Desarrollado con dedicación por **Ezequiel Suárez** — AI Software Engineer & Full-Stack Architect.

- 🌐 **Portfolio:** [ezequielsuarez-dev.com](https://www.ezequielsuarez-dev.com/)
- 🛒 **Agensi Marketplace:** [agensi.io/r/EZEQUIELSUAREZ](https://www.agensi.io/r/EZEQUIELSUAREZ)
- 🐙 **GitHub:** [@ezequiel-dev93](https://github.com/ezequiel-dev93)
- 💼 **LinkedIn:** [in/ezequiel-suarez-dev](https://www.linkedin.com/in/ezequiel-suarez-dev/)
- ✉️ **Contacto:** [ezequielsuarez.dev@gmail.com](mailto:ezequielsuarez.dev@gmail.com)
