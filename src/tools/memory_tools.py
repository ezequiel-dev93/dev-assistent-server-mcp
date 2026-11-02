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
