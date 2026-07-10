"""Wire cross-module imports for Phase 8 knowledge package and write __init__.py."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "app" / "services" / "knowledge"
MODULES = [
    "utils",
    "permissions",
    "ranking",
    "grounding",
    "settings",
    "feedback",
    "gaps",
    "analytics",
    "library",
    "ingestion",
    "retrieval",
    "qa",
    "streaming",
]


def defined_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def loaded_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
    return names


def strip_bad_imports(text: str) -> str:
    out = []
    for line in text.splitlines(True):
        if "from app.services.knowledge.utils import *" in line:
            continue
        if "from app.services.knowledge import permissions as _knowledge_permissions" in line:
            continue
        out.append(line)
    return "".join(out)


def main() -> None:
    owners: dict[str, str] = {}
    module_defs: dict[str, set[str]] = {}
    for mod in MODULES:
        defs = defined_names(PKG / f"{mod}.py")
        module_defs[mod] = defs
        for name in defs:
            owners[name] = mod

    # Build required imports per module (excluding self and builtins-ish)
    skip = {
        "True",
        "False",
        "None",
        "list",
        "dict",
        "set",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "object",
        "type",
        "len",
        "min",
        "max",
        "sum",
        "sorted",
        "enumerate",
        "zip",
        "range",
        "isinstance",
        "issubclass",
        "getattr",
        "setattr",
        "hasattr",
        "print",
        "Exception",
        "ValueError",
        "RuntimeError",
        "TypeError",
        "KeyError",
        "AttributeError",
        "StopIteration",
        "any",
        "all",
        "next",
        "iter",
        "open",
        "super",
        "property",
        "classmethod",
        "staticmethod",
        "round",
        "abs",
        "repr",
        "ascii",
        "format",
        "id",
        "hash",
        "hex",
        "ord",
        "chr",
        "vars",
        "dir",
        "map",
        "filter",
        "reversed",
        "slice",
        "memoryview",
        "bytearray",
        "frozenset",
        "complex",
        "Ellipsis",
        "NotImplemented",
        "__name__",
        "__file__",
        "logger",
    }

    needed: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for mod in MODULES:
        path = PKG / f"{mod}.py"
        used = loaded_names(path) - module_defs[mod] - skip
        for name in used:
            owner = owners.get(name)
            if owner and owner != mod:
                needed[mod][owner].add(name)

    # Known cycles: break by making analytics<-library and gaps<-qa use local imports later if needed
    for mod in MODULES:
        path = PKG / f"{mod}.py"
        text = strip_bad_imports(path.read_text(encoding="utf-8"))

        import_block = []
        for owner, names in sorted(needed[mod].items()):
            # Avoid hard cycle analytics <-> library at module top-level:
            # analytics imports library symbols lazily if any.
            if mod == "analytics" and owner == "library":
                continue
            if mod == "library" and owner in {"ingestion", "qa", "streaming", "retrieval"}:
                # library shouldn't need these; if AST says so, skip and rely on local imports later
                continue
            if mod == "gaps" and owner in {"qa", "streaming", "retrieval"}:
                continue
            if mod == "ranking" and owner in {"ingestion", "retrieval", "qa", "library"}:
                continue
            if mod == "grounding" and owner in {"qa", "streaming", "retrieval", "ingestion"}:
                continue
            if mod == "permissions" and owner not in {"utils"}:
                continue
            if mod == "utils" and owner:
                continue
            sorted_names = ",\n    ".join(sorted(names))
            import_block.append(
                f"from app.services.knowledge.{owner} import (\n    {sorted_names},\n)\n"
            )

        # Insert imports after logger line
        if "logger = logging.getLogger(__name__)\n" in text:
            marker = "logger = logging.getLogger(__name__)\n"
            insert = marker + "\n" + "".join(import_block) + ("\n" if import_block else "")
            text = text.replace(marker, insert, 1)
        else:
            text = "".join(import_block) + text

        path.write_text(text, encoding="utf-8")
        print(f"wired {mod}: imports from {sorted(needed[mod].keys())}")

    # Write __init__.py with explicit re-exports for compatibility
    export_groups = {
        "utils": sorted(module_defs["utils"]),
        "permissions": sorted(module_defs["permissions"]),
        "ranking": sorted(module_defs["ranking"]),
        "grounding": sorted(module_defs["grounding"]),
        "settings": sorted(module_defs["settings"]),
        "feedback": sorted(module_defs["feedback"]),
        "gaps": sorted(module_defs["gaps"]),
        "analytics": sorted(module_defs["analytics"]),
        "library": sorted(module_defs["library"]),
        "ingestion": sorted(module_defs["ingestion"]),
        "retrieval": sorted(module_defs["retrieval"]),
        "qa": sorted(module_defs["qa"]),
        "streaming": sorted(module_defs["streaming"]),
    }

    init_lines = [
        '"""Operational Knowledge Agent services (Phase 8 modular package)."""',
        "",
        "from __future__ import annotations",
        "",
        "# Import order matters: leaf modules first to avoid circular imports.",
    ]
    for mod in MODULES:
        names = export_groups[mod]
        if not names:
            continue
        init_lines.append(f"from app.services.knowledge.{mod} import (  # noqa: F401")
        for name in names:
            init_lines.append(f"    {name},")
        init_lines.append(")")
        init_lines.append("")

    # Re-export LLMClient / get_openai_client for monkeypatch compatibility
    init_lines.extend(
        [
            "from app.services.llm.client import LLMClient  # noqa: F401",
            "from app.services.llm.openai_client import get_openai_client  # noqa: F401",
            "",
            "__all__ = [",
        ]
    )
    all_names = []
    for mod in MODULES:
        all_names.extend(export_groups[mod])
    all_names.extend(["LLMClient", "get_openai_client"])
    for name in sorted(set(all_names)):
        init_lines.append(f'    "{name}",')
    init_lines.append("]")
    init_lines.append("")

    (PKG / "__init__.py").write_text("\n".join(init_lines) + "\n", encoding="utf-8")
    print("wrote __init__.py")


if __name__ == "__main__":
    main()
