#!/usr/bin/env bash
# wiki-kb-watch.sh — 实时文件监听：Wiki 变动 → 自动同步到 Astra KB
#
# 依赖: inotify-tools, python3, 环境变量 ASTRA_EMBED_*
# 用法:
#   bash wiki-kb-watch.sh                    # 前台运行
#   bash wiki-kb-watch.sh --daemon           # 后台守护模式
#   bash wiki-kb-watch.sh --once             # 处理现有变更后退出
#
# 每当 .md 文件被修改、创建、删除时，自动触发同步。

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SYNC_SCRIPT="$HERE/wiki-kb-sync.py"
WIKI="/home/alrcatraz/Extra/DS425Plus/homes/Alrcatraz/Novels/[世界观] 格利欧萨共和国/wiki"
PIDFILE="/tmp/wiki-kb-watch.pid"
LOGFILE="/tmp/wiki-kb-watch.log"

DAEMON=false
ONCE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --daemon|-d) DAEMON=true; shift ;;
    --once|-1)   ONCE=true; shift ;;
    *) echo "Usage: $0 [--daemon|--once]"; exit 1 ;;
  esac
done

# 确保环境变量加载
if [[ -f "$HERE/../.env" ]]; then
  set -a
  source "$HERE/../.env"
  set +a
fi

log() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "[$ts] $*" | tee -a "$LOGFILE"
}

do_sync() {
  local file="$1"
  local event="$2"
  local rel="${file#$WIKI/}"

  # 只处理 .md 文件（排除 index.md）
  case "$rel" in
    *.md) ;;
    *) return ;;
  esac
  [[ "$rel" == "index.md" ]] && return
  [[ "$rel" == SCHEMA.md ]] && return

  # 消抖：一秒内同一文件的重复事件合并
  local lock="/tmp/wiki-kb-watch-$(echo "$rel" | md5sum | cut -c1-8)"
  if [[ -f "$lock" ]]; then
    local age
    age=$(($(date +%s) - $(stat -c %Y "$lock" 2>/dev/null || echo 0)))
    [[ $age -lt 1 ]] && return
  fi
  touch "$lock"

  case "$event" in
    DELETE*|MOVED_FROM*)
      log "🗑  DELETE  $rel"
      python3 "$SYNC_SCRIPT" --file "$rel" 2>&1 | tee -a "$LOGFILE"
      ;;
    *)
      log "📝  $event  $rel"
      python3 "$SYNC_SCRIPT" --file "$rel" 2>&1 | tee -a "$LOGFILE"
      ;;
  esac
}

if $DAEMON; then
  if [[ -f "$PIDFILE" ]]; then
    old_pid=$(cat "$PIDFILE")
    if kill -0 "$old_pid" 2>/dev/null; then
      echo "Already running (PID $old_pid). Use: kill $old_pid"
      exit 1
    fi
    rm -f "$PIDFILE"
  fi
  echo "$$" > "$PIDFILE"
  log "Watch daemon started (PID $$)"
  exec &> >(tee -a "$LOGFILE")
fi

log "Watching: $WIKI"

# 初次手动同步
if $ONCE; then
  log "Running initial sync (--once)..."
  python3 "$SYNC_SCRIPT" 2>&1 | tee -a "$LOGFILE"
  log "Sync complete."
  exit 0
fi

# 主循环：inotifywait 监听
inotifywait -m -r "$WIKI" \
  -e modify -e create -e delete -e moved_from -e moved_to \
  --format '%w %e' |
while read -r path events; do
  do_sync "$path" "$events"
done
