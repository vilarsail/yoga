#!/usr/bin/env python3
"""
fix_circled.py - 检测并修复 output/{N}.md / {N}.notes.md 中的圈号跳号问题。

原理：
1. 读取 {N}.md 原文段（　　开头）中的圈号，按阅读顺序应为 ①②③… 连续递增
2. 若检测到跳号，建立 {实际圈号: 应有圈号} 映射
3. 用临时占位符两遍替换（避免连锁冲突），同时修复 {N}.md 与 {N}.notes.md
4. 修复后重新校验连续性

用法：
    python3 fix_circled.py <N>            # 单卷
    python3 fix_circled.py <start> <end>  # 区间
    python3 fix_circled.py <start> <end> --dry-run  # 只检测不修改
"""

from __future__ import annotations
import re
import sys
from pathlib import Path

OUTPUT_DIR = Path('output')

CIRCLED = ('①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
           '㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚'
           '㉛㉜㉝㉞㉟'
           '㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿')
CIRCLED_SET = set(CIRCLED)
CIRCLED_INDEX = {ch: i + 1 for i, ch in enumerate(CIRCLED)}


def extract_md_sequence(n: int) -> list[str]:
    """提取 {N}.md 原文段（　　开头）中的圈号序列。"""
    path = OUTPUT_DIR / f'{n}.md'
    if not path.exists():
        return []
    text = path.read_text(encoding='utf-8')
    seq = []
    for line in text.split('\n'):
        if line.startswith('　　'):
            for ch in line:
                if ch in CIRCLED_SET:
                    seq.append(ch)
    return seq


def build_fix_map(actual_seq: list[str]) -> dict[str, str]:
    """对比实际序列与标准序列，返回 {actual: expected} 映射。空 = 无需修复。"""
    fix = {}
    for i, actual in enumerate(actual_seq):
        if i >= len(CIRCLED):
            break
        expected = CIRCLED[i]
        if actual != expected:
            fix[actual] = expected
    return fix


def apply_fix(text: str, fix_map: dict[str, str]) -> str:
    """用两遍替换法修复文本中的圈号（避免连锁冲突）。"""
    if not fix_map:
        return text
    # 第一遍：需要修改的圈号 → 临时占位符
    placeholder_map = {}
    for actual, expected in fix_map.items():
        ph = f'\x00CIRC{ord(expected)}\x00'
        placeholder_map[ph] = expected
        text = text.replace(actual, ph)
    # 第二遍：占位符 → 正确圈号
    for ph, expected in placeholder_map.items():
        text = text.replace(ph, expected)
    return text


def fix_volume(n: int, dry_run: bool = False) -> list[str]:
    """修复一卷，返回问题/操作列表。"""
    results = []

    # 1. 检测
    seq = extract_md_sequence(n)
    if not seq:
        results.append(f'[{n}] 无圈号或文件不存在，跳过')
        return results

    fix_map = build_fix_map(seq)
    if not fix_map:
        return results  # 无问题，静默

    results.append(f'[{n}] 检测到圈号跳号，{len(fix_map)} 处需修复:')
    for actual, expected in fix_map.items():
        results.append(f'       {actual}(第{CIRCLED_INDEX.get(actual,"?")}位) → {expected}(第{CIRCLED_INDEX.get(expected,"?")}位)')

    if dry_run:
        results.append(f'       [dry-run] 未修改文件')
        return results

    # 2. 修复 {N}.md
    md_path = OUTPUT_DIR / f'{n}.md'
    md_text = md_path.read_text(encoding='utf-8')
    md_fixed = apply_fix(md_text, fix_map)
    if md_fixed != md_text:
        md_path.write_text(md_fixed, encoding='utf-8')
        results.append(f'       已修复 {n}.md')

    # 3. 修复 {N}.notes.md
    notes_path = OUTPUT_DIR / f'{n}.notes.md'
    if notes_path.exists():
        notes_text = notes_path.read_text(encoding='utf-8')
        notes_fixed = apply_fix(notes_text, fix_map)
        if notes_fixed != notes_text:
            notes_path.write_text(notes_fixed, encoding='utf-8')
            results.append(f'       已修复 {n}.notes.md')

    # 4. 复验
    new_seq = extract_md_sequence(n)
    new_fix = build_fix_map(new_seq)
    if new_fix:
        results.append(f'       ✗ 修复后仍有跳号: {new_fix}')
    else:
        results.append(f'       ✓ 修复后圈号连续 (①…{new_seq[-1] if new_seq else "无"}, 共{len(new_seq)}个)')

    return results


def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    args = [a for a in args if a != '--dry-run']

    if not args:
        print('用法: python3 fix_circled.py <N> | <start> <end> [--dry-run]')
        return 2
    if len(args) == 2:
        s, e = int(args[0]), int(args[1])
        ns = list(range(s, e + 1))
    else:
        ns = [int(a) for a in args]

    print('=' * 60)
    print(f'fix_circled: 共 {len(ns)} 卷{" (dry-run)" if dry_run else ""}')
    print('=' * 60)

    fixed_count = 0
    for n in ns:
        results = fix_volume(n, dry_run)
        if results:
            for r in results:
                print(r)
            if not dry_run and '✓' in results[-1]:
                fixed_count += 1

    print('=' * 60)
    if dry_run:
        # dry-run 统计有问题的卷数
        problem_count = sum(1 for n in ns if build_fix_map(extract_md_sequence(n)))
        print(f'汇总: {problem_count}/{len(ns)} 卷存在跳号（dry-run，未修改）')
    else:
        print(f'汇总: {fixed_count} 卷已修复')
    return 0


if __name__ == '__main__':
    sys.exit(main())
