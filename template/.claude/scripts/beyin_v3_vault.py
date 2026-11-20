"""Local coordination for read-modify-write operations on vault files."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import subprocess
import time

try:
    from beyin_v3_portalock import exclusive
except ModuleNotFoundError:  # source checkout, before the installer assigns the V3 name
    from _portalock import exclusive


@contextmanager
def file_lock(vault, path, timeout=2.0):
    """Lock a stable sidecar; replacing the Markdown must not replace its lock."""
    vault = Path(vault).resolve()
    path = Path(path)
    relative = path.resolve().relative_to(vault)
    if path.is_symlink():
        raise ValueError(f'Vault yazma hedefi sembolik bağlantı: {relative}')
    folder = vault / '.beyin-locks'
    if folder.is_symlink():
        raise ValueError('.beyin-locks vault içinde bir klasör olmalı')
    folder.mkdir(exist_ok=True)
    try:
        with (folder / '.gitignore').open('x', encoding='utf-8') as handle:
            handle.write('*\n')
    except FileExistsError:
        pass
    key = hashlib.sha256(os.path.normcase(str(relative)).encode('utf-8')).hexdigest()
    sidecar = folder / (key + '.lock')
    if sidecar.is_symlink():
        raise ValueError(f'Geçersiz vault kilidi: {relative}')
    deadline = time.monotonic() + timeout
    # Never use the OS blocking primitive here: its wait is not bounded on POSIX.
    with sidecar.open('a+b') as handle:
        while True:
            with exclusive(handle, blocking=False) as held:
                if held:
                    yield
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'Vault dosyası kilitli: {relative}. Başka bir yazıcıyı bekleyip yeniden deneyin.')
            time.sleep(min(0.025, remaining))


def branch_status(vault, settings=None):
    from beyin_v3_preferences import read

    expected = (read(vault) if settings is None else settings).get('beklenen_dal')
    if not expected:
        return {'status': 'disabled'}
    vault = Path(vault).resolve()
    # Ask Git about this checkout even when the caller is running in another repo.
    env = {key: value for key, value in os.environ.items()
           if key not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_NAMESPACE', 'GIT_CEILING_DIRECTORIES')}
    env['LC_ALL'] = 'C'
    try:
        result = subprocess.run(['git', 'symbolic-ref', '--quiet', 'HEAD'],
                                cwd=vault, env=env, capture_output=True, timeout=0.4)
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode in (0, 1):
        current = result.stdout.decode('utf-8', errors='replace').strip().removeprefix('refs/heads/') if result.returncode == 0 else None
        status = 'match' if current == expected else 'mismatch'
    elif result is not None and b'not a git repository (or any parent' in result.stderr:
        current, status = None, 'not_git'
    else:
        current = None
        status = 'unavailable' if any((parent / '.git').exists() for parent in (vault, *vault.parents)) else 'not_git'
    report = {'status': status, 'expected': expected, 'current': current}
    if status == 'mismatch':
        actual = repr(current) if current else 'ayrık HEAD'
        report['warning'] = f'Vault dalı {actual}, beklenen dal {expected!r}. Paylaşılan dosyalara yazma durduruldu.'
    elif status == 'unavailable':
        report['warning'] = f'Vault dalı doğrulanamadı (beklenen {expected!r}). Paylaşılan dosyalara yazma durduruldu.'
    return report


def require_branch(vault):
    warning = branch_status(vault).get('warning')
    if warning:
        raise ValueError(warning)
