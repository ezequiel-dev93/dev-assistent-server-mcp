import sys
from pathlib import Path
from typing import Optional, Set
from ...core.ports import IModuleResolver

_STDLIB_NAMES: Set[str] = getattr(
    sys,
    "stdlib_module_names",
    {
        "abc", "argparse", "ast", "asyncio", "base64", "collections", "concurrent",
        "contextlib", "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal",
        "difflib", "email", "enum", "errno", "fnmatch", "fractions", "functools",
        "gc", "getpass", "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http",
        "importlib", "inspect", "io", "itertools", "json", "keyword", "linecache",
        "locale", "logging", "lzma", "math", "mimetypes", "multiprocessing", "numbers",
        "operator", "os", "pathlib", "pickle", "platform", "plistlib", "pprint",
        "profile", "pstats", "queue", "quopri", "random", "re", "reprlib", "resource",
        "runpy", "sched", "secrets", "select", "selectors", "shelve", "shlex", "shutil",
        "signal", "site", "smtplib", "socket", "socketserver", "sqlite3", "ssl", "stat",
        "statistics", "string", "stringprep", "struct", "subprocess", "sys", "sysconfig",
        "syslog", "tabnanny", "tarfile", "tempfile", "textwrap", "threading", "time",
        "timeit", "tkinter", "token", "tokenize", "tomllib", "trace", "traceback",
        "tracemalloc", "tty", "turtle", "turtledemo", "types", "typing", "unicodedata",
        "unittest", "urllib", "uuid", "venv", "warnings", "wave", "weakref", "webbrowser",
        "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile",
        "zipimport", "zlib", "zoneinfo", "__future__",
    },
)

# Persistence & raw network drivers in stdlib are treated as external adapters so Hexagonal rules catch sqlite3 in domain!
_INFRA_STDLIB_DRIVERS = {"sqlite3", "urllib", "http", "socket", "smtplib", "xmlrpc"}

_NODE_BUILTINS = {
    "assert", "buffer", "child_process", "cluster", "crypto", "dgram", "dns",
    "events", "fs", "http", "http2", "https", "net", "os", "path", "perf_hooks",
    "process", "querystring", "readline", "stream", "string_decoder", "timers",
    "tls", "tty", "url", "util", "v8", "vm", "worker_threads", "zlib",
}


class ProjectModuleResolver(IModuleResolver):
    """Resolves Python and TypeScript/JS imports to project-relative files, stdlib, or external packages."""

    def is_stdlib(self, imported_module: str, source_file: Path) -> bool:
        ext = source_file.suffix.lower()
        top = imported_module.split(".")[0].split("/")[0]
        if ext == ".py":
            if top in _INFRA_STDLIB_DRIVERS:
                return False
            return top in _STDLIB_NAMES
        if imported_module.startswith("node:"):
            return True
        return top in _NODE_BUILTINS

    def resolve_internal(
        self,
        imported_module: str,
        source_file: Path,
        project_root: Path,
    ) -> Optional[Path]:
        ext = source_file.suffix.lower()
        if ext == ".py":
            return self._resolve_python(imported_module, project_root)
        return self._resolve_ts_js(imported_module, source_file, project_root)

    def _resolve_python(self, imported_module: str, project_root: Path) -> Optional[Path]:
        mod_path = imported_module.replace(".", "/")
        # Support `dev_assistant_mcp.*` mapped to `src/*` as well as direct `src.*` or root packages
        candidates_mod = [mod_path]
        if mod_path.startswith("dev_assistant_mcp/"):
            candidates_mod.append("src/" + mod_path[len("dev_assistant_mcp/") :])
        elif mod_path == "dev_assistant_mcp":
            candidates_mod.append("src")

        search_bases = [project_root, project_root / "src"]

        for m_rel in candidates_mod:
            for base in search_bases:
                if not base.is_dir():
                    continue
                py_candidate = base / f"{m_rel}.py"
                if py_candidate.is_file():
                    return py_candidate.relative_to(project_root)

                pkg_init = base / m_rel / "__init__.py"
                if pkg_init.is_file():
                    return pkg_init.relative_to(project_root)

                # Symbol import fallback: `from pkg.mod import ClassOrFunc` -> resolves to `pkg/mod.py`
                if "/" in m_rel:
                    parent_mod = m_rel.rsplit("/", 1)[0]
                    parent_py = base / f"{parent_mod}.py"
                    if parent_py.is_file():
                        return parent_py.relative_to(project_root)
                    parent_init = base / parent_mod / "__init__.py"
                    if parent_init.is_file():
                        return parent_init.relative_to(project_root)

        return None

    def _resolve_ts_js(
        self, imported_module: str, source_file: Path, project_root: Path
    ) -> Optional[Path]:
        candidate_base: Optional[Path] = None
        if imported_module.startswith("."):
            candidate_base = (source_file.parent / imported_module).resolve()
        elif imported_module.startswith("@/") or imported_module.startswith("~/"):
            rel_part = imported_module[2:]
            src_dir = project_root / "src"
            candidate_base = (src_dir / rel_part) if src_dir.is_dir() else (project_root / rel_part)
        else:
            return None

        try:
            if not candidate_base.is_relative_to(project_root.resolve()):
                return None
        except ValueError:
            return None

        ts_exts = ["", ".ts", ".tsx", ".js", ".jsx", ".astro", ".mjs"]
        for suffix in ts_exts:
            f_cand = candidate_base.with_suffix(suffix) if suffix else candidate_base
            if f_cand.is_file():
                return f_cand.relative_to(project_root.resolve())

        if candidate_base.is_dir():
            for idx_name in ["index.ts", "index.tsx", "index.js", "index.jsx"]:
                idx_file = candidate_base / idx_name
                if idx_file.is_file():
                    return idx_file.relative_to(project_root.resolve())

        return None
