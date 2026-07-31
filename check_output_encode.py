#!/usr/bin/env python3
"""扫描 output/*.md 的特殊字符（PUA、控制字符、IDS 等）
基于 /Users/zhangwei/work/dazhuangyanlun/check_encode.py 的逻辑
"""
import os
import json
from collections import defaultdict

OUTPUT_DIR = '/Users/zhangwei/work/yoga/output'


def classify_char(ch):
    code = ord(ch)
    if 0xE000 <= code <= 0xF8FF:
        return "PUA(私有区-疑似CBETA缺字)"
    elif 0x20000 <= code <= 0x2A6DF:
        return "Unicode扩展区B"
    elif 0x2A700 <= code <= 0x2B73F:
        return "Unicode扩展区C"
    elif 0x2B740 <= code <= 0x2B81F:
        return "Unicode扩展区D"
    elif 0x2B820 <= code <= 0x2CEAF:
        return "Unicode扩展区E"
    elif 0x2CEB0 <= code <= 0x2EBEF:
        return "Unicode扩展区F"
    elif 0x30000 <= code <= 0x3134F:
        return "Unicode扩展区G"
    elif 0x31350 <= code <= 0x323AF:
        return "Unicode扩展区H"
    elif code >= 0x20000:
        return "Unicode扩展区(其他)"
    elif ch == "�":
        return "乱码替换符"
    elif code < 32 and ch not in ['\n', '\t', '\r']:
        return "不可见控制字符"
    elif 127 <= code <= 159:
        return "C1控制字符"
    elif '⿰' <= ch <= '⿿':
        return "组合字结构符(IDS)"
    elif ch == '　':
        return None  # 全角空格, 正常
    elif ch.isspace() and ch not in [' ', '\n', '\r', '\t']:
        return "其他空白字符"
    return None


def analyze_file(filepath, context_window=15):
    stats = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    for i, ch in enumerate(text):
        category = classify_char(ch)
        if category:
            hex_code = f"U+{ord(ch):04X}"
            key = f"{ch} ({hex_code})"
            if key not in stats:
                stats[key] = {
                    "char": ch,
                    "hex": hex_code,
                    "type": category,
                    "count": 0,
                    "occurrences": []
                }
            stats[key]["count"] += 1
            if len(stats[key]["occurrences"]) < 5:
                start = max(0, i - context_window)
                end = min(len(text), i + context_window + 1)
                snippet = text[start:end].replace("\n", "\\n").replace("\r", "\\r")
                # 找行号
                line_no = text[:i].count('\n') + 1
                stats[key]["occurrences"].append({
                    "line": line_no,
                    "context": snippet
                })
    return stats


def main():
    all_stats = {}
    file_stats_map = {}
    for n in range(1, 101):
        path = os.path.join(OUTPUT_DIR, f'{n}.md')
        if not os.path.exists(path):
            continue
        fs = analyze_file(path)
        if fs:
            file_stats_map[n] = fs
        for k, v in fs.items():
            if k in all_stats:
                all_stats[k]["count"] += v["count"]
                # 保留前 5 个出现位置
                remaining = 5 - len(all_stats[k]["occurrences"])
                if remaining > 0:
                    all_stats[k]["occurrences"].extend(v["occurrences"][:remaining])
            else:
                all_stats[k] = v

    print('=' * 70)
    print('特殊字符校对报告 - output/*.md')
    print('=' * 70)
    print()

    if not all_stats:
        print('✓ 未发现特殊字符，全部 100 章字符正常')
        return 0

    sorted_stats = dict(sorted(all_stats.items(), key=lambda x: (x[1]['type'], x[1]['hex'])))

    by_type = defaultdict(list)
    for k, v in sorted_stats.items():
        by_type[v["type"]].append((k, v))

    for typ, items in by_type.items():
        total = sum(v["count"] for _, v in items)
        print(f'## {typ} (共 {len(items)} 种字符, {total} 次)')
        print()
        for k, v in items:
            files_with = [n for n in range(1, 101) if n in file_stats_map and k in file_stats_map[n]]
            print(f'  {k} - 类型: {v["type"]}, 总计: {v["count"]} 次')
            print(f'    出现在 {len(files_with)} 章: {files_with[:20]}{"..." if len(files_with) > 20 else ""}')
            for occ in v["occurrences"][:3]:
                print(f'    行 {occ["line"]}: ...{occ["context"]}...')
            print()

    # 保存 JSON
    out_json = '/Users/zhangwei/work/yoga/output_encode_check.json'
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump({k: v for k, v in sorted_stats.items()}, f, ensure_ascii=False, indent=2)
    print(f'详细结果: {out_json}')
    return 0


if __name__ == '__main__':
    main()
