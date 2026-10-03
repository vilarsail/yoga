#!/usr/bin/env python3
"""
verify_reading.py - 校验 output/{N}.md / {N}.guide.md / {N}.notes.md 的完整性与对应关系。

检查项：
1. 三个产物文件存在且非空
2. 原文段（　　开头）中的标记合法（圈号 ①-㊿ 或扩展〔n〕）
3. 原文中标记按阅读顺序连续递增、无跳号、无重复
4. 注释表 {N}.notes.md 解析出的标记集合 == 原文标记集合
5. 注释表条目数 == 原文标记数
6. 序号-位置对应：注释表中每条 term（去空白）必须紧贴对应标记左侧出现于原文段中
7. 标记只出现在原文段（　　开头），不出现在译文（*）或标题（#）行
8. 导读 {N}.guide.md 含五节标题（一~五），字数 400-1500（仅提示不阻断）

用法：
    python3 verify_reading.py <start> <end>
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
# 编号方案与 build_reading.py 一致：统一样式〔1〕〔2〕…；圈号表仅用于识别历史遗留标注
MARKER_RE = re.compile(r'〔\d+〕|[' + ''.join(CIRCLED) + ']')


def marker(i: int) -> str:
    return f'〔{i}〕'

GUIDE_SECTIONS = ['## 一、', '## 二、', '## 三、', '## 四、', '## 五、']


def ws_strip(s: str) -> str:
    return ''.join(ch for ch in s if not ch.isspace())


def parse_md_with_markers(n: int):
    """返回 (title, para_segments, all_lines)。
    para_segments: list[str]，每个为合并后的原文段（含 　前缀、含圈号）。
    all_lines: list[str]，原文文件全部行（用于检查圈号是否越界到非原文段）。
    """
    path = OUTPUT_DIR / f'{n}.md'
    if not path.exists():
        return None
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')
    title = ''
    paragraphs = []
    cur = None
    for line in lines:
        if line.startswith('#'):
            if cur is not None:
                paragraphs.append('\n'.join(cur))
                cur = None
            if not title:
                title = line.lstrip('#').strip()
        elif line.startswith('　　'):
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
    return title, paragraphs, lines


def parse_notes_md(n: int):
    """解析 {N}.notes.md，返回 [(marker, term, note), ...] 或 None（文件不存在/格式错）。"""
    path = OUTPUT_DIR / f'{n}.notes.md'
    if not path.exists():
        return None
    text = path.read_text(encoding='utf-8')
    items = []
    for line in text.split('\n'):
        if not line or line.startswith('#'):
            continue
        # 形如「① 嗢拖南　注释...」
        m = re.match(r'^(\S+)\s+(\S.*?)\u3000(.*)$', line)
        if not m:
            # 容错：term 与 note 之间可能用普通空格
            m2 = re.match(r'^(\S+)\s+(\S+?)\s+(.*)$', line)
            if not m2:
                continue
            marker, term, note = m2.group(1), m2.group(2), m2.group(3)
        else:
            marker, term, note = m.group(1), m.group(2), m.group(3)
        items.append((marker, term, note))
    return items


def verify_volume(n: int) -> tuple[list[str], list[str]]:
    """返回 (problems, warnings)。problems 阻断（退出码 1），warnings 仅提示。"""
    problems = []
    warnings = []

    # 1. 文件存在性
    for fname in (f'{n}.md', f'{n}.guide.md', f'{n}.notes.md'):
        p = OUTPUT_DIR / fname
        if not p.exists():
            problems.append(f'缺失文件 {fname}')
            return problems
        if not p.read_text(encoding='utf-8').strip():
            problems.append(f'文件为空 {fname}')

    parsed = parse_md_with_markers(n)
    if parsed is None:
        problems.append(f'无法解析 {n}.md')
        return problems
    title, paragraphs, all_lines = parsed

    # 2. 编号合法性 + 7. 编号只出现在原文段
    for line in all_lines:
        # 编号越界检查：标题行/译文行不应含任何标注记号
        if line.startswith('#') or line.startswith('*'):
            hit = MARKER_RE.search(line)
            if hit:
                problems.append(f'编号越界：{n}.md 标题/译文行含标记「{hit.group(0)}」: {line[:40]}')

    # 3. 原文编号连续性（按阅读顺序，token 化提取）
    seq_in_text = MARKER_RE.findall(''.join(paragraphs))
    expected = [marker(i + 1) for i in range(len(seq_in_text))]
    if seq_in_text != expected:
        # 找出第一个不一致的位置
        first_break = -1
        for i, tok in enumerate(seq_in_text):
            if i >= len(expected) or tok != expected[i]:
                first_break = i
                break
        problems.append(
            f'原文编号不连续：共 {len(seq_in_text)} 个，'
            f'首次错位在第 {first_break + 1} 位'
            f'（应为 {expected[first_break] if first_break < len(expected) else "无"}, '
            f'实为 {seq_in_text[first_break] if first_break < len(seq_in_text) else "无"}）'
        )

    # 4 & 5. 注释表解析与对应
    notes_items = parse_notes_md(n)
    if notes_items is None:
        problems.append(f'无法解析 {n}.notes.md')
        return problems

    notes_markers = [m for m, _, _ in notes_items]
    # 注释表标记合法性 + 重复
    notes_illegal = [m for m in notes_markers if not MARKER_RE.fullmatch(m)]
    if notes_illegal:
        problems.append(f'注释表含非法标记: {notes_illegal[:5]}')
    # 注释表标记应连续 ①②③…〔51〕〔52〕…
    expected_notes = [marker(i + 1) for i in range(len(notes_markers))]
    if notes_markers != expected_notes:
        problems.append(
            f'注释表标记不连续：共 {len(notes_markers)} 个，'
            f'应为 {expected_notes[:3]}... 递增'
        )

    text_set = set(seq_in_text)
    notes_set = set(notes_markers)
    if text_set != notes_set:
        only_text = text_set - notes_set
        only_notes = notes_set - text_set
        if only_text:
            problems.append(f'标记只在原文出现、注释表缺失: {sorted(only_text)}')
        if only_notes:
            problems.append(f'标记只在注释表出现、原文缺失: {sorted(only_notes)}')

    if len(notes_items) != len(seq_in_text):
        problems.append(f'注释表 {len(notes_items)} 条 与 原文标记 {len(seq_in_text)} 个 数量不符')

    # 6. 序号-位置对应：注释表中 term 必须紧贴对应标记左侧
    # 构建 marker -> term 映射
    marker_to_term = {}
    for m, term, _ in notes_items:
        if m in marker_to_term:
            problems.append(f'注释表标记重复: {m}')
            continue
        marker_to_term[m] = term

    # 对原文中每个标记，取其左侧文本，检查是否以 term（去空白）结尾
    for pi, para in enumerate(paragraphs):
        for mt in MARKER_RE.finditer(para):
            term = marker_to_term.get(mt.group(0))
            if term is None:
                continue
            term_ws = ws_strip(term)
            # 取标记左侧所有非空白字符
            left = ws_strip(para[:mt.start()])
            if not left.endswith(term_ws):
                # 找出实际左侧结尾
                tail = left[-min(len(term_ws) + 5, len(left)):]
                problems.append(
                    f'序号-位置错乱：{n}.md 第 {pi + 1} 段标记 {mt.group(0)} '
                    f'左侧应为「{term}」（去空白 {term_ws}），'
                    f'实为「...{tail}」'
                )

    # 8. 导读结构与字数
    guide_path = OUTPUT_DIR / f'{n}.guide.md'
    guide_text = guide_path.read_text(encoding='utf-8')
    missing_sections = [s for s in GUIDE_SECTIONS if s not in guide_text]
    if missing_sections:
        problems.append(f'导读缺失章节: {missing_sections}')
    guide_body = guide_text.split('\n', 2)[-1] if '\n' in guide_text else guide_text
    glen = len(ws_strip(guide_body))
    if glen < 400:
        problems.append(f'导读字数偏短: {glen} 字')
    elif glen > 1500:
        # 按 skill 规定「1200 左右或略超均可接受」，仅作提示不计入阻断问题
        warnings.append(f'导读字数偏长: {glen} 字（skill 允许略超，仅提示）')

    return problems, warnings


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        print('用法: python3 verify_reading.py <start> <end>')
        return 2
    s, e = int(args[0]), int(args[1])
    ns = list(range(s, e + 1))

    print('=' * 60)
    print(f'verify_reading: 共 {len(ns)} 章 ({s}-{e})')
    print('=' * 60)

    total_ok = 0
    total_issues = 0
    total_warns = 0
    for n in ns:
        problems, warnings = verify_volume(n)
        if not problems:
            tag = '✓ 全部通过'
            if warnings:
                tag += f'（含 {len(warnings)} 条提示）'
            print(f'  [{n}] {tag}')
            for w in warnings:
                print(f'       · {w}')
            total_ok += 1
            total_warns += len(warnings)
        else:
            print(f'  [{n}] ✗ {len(problems)} 个问题:')
            for p in problems:
                print(f'       - {p}')
            for w in warnings:
                print(f'       · {w}')
            total_issues += len(problems)
            total_warns += len(warnings)

    print('=' * 60)
    print(f'汇总: {total_ok}/{len(ns)} 卷通过, 共 {total_issues} 个阻断问题, {total_warns} 条提示')
    return 0 if total_issues == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
