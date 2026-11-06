# 🗺️ Roadmap de Producto y Expansión de Stacks — DevAssistant MCP

Este documento registra la estrategia de evolución técnica y comercial de **DevAssistant MCP Server**, priorizando las integraciones por impacto en el mercado de agentes de IA y costo de implementación sobre nuestra arquitectura Hexagonal.

---

## ✅ v2.0.0 — En Producción (Base Sólida Python + TypeScript)

### Stacks Soportados Actualmente
- **Python (`PythonAstImportExtractor`):**
  - **FastAPI** (Hexagonal / Ports & Adapters / Clean Layered)
  - **Django** (Preset dedicado: aislamiento de `models`, `services`, `serializers`, `views`)
  - **Streamlit** (Data & AI Apps con separación de dominio)
  - **Python Genérico** (Librerías, CLIs, servidores MCP)
- **TypeScript / JavaScript (`TypeScriptRegexImportExtractor`):**
  - **Next.js** (App Router & Pages, Screaming Architecture `features/` o `modules/`)
  - **Astro** (Soporte de frontmatter `---` + islas React/TS)
  - **React** (Vite / SPA con aislamiento de componentes y servicios)
  - **NestJS** (Detección de `@nestjs/core`, módulos y controladores)
  - **Node.js Genérico**

### Capacidades Core v2.0.0
- Grafo de módulos resuelto + detección de ciclos (Tarjan SCC) + exportación **SARIF 2.1.0**.
- Reglas declarativas por proyecto (`devassistant.toml` o `[tool.devassistant]` en `pyproject.toml`).
- Gestión de ADRs en formato **MADR** (`docs/adr/NNNN-slug.md`) y detección de **ADR Drift** (`check_adr_drift`).
- Memoria soberana **SQLite FTS5** (BM25 sin tildes), versionado con `supersedes` y redacción automática de secretos.
- Seguridad multi-raíz (`WorkspaceGuard`) y delimitadores anti *prompt-injection* (`<stored_memory>`).

---

## 🔜 v2.1.0 — Expansión Full-Stack Web TS/JS (Bajo Esfuerzo / Rápido Retorno)

Aprovechando que el motor de resolución TypeScript/JavaScript (`ProjectModuleResolver`) ya está construido, sumaremos soporte nativo para los frameworks full-stack modernos más usados:

### 1. Nuevos Stacks en `ProjectStack` (`src/core/models.py`)
- **Remix / React Router v7 (`REMIX`):**
  - **Detección:** `@remix-run/react`, `@remix-run/node` o `@react-router/dev` en `package.json`.
  - **Reglas / Preset:** Separar `app/routes/` (UI + loaders/actions) de `app/domain/` o `app/services/`, evitando que componentes puramente visuales importen clientes de base de datos o SDKs de servidor.
- **Nuxt 3/4 (`NUXT`):**
  - **Detección:** `nuxt` en `package.json` o `nuxt.config.ts`.
  - **Extractor:** Extender `TypeScriptRegexImportExtractor` para extraer bloques `<script setup lang="ts">` y `<script>` en archivos `.vue`.
  - **Resolución:** Soportar alias `~/` además de `@/`.
- **SvelteKit (`SVELTEKIT`):**
  - **Detección:** `@sveltejs/kit` en `package.json` o `svelte.config.js`.
  - **Extractor:** Soportar bloques `<script>` en archivos `.svelte` y distinguir archivos `+page.svelte` (cliente) de `+page.server.ts` / `src/lib/server/` (servidor).
- **Hono / Fastify / Express (`NODE_API`):**
  - **Detección:** `hono`, `fastify` o `express` en `package.json` para APIs ligeras con arquitectura Hexagonal.

---

## 🚀 v2.2.0 — Soporte Nativo para Go (`golang`) (Gran Hito Backend & Microservicios)

**Argumento comercial:** La comunidad de **Go** es una de las que más aplica *Hexagonal Architecture*, *Clean Architecture* y *Standard Go Project Layout* (`cmd/`, `internal/domain`, `internal/ports`, `internal/adapter`), y prácticamente no existen servidores MCP especializados en auditar arquitectura en Go.

### Plan Técnico de Implementación (Sin tocar el Dominio)
1. **Detección de Proyecto (`filesystem_scanner.py`):**
   - Detectar `go.mod` como indicador de proyecto (`ProjectStack.GO`).
   - Extraer el nombre del módulo raíz (`module github.com/org/repo`) y dependencias clave (`gin`, `echo`, `fiber`, `chi`, `gorm`, `sqlx`, `pgx`, `grpc`).
2. **Nuevo Extractor (`src/infrastructure/extractors/go_extractor.py`):**
   - Implementar el puerto `IImportExtractor` para archivos `.go`.
   - Parsear bloques `import "pkg"` e `import ( ... )` (incluyendo alias e imports en blanco `_`), ignorando comentarios `//` y `/* ... */`.
3. **Resolución de Paquetes Go (`module_resolver.py`):**
   - Si el import comienza con el `module` de `go.mod` (ej. `github.com/org/repo/internal/domain`), resolverlo como arista interna hacia los archivos `.go` de ese directorio.
   - Distinguir librería estándar de Go (paquetes sin punto en el primer segmento, ej. `context`, `fmt`, `net/http`, `database/sql`) de paquetes externos (`github.com/...`, `gorm.io/...`).
4. **Preset `hexagonal-go` (`toml_loader.py`) y Blueprints (`blueprint_planner.py`):**
   - Capas por defecto:
     - `domain`: `["internal/domain/**", "internal/core/domain/**"]`
     - `application`: `["internal/usecase/**", "internal/application/**", "internal/ports/**"]`
     - `infrastructure`: `["internal/adapter/**", "internal/infrastructure/**", "internal/repository/**"]`
     - `entrypoint`: `["cmd/**", "main.go"]`
   - Prohibir que `domain` importe `gorm.io/*`, `github.com/gin-gonic/gin`, `github.com/gofiber/fiber`, `net/http` o `database/sql`.

---

## 🔭 v2.3+ — Evoluciones Futuras (Opcional según demanda)

- **AST Multi-lenguaje con `tree-sitter`:** Reemplazar los extractores regex de TS/Vue/Svelte por gramáticas `tree-sitter` detrás del puerto `IImportExtractor`.
- **Rust / Java / C# (.NET):** Extender el puerto `IImportExtractor` para proyectos Cargo (`Cargo.toml`) o soluciones `.NET` con Clean Architecture.
- **Modo HTTP / SSE Opcional:** Permitir ejecutar `dev-assistant-mcp serve --transport http` para equipos que compartan un auditor en red interna.
