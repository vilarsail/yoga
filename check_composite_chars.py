#!/usr/bin/env python3
"""补充扫描：CBETA 组合字标记 [部件+部件] 和其他标记字符"""
import os
import re
from collections import defaultdict

OUTPUT_DIR = '/Users/zhangwei/work/yoga/output'

# CBETA 组合字标记模式：[汉字/部件+-+部件+...] 形式
# 例如 [竺-二+韋], [月*逄], [一/(哭-、)] 等
COMPOSITE_PATTERN = re.compile(r'\[[^\[\]]{1,20}\]')


def scan_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    results = []
    for m in COMPOSITE_PATTERN.finditer(text):
        # 找行号
        line_no = text[:m.start()].count('\n') + 1
        # 取上下文
        start = max(0, m.start() - 10)
        end = min(len(text), m.end() + 10)
        context = text[start:end].replace('\n', '\\n')
        results.append({
            'match': m.group(),
            'line': line_no,
            'context': context
        })
    return results


def main():
    all_matches = {}  # match_text -> {count, files, occurrences}
    for n in range(1, 101):
        path = os.path.join(OUTPUT_DIR, f'{n}.md')
        if not os.path.exists(path):
            continue
        matches = scan_file(path)
        for m in matches:
            key = m['match']
            if key not in all_matches:
                all_matches[key] = {'count': 0, 'files': set(), 'occurrences': []}
            all_matches[key]['count'] += 1
            all_matches[key]['files'].add(n)
            if len(all_matches[key]['occurrences']) < 3:
                all_matches[key]['occurrences'].append((n, m['line'], m['context']))

    print('=' * 70)
    print('CBETA 组合字标记扫描 - output/*.md')
    print('=' * 70)
    print()

    if not all_matches:
        print('✓ 未发现 CBETA 组合字标记')
        return 0

    # 按出现次数排序
    sorted_items = sorted(all_matches.items(), key=lambda x: -x[1]['count'])
    total = sum(v['count'] for _, v in sorted_items)
    print(f'共发现 {len(sorted_items)} 种组合字标记，总计 {total} 次')
    print()
    for match, info in sorted_items:
        print(f'  {match} - {info["count"]} 次, {len(info["files"])} 章')
        for ch, line, ctx in info['occurrences'][:2]:
            print(f'    ch{ch} 行{line}: ...{ctx}...')
        print()

    return 0


if __name__ == '__main__':
    main()
