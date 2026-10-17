#!/usr/bin/env python3
"""
apply_smooth.py — 合并各批改写结果，对 output/{N}.md 应用新译文，
并机械拼装阶段B的校验批次文件（原文 + 原译文 + 新译文）。

读取：
- smooth_{N}_pairs.json（全部段对，由 prepare_smooth.py 生成）
- smooth_{N}_batch*.rewrite.json（阶段A子 Agent 改写结果）

输出：
- 更新 output/{N}.md（应用格式校验通过的新译文）
- smooth_{N}_applied.json（改写记录 + 状态，供 finalize_smooth.py 生成报告）
- smooth_{N}_vbatch{b}.json（校验批次文件，供阶段B子 Agent 使用）

本脚本不做任何语义判断；格式校验（每行 "> " 开头、颂偈行数）通过后才应用。
"""

from __future__ import annotations
import json, sys, os, glob

# 复用 fix-yoga 的格式校验、段落定位与替换逻辑
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fix-yoga'))
from apply_fix import (  # noqa: E402
    load_verdicts_json, validate_new_trans,
    locate_paragraph_block, replace_trans_block,
)

VBATCH = 20  # 每批校验段落数


def sort_key(k):
    try:
        return int(k)
    except ValueError:
        return 10 ** 9


def main():
    if len(sys.argv) < 2:
        print("Usage: python apply_smooth.py <N>", file=sys.stderr)
        sys.exit(1)
    n = int(sys.argv[1])

    pairs_path = f'smooth_{n}_pairs.json'
    if not os.path.exists(pairs_path):
        print(f"Error: {pairs_path} not found. Run prepare_smooth.py first.", file=sys.stderr)
        sys.exit(1)
    pairs = json.load(open(pairs_path, encoding='utf-8'))

    # 合并各批改写结果（扫描 .rewrite.json）
    rewrites = {}
    batch_files_failed = []
    for path in sorted(glob.glob(f'smooth_{n}_batch*.rewrite.json')):
        batch = load_verdicts_json(path)
        if batch is None:
            batch_files_failed.append(os.path.basename(path))
            continue
        for key, value in batch.items():
            if key.startswith('_'):
                continue
            rewrites[key] = value

    if not rewrites:
        with open(f'smooth_{n}_applied.json', 'w', encoding='utf-8') as f:
            json.dump({'records': {}, 'batch_files_failed': batch_files_failed}, f,
                      ensure_ascii=False, indent=2)
        print('No paragraphs judged obscure. Nothing to apply.')
        return

    with open(f'output/{n}.md', 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')

    # 第一遍：格式校验，确定可应用集合
    records = {}  # k -> {orig, old_trans, new_trans, reason, status, detail}
    to_apply = []
    for k in sorted(rewrites.keys(), key=sort_key):
        pair = pairs.get(k, {})
        v = rewrites[k]
        if not v.get('obscure', True):
            continue  # 明确标记不晦涩的，跳过
        reason = v.get('reason', '')
        new_trans = (v.get('new_trans') or '').strip()
        if not new_trans:
            records[k] = {'orig': pair.get('orig', ''), 'old_trans': pair.get('trans', ''),
                          'new_trans': '', 'reason': reason,
                          'status': 'validation_failed', 'detail': 'obscure=true 但 new_trans 为空'}
            continue
        is_valid, val_reason = validate_new_trans(new_trans, pair.get('orig', ''))
        if not is_valid:
            records[k] = {'orig': pair.get('orig', ''), 'old_trans': pair.get('trans', ''),
                          'new_trans': new_trans, 'reason': reason,
                          'status': 'validation_failed', 'detail': val_reason}
            continue
        to_apply.append(k)
        records[k] = {'orig': pair.get('orig', ''), 'old_trans': pair.get('trans', ''),
                      'new_trans': new_trans, 'reason': reason, 'status': 'applied', 'detail': ''}

    # 第二遍：从后往前应用（避免行索引偏移）
    for k in sorted(to_apply, key=sort_key, reverse=True):
        try:
            para_num = int(k)
        except ValueError:
            records[k]['status'] = 'application_failed'
            records[k]['detail'] = '段落号无效'
            continue
        result = locate_paragraph_block(lines, para_num)
        if result is None:
            records[k]['status'] = 'application_failed'
            records[k]['detail'] = '段落未在 .md 中找到'
            continue
        _, _, trans_start, trans_end = result
        if trans_start == -1:
            records[k]['status'] = 'application_failed'
            records[k]['detail'] = '原文段后无译文块（MISSING），不属于明晰化范围'
            continue
        lines = replace_trans_block(lines, trans_start, trans_end, records[k]['new_trans'])

    with open(f'output/{n}.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    with open(f'smooth_{n}_applied.json', 'w', encoding='utf-8') as f:
        json.dump({'records': records, 'batch_files_failed': batch_files_failed}, f,
                  ensure_ascii=False, indent=2)

    # 拼装阶段B校验批次（只含已应用的段落；文本来自 pairs + rewrite 结果，无需重读 md）
    applied_keys = sorted([k for k in records if records[k]['status'] == 'applied'], key=sort_key)
    vbatches = []
    for start in range(0, len(applied_keys), VBATCH):
        chunk = applied_keys[start:start + VBATCH]
        b = len(vbatches) + 1
        batch = {
            '_batch_info': {
                'start': chunk[0], 'end': chunk[-1], 'count': len(chunk), 'total': len(applied_keys),
            },
            'paragraphs': {
                k: {'orig': records[k]['orig'],
                    'old_trans': records[k]['old_trans'],
                    'new_trans': records[k]['new_trans']} for k in chunk
            },
        }
        with open(f'smooth_{n}_vbatch{b}.json', 'w', encoding='utf-8') as f:
            json.dump(batch, f, ensure_ascii=False, indent=2)
        vbatches.append(batch)

    counts = {}
    for r in records.values():
        counts[r['status']] = counts.get(r['status'], 0) + 1
    print(f"Applied {len(applied_keys)} rewrites to output/{n}.md; "
          f"{counts.get('validation_failed', 0)} validation_failed, "
          f"{counts.get('application_failed', 0)} application_failed")
    if batch_files_failed:
        print(f"  [WARN] batch parse failed: {', '.join(batch_files_failed)}")
    print(f"Generated smooth_{n}_applied.json and {len(vbatches)} verify batches")


if __name__ == '__main__':
    main()
