#!/usr/bin/env python3
"""Convert markdown: wrap MkDocs tab blocks and R18 admonitions in blockquotes."""

import sys, re

TAB_RE = re.compile(r'^\s*=== "([^"]+)"\s*$')
R18_RE = re.compile(r'^\s*!!! info "R18 扩展"\s*$')
LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]*)\)')

def process(text):
    lines = text.split('\n')
    out = []
    in_tab = False
    in_r18 = False

    for line in lines:
        m = TAB_RE.match(line)
        if m:
            if in_tab:
                out.append('')
                in_tab = False
                in_r18 = False
            out.append(f'> **{m.group(1)}**')
            out.append('> ')
            in_tab = True
            continue

        r = R18_RE.match(line)
        if r:
            if in_tab:
                out.append('> > **>> R18 扩展 <<**')
                out.append('> > ')
                in_r18 = True
                continue

        if in_tab:
            stripped = line.strip()
            if stripped == '':
                out.append('> > ' if in_r18 else '> ')
            else:
                out.append(f'> > {stripped}' if in_r18 else f'> {stripped}')
        else:
            out.append(LINK_RE.sub(r'\1', line))

    if in_tab:
        out.append('')
    return '\n'.join(out)

def main():
    sys.stdout.write(process(sys.stdin.read()))

if __name__ == '__main__':
    main()
