#!/usr/bin/env python3
"""
build_report.py — 合并各批校对 issues，生成 output/{N}.check.md 质量报告。

读取 pairs_{N}.json（段对）与 issues_{N}_batch*.json（各批问题），
按段落号排序输出问题明细与分类汇总。
"""

from __future__ import annotations
import json, sys, os, glob, re
from datetime import datetime

TYPE_LABEL = {
    'MISSING': '译文缺失',
    'NEAR-COPY': '近似未翻译',
    'VERSE-NOT-TRANSLATED': '颂偈未译',
    'FORMAT': '格式问题',
    'ERROR': '翻译错误',
    'OTHER': '其它质量',
}

TYPE_ORDER = ['NEAR-COPY', 'VERSE-NOT-TRANSLATED', 'MISSING', 'ERROR', 'FORMAT', 'OTHER']


def load_issues_json(path: str) -> dict | None:
    """读取 issues 批次 JSON，失败时尝试自动修复。

    LLM 生成的 JSON 可能因值内含 ASCII 双引号/换行未转义而解析失败。
    修复策略：按段落号键边界切分，逐行提取字段——
      - type：值不含引号，用严格正则
      - problem / suggestion：值可能内含 ASCII 双引号，取行首引号后到行尾的内容（去掉末尾 `",`）
    """
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    try:
        with open(path, encoding='utf-8') as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    # 去掉外层花括号
    raw = content.strip()
    if raw.startswith('{'):
        raw = raw[1:]
    if raw.endswith('}'):
        raw = raw[:-1]
    raw = raw.strip()

    # 按 "\d+": 键边界切分（每个段落一个块）
    entries = re.split(r'\n\s*(?="\d+":)', raw)
    result = {}
    for entry in entries:
        entry = entry.strip().rstrip(',')
        if not entry:
            continue
        m = re.match(r'"(\d+)":\s*', entry)
        if not m:
            continue
        key = m.group(1)
        obj_raw = entry[m.end():].strip()
        fields = {}

        # 逐行扫描字段（LLM 用 indent 输出时字段各占一行；值内含 ASCII 引号时容忍）
        for line in obj_raw.split('\n'):
            line = line.strip()
            if line.startswith('"type"'):
                tm = re.search(r'"type"\s*:\s*"([^"]*)"', line)
                if tm:
                    fields['type'] = tm.group(1)
            elif line.startswith('"problem"'):
                # 贪婪 (.*) 回溯到最后一个 "，容忍值内含 ASCII 引号；末尾 ", 被外层匹配
                fm = re.match(r'"problem"\s*:\s*"(.*)"\s*,?\s*$', line)
                if fm:
                    fields['problem'] = fm.group(1).replace('\\"', '"').replace('\\\\', '\\')
            elif line.startswith('"suggestion"'):
                fm = re.match(r'"suggestion"\s*:\s*"(.*)"\s*,?\s*$', line)
                if fm:
                    fields['suggestion'] = fm.group(1).replace('\\"', '"').replace('\\\\', '\\')

        if fields:
            result[key] = fields

    if result:
        print(f'  [repair] {os.path.basename(path)}: JSON 损坏，已自动修复 {len(result)} 条')
        return result
    print(f'  [WARN] {os.path.basename(path)}: 无法解析，跳过此批次')
    return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python build_report.py <N>", file=sys.stderr)
        sys.exit(1)
    n = int(sys.argv[1])

    if not os.path.exists(f'pairs_{n}.json'):
        print(f"Error: pairs_{n}.json not found. Run prepare_check.py first.", file=sys.stderr)
        sys.exit(1)

    pairs = json.load(open(f'pairs_{n}.json', encoding='utf-8'))

    # 合并各批 issues（扫描所有存在的批次文件），带 JSON 校验+修复，过滤 _ 前缀键
    issues = {}
    for path in sorted(glob.glob(f'issues_{n}_batch*.json')):
        batch = load_issues_json(path)
        if batch is None:
            continue
        for key, value in batch.items():
            if key.startswith('_'):
                continue
            issues[key] = value

    # 按段落号排序
    def sort_key(k):
        try:
            return int(k)
        except ValueError:
            return 10 ** 9

    ordered = sorted(issues.keys(), key=sort_key)

    total = len(pairs)
    problem = len(ordered)
    pct = 100.0 * problem / total if total else 0

    # 分类统计
    by_type = {t: 0 for t in TYPE_LABEL}
    for k in ordered:
        t = issues[k].get('type', 'OTHER')
        by_type.setdefault(t, 0)
        by_type[t] += 1

    lines = []
    lines.append(f'# output/{n}.md 译文校对报告')
    lines.append('')
    lines.append(f'- 段落总数：{total}')
    lines.append(f'- 问题段落数：{problem}（占 {pct:.1f}%）')
    lines.append(f'- 校对时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append('')

    if problem == 0:
        lines.append('✅ 未发现译文质量问题，本文件无需修改。')
    else:
        lines.append('## 问题列表')
        lines.append('')
        for k in ordered:
            issue = issues[k]
            t = issue.get('type', 'OTHER')
            label = TYPE_LABEL.get(t, '其它质量')
            lines.append(f'### 段落 {k} 【{label}】')
            lines.append('')
            pair = pairs.get(k, {})
            orig = pair.get('orig', '')
            trans = pair.get('trans', '')
            if orig:
                lines.append(f'- **原文**：{orig}')
            if trans:
                lines.append(f'- **译文**：{trans}')
            elif t == 'MISSING':
                lines.append('- **译文**：（无）')
            lines.append(f'- **问题**：{issue.get("problem", "")}')
            if issue.get('suggestion'):
                lines.append(f'- **修改建议**：{issue["suggestion"]}')
            lines.append('')

        lines.append('## 汇总')
        lines.append('')
        for t in TYPE_ORDER:
            lines.append(f'- {TYPE_LABEL[t]}（{t}）：{by_type.get(t, 0)} 段')

    out_path = f'output/{n}.check.md'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    print(f'Generated {out_path}: {problem}/{total} paragraphs with issues')
    if problem:
        for t in TYPE_ORDER:
            print(f'  {TYPE_LABEL[t]}: {by_type.get(t, 0)}')


if __name__ == '__main__':
    main()
