import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from ..core.errors import DevAssistantError
from ..core.models import MemoryCategory, MemoryEntry, MemoryScope
from ..core.ports import IMemoryRepository
from ..core.services.redaction import redact
from .markdown_presenter import (
    render_memory_list,
    render_recalled_memories,
    render_saved_memory,
)
from .workspace_guard import WorkspaceGuard


class MemoryTools:
    """Application tools for persistent sovereign memory with secret redaction, versioning, and FTS5 recall."""

    def __init__(
        self,
        repository: IMemoryRepository,
        guard: Optional[WorkspaceGuard] = None,
    ) -> None:
        self.repository = repository
        self.guard = guard

    def remember(
        self,
        content: str,
        category: str = "general",
        project_name: Optional[str] = None,
        tags: Optional[str] = None,
        supersedes: Optional[int] = None,
    ) -> str:
        try:
            cat_enum = MemoryCategory(category.lower().strip())
        except ValueError:
            cat_enum = MemoryCategory.GENERAL

        redacted_content, content_labels = redact(content.strip())
        raw_tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        clean_tags: List[str] = []
        tag_labels: List[str] = []
        for raw_t in raw_tag_list:
            red_t, t_lbls = redact(raw_t)
            clean_tags.append(red_t)
            for lbl in t_lbls:
                if lbl not in tag_labels:
                    tag_labels.append(lbl)

        all_labels = list(dict.fromkeys([*content_labels, *tag_labels]))

        entry = MemoryEntry(
            category=cat_enum,
            content=redacted_content,
            project_name=project_name.strip() if project_name and project_name.strip() else None,
            tags=clean_tags,
            redacted_labels=all_labels,
        )

        saved = self.repository.save_memory(entry, supersedes=supersedes)
        saved.redacted_labels = all_labels
        return render_saved_memory(saved, superseded_id=supersedes)

    def recall(
        self,
        query: str = "",
        category: Optional[str] = None,
        project_name: Optional[str] = None,
        scope: str = "all",
        include_history: bool = False,
        limit: int = 50,
    ) -> str:
        cat_enum = None
        if category and category.strip():
            try:
                cat_enum = MemoryCategory(category.lower().strip())
            except ValueError:
                pass

        try:
            scope_enum = MemoryScope(scope.lower().strip())
        except ValueError:
            scope_enum = MemoryScope.ALL

        results = self.repository.search_memories(
            query=query,
            category=cat_enum,
            project_name=project_name,
            scope=scope_enum,
            include_history=include_history,
            limit=limit,
        )

        if not results:
            scope_msg = f" con búsqueda '{query}'" if query else ""
            if project_name:
                scope_msg += f" en proyecto '{project_name}'"
            return f"No se encontraron recuerdos persistentes{scope_msg}."

        return render_recalled_memories(results)

    def list_all(
        self,
        project_name: Optional[str] = None,
        scope: str = "all",
        include_history: bool = False,
        limit: int = 25,
    ) -> str:
        try:
            scope_enum = MemoryScope(scope.lower().strip())
        except ValueError:
            scope_enum = MemoryScope.ALL

        results = self.repository.list_memories(
            project_name=project_name,
            scope=scope_enum,
            include_history=include_history,
            limit=limit,
        )
        if not results:
            filter_str = f" para el proyecto '{project_name}'" if project_name else ""
            return f"No hay recuerdos almacenados en la base de datos{filter_str}."

        return render_memory_list(results, title="Historial de Memoria")

    def review_stale(self, days: int = 180) -> str:
        """Lists stale memories unused for `days` days as review candidates without deleting anything."""
        stale = self.repository.list_stale_memories(days=days)
        if not stale:
            return f"✅ No se detectaron recuerdos obsoletos sin uso en los últimos {days} días."
        return render_memory_list(
            stale,
            title=f"Candidatos a Revisión (Sin uso por >{days} días — sugerencia, nada fue eliminado)",
        )

    def forget(self, memory_id: int) -> str:
        success = self.repository.delete_memory(memory_id)
        if success:
            return f"🗑️ Recuerdo con ID {memory_id} eliminado exitosamente."
        return f"⚠️ No se encontró ningún recuerdo con ID {memory_id} para eliminar."

    def render_consolidated_adr_from_memory(
        self, project_name: Optional[str] = None
    ) -> str:
        """Consolidates architecture & decision memories into a readable Markdown document (read-only)."""
        clean_proj = project_name.strip() if project_name and project_name.strip() else None
        memories = self.repository.list_memories(
            project_name=clean_proj,
            scope=MemoryScope.PROJECT if clean_proj else MemoryScope.ALL,
            include_history=False,
            limit=500,
        )

        if not memories:
            scope = f" para el proyecto `{clean_proj}`" if clean_proj else ""
            return f"No existen registros en memoria{scope} para generar un ADR."

        title_scope = f" — Proyecto `{clean_proj}`" if clean_proj else " — Global Workspace"
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        sections = {
            MemoryCategory.ARCHITECTURE: "🏛️ 1. Reglas y Límites de Arquitectura (`architecture`)",
            MemoryCategory.DECISION: "⚖️ 2. Decisiones Técnicas y Trade-offs (`decision`)",
            MemoryCategory.PREFERENCE: "⚙️ 3. Estándares de Código y Preferencias (`preference`)",
            MemoryCategory.CLIENT_CONTEXT: "🤝 4. Contexto de Dominio y Reglas de Negocio (`client_context`)",
            MemoryCategory.GENERAL: "📌 5. Notas Generales (`general`)",
        }

        md_lines = [
            f"# 📄 Architecture Decision Records (ADR){title_scope}",
            "",
            "> **Generado automáticamente por:** `DevAssistant MCP Server`  ",
            f"> **Fecha de consolidación:** `{today_str}`  ",
            f"> **Total de registros documentados:** `{len(memories)}`",
            "",
            "---",
            "",
        ]

        seq_idx = 1
        for cat_enum, header in sections.items():
            cat_items = [m for m in memories if m.category == cat_enum]
            if not cat_items:
                continue

            md_lines.append(f"## {header}")
            md_lines.append("")
            for item in reversed(cat_items):
                date_badge = (
                    item.created_at.strftime("%Y-%m-%d") if item.created_at else today_str
                )
                proj_badge = (
                    f" **[`{item.project_name}`]**"
                    if item.project_name and not clean_proj
                    else ""
                )
                tags_badge = f" — *Tags: `{', '.join(item.tags)}`*" if item.tags else ""
                md_lines.append(
                    f"- **[ADR-{seq_idx:03d}]** ({date_badge}){proj_badge}: {item.content}{tags_badge}"
                )
                seq_idx += 1
            md_lines.append("")

        return "\n".join(md_lines).strip() + "\n"

    def write_consolidated_adr(
        self,
        output_path: str,
        project_name: Optional[str] = None,
        overwrite: bool = False,
    ) -> str:
        """Writes consolidated ADR Markdown strictly within WorkspaceGuard (.md only)."""
        try:
            if self.guard is not None:
                target_file = self.guard.resolve_output(
                    output_path, suffixes=frozenset({".md"})
                )
            else:
                target_file = Path(output_path).resolve()
                if target_file.suffix.lower() != ".md":
                    return f"Error: Disallowed extension '{target_file.suffix}'. Only .md is permitted."

            if target_file.exists() and not overwrite:
                return (
                    f"Error: File '{target_file}' already exists. Pass `overwrite=True` to replace it."
                )

            md = self.render_consolidated_adr_from_memory(project_name=project_name)
            if md.startswith("No existen registros"):
                return md

            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(md, encoding="utf-8")
            return f"✅ Documento ADR exportado exitosamente en `{target_file}`\n\n{md}"
        except (DevAssistantError, ValueError, OSError) as exc:
            return f"Error: {exc}"

    def export_adr(
        self,
        project_name: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """Backwards-compatible helper: renders if output_path is empty, otherwise writes with overwrite=True inside guard."""
        if output_path and output_path.strip():
            return self.write_consolidated_adr(
                output_path=output_path,
                project_name=project_name,
                overwrite=True,
            )
        return self.render_consolidated_adr_from_memory(project_name=project_name)

    def export_json_payload(self, project_name: Optional[str] = None) -> str:
        """CLI-only helper to export memories as versioned JSON."""
        memories = self.repository.list_memories(
            project_name=project_name,
            scope=MemoryScope.PROJECT if project_name else MemoryScope.ALL,
            include_history=True,
            limit=10_000,
        )
        payload = {
            "schema": 4,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": len(memories),
            "memories": [
                {
                    "id": m.id,
                    "category": m.category.value,
                    "content": m.content,
                    "project_name": m.project_name,
                    "tags": m.tags,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                    "superseded_by": m.superseded_by,
                    "content_hash": m.content_hash,
                }
                for m in reversed(memories)
            ],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def import_json_payload(self, raw_json: str) -> Dict[str, Any]:
        """CLI-only idempotent import of versioned JSON memories with automatic secret redaction."""
        data = json.loads(raw_json)
        items = data.get("memories", [])
        if not isinstance(items, list):
            raise ValueError("Invalid JSON backup: 'memories' must be a list.")

        imported = 0
        redacted_count = 0
        for item in items:
            if not isinstance(item, dict) or not item.get("content"):
                continue
            red_content, lbls = redact(str(item["content"]))
            if lbls:
                redacted_count += 1
            cat_str = str(item.get("category", "general")).lower()
            try:
                cat = MemoryCategory(cat_str)
            except ValueError:
                cat = MemoryCategory.GENERAL
            tags = [ redact(str(t))[0] for t in item.get("tags", []) if str(t).strip() ]
            entry = MemoryEntry(
                category=cat,
                content=red_content,
                project_name=item.get("project_name"),
                tags=tags,
            )
            self.repository.save_memory(entry)
            imported += 1

        return {"imported": imported, "redacted_entries": redacted_count}
