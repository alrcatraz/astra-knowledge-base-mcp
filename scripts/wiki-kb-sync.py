#!/usr/bin/env python3
"""
wiki-kb-sync.py — 单向同步：Wiki → Astra KB（薄封装）

自 Phase 3 起，同步逻辑已泛化到 dir-kb-sync.py（任意目录 → 任意 KB）。
本脚本保留原有命令行接口（--full / --file / --dry-run）与 WIKI / KB_NAME
全局量，仅作为薄封装把请求转发给 dir-kb-sync.py：
    dir-kb-sync.py --dir <WIKI> --kb gloriosa_world [--full|--file|--dry-run]

因此原调用方（含外部脚本、wiki-kb-watch.py 等）继续可用，行为与旧版一致。

Usage:
  python3 wiki-kb-sync.py                    # 增量同步（按 mtime）
  python3 wiki-kb-sync.py --full             # 全量重同步
  python3 wiki-kb-sync.py --file 入门/概述.md  # 单个文件同步
  python3 wiki-kb-sync.py --dry-run          # 仅报告不做
"""

import sys, os, subprocess, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

# ── 项目配置（保留向后兼容，供原调用方引用）───────────────────
WIKI = '/home/alrcatraz/Extra/DS425Plus/homes/Alrcatraz/Novels/[世界观] 格利欧萨共和国/wiki'
KB_NAME = 'gloriosa_world'
# ─────────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
_GENERIC_SYNC = os.path.join(_HERE, 'dir-kb-sync.py')


def main():
    parser = argparse.ArgumentParser(description='Wiki → KB Sync (wrapper)')
    parser.add_argument('--full', action='store_true', help='全量重同步')
    parser.add_argument('--file', type=str, help='同步单个文件（相对路径）')
    parser.add_argument('--dry-run', action='store_true', help='仅报告不做')
    args = parser.parse_args()

    cmd = [sys.executable, _GENERIC_SYNC,
           '--dir', WIKI,
           '--kb', KB_NAME]
    if args.full:
        cmd.append('--full')
    if args.file:
        cmd += ['--file', args.file]
    if args.dry_run:
        cmd.append('--dry-run')

    ret = subprocess.call(cmd)
    sys.exit(ret)


if __name__ == '__main__':
    main()