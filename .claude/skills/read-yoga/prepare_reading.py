#!/usr/bin/env python3
"""
prepare_reading.py - 从 output/{N}.md 提取「原文-only 紧凑文本」供 LLM 生成导读与词语注释。

提取内容：
- 标题行（#/## 原样保留）
- 原文段落（　　 开头，多行颂偈合并为一段，段号 P{n} 标注首行）
- 跳过 * 译文行、空行、其他行

用法：
    python3 prepare_reading.py <N>            # 单章
    python3 prepare_reading.py <s> <e>        # 区间
"""

from __future__ import annotations
import re
import sys
from pathlib import Path

OUTPUT_DIR = Path('output')
TMP_PREFIX = 'reading_{n}_orig.txt'

# 编号方案与 build_reading.py 保持一致：统一样式〔n〕 + 圈号表（仅识别历史遗留），用于剥离上一轮残留标注
CIRCLED = ('①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
           '㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚'
           '㉛㉜㉝㉞㉟'
           '㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿')
MARKER_RE = re.compile(r'〔\d+〕|[' + ''.join(CIRCLED) + ']')


def parse_md(n: int):
    """返回 (title, headings, paragraphs)。paragraphs 为多行字符串列表（含 　　 前缀）。"""
    path = OUTPUT_DIR / f'{n}.md'
    if not path.exists():
        print(f'[ERROR] {path} 不存在')
        return None
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')
    title = ''
    headings = []
    paragraphs = []
    cur = None
    for line in lines:
        if line.startswith('#'):
            if cur is not None:
                paragraphs.append('\n'.join(cur))
                cur = None
            if not title:
                title = line.lstrip('#').strip()
            headings.append(line)
        elif line.startswith('　　'):
            # 剥离旧标注（幂等：重跑时清除上一轮的圈号与〔n〕扩展标记，避免 LLM 把标记当原文）
            line = MARKER_RE.sub('', line)
            if cur is None:
                cur = [line]
            else:
                cur.append(line)
        else:
            if cur is not None:
                paragraphs.append('\n'.join(cur))
                cur = None
    if cur is not None:
        paragraphs.append('\n'.join(cur))
    return title, headings, paragraphs


def build_extract(title: str, headings: list[str], paragraphs: list[str]) -> str:
    out = []
    out.append(f'# {title}')
    for h in headings:
        if h.lstrip('#').strip() != title:
            out.append(h)
    out.append('')
    for i, para in enumerate(paragraphs, 1):
        lines = para.split('\n')
        out.append(f'P{i}' + lines[0])
        out.extend(lines[1:])
    return '\n'.join(out) + '\n'


def main():
    args = sys.argv[1:]
    if not args:
        print('用法: python3 prepare_reading.py <N> | <s> <e>')
        return 2
    if len(args) == 2:
        s, e = int(args[0]), int(args[1])
        ns = list(range(s, e + 1))
    else:
        ns = [int(a) for a in args]

    print('=' * 60)
    print(f'prepare_reading: 共 {len(ns)} 章')
    print('=' * 60)
    for n in ns:
        parsed = parse_md(n)
        if parsed is None:
            return 1
        title, headings, paragraphs = parsed
        out_path = OUTPUT_DIR / TMP_PREFIX.format(n=n)
        out_path.write_text(build_extract(title, headings, paragraphs), encoding='utf-8')
        print(f'  [{n}] ✓ {title}: 标题={len(headings)}, 段={len(paragraphs)}'
              f' -> {out_path.name}')
    print('')
    print('LLM 输入文件: output/reading_{N}_orig.txt')
    return 0


if __name__ == '__main__':
    sys.exit(main())
