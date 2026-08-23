#!/usr/bin/env python3
"""
wiki-kb-watch.py — 实时文件监听：Wiki 文件变动 → 自动同步到 Astra KB

自 Phase 3 起，同步逻辑已泛化到 dir-kb-sync.py（任意目录 → 任意 KB）。
本脚本保留原有监听/去抖/PID/日志与环境变量逻辑，仅把同步子进程指向
dir-kb-sync.py --dir <WIKI> --kb gloriosa_world --file <rel>。
原调用方（--daemon / --once）行为不变。

使用 watchdog 库监听 inotify 事件，消除 bash 方括号路径问题。
"""

import os, sys, time, logging, atexit, subprocess, shlex

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

WIKI = '/home/alrcatraz/Extra/DS425Plus/homes/Alrcatraz/Novels/[世界观] 格利欧萨共和国/wiki'
KB_NAME = 'gloriosa_world'
SYNC_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dir-kb-sync.py')
SYNC_CWD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIDFILE = '/tmp/wiki-kb-watch.pid'
LOGFILE = '/tmp/wiki-kb-watch.log'
DEBOUNCE = 1.5

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOGFILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# Debounce state: path → last_event_time
_pending = {}


def debounce(rel_path):
    now = time.time()
    last = _pending.get(rel_path, 0)
    if now - last < DEBOUNCE:
        return True
    _pending[rel_path] = now
    # Evict stale entries to prevent unbounded growth
    if len(_pending) > 1000:
        cutoff = now - 60
        stale = [k for k, v in _pending.items() if v < cutoff]
        for k in stale:
            del _pending[k]
    return False


def _sync_cmd(rel_path):
    """Build the shell command for a generic-dir sync of one file."""
    cmd = (
        f'python3 {shlex.quote(SYNC_SCRIPT)} '
        f'--dir {shlex.quote(WIKI)} '
        f'--kb {shlex.quote(KB_NAME)} '
        f'--file {shlex.quote(rel_path)} '
        f'>> {shlex.quote(LOGFILE)} 2>&1'
    )
    return cmd


def sync_file(rel_path):
    if debounce(rel_path):
        return
    if not rel_path.endswith('.md') or rel_path in ('index.md', 'SCHEMA.md'):
        return
    log.info(f'📝  {rel_path}')

    # Build env dict (provider-agnostic: only ASTRA_EMBED_* vars)
    env = os.environ.copy()
    env.setdefault('ASTRA_EMBED_BASE_URL', 'http://127.0.0.1:20128/v1')
    env.setdefault('ASTRA_EMBED_API_KEY', '')
    env.setdefault('ASTRA_EMBED_MODEL', 'siliconflow-cn/Qwen/Qwen3-VL-Embedding-8B')
    env.setdefault('ASTRA_EMBED_DIM', '1024')

    # subprocess.run with shlex.quote prevents shell injection
    cmd = _sync_cmd(rel_path)
    ret = subprocess.run(cmd, shell=True, cwd=SYNC_CWD, env=env).returncode

    if ret == 0:
        log.info(f'  ✓ synced')
    else:
        log.warning(f'  ✗ sync failed (exit={ret})')


def main():
    import argparse
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    parser = argparse.ArgumentParser()
    parser.add_argument('--daemon', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()

    # Daemon mode
    if args.daemon:
        if os.path.exists(PIDFILE):
            with open(PIDFILE) as f:
                try:
                    old_pid = int(f.read().strip())
                    os.kill(old_pid, 0)
                    print(f'Already running (PID {old_pid})')
                    sys.exit(1)
                except (OSError, ValueError):
                    pass
        with open(PIDFILE, 'w') as f:
            f.write(str(os.getpid()))
        atexit.register(lambda: os.path.exists(PIDFILE) and os.remove(PIDFILE))

    # --once: full sync then exit
    if args.once:
        log.info('Running initial sync (--once)...')
        env = os.environ.copy()
        env.setdefault('ASTRA_EMBED_BASE_URL', 'http://127.0.0.1:20128/v1')
        env.setdefault('ASTRA_EMBED_API_KEY', '')
        env.setdefault('ASTRA_EMBED_MODEL', 'siliconflow-cn/Qwen/Qwen3-VL-Embedding-8B')
        env.setdefault('ASTRA_EMBED_DIM', '1024')
        cmd = (
            f'python3 {shlex.quote(SYNC_SCRIPT)} '
            f'--dir {shlex.quote(WIKI)} '
            f'--kb {shlex.quote(KB_NAME)} '
            f'>> {shlex.quote(LOGFILE)} 2>&1'
        )
        ret = subprocess.run(cmd, shell=True, cwd=SYNC_CWD, env=env).returncode
        log.info(f'Sync complete (exit={ret})')
        return

    class WikiHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.is_directory:
                return
            sync_file(os.path.relpath(event.src_path, WIKI))

        def on_created(self, event):
            if event.is_directory:
                return
            sync_file(os.path.relpath(event.src_path, WIKI))

        def on_deleted(self, event):
            if event.is_directory:
                return
            sync_file(os.path.relpath(event.src_path, WIKI))

        def on_moved(self, event):
            if event.is_directory:
                return
            sync_file(os.path.relpath(event.dest_path, WIKI))

    log.info(f'Watching: {WIKI}')
    observer = Observer()
    observer.schedule(WikiHandler(), WIKI, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == '__main__':
    main()