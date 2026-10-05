"""Import graph purity: domain/ and ports/ must stay adapter- and I/O-free."""

import ast
import importlib
import sys
from pathlib import Path

import email_classifier

SRC = Path(email_classifier.__file__).parent

FORBIDDEN_ROOTS = {"httpx", "sqlite3", "fastapi", "yaml"}
FORBIDDEN_PREFIXES = (
    "email_classifier.adapters",
    "email_classifier.pipeline",
    "email_classifier.api",
    "email_classifier.config",
)

PURE_PACKAGES = [
    SRC / "domain",
    SRC / "ports",
]


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_domain_and_ports_import_no_adapters_or_io_modules():
    violations: list[str] = []
    for package_dir in PURE_PACKAGES:
        for py_file in package_dir.glob("*.py"):
            for module in _imports_of(py_file):
                root = module.split(".")[0]
                if root in FORBIDDEN_ROOTS or module.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f"{py_file.name}: imports {module}")
    assert violations == [], f"impure imports in domain/ports: {violations}"


def test_importing_domain_does_not_load_io_modules():
    # Re-import the pure packages from a CLEAN state, but only remove the
    # forbidden I/O roots and domain/ports submodules. Purging every
    # email_classifier* module would orphan class objects other tests already
    # imported (e.g. ScoreError), breaking `except ScoreError` identity.
    for module_name in list(sys.modules):
        root = module_name.split(".")[0]
        if root in FORBIDDEN_ROOTS or module_name in (
            "email_classifier",
            "email_classifier.domain",
            "email_classifier.domain.models",
            "email_classifier.ports",
        ):
            del sys.modules[module_name]

    importlib.import_module("email_classifier.domain.models")
    importlib.import_module("email_classifier.ports")

    loaded = {name for name in sys.modules if name.split(".")[0] in FORBIDDEN_ROOTS}
    assert loaded == set(), f"I/O modules loaded by pure packages: {sorted(loaded)}"
