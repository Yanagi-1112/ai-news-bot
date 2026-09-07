"""An update must preserve deployed fixes and require a valid backup."""
import os
from pathlib import Path
import subprocess
import pytest

pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Deployment shell runs on Linux')


@pytest.mark.parametrize('contains_fix,backup_ok,expected', [(False, True, False), (True, False, False), (True, True, True)])
def test_update_does_not_checkout_before_safe_backup(tmp_path, contains_fix, backup_ok, expected):
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    log = tmp_path / 'calls'
    git = binaries / 'git'
    git.write_text('''#!/bin/sh
case "$1" in
  status|fetch) exit 0;;
  tag) echo v0.3.0;;
  merge-base) exit "$CONTAINS_FIX_EXIT";;
  checkout) echo checkout >> "$CALL_LOG";;
  *) exit 90;;
esac
''')
    docker = binaries / 'docker'
    docker.write_text('''#!/bin/sh
echo "$2" >> "$CALL_LOG"
if [ "$2" = exec ]; then exit "$BACKUP_EXIT"; fi
''')
    git.chmod(0o755)
    docker.chmod(0o755)
    env = dict(os.environ, PATH=str(binaries)+os.pathsep+os.environ['PATH'], CALL_LOG=str(log),
               CONTAINS_FIX_EXIT='0' if contains_fix else '1', BACKUP_EXIT='0' if backup_ok else '1')
    command = Path(__file__).resolve().parents[1] / 'manage.sh'
    result = subprocess.run(['bash', str(command), 'update'], cwd=tmp_path, env=env, capture_output=True)
    assert (result.returncode == 0) == expected
    calls = log.read_text().splitlines() if log.exists() else []
    if expected:
        assert calls == ['exec', 'cp', 'checkout', 'up']
    else:
        assert 'checkout' not in calls and 'up' not in calls
