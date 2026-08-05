#!/usr/bin/env python3
"""
split_paragraphs.py — 从 output/{N}.md 提取所有段落，写入 paragraphs_{N}.json

段落定义：以全角空格（　　）开头的连续行块
- 标题行 (#/##/###) 不参与
- 多行颂偈等连续块算 1 段
- 输出 {"1": "原文", "2": "原文\n多行", ...}
"""

import json, sys, os

def split_paragraphs(filepath: str) -> dict[str, str]:
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    paragraphs = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('　　'):  # 全角空格开头
            para_lines = []
            while i < len(lines) and lines[i].startswith('　　'):
                para_lines.append(lines[i].rstrip('\n'))
                i += 1
            paragraphs.append('\n'.join(para_lines))
        else:
            i += 1

    return {str(idx + 1): text for idx, text in enumerate(paragraphs)}


def main():
    if len(sys.argv) < 2:
        print("Usage: python split_paragraphs.py <N>", file=sys.stderr)
        sys.exit(1)

    n = int(sys.argv[1])
    src = f'output/{n}.md'
    dst = f'paragraphs_{n}.json'

    if not os.path.exists(src):
        print(f"Error: {src} not found", file=sys.stderr)
        sys.exit(1)

    paragraphs = split_paragraphs(src)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(paragraphs, f, ensure_ascii=False, indent=2)

    print(f"Split {src} → {dst} ({len(paragraphs)} paragraphs)")

if __name__ == '__main__':
    main()