#!/usr/bin/env bash
# ============================================================
# build-pdf.sh — 通用 MkDocs wiki → PDF 导出脚本
#
# 使用方法:
#   1. 复制此脚本到项目目录
#   2. 在脚本顶部设置 WIKI=、OUTPUT=、nav_order
#   3. 按需调整 preprocess.py 路径和 header.tex 路径
#   4. bash build-pdf.sh
#
# 依赖: pandoc, lualatex, Noto Sans CJK SC, mdframed, xcolor
# ============================================================

# >>> 项目配置 — 修改这里 <<<
WIKI="/path/to/your/wiki"               # MkDocs wiki 源文件目录
OUTPUT="/tmp/exported-wiki.pdf"          # 输出 PDF 路径
HERE="$(cd "$(dirname "$0")" && pwd)"    # 脚本所在目录（放 preprocess.py 和 header.tex）

# >>> 页面顺序 — 按 MkDocs nav 顺序排列 <<<
nav_order=(
  # 格式: "分类/页面.md"
  # 例如:
  # "入门/概述.md"
  # "概念/核心概念.md"
  # "实体/人物.md"
)

# ------------------------------------------------------------
# 以下为通用处理逻辑，通常不需要修改
# ------------------------------------------------------------

MERGED="/tmp/_pdf-merged.md"
PREPROC="$HERE/preprocess.py"
HEADER="$HERE/header.tex"
HAS_IMAGE_FIX=false  # 设为 true 启用 sed 图片路径修复

# 清理上次临时文件
rm -f "$MERGED"

# --- Frontmatter (封面 + 目录) ---
cat > "$MERGED" << 'LATEX'
---
title: 我的 Wiki
subtitle: 全本导出
papersize: a4
fontsize: 11pt
documentclass: article
classoption: titlepage
geometry: margin=2cm
mainfont: Noto Sans CJK SC
CJKmainfont: Noto Sans CJK SC
---

\maketitle
\tableofcontents
\newpage
LATEX

# --- 合并所有源文件 ---
for rel in "${nav_order[@]}"; do
  fp="$WIKI/$rel"
  [ -f "$fp" ] || continue

  echo "" >> "$MERGED"
  echo '\newpage' >> "$MERGED"
  echo "" >> "$MERGED"

  # 去除 frontmatter → 图片路径修复（可选）→ preprocess.py
  cmd="sed -n '/^---$/,/^---$/!p' \"$fp\""
  if [ "$HAS_IMAGE_FIX" = true ]; then
    cmd="$cmd | sed 's|](/images/|](images/|g'"
  fi
  cmd="$cmd | python3 \"$PREPROC\""
  eval "$cmd" >> "$MERGED"
done

# --- Pandoc 构建 PDF ---
pandoc "$MERGED" \
  --pdf-engine=lualatex \
  -H "$HEADER" \
  --toc \
  -o "$OUTPUT"

echo "PDF: $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
ls -la "$OUTPUT"

# 清理
rm -f "$MERGED"
