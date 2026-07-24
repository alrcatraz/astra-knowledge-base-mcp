#!/usr/bin/env bash
# wiki-kb-sync.sh — Sync LLM Wiki pages to Astra Knowledge Base
#
# Usage:
#   ./scripts/wiki-kb-sync.sh --wiki /path/to/wiki              # incremental
#   ./scripts/wiki-kb-sync.sh --wiki /path/to/wiki --full        # full resync
#   ./scripts/wiki-kb-sync.sh --wiki /path/to/wiki --dry-run     # report only
#   ./scripts/wiki-kb-sync.sh --wiki /path/to/wiki --verbose     # detailed output
#
# Dependencies:
#   - Astra KB MCP server running (kb_add, kb_extract, kb_search)
#   - Unix tools: find, stat, date, jq (optional for JSON output)
#
# Selective sync:
#   Only processes pages with `kb_sync: true` in YAML frontmatter.
#   Pages without the field default to `kb_sync: false`.

set -euo pipefail

# --- Config ---
WIKI=""
MODE="incremental"  # incremental | full
DRY_RUN=false
VERBOSE=false
STATE_FILE=".kb-sync-state"

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --wiki) WIKI="$2"; shift 2 ;;
        --full) MODE="full"; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --verbose) VERBOSE=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$WIKI" ]]; then
    echo "Usage: $0 --wiki /path/to/wiki [--full] [--dry-run] [--verbose]"
    exit 1
fi

# Normalise path
WIKI="$(realpath "$WIKI")"
STATE_FILE="$WIKI/$STATE_FILE"

if [[ ! -d "$WIKI" ]]; then
    echo "Error: Wiki directory not found: $WIKI"
    exit 1
fi

echo "=== Wiki → KB Sync ==="
echo "  Wiki:  $WIKI"
echo "  Mode:  $MODE"
echo "  Dry:   $DRY_RUN"
echo ""

# --- Helper: check if page has kb_sync: true ---
has_kb_sync() {
    local file="$1"
    # Read first 20 lines (frontmatter block)
    local frontmatter
    frontmatter=$(head -20 "$file" 2>/dev/null)
    if echo "$frontmatter" | grep -qE '^kb_sync:\s*true'; then
        return 0
    fi
    return 1
}

# --- Helper: extract title from frontmatter ---
get_title() {
    local file="$1"
    local title
    title=$(head -20 "$file" 2>/dev/null | grep -E '^title:' | sed 's/^title:\s*//; s/^"//; s/"$//')
    echo "${title:-$(basename "$file" .md)}"
}

# --- Helper: get page last modified (Unix timestamp) ---
get_mtime() {
    local file="$1"
    stat -c "%Y" "$file" 2>/dev/null || echo "0"
}

# --- Read last sync timestamp ---
LAST_SYNC=0
if [[ -f "$STATE_FILE" ]]; then
    LAST_SYNC=$(cat "$STATE_FILE")
    if $VERBOSE; then
        echo "  Last sync: $(date -d @"$LAST_SYNC" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "timestamp $LAST_SYNC")"
    fi
fi

if [[ "$MODE" == "full" ]]; then
    LAST_SYNC=0
    echo "  (Full resync — ignoring previous sync state)"
fi
echo ""

# --- Scan wiki pages ---
echo "Scanning wiki pages..."

CHANGED=0
ADDED=0
SKIPPED=0
ERRORS=0

# Only scan entities/, concepts/, comparisons/ — skip raw/, queries/, log
for DIR in entities concepts comparisons; do
    DIR_PATH="$WIKI/$DIR"
    if [[ ! -d "$DIR_PATH" ]]; then
        continue
    fi

    while IFS= read -r -d '' PAGE; do
        # Skip if not syncable
        if ! has_kb_sync "$PAGE"; then
            SKIPPED=$((SKIPPED + 1))
            continue
        fi

        MTIME=$(get_mtime "$PAGE")
        REL_PATH="${PAGE#$WIKI/}"

        if [[ "$MODE" == "incremental" ]] && [[ "$MTIME" -le "$LAST_SYNC" ]]; then
            # Page hasn't changed since last sync
            continue
        fi

        TITLE=$(get_title "$PAGE")
        CONTENT=$(cat "$PAGE")

        CHANGED=$((CHANGED + 1))

        if $DRY_RUN; then
            echo "  [DRY-RUN] Would sync: $REL_PATH  ($TITLE)"
            continue
        fi

        # Sync to KB
        if $VERBOSE; then
            echo "  Syncing: $REL_PATH  ($TITLE)"
        fi

        # Determine chunker from frontmatter (default: heading-anchor)
        CHUNKER="heading-anchor"
        FRONTMATTER=$(head -20 "$PAGE")
        if echo "$FRONTMATTER" | grep -qE '^kb_chunker:\s*'; then
            CHUNKER=$(echo "$FRONTMATTER" | grep -E '^kb_chunker:' | sed 's/^kb_chunker:\s*//')
        fi

        # Call kb_add via MCP (depends on Hermes MCP tools)
        if command -v hermes &>/dev/null; then
            # Attempt via hermes CLI
            if hermes mcp call astra_kb kb_add \
                --arg kb="wiki_${DIR}" \
                --arg title="$TITLE" \
                --arg content="$CONTENT" \
                --arg source="$REL_PATH" \
                --arg tags="[\"wiki\",\"${DIR}\"]" \
                --arg chunker="$CHUNKER" 2>/dev/null; then
                ADDED=$((ADDED + 1))
            else
                echo "  [ERROR] Failed to sync: $REL_PATH"
                ERRORS=$((ERRORS + 1))
            fi
        else
            # Fallback: print what would be synced
            echo "  [INFO] hermes not found. Would kb_add: $REL_PATH"
            echo "    KB: wiki_${DIR}"
            echo "    Chunker: $CHUNKER"
            ADDED=$((ADDED + 1))
        fi

    done < <(find "$DIR_PATH" -name '*.md' -type f -print0)
done

echo ""
echo "=== Summary ==="
echo "  Changed:    $CHANGED"
echo "  Synced:     $ADDED"
echo "  Skipped:    $SKIPPED"
echo "  Errors:     $ERRORS"

# --- Update sync timestamp ---
if ! $DRY_RUN && [[ "$ADDED" -gt 0 ]]; then
    date +%s > "$STATE_FILE"
    echo "  Sync state updated: $(date '+%Y-%m-%d %H:%M:%S')"
fi

echo ""

# --- Optional: run kb_extract for SAG indexing ---
if ! $DRY_RUN && [[ "$ADDED" -gt 0 ]]; then
    echo "Running kb_extract for SAG indexing..."
    for DIR in entities concepts comparisons; do
        KB_NAME="wiki_${DIR}"
        if command -v hermes &>/dev/null; then
            hermes mcp call astra_kb kb_extract --arg kb="$KB_NAME" 2>/dev/null || true
        fi
    done
    echo "  SAG extraction triggered."
fi

echo "Done."
