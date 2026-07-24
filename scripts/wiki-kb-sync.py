#!/usr/bin/env python3
"""
wiki-kb-sync.py — 单向同步：Wiki → Astra KB

Usage:
  python3 wiki-kb-sync.py                    # 增量同步（按 mtime）
  python3 wiki-kb-sync.py --full             # 全量重同步
  python3 wiki-kb-sync.py --file 入门/概述.md  # 单个文件同步
  python3 wiki-kb-sync.py --dry-run          # 仅报告不做

依赖：
  ASTRA_EMBED_BASE_URL, ASTRA_EMBED_API_KEY, ASTRA_EMBED_MODEL
  环境变量需要设置。

语义分块：
  如果 KB 在 kb_registry 中设了 chunker='semantic'，会用 batch 嵌入模式。
  否则回退到 recursive。
"""

import sys, os, yaml, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

# ── 项目配置 ─────────────────────────────────────────────
WIKI = '/home/alrcatraz/Extra/DS425Plus/homes/Alrcatraz/Novels/[世界观] 格利欧萨共和国/wiki'
KB_NAME = 'gliousa'
STATE_FILE = os.path.join(WIKI, '.kb-sync-state')
# ─────────────────────────────────────────────────────────

from pg_backend import add_chunks, _execute, _fetch_all
from chunking.registry import get_chunker_for_kb
from chunking.semantic import SemanticChunker
from embed_client import embed_text, embed_batch

CATEGORIES = {
    '入门': 'overview', '地理': 'geography', '概念': 'concept',
    '种族': 'race', '国家与城邦': 'location', '神祇与信仰': 'deity',
    '组织与机构': 'organization',
}


def parse_page(fp):
    """Parse a wiki page → {title, body, source, tags}"""
    rel = os.path.relpath(fp, WIKI)
    with open(fp, 'r') as fh:
        content = fh.read()
    title = os.path.splitext(os.path.basename(fp))[0]
    tags = ['wiki', 'gliousa']
    body = content
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
                title = fm.get('title', title)
            except:
                pass
            body = parts[2].strip()
    path_parts = rel.split(os.sep)
    tags.append(CATEGORIES.get(path_parts[0], 'general'))
    return {'title': title, 'body': body, 'source': rel, 'tags': tags}


def chunk_page(page_data, chunker):
    """Apply chunker to a single page, return list of chunk dicts."""
    body = page_data['body']
    paras = [p.strip() for p in body.split('\n\n') if p.strip()]
    if len(paras) <= 1:
        return [{
            'title': page_data['title'],
            'content': body,
            'source': page_data['source'],
            'tags': page_data['tags'],
        }]
    if isinstance(chunker, SemanticChunker):
        # Batch-embed this single page's paragraphs
        vectors = embed_batch(paras)
        if vectors and len(vectors) == len(paras):
            return chunker.chunk_with_vectors(body, vectors, metadata={
                'title': page_data['title'],
                'source': page_data['source'],
                'tags': page_data['tags'],
            })
    # Fallback to basic chunk
    return chunker.chunk(body, metadata={
        'title': page_data['title'],
        'source': page_data['source'],
        'tags': page_data['tags'],
    })


def delete_source(source):
    """Delete all chunks for a given source path."""
    schema = f'kb_{KB_NAME}'
    _execute(f'DELETE FROM {schema}.chunks WHERE source = %s', (source,))


def sync_file(fp, chunker, dry_run=False):
    """Sync a single wiki file to KB (delete old + insert new)."""
    if not os.path.isfile(fp):
        return {'status': 'not_found', 'source': os.path.relpath(fp, WIKI)}
    page = parse_page(fp)
    if dry_run:
        return {'status': 'dry_run', 'source': page['source'], 'title': page['title']}
    # Delete old chunks for this source
    delete_source(page['source'])
    # Chunk and insert
    chunks = chunk_page(page, chunker)
    result = add_chunks(KB_NAME, chunks)
    return {'status': 'synced', 'source': page['source'], 'title': page['title'],
            'chunks': len(chunks)}


def get_all_wiki_files():
    """Return list of all wiki page paths (absolute)."""
    files = []
    for root, dirs, fnames in os.walk(WIKI):
        for f in sorted(fnames):
            if not f.endswith('.md') or f in ('index.md',):
                continue
            files.append(os.path.join(root, f))
    return files


def main():
    parser = argparse.ArgumentParser(description='Wiki → KB Sync')
    parser.add_argument('--full', action='store_true', help='全量重同步')
    parser.add_argument('--file', type=str, help='同步单个文件（相对路径）')
    parser.add_argument('--dry-run', action='store_true', help='仅报告不做')
    args = parser.parse_args()

    # Resolve chunker
    try:
        chunker = get_chunker_for_kb(KB_NAME, embed_fn=embed_text)
        print(f'  Chunker: {type(chunker).__name__}')
    except Exception as e:
        from chunking.recursive import RecursiveChunker
        chunker = RecursiveChunker(chunk_size=1000, chunk_overlap=200)
        print(f'  Chunker: Recursive (fallback: {e})')

    # Single file sync
    if args.file:
        fp = os.path.join(WIKI, args.file)
        result = sync_file(fp, chunker, dry_run=args.dry_run)
        print(f'  {result["status"]}: {result.get("source", "?")}'
              + (f' → {result["chunks"]} chunks' if 'chunks' in result else ''))
        return

    # Full or incremental sync
    if args.full:
        print('  Full resync: clearing KB...')
        schema = f'kb_{KB_NAME}'
        _execute(f'DELETE FROM {schema}.chunks')
        print('  Cleared.')

    # Read last sync timestamp
    last_sync = 0
    if os.path.exists(STATE_FILE) and not args.full:
        with open(STATE_FILE) as f:
            try:
                last_sync = int(f.read().strip())
            except:
                pass

    # Scan
    files = get_all_wiki_files()
    total_pages = 0
    total_chunks = 0
    skipped = 0

    for fp in files:
        mtime = os.path.getmtime(fp)
        if not args.full and mtime <= last_sync:
            skipped += 1
            continue
        result = sync_file(fp, chunker, dry_run=args.dry_run)
        if args.dry_run:
            print(f'  [DRY] {result["source"]}')
            total_pages += 1
        elif result['status'] == 'synced':
            total_pages += 1
            total_chunks += result['chunks']
            print(f'  {result["source"]} → {result["chunks"]} chunks')

    print(f'\nDone: {total_pages} pages, {total_chunks} chunks (skipped {skipped})')

    # Update timestamp
    if not args.dry_run and total_pages > 0:
        with open(STATE_FILE, 'w') as f:
            f.write(str(int(time.time())))
        print(f'  Sync state updated.')


if __name__ == '__main__':
    main()
