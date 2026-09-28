#!/usr/bin/env python3
"""
finalize_smooth.py — 合并阶段B校验结果，对 output/{N}.md 应用修正或回退，
生成 output/{N}.smooth.md 报告。

读取：
- smooth_{N}_applied.json（改写记录，由 apply_smooth.py 生成）
- smooth_{N}_vbatch*.result.json（阶段B子 Agent 校验结果）

处理规则：
- PASS → 保留改写
- FAIL 带 fixed_trans（格式校验通过）→ 应用修正
- FAIL 无 fixed_trans → 回退为原译文
- 无校验结果（批次解析失败）→ 保留改写，报告中标注

输出：
- 更新 output/{N}.md
- output/{N}.smooth.md 报告
"""

from __future__ import annotations
import json, sys, os, glob
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fix-yoga'))
from apply_fix import (  # noqa: E402
    load_verdicts_json, validate_new_trans,
    locate_paragraph_block, replace_trans_block,
)


def sort_key(k):
    try:
        return int(k)
    except ValueError:
        return 10 ** 9


STATUS_LABEL = {
    'passed': '✅ 改写并通过校验',
    'corrected': '⚠️ 改写有误，已修正',
    'reverted': '❌ 改写有误，已回退原译文',
    'unverified': '❓ 未经校验（批次解析失败），已保留改写',
    'validation_failed': '⚠️ 格式校验失败，未应用',
    'application_failed': '⚠️ 应用失败',
}


def main():
    if len(sys.argv) < 2:
        print("Usage: python finalize_smooth.py <N>", file=sys.stderr)
        sys.exit(1)
    n = int(sys.argv[1])

    applied_path = f'smooth_{n}_applied.json'
    if not os.path.exists(applied_path):
        print(f"Error: {applied_path} not found. Run apply_smooth.py first.", file=sys.stderr)
        sys.exit(1)
    applied = json.load(open(applied_path, encoding='utf-8'))
    records = applied.get('records', {})
    batch_files_failed = applied.get('batch_files_failed', [])

    # 合并各批校验结果
    verdicts = {}
    result_files_failed = []
    for path in sorted(glob.glob(f'smooth_{n}_vbatch*.result.json')):
        batch = load_verdicts_json(path)
        if batch is None:
            result_files_failed.append(os.path.basename(path))
            continue
        for key, value in batch.items():
            if key.startswith('_'):
                continue
            verdicts[key] = value

    with open(f'output/{n}.md', 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')

    # 确定每段最终状态
    to_apply = []  # (k, text) — 需要替换译文块（修正或回退）
    for k, rec in records.items():
        if rec['status'] != 'applied':
            continue  # validation_failed / application_failed 已在 apply 阶段定稿
        if k not in verdicts:
            rec['status'] = 'unverified'
            rec['detail'] = '校验批次解析失败，未能校验'
            continue
        v = verdicts[k]
        verdict = (v.get('verdict') or '').upper()
        if verdict == 'PASS':
            rec['status'] = 'passed'
            rec['verify_reason'] = v.get('reason', '')
            continue
        issue = v.get('issue', '')
        fixed_trans = (v.get('fixed_trans') or '').strip()
        if fixed_trans and fixed_trans != 'null':
            is_valid, val_reason = validate_new_trans(fixed_trans, rec['orig'])
            if is_valid:
                rec['status'] = 'corrected'
                rec['verify_issue'] = issue
                rec['new_trans'] = fixed_trans
                to_apply.append((k, fixed_trans))
            else:
                rec['status'] = 'reverted'
                rec['verify_issue'] = issue
                rec['detail'] = f'fixed_trans 格式校验失败（{val_reason}），回退为原译文'
                to_apply.append((k, rec['old_trans']))
        else:
            rec['status'] = 'reverted'
            rec['verify_issue'] = issue
            to_apply.append((k, rec['old_trans']))

    # 应用修正/回退（从后往前）
    for k, text in sorted(to_apply, key=lambda x: sort_key(x[0]), reverse=True):
        try:
            para_num = int(k)
        except ValueError:
            records[k]['detail'] = (records[k].get('detail') or '') + '；段落号无效，未能应用'
            continue
        result = locate_paragraph_block(lines, para_num)
        if result is None:
            records[k]['detail'] = (records[k].get('detail') or '') + '；段落未找到，未能应用'
            continue
        _, _, trans_start, trans_end = result
        if trans_start == -1:
            records[k]['detail'] = (records[k].get('detail') or '') + '；译文块未找到，未能应用'
            continue
        lines = replace_trans_block(lines, trans_start, trans_end, text)

    with open(f'output/{n}.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    # 统计
    counts = {}
    for r in records.values():
        counts[r['status']] = counts.get(r['status'], 0) + 1
    n_applied_total = len(records)

    # 生成报告
    out_path = f'output/{n}.smooth.md'
    L = []
    L.append(f'# output/{n}.md 译文明晰化报告')
    L.append('')
    L.append(f'- 时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}')
    if n_applied_total == 0:
        L.append('- 判定晦涩并改写：0')
        L.append('')
        L.append('✅ 全部译文表达清晰，无需明晰化。')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(L) + '\n')
        print(f'No obscure paragraphs. Generated {out_path}')
        return

    L.append(f'- 判定晦涩并改写：{n_applied_total} 段')
    L.append(f'- 校验通过：{counts.get("passed", 0)}')
    L.append(f'- 校验不通过、已修正：{counts.get("corrected", 0)}')
    L.append(f'- 校验不通过、已回退：{counts.get("reverted", 0)}')
    L.append(f'- 未经校验（批次解析失败）：{counts.get("unverified", 0)}')
    L.append(f'- 格式校验失败、未应用：{counts.get("validation_failed", 0)}')
    L.append(f'- 应用失败：{counts.get("application_failed", 0)}')
    if batch_files_failed:
        L.append(f'- 改写批次解析失败：{", ".join(batch_files_failed)}')
    if result_files_failed:
        L.append(f'- 校验批次解析失败：{", ".join(result_files_failed)}')
    L.append('')
    L.append('## 改写记录')
    L.append('')
    for k in sorted(records.keys(), key=sort_key):
        rec = records[k]
        st = rec['status']
        label = STATUS_LABEL.get(st, st)
        L.append(f'### 段落 {k} {label}')
        L.append('')
        if rec.get('orig'):
            L.append(f'- **原文**：{rec["orig"]}')
        if rec.get('old_trans'):
            L.append(f'- **原译文**：{rec["old_trans"]}')
        if rec.get('reason'):
            L.append(f'- **判定理由**：{rec["reason"]}')
        if st in ('passed', 'corrected', 'unverified') and rec.get('new_trans'):
            L.append(f'- **新译文**：{rec["new_trans"]}')
        if st == 'reverted':
            L.append(f'- **拟改写译文**：{rec.get("new_trans", "")}')
        if rec.get('verify_reason'):
            L.append(f'- **校验意见**：{rec["verify_reason"]}')
        if rec.get('verify_issue'):
            L.append(f'- **校验问题**：{rec["verify_issue"]}')
        if rec.get('detail'):
            L.append(f'- **说明**：{rec["detail"]}')
        L.append('')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')

    print(f'Finalized output/{n}.md: passed={counts.get("passed", 0)}, '
          f'corrected={counts.get("corrected", 0)}, reverted={counts.get("reverted", 0)}, '
          f'unverified={counts.get("unverified", 0)}')
    print(f'Generated {out_path}')


if __name__ == '__main__':
    main()
