"""Private fixture roots for module workers and direct unittest invocation."""

import os
from pathlib import Path
import shutil
import stat
import subprocess
import threading
import tempfile
import time
import uuid
from unittest.mock import patch


def fixture_dir(test, label: str, *, parent=None) -> Path:
    """Create an ACL-inheriting directory and immediately register its cleanup."""
    private = os.environ.get("HHWIKI_TEST_ROOT")
    if parent is None:
        parent = Path(private) if private else Path(tempfile.gettempdir()) / "hhw"
    parent = Path(parent).resolve()
    repository = Path(__file__).resolve().parents[1]
    if parent.is_relative_to(repository):
        raise ValueError(f"Fixture parent must be outside repository {repository}: {parent}")
    parent.mkdir(parents=True, exist_ok=True)
    while True:
        path = parent / (label[:8] + "-" + uuid.uuid4().hex[:8])
        try:
            # mkdtemp uses mode 0o700, which creates an owner-only ACL on Windows.
            os.mkdir(path)
            break
        except FileExistsError:
            continue
    cleanup = test.addClassCleanup if isinstance(test, type) else test.addCleanup
    cleanup(remove_tree, path)
    return path.resolve()


def remove_tree(path) -> None:
    """Remove owned fixtures, including read-only Git objects and briefly busy files."""
    path = Path(path)

    def writable(function, name, info):
        error = info[1]
        if isinstance(error, PermissionError) and not os.stat(name).st_mode & stat.S_IWRITE:
            os.chmod(name, os.stat(name).st_mode | stat.S_IWRITE)
            function(name)
        else:
            raise error

    deadline = time.monotonic() + 5
    while True:
        try:
            if path.exists():
                shutil.rmtree(path, onerror=writable)
            return
        except OSError as error:
            if getattr(error, "winerror", None) == 32 and time.monotonic() < deadline:
                time.sleep(0.1)
                continue
            raise OSError(f"Could not remove fixture {path}: {error}") from error


