from __future__ import annotations

import ast
import unittest
from pathlib import Path


COMPONENTS_ROOT = Path(__file__).resolve().parent


class ComponentImportBoundaryTests(unittest.TestCase):
    def test_runtime_code_imports_other_components_through_api(self) -> None:
        violations: list[str] = []
        for path in COMPONENTS_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts or "test" in path.parts:
                continue
            relative = path.relative_to(COMPONENTS_ROOT)
            if len(relative.parts) < 3:
                continue
            owner = relative.parts[0]
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                for module in self._imported_modules(node):
                    parts = module.split(".")
                    if len(parts) >= 3 and parts[:1] == ["components"] and parts[2] == "src" and parts[1] != owner:
                        violations.append(f"{relative}:{node.lineno}: {module}")
        self.assertEqual([], violations)

    def _imported_modules(self, node: ast.AST) -> list[str]:
        if isinstance(node, ast.ImportFrom) and node.module:
            return [node.module]
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        return []


if __name__ == "__main__":
    unittest.main()
