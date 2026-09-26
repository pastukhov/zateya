"""Rename legacy ID-named ideas/plans to readable titles and update vault links."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .store import metadata, title_filename


LEGACY_NAME = re.compile(r"[a-f0-9]{32}\.md")


def migration_plan(vault: Path) -> dict[Path, Path]:
    root = vault / "Hermes" if (vault / "Hermes").exists() else vault / "Затея"
    moves: dict[Path, Path] = {}
    occupied = {path.relative_to(root).as_posix().casefold()
                for folder in ("ideas", "builds")
                for path in (root / folder).glob("*.md")}
    for folder in ("ideas", "builds"):
        for source in sorted((root / folder).glob("*.md")):
            if not LEGACY_NAME.fullmatch(source.name):
                continue
            if source.is_symlink():
                raise ValueError(f"symlink note: {source}")
            title = metadata(source.read_bytes()).get("title")
            if not isinstance(title, str) or not title.strip():
                raise ValueError(f"missing title: {source}")
            stem = title_filename(title)
            for number in range(1, 10000):
                suffix = "" if number == 1 else f" ({number})"
                target = source.with_name(f"{stem}{suffix}.md")
                relative = target.relative_to(root).as_posix().casefold()
                if relative not in occupied:
                    moves[source] = target
                    occupied.add(relative)
                    break
            else:
                raise ValueError(f"too many notes titled {title}")
    return moves


def migrate(vault: Path, *, apply: bool = False) -> dict[str, str]:
    root = vault / "Hermes" if (vault / "Hermes").exists() else vault / "Затея"
    moves = migration_plan(vault)
    names = {old.relative_to(root).as_posix()[:-3]: new.relative_to(root).as_posix()[:-3]
             for old, new in moves.items()}
    all_names = dict(names)
    for folder in ("ideas", "builds"):
        for page in (root / folder).glob("*.md"):
            if page in moves:
                continue
            idea_id = metadata(page.read_bytes()).get("idea_id")
            if isinstance(idea_id, str) and re.fullmatch(r"[a-f0-9]{32}", idea_id):
                all_names[f"{folder}/{idea_id}"] = page.relative_to(root).as_posix()[:-3]
    if not apply:
        return names
    snapshots: dict[Path, bytes] = {}
    for path in vault.rglob("*.md"):
        if path.is_symlink():
            raise ValueError(f"symlink page: {path}")
        snapshots[path] = path.read_bytes()
    for workspace in (vault / ".obsidian/workspace.json", vault / ".obsidian/workspace-mobile.json"):
        if workspace.is_file() and not workspace.is_symlink():
            snapshots[workspace] = workspace.read_bytes()
    for cache in (vault / ".smart-env/multi").glob("Hermes_*.ajson"):
        if cache.is_symlink():
            raise ValueError(f"symlink cache: {cache}")
        snapshots[cache] = cache.read_bytes()
    updates: dict[Path, bytes] = {}
    for source, data in snapshots.items():
        text = data.decode("utf-8")
        for old, new in all_names.items():
            text = text.replace(f"Hermes/{old}", f"Hermes/{new}")
            text = text.replace(f"id: {old}\n", f"id: {new}\n")
            text = text.replace(f"{old}.md", f"{new}.md")
        text = text.replace("Hermes/", "Затея/")
        target = moves.get(source, source)
        if source.suffix == ".ajson" and source.name.startswith("Hermes_"):
            cache_name = source.name.replace("Hermes_", "Затея_", 1)
            for old, new in all_names.items():
                cache_name = cache_name.replace(old.replace("/", "_") + "_md",
                                                new.replace("/", "_") + "_md")
            target = source.with_name(cache_name)
        updates[target] = text.encode("utf-8")
    if any(target.exists() for target in moves.values()):
        raise ValueError("target appeared during migration")
    if any(path.read_bytes() != data for path, data in snapshots.items()):
        raise ValueError("vault changed during migration")
    for source, target in moves.items():
        source.rename(target)
    for source in snapshots:
        if source.suffix == ".ajson" and source not in updates:
            source.unlink()
    for target, data in updates.items():
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)
    if root.name == "Hermes":
        root.rename(vault / "Затея")
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    for old, new in migrate(args.vault, apply=args.apply).items():
        print(f"{old} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
