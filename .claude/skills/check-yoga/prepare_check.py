#!/usr/bin/env python3
"""
prepare_check.py — 校对前置：从 output/{N}.md 提取「原文段 → 译文段」对，生成批次 chunk 文件。

仅做机械工作（段对提取、分批切块），不做任何质量判断。
质量判断全部由 LLM 在读取 chunk 全量信息后完成。

输出：
- pairs_{N}.json：所有段对 {"1": {"orig": "...", "trans": "..."}, ...}
- check_{N}_batch{b}.json：每批最多 BATCH 个段对，含前 2 段上下文，供子 Agent 逐段判断
"""

import json, sys, os

BATCH = 20  # 每批段对数（含上下文）。校对需逐段对比原文与译文，认知负荷高，与翻译 skill 对齐取 20

def extract_pairs(filepath: str) -> dict[str, dict]:
    """从交替结构 output/{N}.md 提取 原文段→译文段 对。
    原文段以 　　 开头（可多行颂偈），译文段以 * 开头（可多行）。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    pairs = {}
    idx = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip('\n')
        if line.startswith('　　'):
            # 收集原文段（连续 　　 开头的行，含多行颂偈）
            orig_lines = [line]
            i += 1
            while i < n and lines[i].startswith('　　'):
                orig_lines.append(lines[i].rstrip('\n'))
                i += 1
            # 跳过空行
            while i < n and lines[i].strip() == '':
                i += 1
            # 收集译文段（* 开头的行）。颂偈等译文可能跨多行，有两种合法格式：
            #   格式A：每行独立以 * 包裹（*行1* / *行2*）
            #   格式B：整块跨行包裹（首行 *开头，末行 结尾*，中间行无 *）
            # 因此遇到 * 开头行后，继续收集后续"非空、非 　　原文、非 # 标题"的行（含跨行续行），
            # 直到遇到空行后非 * 行、或 　　原文、或标题、或文件结束。
            trans_lines = []
            while i < n:
                line = lines[i]
                if line.startswith('*'):
                    trans_lines.append(line.rstrip('\n'))
                    i += 1
                elif line.startswith('　　') or line.lstrip().startswith('#'):
                    break  # 下一段原文或标题，译文块结束
                elif line.strip() == '':
                    # 空行：向后看是否还有 * 行（格式A续行）；跨行续行（格式B）中间通常无空行
                    j = i
                    while j < n and lines[j].strip() == '':
                        j += 1
                    if j < n and lines[j].startswith('*'):
                        i = j  # 空行后仍是 * 译文，跳过空行继续
                    else:
                        break
                else:
                    # 非 * 开头、非空、非原文、非标题 → 跨行 *...* 的续行
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


def build_batches(pairs: dict[str, dict]) -> list[dict]:
    """按每批 BATCH 段切块，每批注入前 2 段作为上下文参考。"""
    keys = list(pairs.keys())
    total = len(keys)
    batches = []
    for start in range(0, total, BATCH):
        end = min(start + BATCH, total)
        batch_keys = keys[start:end]
        ctx_start = max(0, start - 2)
        ctx_keys = keys[ctx_start:start]
        batch = {
            '_batch_info': {
                'start': batch_keys[0] if batch_keys else '',
                'end': batch_keys[-1] if batch_keys else '',
                'count': len(batch_keys),
                'total': total,
            },
            '_context': {k: pairs[k] for k in ctx_keys},
            'paragraphs': {k: pairs[k] for k in batch_keys},
        }
        batches.append(batch)
    return batches


def main():
    if len(sys.argv) < 2:
        print("Usage: python prepare_check.py <N>", file=sys.stderr)
        sys.exit(1)
    n = int(sys.argv[1])
    src = f'output/{n}.md'
    if not os.path.exists(src):
        print(f"Error: {src} not found", file=sys.stderr)
        sys.exit(1)

    pairs = extract_pairs(src)
    with open(f'pairs_{n}.json', 'w', encoding='utf-8') as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)

    batches = build_batches(pairs)
    for b, batch in enumerate(batches, 1):
        with open(f'check_{n}_batch{b}.json', 'w', encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False, indent=2)

    print(f"Extracted {len(pairs)} pairs from {src} → pairs_{n}.json, {len(batches)} batches")
    for b, batch in enumerate(batches, 1):
        info = batch['_batch_info']
        print(f"  Batch {b}: paragraphs {info['start']}-{info['end']} ({info['count']} pairs)")


if __name__ == '__main__':
    main()
