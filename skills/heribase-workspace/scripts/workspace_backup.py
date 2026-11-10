"""工作空间备份：SQLite 在线快照 + 在任务锁内复制证据；恢复到新的空目录。"""
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from workspace_store import WorkspaceError
from workspace_tasks import operations, core


def backup(store, tasks, executor):
    directory = store.directory / 'backups'
    if directory.is_symlink():
        raise WorkspaceError('unsafe_path', '备份目录不能是符号链接')
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / ('heribase-' + secrets.token_hex(8) + '.zip')
    with executor.lock, tasks._create_lock, ExitStack() as locks, tempfile.TemporaryDirectory(dir=str(directory)) as temp:
        for key in tasks.keys():
            executor.assert_idle(key)
            locks.enter_context(operations.task_lock(tasks.root, key))
            health = core.validate_package_structure(tasks.root / key, key, check_integrity=True)
            if not health['ok']:
                raise WorkspaceError('data_inconsistent', '任务完整性未通过，先核验再备份', 409)
        snapshot = Path(temp) / 'heribase.sqlite'
        with store.connection() as source, sqlite3.connect(str(snapshot)) as destination:
            source.backup(destination)
        files = [('heribase.sqlite', snapshot)]
        for key in tasks.keys():
            for path in (tasks.root / key).rglob('*'):
                if path.is_symlink():
                    raise WorkspaceError('unsafe_path', '备份不跟随符号链接')
                if path.is_file():
                    files.append(('user-tasks/' + str(path.relative_to(tasks.root)), path))
        manifest = {'version': 1, 'createdAt': store.timestamp(), 'files': {}}
        staging = Path(temp) / 'backup.zip'
        with zipfile.ZipFile(staging, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, path in files:
                content = path.read_bytes()
                manifest['files'][name] = hashlib.sha256(content).hexdigest()
                archive.writestr(name, content)
            archive.writestr('backup-manifest.json', json.dumps(manifest, ensure_ascii=False))
        os.chmod(staging, 0o600)
        os.replace(staging, target)
    store.emit('backup.created', 'backup', target.name, 'user:web', {'file': target.name})
    return {'path': str(target), 'fileCount': len(manifest['files'])}


def restore(archive_path, destination_home):
    """不覆盖已有工作空间；损坏包在临时目录中拒绝，不留下半恢复的数据。"""
    destination = Path(destination_home).expanduser() / '.heribase'
    if destination.exists() or destination.is_symlink():
        raise WorkspaceError('destination_exists', '恢复目标已有 .heribase，请选择新的空目录', 409)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='restore-', dir=str(destination.parent)) as temporary:
        staged = Path(temporary) / '.heribase'
        staged.mkdir(mode=0o700)
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or sum(i.file_size for i in infos) > 10 * 1024**3:
                raise WorkspaceError('invalid_backup', '备份包含重复项或超过 10 GiB')
            manifest = json.loads(archive.read('backup-manifest.json'))
            if manifest.get('version') != 1 or set(names) != set(manifest['files']) | {'backup-manifest.json'}:
                raise WorkspaceError('invalid_backup', '备份清单不完整')
            for info in infos:
                name = info.filename
                if name == 'backup-manifest.json':
                    continue
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or '\\' in name or (name != 'heribase.sqlite' and not name.startswith('user-tasks/')):
                    raise WorkspaceError('invalid_backup', '备份路径不在允许范围')
                content = archive.read(info)
                if hashlib.sha256(content).hexdigest() != manifest['files'][name]:
                    raise WorkspaceError('invalid_backup', '备份内容与校验摘要不一致')
                target = staged.joinpath(*path.parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.write_bytes(content)
                os.chmod(target, 0o600)
        if not (staged / 'heribase.sqlite').is_file():
            raise WorkspaceError('invalid_backup', '备份没有数据库快照')
        with sqlite3.connect(str(staged / 'heribase.sqlite')) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise WorkspaceError('invalid_backup', '数据库完整性检查失败')
        root = staged / 'user-tasks'
        if root.exists():
            for task in root.iterdir():
                for relative in core.REQUIRED_DIRS:
                    (task / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
                result = core.validate_package_structure(task, task.name, check_integrity=True)
                if not result['ok']:
                    raise WorkspaceError('invalid_backup', '备份任务校验失败', 409)
        # 同目录 rename 为恢复提交点；不存在覆盖已有账户配置和凭据的路径。
        staged.rename(destination)
    return {'ok': True, 'home': str(destination.parent), 'requiresLogin': True}
