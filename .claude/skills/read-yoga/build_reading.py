#!/usr/bin/env python3
"""
build_reading.py - 由 notes_{N}.json 生成 output/{N}.guide.md（导读）与 output/{N}.notes.md（注释表），并把圈号标注写入 output/{N}.md 的原文。

LLM 已写好 notes_{N}.json：{"guide": "...", "terms": [{"term": "...", "note": "..."}, ...]}
本脚本做全部确定性工作（LLM 不做任何序号与定位）：
1. 解析 output/{N}.md → 标题 + 原文段（　　 开头，多行颂偈合并为一段）
2. 校验术语：每 term 必须出现在原文中、≤50 个、无重复、guide 非空
3. 按首次出现位置分配 ①-㊿（①-⑳=1-20、㉑-㉟=21-35、㊱-㊿=36-50，共 50 个圈号）；重叠冲突自动顺延；右向左插入
4. 圈号标注写回 output/{N}.md 原文（译文/标题/空行不动）；生成 notes.md（注释表）与 guide.md（导读）
5. 校验：字符流完整性（标注后-圈号-空白 == 原文-空白）、圈号连续性、注释表与标注一一对应

用法：
    python3 build_reading.py <N>            # 单章
    python3 build_reading.py <s> <e>        # 区间
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

OUTPUT_DIR = Path('output')

# 圈号 1-50（①-⑳=1-20, ㉑-㉟=21-35, ㊱-㊿=36-50）
CIRCLED = ('①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
           '㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚'
           '㉛㉜㉝㉞㉟'
           '㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿')
CIRCLED_SET = set(CIRCLED)
MAX_TERMS = len(CIRCLED)  # 50


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
            # 剥离旧圈号（幂等：重跑时先清除上一轮标注）
            line = ''.join(ch for ch in line if ch not in CIRCLED_SET)
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


def ws_strip(s: str) -> str:
    return ''.join(ch for ch in s if not ch.isspace())


def all_occurrences(paragraphs: list[str], term: str):
    """返回所有出现位置 [(pi, start_char, end_char)]，按阅读顺序排序。"""
    t = ws_strip(term)
    if not t:
        return []
    res = []
    for pi, para in enumerate(paragraphs):
        nonws = [i for i, ch in enumerate(para) if not ch.isspace()]
        if len(nonws) < len(t):
            continue
        stream = ''.join(para[i] for i in nonws)
        start = 0
        while True:
            li = stream.find(t, start)
            if li == -1:
                break
            if li + len(t) <= len(nonws):
                res.append((pi, nonws[li], nonws[li + len(t) - 1]))
            start = li + 1
    return res


def assign(paragraphs: list[str], terms_notes: list[tuple[str, str]]):
    """贪心分配出现位：先出现的（同位置时较长者优先）先占位，重叠自动顺延。

    返回 (assigned, dropped)。assigned 按阅读顺序排序，含 marker。
    dropped: 找不到独立出现位而被丢弃的术语。
    """
    occs = []
    for term, note in terms_notes:
        occ = all_occurrences(paragraphs, term)
        if occ:
            occs.append({'term': term, 'note': note, 'occ': occ})
    occs.sort(key=lambda o: (o['occ'][0][0], o['occ'][0][1], -len(o['term'])))

    used = {}
    assigned = []
    dropped = []
    for o in occs:
        chosen = None
        for pi, s, e in o['occ']:
            spans = used.get(pi, [])
            if all(e < s2 or s > e2 for (s2, e2) in spans):
                chosen = (pi, s, e)
                break
        if chosen is None:
            dropped.append(o['term'])
            continue
        pi, s, e = chosen
        used.setdefault(pi, []).append((s, e))
        assigned.append({'pi': pi, 's': s, 'e': e,
                         'term': o['term'], 'note': o['note']})
    assigned.sort(key=lambda a: (a['pi'], a['s']))
    for i, a in enumerate(assigned):
        a['marker'] = CIRCLED[i]
    return assigned, dropped


def insert_markers(paragraphs: list[str], assigned: list[dict]) -> list[str]:
    marked = [list(p) for p in paragraphs]
    by_pi = {}
    for a in assigned:
        by_pi.setdefault(a['pi'], []).append(a)
    for pi, items in by_pi.items():
        for it in sorted(items, key=lambda x: x['e'], reverse=True):
            marked[pi].insert(it['e'] + 1, it['marker'])
    return [''.join(m) for m in marked]


def verify(original: list[str], marked: list[str], assigned: list[dict]) -> list[str]:
    """返回问题列表（空 = 全部通过）。"""
    problems = []

    def collapse(paras, drop_circled):
        s = ''.join(paras)
        if drop_circled:
            return ''.join(ch for ch in s if not ch.isspace() and ch not in CIRCLED_SET)
        return ''.join(ch for ch in s if not ch.isspace())

    if collapse(marked, True) != collapse(original, False):
        problems.append('字符流校验失败：标注后文本与原文不一致')

    seq = [ch for ch in ''.join(marked) if ch in CIRCLED_SET]
    expect = list(CIRCLED[:len(assigned)])
    if seq != expect:
        problems.append(f'圈号顺序不连续：正文出现 {len(seq)} 个，'
                        f'应为 {len(expect)} 个且递增无跳号')

    if len(assigned) != len(seq):
        problems.append(f'注释表 {len(assigned)} 条 与 正文标注 {len(seq)} 个 不一致')

    return problems


def build_notes_md(title: str, assigned: list[dict]) -> str:
    out = [f'# {title} 词语注释', '']
    for a in assigned:
        out.append(f'{a["marker"]} {a["term"]}　{a["note"]}')
    out.append('')
    return '\n'.join(out)


def rewrite_md(n: int, marked: list[str]) -> bool:
    """把带圈号的原文段写回 output/{N}.md，译文/标题/空行原样保留。

    逐行扫描，遇到连续的 　　 行（一个原文段）用 marked 中对应段替换。
    返回 False 表示段落数与原文不匹配（不应发生，防御）。
    """
    path = OUTPUT_DIR / f'{n}.md'
    lines = path.read_text(encoding='utf-8').split('\n')
    out = []
    q = [m.split('\n') for m in marked]
    qi = 0
    cur = None
    for line in lines:
        if line.startswith('　　'):
            if cur is None:
                if qi >= len(q):
                    return False
                cur = q[qi]
                qi += 1
            if not cur:
                return False
            out.append(cur.pop(0))
            if not cur:
                cur = None
        else:
            cur = None
            out.append(line)
    if qi != len(q):
        return False
    path.write_text('\n'.join(out), encoding='utf-8')
    return True


def build_guide_md(title: str, guide: str) -> str:
    head = f'# {title} 导读\n'
    return head + '\n' + guide.rstrip() + '\n'


def load_notes(n: int):
    """加载 notes_{N}.json，返回 (guide, terms_notes, errors)。"""
    path = OUTPUT_DIR / f'notes_{n}.json'
    if not path.exists():
        return '', [], [f'缺少 notes_{n}.json']
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        return '', [], [f'notes_{n}.json 解析失败: {e}']

    errors = []
    guide = data.get('guide') if isinstance(data, dict) else ''
    if not guide or not guide.strip():
        errors.append('guide 为空或缺失')

    raw_terms = data.get('terms') if isinstance(data, dict) else None
    if not isinstance(raw_terms, list) or not raw_terms:
        errors.append('terms 为空或缺失')
        return guide, [], errors

    terms_notes = []
    seen = set()
    for t in raw_terms:
        if not isinstance(t, dict) or not t.get('term') or not t.get('note'):
            errors.append(f'术语条目格式错误: {t}')
            continue
        term, note = t['term'].strip(), t['note'].strip()
        key = ws_strip(term)
        if not key:
            errors.append(f'术语为空白: {t!r}')
            continue
        if key in seen:
            errors.append(f'重复术语: {term}')
            continue
        seen.add(key)
        terms_notes.append((term, note))

    if len(terms_notes) > MAX_TERMS:
        errors.append(f'术语 {len(terms_notes)} 个超过上限 {MAX_TERMS}，请精简')
    return guide, terms_notes, errors


def build_file(n: int):
    parsed = parse_md(n)
    if parsed is None:
        return 1
    title, _, paragraphs = parsed

    guide, terms_notes, errors = load_notes(n)
    if errors:
        for e in errors:
            print(f'  [{n}] ✗ {e}')
        return 1
    guide = guide or ''
    terms_notes = terms_notes or []

    # 术语必须在原文中出现
    missing = [term for term, _ in terms_notes if not all_occurrences(paragraphs, term)]
    if missing:
        for term in missing:
            print(f'  [{n}] ✗ 术语未在原文中找到: 「{term}」')
        print(f'  [{n}] 请在 notes_{n}.json 中改为原文精确子串后重跑 build')
        return 1

    assigned, dropped = assign(paragraphs, terms_notes)
    if dropped:
        for term in dropped:
            print(f'  [{n}] ⚠ 术语被丢弃（与已标注术语重叠且无独立出现位）: 「{term}」')

    marked = insert_markers(paragraphs, assigned)
    problems = verify(paragraphs, marked, assigned)
    if problems:
        for p in problems:
            print(f'  [{n}] ✗ {p}')
        return 1

    if not rewrite_md(n, marked):
        print(f'  [{n}] ✗ 重写 output/{n}.md 失败：原文段落数不匹配')
        return 1
    (OUTPUT_DIR / f'{n}.notes.md').write_text(
        build_notes_md(title, assigned), encoding='utf-8')
    (OUTPUT_DIR / f'{n}.guide.md').write_text(
        build_guide_md(title, guide), encoding='utf-8')

    glen = len(ws_strip(guide))
    # 字数策略：400-1500 均可接受（1200 左右或略超不提示）；
    # 仅 <400（偏短）或 >1500（异常偏长）时以 ⚠ 提示。
    flag = '' if 400 <= glen <= 1500 else \
        ' ⚠ 导读 ' + str(glen) + ' 字，建议 400-1200'
    print(f'  [{n}] ✓ {title}: 术语={len(assigned)}, '
          f'圈号={len(assigned)}, 导读={glen} 字{flag}')
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        print('用法: python3 build_reading.py <N> | <s> <e>')
        return 2
    if len(args) == 2:
        s, e = int(args[0]), int(args[1])
        ns = list(range(s, e + 1))
    else:
        ns = [int(a) for a in args]

    print('=' * 60)
    print(f'build_reading: 共 {len(ns)} 章')
    print('=' * 60)
    code = 0
    for n in ns:
        code |= build_file(n)
    return code


if __name__ == '__main__':
    sys.exit(main())