def cache_git_queries(test, root):
    """Reuse Git readers and unchanged queries within a private fixture.

    Content and mutations use real commands. Ref/config/object changes invalidate
    metadata; checkout queries also check every visible file and the Git index.
    """
    original = subprocess.run
    cache = {}
    batches = {}
    logs = threading.local()
    # Copying an open TemporaryFile fails on Windows. Keep cache streams beside
    # the snapshot, within the same worker root, and close them before cleanup.
    log_root = fixture_dir(test, "git-log", parent=Path(root).resolve().parent)

    def native(command, *args, **kwargs):
        # With one captured pipe, communicate reads directly instead of
        # starting and joining two Windows reader threads for every Git call.
        if not kwargs.get("capture_output") and kwargs.get("stderr") != subprocess.PIPE:
            return original(command, *args, **kwargs)
        if not hasattr(logs, 'error'):
            logs.error = tempfile.TemporaryFile(dir=log_root)
            test.addCleanup(logs.error.close)
        stream = logs.error
        stream.seek(0)
        stream.truncate()
        options = dict(kwargs)
        if options.pop('capture_output', False):
            options['stdout'] = subprocess.PIPE
        options['stderr'] = stream
        data = options.pop('input', None)
        if data is not None:
            if not hasattr(logs, 'input'):
                logs.input = tempfile.TemporaryFile(dir=log_root)
                test.addCleanup(logs.input.close)
            source = logs.input
            source.seek(0)
            source.truncate()
            if isinstance(data, str):
                data = data.encode(kwargs.get('encoding') or 'utf-8', kwargs.get('errors') or 'strict')
            source.write(data)
            source.seek(0)
            options['stdin'] = source
        checked = options.pop('check', False)
        value = original(command, *args, **options)
        stream.seek(0)
        value.stderr = stream.read()
        if kwargs.get('text') or kwargs.get('encoding') or kwargs.get('universal_newlines'):
            value.stderr = value.stderr.decode(kwargs.get('encoding') or 'utf-8', kwargs.get('errors') or 'strict')
            value.stderr = value.stderr.replace('\r\n', '\n').replace('\r', '\n')
        if checked:
            value.check_returncode()
        return value

    def close(process):
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        finally:
            process.stdout.close()
            process.stderr.close()

    def object_read(path, name, contents=False):
        key = (path, contents)
        if key not in batches:
            process = subprocess.Popen(["git", "-C", str(path), "cat-file",
                                        "--batch" if contents else "--batch-check"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            test.addCleanup(close, process)
            batches[key] = process, threading.Lock()
        process, lock = batches[key]
        with lock:
            process.stdin.write((name + "\n").encode())
            process.stdin.flush()
            row = process.stdout.readline().split()
            if len(row) != 3:
                return None
            if not contents:
                return row[0] + b"\n"
            data = process.stdout.read(int(row[2]))
            if process.stdout.read(1) != b'\n':
                raise OSError('Invalid Git batch object terminator')
            return data if row[1] == b'blob' else None

    def state(path, arguments, *, objects=True):
        git = path / ".git"
        if arguments[0] in {'remote', 'config'} or arguments in (
                ['rev-parse', '--show-toplevel'], ['rev-parse', '--show-object-format']):
            return (git / 'config').read_bytes()
        if arguments == ['symbolic-ref', 'HEAD']:
            return (git / 'HEAD').read_bytes()
        names = [git / name for name in ("HEAD", "config", "packed-refs", "shallow")]
        names.extend(sorted((git / "refs").rglob("*")))
        version = []
        for name in names:
            if name.is_file():
                version.append((str(name), name.read_bytes()))
        # Object removal/addition and repacking also affect name resolution.
        if objects:
            for name in sorted((git / "objects").glob("*")):
                info = name.stat()
                version.append((str(name), info.st_mtime_ns, info.st_size))
        return tuple(version)

    def checkout_state(path):
        """Use scandir's cached Windows metadata to notice edits, additions and staging."""
        version = []
        ignore_local = '.local/' in (path / '.gitignore').read_text().splitlines()

        def walk(directory):
            with os.scandir(directory) as entries:
                for entry in sorted(entries, key=lambda item: item.name):
                    if entry.name == '.git' or entry.name == '.local' and ignore_local:
                        continue
                    info = entry.stat(follow_symlinks=False)
                    version.append((entry.path, info.st_size, info.st_mtime_ns,
                                    info.st_ctime_ns, info.st_mode))
                    if entry.is_dir(follow_symlinks=False) and (os.name != 'nt' or not entry.is_junction()):
                        walk(entry.path)
        walk(path)
        for name in ('index', 'config', 'HEAD', 'packed-refs', 'info/exclude'):
            file = path / '.git' / name
            if file.exists():
                info = file.stat()
                version.append((str(file), info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode))
        return tuple(version)

    def run(command, *args, **kwargs):
        if (not isinstance(command, (list, tuple)) or len(command) < 4
                or command[:2] != ["git", "-C"] or args):
            return original(command, *args, **kwargs)
        path, arguments = Path(command[2]), command[3:]
        if arguments[0] == '--literal-pathspecs':
            arguments = arguments[1:]
        if not path.is_relative_to(root):
            return original(command, *args, **kwargs)
        if kwargs.get('input') is not None:
            return native(command, *args, **kwargs)
        captured = kwargs.get("capture_output") or kwargs.get("stdout") == subprocess.PIPE
        expressions = [argument for argument in arguments[1:] if argument != "--verify"]
        if (captured and arguments[0] == "rev-parse" and len(expressions) == 1
                and not expressions[0].startswith("-") and "\n" not in expressions[0]
                and path.is_relative_to(root) and (path / ".git").is_dir()
                and (path == root or path.is_relative_to(root / "repositories"))):
            value = object_read(path, expressions[0])
            if value is not None:
                if kwargs.get("text") or kwargs.get("encoding") or kwargs.get("universal_newlines"):
                    value = value.decode(kwargs.get("encoding") or "utf-8")
                return subprocess.CompletedProcess(command, 0, value, "" if isinstance(value, str) else b"")
        if (captured and arguments[:2] == ['cat-file', 'blob'] and len(arguments) == 3
                and '\n' not in arguments[2] and '\r' not in arguments[2]
                and (path == root or path.is_relative_to(root / 'repositories'))):
            value = object_read(path, arguments[2], contents=True)
            if value is not None:
                if kwargs.get('text') or kwargs.get('encoding') or kwargs.get('universal_newlines'):
                    value = value.decode(kwargs.get('encoding') or 'utf-8', kwargs.get('errors') or 'strict')
                    value = value.replace('\r\n', '\n').replace('\r', '\n')
                return subprocess.CompletedProcess(command, 0, value, '' if isinstance(value, str) else b'')
        safe = arguments[0] in {"rev-parse", "rev-list", "ls-tree", "merge-base", "show-ref"}
        safe |= arguments[0] == "symbolic-ref" and arguments[1:] == ["HEAD"]
        safe |= arguments[0] == "remote" and len(arguments) == 1
        safe |= arguments[0] == "config" and arguments[1:2] == ["--get"]
        checkout = (arguments[0] in {'status', 'diff-files', 'ls-files', 'write-tree'}
                    and path.is_relative_to(root) and (path / '.gitignore').is_file()
                    and not any((kwargs.get('env') or {}).get(name) for name in ('GIT_INDEX_FILE', 'GIT_WORK_TREE')))
        safe |= checkout
        if not safe or not captured or not path.is_relative_to(root) or not (path / ".git").is_dir():
            return native(command, *args, **kwargs)
        version = (state(path, arguments, objects=arguments[0] == 'write-tree'),
                   checkout_state(path)) if checkout else state(path, arguments)
        key = (tuple(command), repr(kwargs))
        saved = cache.get(key)
        if saved is not None and saved[0] == version:
            value = saved[1]
            return subprocess.CompletedProcess(command, value.returncode, value.stdout, value.stderr)
        value = native(command, *args, **kwargs)
        after = (state(path, arguments, objects=arguments[0] == 'write-tree'),
                 checkout_state(path)) if checkout else state(path, arguments)
        stable = version == after
        if checkout and not stable and version[0] == after[0]:
            # status and write-tree may refresh the index without changing its
            # tree. Cache that result against the refreshed index only when
            # every other observed file and ref stayed unchanged.
            index = str(path / '.git/index')
            stable = ([row for row in version[1] if row[0] != index]
                      == [row for row in after[1] if row[0] != index])
        if value.returncode == 0 and stable:
            cache[key] = (after, value)
        return value

    replacement = patch.object(subprocess, "run", run)
    replacement.start()
    test.addCleanup(replacement.stop)
    return cache
