#!/usr/bin/env bash
# classify-input.sh — Classify and convert user input for knowledge ingestion
#
# Determines whether input is:
#   - An existing wiki (SCHEMA.md + index.md + subdirectories)
#   - A document stack (PDFs, Office files, images)
#   - A single file
#
# If it is not a wiki, converts documents to Markdown (via MarkItDown MCP
# or OfficeCLI) and reports the result for the next step.
#
# Usage:
#   ./scripts/classify-input.sh --path /path/to/input
#   ./scripts/classify-input.sh --path /path/to/input.zip
#   ./scripts/classify-input.sh --path /path/to/file.pdf
#   ./scripts/classify-input.sh --path /path/to/ --verbose
#
# Output:
#   Prints classification result as JSON to stdout:
#   {"type": "wiki|doc_stack|single_file", "path": "...", "files": [...], "converted": [...]}
#
# Dependencies:
#   - unzip / tar (for archives)
#   - MarkItDown MCP (for conversion, optional — reports what would convert)
#   - OfficeCLI MCP (fallback for complex Office files)

set -euo pipefail

INPUT_PATH=""
VERBOSE=false
WORK_DIR=""

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --path) INPUT_PATH="$2"; shift 2 ;;
        --verbose) VERBOSE=true; shift ;;
        --work-dir) WORK_DIR="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$INPUT_PATH" ]]; then
    echo "Usage: $0 --path /path/to/input [--verbose] [--work-dir /tmp/classify]"
    exit 1
fi

INPUT_PATH="$(realpath -m "$INPUT_PATH" 2>/dev/null || echo "$INPUT_PATH")"

# --- Helper: log ---
log() {
    if $VERBOSE; then
        echo "[classify] $*" >&2
    fi
}

# --- Helper: detect wiki ---
is_wiki() {
    local dir="$1"
    if [[ -f "$dir/SCHEMA.md" && -f "$dir/index.md" ]]; then
        # At least one content directory with .md files
        # Use find with -maxdepth to avoid glob bracket issues with paths like [世界观]
        for sub in entities concepts comparisons; do
            if [[ -d "$dir/$sub" ]] && \
               find "$dir/$sub" -maxdepth 1 -name '*.md' -type f 2>/dev/null | grep -q .; then
                return 0
            fi
        done
        # Also accept queries/ with .md files
        if [[ -d "$dir/queries" ]] && \
           find "$dir/queries" -maxdepth 1 -name '*.md' -type f 2>/dev/null | grep -q .; then
            return 0
        fi
    fi
    return 1
}

# --- Helper: expand archive ---
expand_archive() {
    local archive="$1"
    local target="$2"
    mkdir -p "$target"

    case "$archive" in
        *.zip)
            unzip -q "$archive" -d "$target" 2>/dev/null
            log "Extracted zip to $target"
            ;;
        *.tar.gz|*.tgz)
            tar -xzf "$archive" -C "$target" 2>/dev/null
            log "Extracted tar.gz to $target"
            ;;
        *.tar)
            tar -xf "$archive" -C "$target" 2>/dev/null
            log "Extracted tar to $target"
            ;;
        *)
            log "Not an archive, using as-is"
            return 1
            ;;
    esac
    return 0
}

# --- Helper: detect format of a single file ---
file_format() {
    local file="$1"
    case "${file,,}" in
        *.pdf)     echo "pdf" ;;
        *.docx|*.doc) echo "docx" ;;
        *.pptx|*.ppt) echo "pptx" ;;
        *.xlsx|*.xls) echo "xlsx" ;;
        *.html|*.htm) echo "html" ;;
        *.md)      echo "markdown" ;;
        *.txt)     echo "text" ;;
        *.png|*.jpg|*.jpeg|*.webp|*.gif|*.bmp|*.tiff) echo "image" ;;
        *.zip|*.tar.gz|*.tgz|*.tar) echo "archive" ;;
        *)         echo "unknown" ;;
    esac
}

# --- Main classification ---
WORK_DIR="${WORK_DIR:-$(mktemp -d /tmp/classify-XXXXX)}"
RESOLVED_PATH="$INPUT_PATH"

log "Classifying: $INPUT_PATH"

# Phase 1: Handle archives
if [[ -f "$INPUT_PATH" ]]; then
    fmt=$(file_format "$INPUT_PATH")
    if [[ "$fmt" == "archive" ]]; then
        log "Input is an archive, expanding..."
        EXPANDED="$WORK_DIR/expanded"
        if expand_archive "$INPUT_PATH" "$EXPANDED"; then
            # Find single top-level directory
            CONTENTS=("$EXPANDED"/*)
            if [[ ${#CONTENTS[@]} -eq 1 && -d "${CONTENTS[0]}" ]]; then
                RESOLVED_PATH="${CONTENTS[0]}"
            else
                RESOLVED_PATH="$EXPANDED"
            fi
            log "Expanded to: $RESOLVED_PATH"
        fi
    fi
fi

# Phase 2: Classify
if [[ -f "$RESOLVED_PATH" ]]; then
    # Single file
    fmt=$(file_format "$RESOLVED_PATH")
    log "Single file detected: $fmt"

    if [[ "$fmt" == "markdown" || "$fmt" == "text" ]]; then
        echo "{\"type\": \"single_file\", \"format\": \"$fmt\", \"path\": \"$RESOLVED_PATH\", \"needs_conversion\": false}"
    else
        echo "{\"type\": \"single_file\", \"format\": \"$fmt\", \"path\": \"$RESOLVED_PATH\", \"needs_conversion\": true}"
    fi

elif [[ -d "$RESOLVED_PATH" ]]; then
    # Directory — check if wiki
    if is_wiki "$RESOLVED_PATH"; then
        log "Detected as wiki project"
        # List wiki pages
        PAGES=$(find "$RESOLVED_PATH/entities" "$RESOLVED_PATH/concepts" "$RESOLVED_PATH/comparisons" -name '*.md' -type f 2>/dev/null | wc -l)
        echo "{\"type\": \"wiki\", \"path\": \"$RESOLVED_PATH\", \"page_count\": $PAGES, \"needs_conversion\": false}"
    else
        # Document stack — enumerate convertible files
        log "Detected as document stack"
        FILES=()
        while IFS= read -r -d '' F; do
            FILES+=("$F")
        done < <(find "$RESOLVED_PATH" -type f \( \
            -iname '*.pdf' -o -iname '*.docx' -o -iname '*.doc' \
            -o -iname '*.pptx' -o -iname '*.ppt' \
            -o -iname '*.xlsx' -o -iname '*.xls' \
            -o -iname '*.html' -o -iname '*.htm' \
            -o -iname '*.md' -o -iname '*.txt' \
            -o -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \
            -o -iname '*.webp' \) -print0 2>/dev/null)

        FILE_LIST=$(printf '%s\n' "${FILES[@]}" | jq -R -s 'split("\n") | map(select(length > 0))' 2>/dev/null || printf '%s\n' "${FILES[@]}")

        echo "{\"type\": \"doc_stack\", \"path\": \"$RESOLVED_PATH\", \"file_count\": ${#FILES[@]}, \"needs_conversion\": true}"
    fi
else
    echo "{\"type\": \"error\", \"message\": \"Path not found: $INPUT_PATH\"}"
    exit 1
fi

# Cleanup temp dir if we created one
if [[ "$WORK_DIR" == /tmp/classify-* ]]; then
    rm -rf "$WORK_DIR" 2>/dev/null || true
fi
