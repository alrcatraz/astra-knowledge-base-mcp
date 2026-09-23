#!/usr/bin/env python3
"""
dir-kb-sync.py — 单向同步：任意目录 → Astra KB

泛化自 wiki-kb-sync.py：把原来硬编码的 WIKI 目录 + KB_NAME 变成命令行
必选参数 --dir / --kb，从而支持任意本地目录同步到任意 KB。

Usage:
  python3 dir-kb-sync.py --dir /path/to/dir --kb <kb_name>                 # 增量同步（按 mtime）
  python3 dir-kb-sync.py --dir /path/to/dir --kb <kb_name> --full          # 全量重同步
  python3 dir-kb-sync.py --dir /path/to/dir --kb <kb_name> --file 子/文件.md  # 单个文件同步
  python3 dir-kb-sync.py --dir /path/to/dir --kb <kb_name> --dry-run      # 仅报告不做
  python3 dir-kb-sync.py --dir /path/to/dir --kb <kb_name> --watch         # 实时监听增改删移，自动单文件同步
  python3 dir-kb-sync.py --dir /path/to/dir --kb <kb_name> --conf 路径/conf.yaml  # 指定 OCR 配置文件

可选 OCR（Phase 3 后段，默认全关——除非显式启用，行为等同仅 .md/.txt）：
  图片（.jpg/.jpeg/.png）默认不纳入扫描。仅在配置里显式启用时才纳入：
  - kb-sync.conf（默认路径），或 --conf <path>（最高优先）> env KB_SYNC_CONF > 默认 scripts/kb-sync.conf。
  - 启用需 ocr.enabled: true 且 ocr.model 非空（如 "ocr"=AI Gate OCR combo，
    或 "deepseek-ai/DeepSeek-OCR"）。base_url 空=默认 http://127.0.0.1:20128/v1；
    api_key 空=回落 env ASTRA_LLM_API_KEY（再空则无鉴权）。
  - 启用后图片经 AI Gate /chat/completions 的 OCR 模型（image base64 + 提取文本
    prompt）→ 识别文本作为该文件 body 入库。--dry-run 下不真正调 AI，仅打印
    [OCR] 占位。
  - 配置文件缺失/字段缺失一律取默认值不报错；OCR 关时完全不涉及 AI Gateway。

当前 caveat：AI Gate 侧 OCR combo 因 OCR 模型缺 visionModels 白名单声明而暂不可执行，
真实 OCR 调用由编排者在 AI Gate 侧修复后验证；本脚本只提供配置框架 + 调用逻辑 +
dry-run 正确性。

依赖：
  ASTRA_EMBED_BASE_URL, ASTRA_EMBED_API_KEY, ASTRA_EMBED_MODEL
  环境变量需要设置。
  --watch 额外需要 watchdog（此环境已有）。--watch 与 --dry-run 叠加时只 log
  不写库。

语义分块：
  如果 KB 在 kb_registry 中设了 chunker='semantic'，会用 batch 嵌入模式。
  否则回退到 recursive。

扫描范围：
  .md：解析 frontmatter（若存在），title/tags 取自 frontmatter，否则取文件名 +
  CATEGORIES fallback。
  .txt：无 frontmatter，全文即正文，title 取去扩展文件名，tags 沿用
  CATEGORIES fallback（顶层目录未命中 → 'general'）。
  两者均排除 index.md / index.txt。
  图片（.jpg/.jpeg/.png）：默认不扫；仅当 kb-sync.conf 显式启用 OCR 时纳入，
  经 AI Gate OCR model 识别文本作为 body 入库（见上文"可选 OCR"）。

增量状态：
  STATE_FILE 位于目标目录内（.kb-sync-state），记录上次成功同步的 mtime 时间戳。
  本期不做 pdf/docx 泛化。
"""

import sys, os, json, base64, yaml, time, argparse, atexit
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

from pg_backend import add_chunks, _execute
from chunking.registry import get_chunker_for_kb
from chunking.semantic import SemanticChunker
from embed_client import embed_text, embed_batch

# 顶层目录 → 分类 tag 的映射。若非 wiki 目录（顶层不在此映射中）则 fallback
# 'general'。此逻辑沿用 wiki-kb-sync.py 的语义，未重写。
CATEGORIES = {
    '入门': 'overview', '地理': 'geography', '概念': 'concept',
    '种族': 'race', '国家与城邦': 'location', '神祇与信仰': 'deity',
    '组织与机构': 'organization',
}

