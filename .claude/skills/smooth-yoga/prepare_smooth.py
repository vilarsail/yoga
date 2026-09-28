#!/usr/bin/env python3
"""
prepare_smooth.py — 明晰化前置：从 output/{N}.md 提取「原文段 → 译文段」对，生成批次 chunk 文件。

仅做机械工作（段对提取、分批切块），不做任何判定。
判定与改写全部由 LLM 子 Agent 读取 chunk 全量信息后完成。

输出：
- smooth_{N}_pairs.json：所有段对 {"1": {"orig": "...", "trans": "..."}, ...}
- smooth_{N}_batch{b}.json：每批最多 BATCH 个段对，含前 2 段上下文
"""

import json, sys, os

# 复用 check-yoga 的段对提取与分批逻辑（同一套段落定义，保证段落号体系一致）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'check-yoga'))
from prepare_check import extract_pairs, build_batches  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("Usage: python prepare_smooth.py <N>", file=sys.stderr)
        sys.exit(1)
    n = int(sys.argv[1])
    src = f'output/{n}.md'
    if not os.path.exists(src):
        print(f"Error: {src} not found", file=sys.stderr)
        sys.exit(1)

    pairs = extract_pairs(src)
    with open(f'smooth_{n}_pairs.json', 'w', encoding='utf-8') as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)

    batches = build_batches(pairs)
    for b, batch in enumerate(batches, 1):
        with open(f'smooth_{n}_batch{b}.json', 'w', encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False, indent=2)

    print(f"Extracted {len(pairs)} pairs from {src} → smooth_{n}_pairs.json, {len(batches)} batches")
    for b, batch in enumerate(batches, 1):
        info = batch['_batch_info']
        print(f"  Batch {b}: paragraphs {info['start']}-{info['end']} ({info['count']} pairs)")


if __name__ == '__main__':
    main()
