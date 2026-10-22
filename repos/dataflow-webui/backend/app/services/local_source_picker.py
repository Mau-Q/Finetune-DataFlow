"""Native desktop source selection with platform-specific adapters."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from starlette.datastructures import UploadFile
from app.services.data_library import LibraryError, IMAGE_TYPES, MAX_BYTES
from app.services.source_datasets import SourceDatasets

SUPPORTED = {'.pdf', '.txt', '.md', '.json', '.jsonl', '.csv', '.parquet', *IMAGE_TYPES}
_SELECTIONS = {}
_LOCK = threading.Lock()
_CHOOSER = threading.Lock()
_SCRIPT = '''
ObjC.import('AppKit');
var app = $.NSApplication.sharedApplication;
app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
var panel = $.NSOpenPanel.openPanel;
panel.canChooseFiles = true;
panel.canChooseDirectories = true;
panel.allowsMultipleSelection = true;
panel.title = '选择文件或文件夹';
app.activateIgnoringOtherApps(true);
var paths = [];
if (panel.runModal == $.NSModalResponseOK) {
    var urls = panel.URLs;
    for (var i = 0; i < urls.count; i++) paths.push(ObjC.unwrap(urls.objectAtIndex(i).path));
}
JSON.stringify(paths);
'''


def pick_paths(*, directories_only=False):
    if sys.platform not in {'darwin', 'win32'}:
        raise LibraryError('此系统请手动填写目录绝对路径' if directories_only else '此系统可直接拖入文件或文件夹，或使用浏览器选择文件', 501)
    if not _CHOOSER.acquire(blocking=False):
        raise LibraryError('系统选择窗口已经打开，请先完成当前选择', 409)
    try:
        script = _SCRIPT
        if directories_only:
            script = script.replace('canChooseFiles = true', 'canChooseFiles = false').replace('allowsMultipleSelection = true', 'allowsMultipleSelection = false').replace('选择文件或文件夹', '选择结果保存目录')
        command = ['osascript', '-l', 'JavaScript', '-e', script]
        if sys.platform == 'win32':
            command = ['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
                       '-File', str(Path(__file__).with_name('desktop_picker.ps1'))]
            if directories_only:
                command.append('-DirectoriesOnly')
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                timeout=180, check=True)
        paths = json.loads(result.stdout)
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            raise ValueError('Invalid picker result')
        return paths
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise LibraryError('无法完成系统文件选择，请重试或直接拖入文件/文件夹') from exc
    finally:
        _CHOOSER.release()


def _stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


class LocalSourcePicker:
    def __init__(self, library, registry):
        self.library, self.registry = library, registry

    def choose(self):
        roots = [Path(p) for p in pick_paths()]
        if not roots:
            return {'cancelled': True}
        entries, skipped = [], []
        has_directory = any(p.is_dir() for p in roots)
        examined = 0
        def add(path, relative):
            nonlocal examined
            examined += 1
            if examined > 5000:
                raise LibraryError('文件夹内容过多，请选择更小的子目录')
            if path.is_symlink() or any(p.startswith('.') or p == '__MACOSX' for p in Path(relative).parts) or path.suffix.lower() not in SUPPORTED:
                skipped.append(relative)
                return
            if not path.is_file():
                raise LibraryError('所选文件不存在或无法读取')
            if len(entries) >= 100:
                raise LibraryError('每次最多导入 100 个支持的文件')
            stamp = _stamp(path)
            if not stamp[0] or stamp[0] > MAX_BYTES:
                raise LibraryError('文件不能为空，单份最多 100 MiB: ' + relative)
            entries.append((path, relative, stamp))
        for root in roots:
            if root.is_symlink():
                skipped.append(root.name)
            elif root.is_dir():
                for directory, dirs, files in os.walk(root, followlinks=False):
                    for name in list(dirs):
                        child = Path(directory) / name
                        if name.startswith('.') or name == '__MACOSX' or child.is_symlink():
                            skipped.append((Path(root.name) / child.relative_to(root)).as_posix())
                            dirs.remove(name)
                    for name in sorted(files):
                        path = Path(directory) / name
                        add(path, (Path(root.name) / path.relative_to(root)).as_posix())
            else:
                add(root, root.name)
        if not entries:
            raise LibraryError('所选内容中没有支持的文件')
        if sum(stamp[0] for _, _, stamp in entries) > 200 * 1024 * 1024:
            raise LibraryError('每次导入总量最多 200 MiB')
        labels = [relative for _, relative, _ in entries]
        if len(set(labels)) != len(labels):
            raise LibraryError('选择中包含重复路径，请只选择一次父文件夹或成员文件')
        kinds = {'PDF' if p.suffix.lower() == '.pdf' else '图片' if p.suffix.lower() in IMAGE_TYPES else '文本' if p.suffix.lower() in {'.txt', '.md'} else '结构化数据' for p, _, _ in entries}
        token = uuid.uuid4().hex
        now = time.monotonic()
        with _LOCK:
            for key in list(_SELECTIONS):
                if now - _SELECTIONS[key]['created'] > 900:
                    del _SELECTIONS[key]
            _SELECTIONS[token] = {'created': now, 'root': str(self.library.root), 'entries': entries, 'directory': has_directory}
        name = roots[0].name if len(roots) == 1 and has_directory else roots[0].stem if len(entries) == 1 else f'原始材料 · {len(entries)} 份'
        return {'selection_id': token, 'name': name, 'count': len(entries),
                'files': [{'name': relative, 'size': stamp[0]} for _, relative, stamp in entries],
                'data_form': next(iter(kinds)) if len(kinds) == 1 else '混合', 'skipped': skipped}

    def import_selection(self, token, name):
        with _LOCK:
            selection = _SELECTIONS.get(token)
            if not selection or selection['root'] != str(self.library.root) or time.monotonic() - selection['created'] > 900:
                raise LibraryError('文件选择已过期，请重新选择', 409)
            # A consumed selection cannot be submitted twice in parallel.
            selection = _SELECTIONS.pop(token)
        with ExitStack() as stack:
            files = []
            for path, relative, stamp in selection['entries']:
                if path.is_symlink() or not path.is_file() or _stamp(path) != stamp:
                    raise LibraryError('所选文件在选择后发生变化，请重新选择', 409)
                files.append(UploadFile(file=stack.enter_context(path.open('rb')), filename=relative))
            service = SourceDatasets(self.library, self.registry)
            if not selection['directory'] and len(files) == 1 and Path(files[0].filename).suffix.lower() not in {'.pdf', *IMAGE_TYPES}:
                return service.upload_data(files[0], name)
            return service.upload_folder(files, name, 'folder' if selection['directory'] else 'files')