# ── 可选 OCR（默认全关）────────────────────────────────────────────
# 配置优先级：--conf <path> > env KB_SYNC_CONF > 默认 scripts/kb-sync.conf。
# 配置文件缺失 / 字段缺失 → 一律默认（enabled=False），不报错。
DEFAULT_OCR_BASE_URL = 'http://127.0.0.1:20128/v1'
DEFAULT_CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kb-sync.conf')
_PAGE_EXTS = ('.md', '.txt')
_EXCLUDE_BASENAMES = ('index.md', 'index.txt')
_IMAGE_EXTS = ('.jpg', '.jpeg', '.png')

# AI Gate OCR 模型（chat/completions）的图片→文本提示词。
OCR_PROMPT = (
    'Extract and transcribe all text in this image. '
    'Return only the text as markdown, no commentary.'
)


def load_ocr_config(conf_path=None):
    """Load OCR config from an optional YAML file.

    优先级：conf_path(--conf) > env KB_SYNC_CONF > 默认 scripts/kb-sync.conf。
    文件缺失或字段缺失 → 取默认值（OCR 全关），不报错；仅当调用方显式传入
    的 conf_path 无效时由调用方（main）负责报错。
    """
    cfg = {
        'enabled': False,
        'model': '',
        'base_url': DEFAULT_OCR_BASE_URL,
        'api_key': os.environ.get('ASTRA_LLM_API_KEY', ''),
        'image_exts': list(_IMAGE_EXTS),
    }
    path = conf_path or os.environ.get('KB_SYNC_CONF') or DEFAULT_CONF
    if not path or not os.path.isfile(path):
        return cfg, path
    try:
        with open(path, 'r') as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as e:
        print(f'  [warn] 读取配置失败 {path}: {e}（OCR 全关）')
        return cfg, path
    ocr = data.get('ocr') or {}
    if 'enabled' in ocr:
        cfg['enabled'] = bool(ocr['enabled'])
    if 'model' in ocr and ocr['model']:
        cfg['model'] = str(ocr['model'])
    # base_url 显式非空才覆盖默认；等价空串=默认。
    if 'base_url' in ocr and ocr['base_url']:
        cfg['base_url'] = str(ocr['base_url']).rstrip('/')
    # api_key 显式非空才覆盖；空=回落 env ASTRA_LLM_API_KEY（或空=无鉴权）。
    if 'api_key' in ocr and ocr['api_key']:
        cfg['api_key'] = str(ocr['api_key'])
    exts = data.get('image_exts')
    if isinstance(exts, list) and exts:
        cfg['image_exts'] = [str(e).lstrip('.').lower() if not str(e).startswith('.')
                             else str(e).lower() for e in exts]
    return cfg, path


def ocr_enabled(cfg):
    """OCR 是否真正启用：enabled 且 model 非空。"""
    return bool(cfg and cfg.get('enabled') and cfg.get('model'))


def ocr_image(fp, cfg):
    """图片 → 文本：经 AI Gate /chat/completions 的 OCR model。

    读图片 base64 → POST {base_url}/chat/completions，messages 含
    image_url (data URI) 与提取文本 prompt，stream:false，
    取 choices[0].message.content 作为识别文本。仅在非 dry-run 调用。

    AI Gateway 概率性返回非标准结构或带 tag 的文本：容错取 content 字段，
    取不到则记警告并返回空串（不让一个坏图打断整轮同步）。
    """
    base_url = (cfg.get('base_url') or DEFAULT_OCR_BASE_URL).rstrip('/')
    model = cfg['model']
    api_key = cfg.get('api_key', '')
    ext = os.path.splitext(fp)[1].lower().lstrip('.') or 'png'
    mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png'}.get(ext, 'png')

    try:
        with open(fp, 'rb') as fh:
            img_b64 = base64.b64encode(fh.read()).decode('ascii')
    except Exception as e:
        print(f'  [warn] 读取图片失败 {fp}: {e}')
        return ''
    data_url = f'data:image/{mime};base64,{img_b64}'
    payload = json.dumps({
        'model': model,
        'messages': [
            {'role': 'user', 'content': [
                {'type': 'text', 'text': OCR_PROMPT},
                {'type': 'image_url', 'image_url': {'url': data_url}},
            ]},
        ],
        'stream': False,
    }).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    try:
        import urllib.request as _ur
        req = _ur.Request(f'{base_url}/chat/completions', data=payload,
                          headers=headers, method='POST')
        with _ur.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        text = result['choices'][0]['message']['content']
        if isinstance(text, str):
            text = text.strip()
            # 容错剥离包裹代码块（aigate 概率性夹带 ```...``` / json 标签）
            if text.startswith('```'):
                text = text.strip('`')
                if text.startswith(('json', 'text')):
                    text = text.split('\n', 1)[-1]
                text = text.strip()
            return text
        return ''
    except Exception as e:
        print(f'  [warn] OCR 调用失败 {fp}: {e}')
        return ''


