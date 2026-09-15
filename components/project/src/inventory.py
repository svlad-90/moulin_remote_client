"""Project inventory workflow service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class ProjectInventoryService:
    """Own project inventory fetch and choose workflows."""

    def parse_ranges(self, raw: str, limit: int) -> list[int]:
        indexes: list[int] = []
        for item in raw.replace(",", " ").split():
            if "-" in item:
                start_s, end_s = item.split("-", 1)
                start = int(start_s)
                end = int(end_s)
                indexes.extend(range(start, end + 1))
            else:
                indexes.append(int(item))
        unique = sorted(set(indexes))
        for index in unique:
            if index < 1 or index > limit:
                raise ValueError(f"selection index out of range: {index}")
        return unique

    def read_selection_file(self, path: Path, *, normalize_path: Callable[[str], str]) -> list[str]:
        if not path.exists():
            raise SystemExit(f"selection file does not exist: {path}")
        paths: list[str] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                paths.append(normalize_path(line))
        if not paths:
            raise SystemExit(f"selection file is empty: {path}")
        return paths

    def write_selection_file(self, path: Path, paths: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(paths) + "\n", encoding="utf-8")

    def parse_inventory_text(self, text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    def format_inventory_choices(self, paths: list[str]) -> list[str]:
        return [f"{index:4d}  {path}" for index, path in enumerate(paths, 1)]

    def selected_paths_from_inventory_input(self, raw: str, paths: list[str]) -> list[str]:
        return [paths[index - 1] for index in self.parse_ranges(raw, len(paths))]

    def run_inventory_fetch(
        self,
        output_path: Path,
        *,
        fetch_inventory_text: Callable[[], str],
        write_line: Callable[[str], Any],
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        text = fetch_inventory_text()
        output_path.write_text(text, encoding="utf-8")
        count = len(self.parse_inventory_text(text))
        write_line(f"inventory: {output_path}")
        write_line(f"directories: {count}")

    def run_inventory_choose(
        self,
        inventory_path: Path,
        selection_path: Path,
        *,
        read_input: Callable[[str], str],
        write_line: Callable[[str], Any],
    ) -> None:
        if not inventory_path.exists():
            raise SystemExit(f"inventory file does not exist, run inventory first: {inventory_path}")
        paths = self.parse_inventory_text(inventory_path.read_text(encoding="utf-8"))
        if not paths:
            raise SystemExit(f"inventory file is empty: {inventory_path}")
        for line in self.format_inventory_choices(paths):
            write_line(line)
        raw = read_input("Select numbers/ranges, for example 1 4 10-12: ").strip()
        self.write_selection_file(selection_path, self.selected_paths_from_inventory_input(raw, paths))
        write_line(f"selection: {selection_path}")


def project_inventory_service() -> ProjectInventoryService:
    return ProjectInventoryService()
