#!/usr/bin/env python3
"""
merge_translations.py — 将 translations_{N}.json 合并回 output/{N}.md

- 读取原始 output/{N}.md，保持标题行原样
- 读取 translations_{N}.json（格式: {"1": "*译文*", "2": "*行1*\n*行2*", ...}）
- 在每段原文后插入对应译文（斜体），中间空一行
- 原文 100% 保持，无需校验
"""

import json, sys, os

def merge(filepath: str, translations_path: str):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    with open(translations_path, 'r', encoding='utf-8') as f:
        translations = json.load(f)

    # Parse original file into blocks
    blocks = []  # list of ('para', text) or ('other', text)
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('　　'):
            para_lines = []
            while i < len(lines) and lines[i].startswith('　　'):
                para_lines.append(lines[i])
                i += 1
            blocks.append(('para', ''.join(para_lines).rstrip('\n')))
        else:
            blocks.append(('other', line))
            i += 1

    # Count paragraphs
    para_count = sum(1 for b in blocks if b[0] == 'para')
    trans_count = len(translations)
    if para_count != trans_count:
        print(f"WARNING: paragraph count mismatch: {para_count} in file vs {trans_count} in translations",
              file=sys.stderr)

    # Assemble
    ti = 1  # translation key starts from "1"
    output = []
    for btype, content in blocks:
        if btype == 'other':
            output.append(content)
        else:
            # Original paragraph
            for pl in content.split('\n'):
                output.append(pl + '\n')
            # Translation
            key = str(ti)
            if key in translations:
                output.append('\n')
                output.append(translations[key] + '\n')
                output.append('\n')
            ti += 1

    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(''.join(output))

    print(f"Merged {ti - 1} translations into {filepath}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python merge_translations.py <N>", file=sys.stderr)
        sys.exit(1)

    n = int(sys.argv[1])
    src = f'output/{n}.md'
    trans = f'translations_{n}.json'

    if not os.path.exists(src):
        print(f"Error: {src} not found", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(trans):
        print(f"Error: {trans} not found", file=sys.stderr)
        sys.exit(1)

    merge(src, trans)

if __name__ == '__main__':
    main()