def parse_page(fp, dir_path, kb_name, ocr_cfg=None, dry_run=False):
    """Parse a page → {title, body, source, tags}

    支持 .md / .txt，以及（OCR 启用时）.jpg/.jpeg/.png：
      - .md  解析 frontmatter（若以 '---' 开头），title/tags 取 frontmatter，否则 fallback。
      - .txt 无 frontmatter：全文即 body，title 取去扩展文件名，tags 走
        CATEGORIES fallback（顶层目录未命中 → 'general'）。
      - 图片（仅当 OCR 启用）body = ocr_image() 识别文本；dry_run 下不真调 AI，
        body 置 '[OCR pending]' 占位，dict 标记 'ocr': True。
    """
    rel = os.path.relpath(fp, dir_path)
    title = os.path.splitext(os.path.basename(fp))[0]
    tags = ['wiki', kb_name]
    path_parts = rel.split(os.sep)
    tags.append(CATEGORIES.get(path_parts[0], 'general'))

    ext = os.path.splitext(fp)[1].lower()
    is_image = ocr_enabled(ocr_cfg) and ocr_cfg is not None \
        and ext in ocr_cfg['image_exts']
    if is_image:
        if dry_run:
            body = '[OCR pending]'
        else:
            body = ocr_image(fp, ocr_cfg)
        return {
            'title': title, 'body': body, 'source': rel, 'tags': tags,
            'ocr': True,
        }

    with open(fp, 'r') as fh:
        content = fh.read()
    is_md = rel.endswith('.md')
    body = content
    # 只有 .md 走 frontmatter 解析；.txt 全文即正文。
    if is_md and content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
                title = fm.get('title', title)
            except:
                pass
            body = parts[2].strip()
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


def delete_source(source, kb_name):
    """Delete all chunks for a given source path."""
    schema = f'kb_{kb_name}'
    _execute(f'DELETE FROM {schema}.chunks WHERE source = %s', (source,))


def sync_file(fp, dir_path, kb_name, chunker, dry_run=False, ocr_cfg=None):
    """Sync a single file to KB (delete old + insert new)."""
    if not os.path.isfile(fp):
        return {'status': 'not_found', 'source': os.path.relpath(fp, dir_path)}
    page = parse_page(fp, dir_path, kb_name, ocr_cfg=ocr_cfg, dry_run=dry_run)
    if dry_run:
        return {'status': 'dry_run', 'source': page['source'], 'title': page['title'],
                'ocr': page.get('ocr', False)}
    # Delete old chunks for this source
    delete_source(page['source'], kb_name)
    # Chunk and insert
    chunks = chunk_page(page, chunker)
    result = add_chunks(kb_name, chunks)
    return {'status': 'synced', 'source': page['source'], 'title': page['title'],
            'chunks': len(chunks)}


def get_all_files(dir_path, page_exts=_PAGE_EXTS):
    """Return list of all page paths (absolute) under dir_path.

    过滤规则沿用原语义：取 .md/.txt（OCR 启用时另加图片扩展）文件，
    排除 index.md / index.txt。图片文件无 index 概念。
    用 os.walk 递归——天然规避带方括号（如 [世界观]）的路径，不要引入 glob。
    """
    files = []
    for root, dirs, fnames in os.walk(dir_path):
        for f in sorted(fnames):
            if not f.endswith(page_exts) or f in _EXCLUDE_BASENAMES:
                continue
            files.append(os.path.join(root, f))
    return files


def _is_page_rel(rel_path, page_exts=_PAGE_EXTS):
    """True if a relative path is an in-scope page (.md/.txt, non-index)."""
    base = os.path.basename(rel_path)
    return rel_path.endswith(page_exts) and base not in _EXCLUDE_BASENAMES


