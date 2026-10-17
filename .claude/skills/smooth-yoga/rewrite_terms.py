#!/usr/bin/env python3
"""
rewrite_terms.py — 对 output/{start}..{end}.md 的**译文块**执行术语统一整改替换。

- 只替换译文（"> " 开头的译文块），原文（　　 开头）一律不动
- PROTECT 中的固定术语先占位保护，替换后还原
- REPLACE 按序应用（长词在前，避免误伤）
- GLOSS 在每个文件内仅对首次出现加括注释义

用法：python3 rewrite_terms.py <start> <end>
"""

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fix-yoga'))
from apply_fix import locate_paragraph_block  # noqa: E402

# 固定术语，保护不替换
PROTECT = ['现法涅槃', '顺现法受业', '现法受业']

# 统一替换表（顺序敏感：长词/搭配在前）
REPLACE = [
    ('俱相违（与可意、不可意二者都相违）', '与可意、不可意二者都相违'),
    ('舍处所的触（非好非恶的触）', '非好非恶的触'),
    ('不避不平等故死', '因不避开种种不适宜的因素而死'),
    ('不避不平等力', '不避开种种不适宜因素之力'),
    ('增上适悦心', '增上的舒适愉悦之心'),
    ('适悦资具', '舒适愉悦的资具'),
    ('适悦感受', '舒适愉悦的感受'),
    ('有见有对色', '可见而有质碍的色'),
    ('无见无对色', '不可见而无质碍的色'),
    ('任运现行', '自然而然地现行'),
    ('任运而灭', '自然而然地灭'),
    ('任运分别', '任运分别（自然而然生起的分别）'),
    ('不避不平等', '不避开种种不适宜的因素'),
    ('无见有对', '不可见而有质碍'),
    ('有见有对', '可见而有质碍'),
    ('无见无对', '不可见而无质碍'),
    ('俱相违', '与两者都相违'),
    ('平等香', '非好非恶的香'),
    ('适悦', '舒适愉悦'),
    ('现法', '现世'),
]

# 每个文件首次出现时加括注释义，其后出现保持原词
GLOSS = [
    ('空一显色', '空一显色（虚空中唯一显现的青色）'),
    ('粗重', '粗重（使身心粗钝沉重的习性）'),
    ('乐着戏论', '乐着戏论（贪爱耽着种种概念言辞）'),
]

PH_L, PH_R = '\x00', '\x01'


def main():
    if len(sys.argv) < 3:
        print("Usage: python rewrite_terms.py <start> <end>", file=sys.stderr)
        sys.exit(1)
    start, end = int(sys.argv[1]), int(sys.argv[2])

    total = 0
    for n in range(start, end + 1):
        path = f'output/{n}.md'
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            lines = f.read().split('\n')

        # 收集全部译文块的行号
        trans_line_idx = []
        para = 1
        while True:
            result = locate_paragraph_block(lines, para)
            if result is None:
                break
            _, _, ts, te = result
            if ts != -1:
                trans_line_idx.extend(range(ts, te + 1))
            para += 1
        if not trans_line_idx:
            continue

        counts = {}
        glossed = set()
        for i in trans_line_idx:
            line = lines[i]
            for p in PROTECT:
                line = line.replace(p, PH_L + p + PH_R)
            for old, new in REPLACE:
                c = line.count(old)
                if c:
                    line = line.replace(old, new)
                    counts[old] = counts.get(old, 0) + c
            for term, glossed_form in GLOSS:
                if term in glossed:
                    continue
                if term in line:
                    line = line.replace(term, glossed_form, 1)
                    glossed.add(term)
                    counts[term + '（加注）'] = counts.get(term + '（加注）', 0) + 1
            for p in PROTECT:
                line = line.replace(PH_L + p + PH_R, p)
            lines[i] = line

        file_total = sum(counts.values())
        total += file_total
        if file_total:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            detail = '，'.join(f'{k}×{v}' for k, v in sorted(counts.items(), key=lambda x: -x[1]))
            print(f'output/{n}.md: {file_total} 处替换 → {detail}')
        else:
            print(f'output/{n}.md: 无匹配')
    print(f'Total: {total} replacements')


if __name__ == '__main__':
    main()
