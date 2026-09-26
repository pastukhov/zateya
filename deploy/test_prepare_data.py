import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare-data.sh")


def project(tmp_path, user=None):
    user = user or f"{os.getuid()}:{os.getgid()}"
    root = tmp_path / "project"
    (root / "deploy").mkdir(parents=True)
    script = root / "deploy/prepare-data.sh"
    script.write_bytes(SCRIPT.read_bytes())
    script.chmod(0o755)
    (root / "docker-compose.yml").write_text("services: {}\n")
    bin_dir = root / "mock-bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"print(json.dumps({{'services': {{'backend': {{'user': {user!r}}}}}}}))\n"
    )
    docker.chmod(0o755)
    env = {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "HOME": os.environ.get("HOME", str(tmp_path))}
    return root, env


def test_prepare_data_is_repeatable_and_preserves_existing_data(tmp_path):
    root, env = project(tmp_path)
    marker = root / "data/archive/kept.bin"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"keep")
    key = root / "data/ssh/id_ed25519"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"private")
    known = root / "data/ssh/known_hosts"
    known.write_text("github.example ssh-ed25519 test\n")

    for _ in range(2):
        result = subprocess.run([str(root / "deploy/prepare-data.sh")], env=env,
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
    assert marker.read_bytes() == b"keep"
    assert key.stat().st_mode & 0o777 == 0o600
    assert known.stat().st_mode & 0o777 == 0o600
    assert (root / "data/ssh").stat().st_mode & 0o777 == 0o700


def test_prepare_data_refuses_root_container_user(tmp_path):
    root, env = project(tmp_path, "0:0")
    result = subprocess.run([str(root / "deploy/prepare-data.sh")], env=env,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "non-root UID:GID" in result.stderr


def test_prepare_data_refuses_symlink_in_data_tree(tmp_path):
    root, env = project(tmp_path)
    (root / "data/archive").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "data/archive/external").symlink_to(outside, target_is_directory=True)
    result = subprocess.run([str(root / "deploy/prepare-data.sh")], env=env,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "Refusing symlink" in result.stderr
    assert outside.stat().st_uid == os.getuid()
