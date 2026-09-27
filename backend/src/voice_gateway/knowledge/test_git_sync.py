import hashlib
import fcntl
import json
import subprocess
from pathlib import Path

import pytest

from backend.src.voice_gateway.knowledge.git_sync import GitSync


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    root = tmp_path / 'vault';root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'Test')
    git(root, 'config', 'user.email', 'test@example.invalid')
    git(root, 'config', 'core.quotepath', 'false')
    (root/'initial.md').write_text('initial')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'initial')
    git(root, 'remote', 'add', 'origin', str(remote))
    git(root, 'push', '-u', 'origin', 'main')
    return root, remote


def enqueue(root, ident='1', content='idea', order=1):
    page = root / 'Затея/ideas/idea.md';page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(content)
    queue = root/'Затея/.sync';queue.mkdir(exist_ok=True)
    task = queue/f'{ident}.json'
    task.write_text(json.dumps(dict(id=ident, created_ns=order, files={
        'Затея/ideas/idea.md': hashlib.sha256(content.encode()).hexdigest()})))
    return task


def test_sync_commits_and_pushes_only_published_pages_preserving_index(repo):
    root, remote = repo
    (root/'personal.md').write_text('private draft')
    git(root, 'add', 'personal.md')
    task = enqueue(root)
    result = GitSync(root).run_once()
    assert result['status'] == 'synced'
    assert git(root, 'diff', '--cached', '--name-only') == 'personal.md'
    assert git(root, 'show', '--pretty=', '--name-only', 'HEAD') == 'Затея/ideas/idea.md'
    assert git(remote, 'rev-parse', 'refs/heads/main') == git(root, 'rev-parse', 'HEAD')
    assert not task.exists()


def test_push_failure_retries_without_duplicate_commit(repo):
    root, remote = repo
    task = enqueue(root)
    git(root, 'remote', 'set-url', 'origin', str(remote) + '-offline')
    assert GitSync(root).run_once()['status'] == 'retry'
    assert task.exists()
    head = git(root, 'rev-parse', 'HEAD')
    git(root, 'remote', 'set-url', 'origin', str(remote))
    assert GitSync(root).run_once()['status'] == 'synced'
    assert git(root, 'rev-parse', 'HEAD') == head
    assert not task.exists()


def test_sync_coalesces_updates_but_blocks_unpublished_manual_changes(repo):
    root, remote = repo
    enqueue(root, 'first', 'old', 1)
    enqueue(root, 'second', 'new', 2)
    assert GitSync(root).run_once()['status'] == 'synced'
    task = enqueue(root, 'third', 'published', 3)
    (root/'Затея/ideas/idea.md').write_text('unpublished manual edit')
    before = git(root, 'rev-parse', 'HEAD')
    assert GitSync(root).run_once()['status'] == 'conflict'
    assert git(root, 'rev-parse', 'HEAD') == before
    assert task.exists()


def test_rejects_paths_outside_hermes_and_symlinks(repo):
    root, _ = repo
    task = enqueue(root)
    payload = json.loads(task.read_text())
    payload['files'] = {'personal.md': hashlib.sha256(b'private').hexdigest()}
    task.write_text(json.dumps(payload))
    assert GitSync(root).run_once()['status'] == 'conflict'
    task.unlink()
    task = enqueue(root)
    page = root/'Затея/ideas/idea.md';page.unlink()
    (root/'outside.md').write_text('idea')
    page.symlink_to(root/'outside.md')
    assert GitSync(root).run_once()['status'] == 'conflict'


def test_sync_respects_shared_writer_lock(repo):
    root, _ = repo
    enqueue(root)
    lock_path = root / 'Затея/.sync/writer.lock'
    descriptor = lock_path.open('a')
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert GitSync(root).run_once()['status'] == 'busy'
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        descriptor.close()
    assert GitSync(root).run_once()['status'] == 'synced'


def test_refresh_fast_forwards_remote_note_before_next_dictation(repo, tmp_path):
    root, remote = repo
    other = tmp_path / 'phone'
    git(tmp_path, 'clone', str(remote), str(other))
    git(other, 'checkout', 'main')
    git(other, 'config', 'user.name', 'Phone')
    git(other, 'config', 'user.email', 'phone@example.invalid')
    (other / 'phone.md').write_text('new context')
    git(other, 'add', 'phone.md')
    git(other, 'commit', '-m', 'phone note')
    git(other, 'push', 'origin', 'main')
    assert GitSync(root).run_once()['status'] == 'updated'
    assert (root / 'phone.md').read_text() == 'new context'


def test_sync_merges_disjoint_remote_note_before_pushing_capture(repo, tmp_path):
    root, remote = repo
    other = tmp_path / 'phone'
    git(tmp_path, 'clone', str(remote), str(other))
    git(other, 'checkout', 'main')
    git(other, 'config', 'user.name', 'Phone')
    git(other, 'config', 'user.email', 'phone@example.invalid')
    task = enqueue(root)
    git(other, 'checkout', '-b', 'phone-work')
    (other / 'phone.md').write_text('new context')
    git(other, 'add', 'phone.md')
    git(other, 'commit', '-m', 'phone note')
    git(other, 'push', 'origin', 'HEAD:main')
    assert GitSync(root).run_once()['status'] == 'synced'
    assert not task.exists()
    assert (root / 'phone.md').read_text() == 'new context'
    assert git(remote, 'show', 'main:Затея/ideas/idea.md') == 'idea'


def test_refresh_keeps_conflicting_local_and_remote_edits(repo, tmp_path):
    root, remote = repo
    other = tmp_path / 'phone'
    git(tmp_path, 'clone', str(remote), str(other))
    git(other, 'checkout', 'main')
    git(other, 'config', 'user.name', 'Phone')
    git(other, 'config', 'user.email', 'phone@example.invalid')
    (root / 'initial.md').write_text('local')
    git(root, 'add', 'initial.md')
    git(root, 'commit', '-m', 'local edit')
    (other / 'initial.md').write_text('phone')
    git(other, 'add', 'initial.md')
    git(other, 'commit', '-m', 'phone edit')
    git(other, 'push', 'origin', 'main')
    before = git(root, 'rev-parse', 'HEAD')
    assert GitSync(root).run_once()['status'] == 'conflict'
    assert git(root, 'rev-parse', 'HEAD') == before
    assert (root / 'initial.md').read_text() == 'local'
    assert not git(root, 'ls-files', '-u')
