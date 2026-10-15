#!/usr/bin/env python3
"""Smoke-test backend orphan reaping using its Compose image/init configuration."""
import json
import subprocess

config = json.loads(subprocess.check_output(
    ['docker', 'compose', 'config', '--format', 'json'], text=True))
backend = config['services']['backend']
probe = r'''
import os, time
from pathlib import Path
for _ in range(8):
    child = os.fork()
    if child == 0:
        if os.fork() == 0:
            time.sleep(0.1)
            os._exit(0)
        os._exit(0)
    os.waitpid(child, 0)
time.sleep(0.3)
for _ in range(30):
    zombies = 0
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            zombies += path.read_text().rsplit(')', 1)[1].split()[0] == 'Z'
        except FileNotFoundError:
            pass
    if not zombies:
        break
    time.sleep(0.1)
print(f'Unreaped orphan processes: {zombies}')
raise SystemExit(bool(zombies))
'''
command = ['docker', 'run', '--rm', '--network=none', '--pids-limit=128']
if backend.get('init'):
    command.append('--init')
command += ['--entrypoint', 'python', backend['image'], '-c', probe]
raise SystemExit(subprocess.run(command, timeout=30).returncode)
