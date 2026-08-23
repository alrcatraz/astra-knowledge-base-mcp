---
# KB-Optimised Wiki Page Template
#
# Frontmatter fields:
#   Standard wiki: title, created, updated, type, tags, sources
#   KB interop:    kb_sync, kb_chunker, kb_excerpt
#
# Usage:
#   1. Copy this template as a starting point
#   2. Fill in the fields below
#   3. Remove fields that do not apply
#   4. Write content with [[wikilinks]] to other pages
---

title: "Page Title"
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query
tags:
  - tag-from-taxonomy
sources:
  - raw/articles/source-file.md

# KB interop — controls how this page syncs to Astra KB
kb_sync: true                    # false = skip this page on export
kb_chunker: heading-anchor       # recursive | heading-anchor | semantic
kb_excerpt: "Brief summary for search results (optional)"

# Optional quality signals:
confidence: high | medium | low
contested: false
---


# Page Title

<!-- One-paragraph overview of what this page covers. -->

## Overview

<!-- Key facts for quick reference. Use [[wikilinks]] to reference other wiki pages. -->

## Details

<!-- Main body content. Structure with headings for multi-topic pages. -->

### Sub-section A

### Sub-section B

## Relationships

<!-- Connections to other pages/entities. -->
<!-- [[Related Concept A]] -->
<!-- [[Related Concept B]] -->

## Sources

<!-- Provenance markers for specific claims: -->
<!-- ^[raw/articles/source-file.md] -->
