from pathlib import Path

from backend.src.voice_gateway.knowledge.migrate_titles import migrate


def test_legacy_note_names_and_links_are_rewritten_without_changing_sources(tmp_path: Path):
    root = tmp_path / "Hermes"
    (root / "ideas").mkdir(parents=True)
    (root / "builds").mkdir()
    (root / "wiki").mkdir()
    old = "a" * 32
    second = "b" * 32
    (root / "ideas" / f"{old}.md").write_text(
        f"---\nid: ideas/{old}\nidea_id: {old}\ntitle: Полив / дача\n---\n# Полив / дача\n"
    )
    (root / "ideas" / f"{second}.md").write_text(
        f"---\nid: ideas/{second}\nidea_id: {second}\ntitle: Полив / дача\n---\n# Полив / дача\n"
    )
    (root / "wiki" / "links.md").write_text(f"[[Hermes/ideas/{old}]]\n[[Hermes/ideas/{second}]]\n")
    (root / "index.md").write_text(f"[[Hermes/ideas/{old}]]\n")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian/workspace.json").write_text(
        f'{{"file":"Hermes/ideas/{old}.md"}}')
    (tmp_path / ".obsidian/workspace-mobile.json").write_text(
        f'{{"file":"Hermes/ideas/{old}.md"}}')
    cache = tmp_path / ".smart-env/multi"
    cache.mkdir(parents=True)
    (cache / f"Hermes_ideas_{old}_md.ajson").write_text(
        f'{{"path":"Hermes/ideas/{old}.md"}}')
    expected = {f"ideas/{old}": "ideas/Полив дача",
                f"ideas/{second}": "ideas/Полив дача (2)"}
    assert migrate(tmp_path) == expected
    assert (root / "ideas" / f"{old}.md").exists()
    assert migrate(tmp_path, apply=True) == expected
    root = tmp_path / "Затея"
    assert root.is_dir()
    assert not (tmp_path / "Hermes").exists()
    assert not (root / "ideas" / f"{old}.md").exists()
    assert f"idea_id: {old}" in (root / "ideas/Полив дача.md").read_text()
    assert "id: ideas/Полив дача\n" in (root / "ideas/Полив дача.md").read_text()
    assert "[[Затея/ideas/Полив дача (2)]]" in (root / "wiki/links.md").read_text()
    assert "Затея/ideas/Полив дача.md" in (tmp_path / ".obsidian/workspace.json").read_text()
    assert "Затея/ideas/Полив дача.md" in (tmp_path / ".obsidian/workspace-mobile.json").read_text()
    assert "Затея/ideas/Полив дача.md" in (cache / "Затея_ideas_Полив дача_md.ajson").read_text()
    assert not (cache / f"Hermes_ideas_{old}_md.ajson").exists()
    assert migrate(tmp_path, apply=True) == {}
