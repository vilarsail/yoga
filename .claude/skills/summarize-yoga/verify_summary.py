#!/usr/bin/env python3
"""
verify_summary.py - 校验 output/{N}.summary.md 的层级列表格式。

校验项：
- 每个非空行都必须是列表项（"- " 开头，可缩进）
- 首条为顶层「- **全篇总括**：」
- 缩进按每层 2 空格规整递进（不跳层、不用 Tab）
- 统计：总条目数、最大层级、顶层条目数

✗ 类错误 -> exit 1；⚠ 类警告仅提示。

用法：
    python3 verify_summary.py <N>            # 单章
    python3 verify_summary.py <s> <e>        # 区间
"""

from __future__ import annotations
import re
import sys
from pathlib import Path

OUTPUT_DIR = Path('output')
ITEM_RE = re.compile(r'^( *)- ')
TOP_SUMMARY_RE = re.compile(r'^- \*\*全篇总括\*\*')

MIN_ITEMS = 8
MAX_DEPTH = 5


def verify(n: int) -> bool:
    path = OUTPUT_DIR / f'{n}.summary.md'
    if not path.exists():
        print(f'  [{n}] ✗ {path} 不存在')
        return False

    ok = True
    first_seen = False
    prev_depth = -1
    items = 0
    topics = 1  # 一级主题数：总括（第0层）之下的直接子条目（第1层）
    max_depth = 0

    for lineno, line in enumerate(path.read_text(encoding='utf-8').split('\n'), 1):
        if not line.strip():
            continue
        m = ITEM_RE.match(line)
        if not m:
            print(f'  [{n}] ✗ 第{lineno}行不是列表项: {line.strip()[:40]}')
            ok = False
            continue

        indent = len(m.group(1))
        if '\t' in line[:indent + 2]:
            print(f'  [{n}] ✗ 第{lineno}行使用了 Tab 缩进')
            ok = False
        if indent % 2 != 0:
            print(f'  [{n}] ✗ 第{lineno}行缩进为奇数空格({indent})，层级错乱')
            ok = False
            continue
        depth = indent // 2

        if not first_seen:
            first_seen = True
            if depth != 0:
                print(f'  [{n}] ✗ 首条列表项不在顶层（缩进 {indent} 空格）')
                ok = False
            elif not TOP_SUMMARY_RE.match(line):
                print(f'  [{n}] ✗ 首条不是「- **全篇总括**：」: {line.strip()[:40]}')
                ok = False
        elif depth > prev_depth + 1:
            print(f'  [{n}] ✗ 第{lineno}行跳层：从第{prev_depth}层直接到第{depth}层')
            ok = False

        prev_depth = depth
        items += 1
        max_depth = max(max_depth, depth)
        if depth == 1:
            topics += 1

    if not first_seen:
        print(f'  [{n}] ✗ 文件为空或没有任何列表项')
        return False

    warn = []
    if items < MIN_ITEMS:
        warn.append(f'条目过少（{items} < {MIN_ITEMS}），覆盖可能不足')
    if topics < 3:
        warn.append(f'一级主题过少（{topics}），可能未按篇章结构展开')
    if max_depth + 1 > MAX_DEPTH:
        warn.append(f'层级过深（{max_depth + 1} 层 > {MAX_DEPTH} 层）')

    detail = f'条目={items}, 一级主题={topics}, 最大层级={max_depth + 1}'
    if ok:
        status = '✓' if not warn else '⚠'
        print(f'  [{n}] {status} {detail}')
        for w in warn:
            print(f'        ⚠ {w}')
    else:
        print(f'  [{n}] ✗ {detail}')
    return ok


def main():
    args = sys.argv[1:]
    if not args:
        print('用法: python3 verify_summary.py <N> | <s> <e>')
        return 2
    if len(args) == 2:
        ns = list(range(int(args[0]), int(args[1]) + 1))
    else:
        ns = [int(a) for a in args]

    print('=' * 60)
    print(f'verify_summary: 共 {len(ns)} 章')
    print('=' * 60)
    all_ok = True
    for n in ns:
        if not verify(n):
            all_ok = False
    print('')
    print('全部通过 ✓' if all_ok else '存在 ✗ 错误，需修正后重跑')
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
