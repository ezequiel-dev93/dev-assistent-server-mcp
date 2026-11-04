import os
from datetime import datetime, timezone
from typing import Optional
from src.core.models import MemoryCategory, MemoryEntry
from src.core.ports import IMemoryRepository


class MemoryTools:
    """Herramientas de memoria persistente del agente para exponer mediante MCP."""

    def __init__(self, repository: IMemoryRepository):
        self.repository = repository

    def remember(
        self,
        content: str,
        category: str = "general",
        project_name: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> str:
        """Guarda un hecho, regla, preferencia del usuario o decisión técnica en la memoria persistente."""
        try:
            cat_enum = MemoryCategory(category.lower().strip())
        except ValueError:
            cat_enum = MemoryCategory.GENERAL

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        entry = MemoryEntry(
            category=cat_enum,
            content=content.strip(),
            project_name=project_name.strip() if project_name else None,
            tags=tag_list,
        )

        saved = self.repository.save_memory(entry)
        project_label = f" para el proyecto `{saved.project_name}`" if saved.project_name else ""
        return (
            f"✅ Recuerdo guardado exitosamente (ID: {saved.id}){project_label}:\n"
            f"- **Categoría:** {saved.category.value}\n"
            f"- **Contenido:** {saved.content}\n"
            f"- **Tags:** {', '.join(saved.tags) if saved.tags else 'ninguno'}"
        )

    def recall(
        self,
        query: str = "",
        category: Optional[str] = None,
        project_name: Optional[str] = None,
    ) -> str:
        """Busca recuerdos persistentes por palabras clave, categoría o proyecto."""
        cat_enum = None
        if category:
            try:
                cat_enum = MemoryCategory(category.lower().strip())
            except ValueError:
                pass

        results = self.repository.search_memories(
            query=query, category=cat_enum, project_name=project_name
        )

        if not results:
            scope = f" con búsqueda '{query}'" if query else ""
            if project_name:
                scope += f" en proyecto '{project_name}'"
            return f"No se encontraron recuerdos persistentes{scope}."

        lines = [f"🧠 Recuerdos recuperados ({len(results)}):", ""]
        for r in results:
            proj_str = f" [`{r.project_name}`]" if r.project_name else ""
            tags_str = f" (tags: {', '.join(r.tags)})" if r.tags else ""
            created_str = f" - {r.created_at.strftime('%Y-%m-%d')}" if r.created_at else ""
            lines.append(
                f"- **[ID {r.id}]** `{r.category.value}`{proj_str}: {r.content}{tags_str}{created_str}"
            )

        return "\n".join(lines)

    def list_all(
        self, project_name: Optional[str] = None, limit: int = 25
    ) -> str:
        """Lista los recuerdos más recientes almacenados en la base de datos local."""
        results = self.repository.list_memories(project_name=project_name, limit=limit)
        if not results:
            filter_str = f" para el proyecto '{project_name}'" if project_name else ""
            return f"No hay recuerdos almacenados en la base de datos{filter_str}."

        lines = [f"📋 Historial de Memoria ({len(results)} registros):", ""]
        for r in results:
            proj_str = f" [`{r.project_name}`]" if r.project_name else ""
            lines.append(f"- **#{r.id}** `[{r.category.value}]`{proj_str}: {r.content}")

        return "\n".join(lines)

    def forget(self, memory_id: int) -> str:
        """Elimina permanentemente un recuerdo usando su ID numérico."""
        success = self.repository.delete_memory(memory_id)
        if success:
            return f"🗑️ Recuerdo con ID {memory_id} eliminado exitosamente."
        return f"⚠️ No se encontró ningún recuerdo con ID {memory_id} para eliminar."

    def export_adr(
        self,
        project_name: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """Genera un documento Markdown de Architecture Decision Records (ADR) a partir de la memoria persistente."""
        clean_proj = project_name.strip() if project_name and project_name.strip() else None
        memories = self.repository.list_memories(project_name=clean_proj, limit=200)

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
            f"> **Generado automáticamente por:** `DevAssistant MCP Server`  ",
            f"> **Fecha de consolidación:** `{today_str}`  ",
            f"> **Total de registros documentados:** `{len(memories)}`",
            "",
            "---",
            "",
        ]

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
                proj_badge = f" **[`{item.project_name}`]**" if item.project_name and not clean_proj else ""
                tags_badge = (
                    f" — *Tags: `{', '.join(item.tags)}`*" if item.tags else ""
                )
                md_lines.append(
                    f"- **[ADR-{item.id:03d}]** ({date_badge}){proj_badge}: {item.content}{tags_badge}"
                )
            md_lines.append("")

        markdown_content = "\n".join(md_lines).strip() + "\n"

        if output_path and output_path.strip():
            abs_out = os.path.abspath(output_path.strip())
            os.makedirs(os.path.dirname(abs_out), exist_ok=True)
            with open(abs_out, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            return (
                f"✅ Documento ADR exportado exitosamente en `{abs_out}`\n\n"
                f"{markdown_content}"
            )

        return markdown_content
