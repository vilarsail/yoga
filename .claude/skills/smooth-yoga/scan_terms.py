#!/usr/bin/env python3
"""
scan_terms.py — 扫描 output/{start}..{end}.md 中的「义理复合术语盲点」。

原理：盲点术语（如"无见有对""俱相违"）的特征是——在古文原文和译文中**逐字共现**。
本脚本对每个段对提取原文与译文的公共子串（3~10 字），剔除标点/数字/清单内
专有名词后，按语料频率聚合并输出上下文样本，供人工甄别出需要白话化的术语。

仅输出候选表，不做任何替换。替换由 rewrite_terms.py 按 term_map 执行。

用法：python3 scan_terms.py <start> <end> [--min-count N] [--top M]
输出：terms_scan.json（候选表）+ 控制台摘要
"""

import json, sys, os, re
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'check-yoga'))
from prepare_check import extract_pairs  # noqa: E402

# 保留清单内术语与常见无嫌疑片段，不作为候选
PROTECTED = {
    '阿赖耶识', '阿赖耶', '三摩呬多地', '三摩呬多', '补特伽罗', '那落迦', '那洛迦',
    '嗢拖南', '萨迦耶见', '萨迦耶', '奢摩他', '毗钵舍那', '等无间依', '等无间缘',
    '俱有依', '种子依', '羯罗蓝', '健达缚', '预流果', '一来果', '不还果', '薄伽梵',
    '三摩地', '三摩钵底', '中有', '末尼', '踰缮那', '由旬', '拘卢舍',
}
# 明显不属于术语的高频共现（连接语/套语经白话化后残留的部分匹配等）
STOP = {
    '是什么', '什么叫', '怎样的', '应当知道', '应当了知', '是这样', '也是如此',
    '如此这般', '所谓', '即是说',
}

MIN_LEN = 3
MAX_LEN = 10


def split_segments(text: str) -> list[str]:
    for ch in '。，、；：？！「」『』（）>…—\n 　　0123456789０１２３４５６７８９⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕':
        text = text.replace(ch, ' ')
    return [s for s in text.split(' ') if len(s) >= MIN_LEN]


def common_substrings(orig: str, trans: str) -> set[str]:
    """原文片段（按标点切段后）的所有 3~10 字子串中，出现在译文里的。"""
    t = trans
    found = set()
    for seg in split_segments(orig):
        L = len(seg)
        for w in range(MIN_LEN, min(MAX_LEN, L) + 1):
            for i in range(0, L - w + 1):
                s = seg[i:i + w]
                if s in STOP or s in PROTECTED:
                    continue
                if s in t:
                    found.add(s)
    return found


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 2:
        print("Usage: python scan_terms.py <start> <end> [--min-count N] [--top M]", file=sys.stderr)
        sys.exit(1)
    start, end = int(args[0]), int(args[1])
    min_count = 3
    top = 120
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == '--min-count' and i + 1 < len(argv):
            min_count = int(argv[i + 1])
        elif a.startswith('--min-count='):
            min_count = int(a.split('=')[1])
        elif a == '--top' and i + 1 < len(argv):
            top = int(argv[i + 1])
        elif a.startswith('--top='):
            top = int(a.split('=')[1])

    freq = Counter()          # substring -> 段落出现次数
    examples = {}             # substring -> [file, para, trans片段]
    for n in range(start, end + 1):
        path = f'output/{n}.md'
        if not os.path.exists(path):
            continue
        pairs = extract_pairs(path)
        for k, v in pairs.items():
            if not v['trans']:
                continue
            for s in common_substrings(v['orig'], v['trans']):
                # 剔除含标点/数字的
                if re.search(r'[，。、；：？！（）「」>0-9]', s):
                    continue
                freq[s] += 1
                if s not in examples or len(examples[s]) < 2:
                    idx = v['trans'].find(s)
                    ctx = v['trans'][max(0, idx - 15): idx + len(s) + 15]
                    examples.setdefault(s, []).append(
                        {'file': n, 'para': k, 'ctx': ctx.replace('\n', ' ')}
                    )

    # 剔除是更长候选子串的子串（保留最大匹配）
    candidates = [s for s, c in freq.items() if c >= min_count]
    maximal = []
    for s in candidates:
        if any(s != o and s in o for o in candidates):
            continue
        maximal.append(s)
    maximal.sort(key=lambda s: (-freq[s], -len(s)))

    out = [
        {'term': s, 'count': freq[s], 'examples': examples.get(s, [])}
        for s in maximal[:top]
    ]
    with open('terms_scan.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f'Scanned output/{start}.md ~ output/{end}.md: {len(freq)} distinct common substrings, '
          f'{len(maximal)} maximal candidates (count>={min_count}), top {min(top, len(maximal))} → terms_scan.json')
    for item in out[:40]:
        ex = item['examples'][0]
        print(f"  {item['term']}  ×{item['count']}  e.g. file{ex['file']}¶{ex['para']}：…{ex['ctx']}…")


if __name__ == '__main__':
    main()
