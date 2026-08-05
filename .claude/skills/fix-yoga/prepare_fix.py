#!/usr/bin/env python3
"""
prepare_fix.py - 修复前置：从 output/{N}.check.md 解析问题列表，从 output/{N}.md
提取「原文段 -> 译文段」对，合并为 fix_{N}_pairs.json，并按批切块生成
fix_{N}_batch*.json，供子 Agent 逐条判断「修改意见是否成立」。

仅做机械工作（解析 + 提取 + 切块），不做任何质量判断。
判断与改写全部由 LLM 子 Agent 完成。
"""

from __future__ import annotations
import json, sys, os, re

BATCH = 10  # 每批问题数。修复判断需逐条对照原文/译文/建议改写，认知负荷高，取 10


def extract_pairs(filepath: str) -> dict[str, dict]:
    """从 output/{N}.md 提取 原文段->译文段 对。
    与 prepare_check.py 完全相同的逻辑：原文段以 　　 开头（可多行颂偈），译文段以 * 开头（可多行）。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    pairs = {}
    idx = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip('\n')
        if line.startswith('　　'):
            orig_lines = [line]
            i += 1
            while i < n and lines[i].startswith('　　'):
                orig_lines.append(lines[i].rstrip('\n'))
                i += 1
            while i < n and lines[i].strip() == '':
                i += 1
            trans_lines = []
            while i < n:
                line = lines[i]
                if line.startswith('*'):
                    trans_lines.append(line.rstrip('\n'))
                    i += 1
                elif line.startswith('　　') or line.lstrip().startswith('#'):
                    break
                elif line.strip() == '':
                    j = i
                    while j < n and lines[j].strip() == '':
                        j += 1
                    if j < n and lines[j].startswith('*'):
                        i = j
                    else:
                        break
                else:
                    trans_lines.append(line.rstrip('\n'))
                    i += 1
            idx += 1
            pairs[str(idx)] = {
                'orig': '\n'.join(orig_lines),
                'trans': '\n'.join(trans_lines) if trans_lines else '',
            }
        else:
            i += 1
    return pairs


def parse_check_md(path: str) -> dict[str, dict]:
    """解析 output/{N}.check.md，提取问题列表。

    格式：
      ### 段落 {N} 【{label}】
      - **原文**：...
      - **译文**：...
      - **问题**：...
      - **修改建议**：...

    返回 {"段落号": {"type": ..., "problem": ..., "suggestion": ..., "orig": ..., "trans": ...}}
    """
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    TYPE_REVERSE = {
        '译文缺失': 'MISSING',
        '近似未翻译': 'NEAR-COPY',
        '颂偈未译': 'VERSE-NOT-TRANSLATED',
        '格式问题': 'FORMAT',
        '翻译错误': 'ERROR',
        '其它质量': 'OTHER',
    }

    issues = {}
    # 按段落标题切分
    sections = re.split(r'\n### 段落\s+', content)
    for sec in sections[1:]:
        # 段落号 + 类型
        m = re.match(r'(\d+)\s*【([^】]+)】', sec)
        if not m:
            continue
        para = m.group(1)
        label = m.group(2).strip()
        type_code = TYPE_REVERSE.get(label, 'OTHER')

        # 提取字段（多行值容忍：值可跨多行直到下一个 "- **字段**："或下一个标题）
        body = sec[m.end():]
        fields = {}
        # 用正则匹配 "- **字段**：内容" 形式；内容为字段名到下一个 "- **X**："或下一个标题（##/###）或末尾
        # 终止条件包含 \n## 以避免最后一段的 suggestion 吞掉整个 ## 汇总 区块
        # 仅提取 问题/修改建议；原文/译文从 .md 文件提取（更可靠）
        for field in ('问题', '修改建议'):
            pm = re.search(rf'- \*\*{field}\*\*[：:]\s*(.*?)(?=\n- \*\*(?:原文|译文|问题|修改建议)\*\*|\n##|\Z)',
                           body, flags=re.DOTALL)
            if pm:
                value = pm.group(1).rstrip()
                fields[field] = value
        issues[para] = {
            'type': type_code,
            'problem': fields.get('问题', '').strip(),
            'suggestion': fields.get('修改建议', '').strip(),
        }
    return issues


def build_batches(pairs: dict[str, dict], issues: dict[str, dict]) -> list[dict]:
    """按每批 BATCH 个问题切块，每条注入完整上下文（原文 + 当前译文 + 问题 + 建议 + 前后段原文）。"""
    keys = sorted(issues.keys(), key=lambda k: int(k) if k.isdigit() else 10**9)
    batches = []
    total = len(keys)
    for start in range(0, total, BATCH):
        end = min(start + BATCH, total)
        batch_keys = keys[start:end]
        items = {}
        for k in batch_keys:
            issue = issues[k]
            pair = pairs.get(k, {})
            # 前后段原文作为语义参考（仅供判断时上下文用）
            ctx = {}
            try:
                k_int = int(k)
                if str(k_int - 1) in pairs:
                    ctx['prev_orig'] = pairs[str(k_int - 1)]['orig']
                if str(k_int + 1) in pairs:
                    ctx['next_orig'] = pairs[str(k_int + 1)]['orig']
            except ValueError:
                pass
            items[k] = {
                'type': issue['type'],
                'problem': issue['problem'],
                'suggestion': issue['suggestion'],
                'orig': pair.get('orig', ''),
                'trans': pair.get('trans', ''),
                'context': ctx,
            }
        batches.append({
            '_batch_info': {
                'start': batch_keys[0] if batch_keys else '',
                'end': batch_keys[-1] if batch_keys else '',
                'count': len(batch_keys),
                'total': total,
            },
            'issues': items,
        })
    return batches


def main():
    if len(sys.argv) < 2:
        print("Usage: python prepare_fix.py <N>", file=sys.stderr)
        sys.exit(1)
    n = int(sys.argv[1])
    check_path = f'output/{n}.check.md'
    md_path = f'output/{n}.md'

    if not os.path.exists(check_path):
        print(f"Error: {check_path} not found. Run check-yoga first.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(md_path):
        print(f"Error: {md_path} not found.", file=sys.stderr)
        sys.exit(1)

    pairs = extract_pairs(md_path)
    issues = parse_check_md(check_path)

    if not issues:
        # 完全没有问题，写空 pairs 文件供后续脚本识别
        with open(f'fix_{n}_pairs.json', 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
        print(f"No issues in {check_path}. Nothing to fix.")
        return

    # 合并 pairs + issues -> fix_{N}_pairs.json
    merged = {}
    for k, issue in issues.items():
        pair = pairs.get(k, {})
        merged[k] = {
            'type': issue['type'],
            'problem': issue['problem'],
            'suggestion': issue['suggestion'],
            'orig': pair.get('orig', ''),
            'trans': pair.get('trans', ''),
        }
    with open(f'fix_{n}_pairs.json', 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    batches = build_batches(pairs, issues)
    for b, batch in enumerate(batches, 1):
        with open(f'fix_{n}_batch{b}.json', 'w', encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False, indent=2)

    print(f"Parsed {len(issues)} issues from {check_path}")
    print(f"Extracted {len(pairs)} paragraph pairs from {md_path}")
    print(f"Generated {len(batches)} batches -> fix_{n}_batch*.json")
    for b, batch in enumerate(batches, 1):
        info = batch['_batch_info']
        print(f"  Batch {b}: paragraphs {info['start']}-{info['end']} ({info['count']} issues)")


if __name__ == '__main__':
    main()