# ── --watch 相关（沿用 wiki-kb-watch.py 的 debounce / PID / 日志模式）────
WATCH_PIDFILE = '/tmp/dir-kb-watch.pid'
WATCH_LOGFILE = '/tmp/dir-kb-watch.log'
WATCH_DEBOUNCE = 1.5

# Debounce state: rel_path → last handled time
_pending = {}


def debounce(rel_path):
    """True if rel_path was handled within the last WATCH_DEBOUNCE seconds."""
    now = time.time()
    last = _pending.get(rel_path, 0)
    if now - last < WATCH_DEBOUNCE:
        return True
    _pending[rel_path] = now
    # Evict stale entries to prevent unbounded growth
    if len(_pending) > 1000:
        cutoff = now - 60
        stale = [k for k, v in _pending.items() if v < cutoff]
        for k in stale:
            del _pending[k]
    return False


def run_watch(dir_path, kb_name, chunker, dry_run=False, ocr_cfg=None, page_exts=_PAGE_EXTS):
    """实时监听 dir_path，对 .md/.txt（OCR 启用时另加图片）的增/改/删/移做单文件增量同步。

    同程直接调用本模块 sync_file（比 subprocess 快且可控）。
    使用 watchdog 的 Observer（需要 watchdog 可 import）。PID 写
    /tmp/dir-kb-watch.pid，日志写 /tmp/dir-kb-watch.log。--dry-run 时
    只同步到 socket 层即由 sync_file 返回 dry_run，不写库。
    """
    import logging
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(WATCH_LOGFILE),
            logging.StreamHandler(),
        ],
    )
    log = logging.getLogger('dir-kb-watch')

    def _warn(msg):
        print(f'  {msg}')
        log.warning(f'  {msg}')

    def _handle(rel_path):
        if not _is_page_rel(rel_path, page_exts=page_exts):
            return
        if debounce(rel_path):
            return
        fp = os.path.join(dir_path, rel_path)
        result = sync_file(fp, dir_path, kb_name, chunker, dry_run=dry_run,
                           ocr_cfg=ocr_cfg)
        tag = 'DRY' if dry_run else result.get('status', '?')
        extra = f' → {result.get("chunks")} chunks' if result.get('chunks') else ''
        log.info(f'  [{tag}] {rel_path}{extra}')

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory:
                _handle(os.path.relpath(event.src_path, dir_path))

        def on_modified(self, event):
            if not event.is_directory:
                _handle(os.path.relpath(event.src_path, dir_path))

        def on_deleted(self, event):
            if not event.is_directory:
                _handle(os.path.relpath(event.src_path, dir_path))

        def on_moved(self, event):
            if not event.is_directory:
                _handle(os.path.relpath(event.dest_path, dir_path))

    if not os.path.exists(WATCH_PIDFILE):
        with open(WATCH_PIDFILE, 'w') as f:
            f.write(str(os.getpid()))
        atexit.register(lambda: os.path.exists(WATCH_PIDFILE) and os.remove(WATCH_PIDFILE))
    else:
        try:
            old = int(open(WATCH_PIDFILE).read().strip())
            os.kill(old, 0)
            _warn(f'Already running (PID {old}), exiting.')
            sys.exit(1)
        except (OSError, ValueError):
            with open(WATCH_PIDFILE, 'w') as f:
                f.write(str(os.getpid()))
            atexit.register(lambda: os.path.exists(WATCH_PIDFILE) and os.remove(WATCH_PIDFILE))

    log.info(f'Watching: {dir_path} (kb={kb_name} dry_run={dry_run})')
    observer = Observer()
    observer.schedule(_Handler(), dir_path, recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def main():
    parser = argparse.ArgumentParser(description='Directory → KB Sync')
    parser.add_argument('--dir', required=True,
                        help='目标目录（绝对路径，递归扫描其中 .md/.txt 文件）')
    parser.add_argument('--kb', required=True, help='目标 KB 名称')
    parser.add_argument('--full', action='store_true', help='全量重同步')
    parser.add_argument('--file', type=str, help='同步单个文件（相对路径）')
    parser.add_argument('--watch', action='store_true',
                        help='实时监听 .md/.txt 增改删移，自动单文件同步（需 watchdog）')
    parser.add_argument('--conf', type=str, default=None,
                        help='OCR 配置文件路径（YAML，见 kb-sync.conf）。缺省用 env '
                             'KB_SYNC_CONF 或 scripts/kb-sync.conf')
    parser.add_argument('--dry-run', action='store_true', help='仅报告不做')
    args = parser.parse_args()

    # 显式 --conf 必须是有效文件；未显式指定时缺失一律静默取默认（OCR 全关）。
    if args.conf and not os.path.isfile(args.conf):
        print(f'Error: --conf 不是有效文件: {args.conf}（请用 --conf 传有效路径）')
        sys.exit(2)

    dir_path = os.path.abspath(args.dir)
    kb_name = args.kb

    if not os.path.isdir(dir_path):
        print(f'Error: --dir 不是有效目录: {dir_path}')
        sys.exit(2)

    ocr_cfg, conf_path = load_ocr_config(args.conf)
    ocr_on = ocr_enabled(ocr_cfg)
    # page_exts = .md/.txt，仅当 OCR 启用时追加图片扩展。
    page_exts = list(_PAGE_EXTS)
    if ocr_on:
        page_exts += [e for e in ocr_cfg['image_exts'] if e not in page_exts]
    page_exts = tuple(page_exts)
    print(f'  OCR: {"enabled (" + (ocr_cfg["model"] or "?") + ")" if ocr_on else "disabled"}'
          + (f'  [conf={conf_path}]' if conf_path else ''))

    state_file = os.path.join(dir_path, '.kb-sync-state')

    # Resolve chunker
    try:
        chunker = get_chunker_for_kb(kb_name, embed_fn=embed_text)
        print(f'  Chunker: {type(chunker).__name__}')
    except Exception as e:
        from chunking.recursive import RecursiveChunker
        chunker = RecursiveChunker(chunk_size=1000, chunk_overlap=200)
        print(f'  Chunker: Recursive (fallback: {e})')

    # --watch: 实时监听（only watch mode; ignores --full/--file/mtime 增量）
    if args.watch:
        run_watch(dir_path, kb_name, chunker, dry_run=args.dry_run,
                  ocr_cfg=ocr_cfg, page_exts=page_exts)
        return

    # Single file sync
    if args.file:
        fp = os.path.join(dir_path, args.file)
        result = sync_file(fp, dir_path, kb_name, chunker, dry_run=args.dry_run,
                           ocr_cfg=ocr_cfg)
        if args.dry_run and result.get('ocr'):
            print(f'  [OCR] {result["source"]}')
        else:
            print(f'  {result["status"]}: {result.get("source", "?")}'
                  + (f' → {result["chunks"]} chunks' if 'chunks' in result else ''))
        return

    # Full or incremental sync
    if args.full:
        print('  Full resync: clearing KB...')
        schema = f'kb_{kb_name}'
        if not args.dry_run:
            _execute(f'DELETE FROM {schema}.chunks')
        print('  Cleared.')

    # Read last sync timestamp
    last_sync = 0
    if os.path.exists(state_file) and not args.full:
        with open(state_file) as f:
            try:
                last_sync = int(f.read().strip())
            except:
                pass

    # Scan
    files = get_all_files(dir_path, page_exts=page_exts)
    if not files:
        print(f'Error: --dir 下没有找到任何可同步 .md/.txt'
              + ('/图片' if ocr_on else '')
              + f' 文件: {dir_path}')
        sys.exit(2)

    total_pages = 0
    total_chunks = 0
    skipped = 0

    for fp in files:
        mtime = os.path.getmtime(fp)
        if not args.full and mtime <= last_sync:
            skipped += 1
            continue
        result = sync_file(fp, dir_path, kb_name, chunker, dry_run=args.dry_run,
                           ocr_cfg=ocr_cfg)
        if args.dry_run:
            # 图片 dry-run：只打 [OCR] 占位，不真正调 AI。
            print(f'  [OCR] {result["source"]}' if result.get('ocr')
                  else f'  [DRY] {result["source"]}')
            total_pages += 1
        elif result['status'] == 'synced':
            total_pages += 1
            total_chunks += result['chunks']
            print(f'  {result["source"]} → {result["chunks"]} chunks')

    print(f'\nDone: {total_pages} pages, {total_chunks} chunks (skipped {skipped})')

    # Update timestamp
    if not args.dry_run and total_pages > 0:
        with open(state_file, 'w') as f:
            f.write(str(int(time.time())))
        print(f'  Sync state updated.')


if __name__ == '__main__':
    main()