#!/usr/bin/env python3
"""
advance_pipeline.py — smooth-yoga 批量流水线推进器。

每次波次派发结束后运行一次，按文件推进状态机：
  rewriting（改写批次未齐）→ 齐了自动 apply → verifying（校验批次未齐）
  → 齐了自动 finalize + 清理 → done

输出：各文件状态 + 待派发任务清单（改写/校验），供组装下一波（优先校验、再改写补足）。

用法：python3 advance_pipeline.py <start> <end>
"""

import glob, os, re, subprocess, sys


def batch_ids(n, kind):
    """kind: 'batch' 或 'vbatch'；返回 (全部输入批次号集合, 已完成输出批次号集合)"""
    total, done = set(), set()
    for p in glob.glob(f'smooth_{n}_{kind}*.json'):
        if p.endswith('.rewrite.json') or p.endswith('.result.json'):
            m = re.search(rf'smooth_{n}_{kind}(\d+)\.(rewrite|result)\.json$', p)
            if m:
                done.add(int(m.group(1)))
            continue
        m = re.search(rf'smooth_{n}_{kind}(\d+)\.json$', p)
        if m:
            total.add(int(m.group(1)))
    return total, done


def main():
    start, end = int(sys.argv[1]), int(sys.argv[2])
    pending_rewrite, pending_verify = [], []
    states = {}
    for n in range(start, end + 1):
        total, done = batch_ids(n, 'batch')
        if os.path.exists(f'output/{n}.smooth.md'):
            states[n] = 'done'
            continue
        if done < total:
            states[n] = f'rewriting({len(done)}/{len(total)})'
            pending_rewrite += [(n, b) for b in sorted(total - done)]
            continue
        if not os.path.exists(f'smooth_{n}_applied.json'):
            r = subprocess.run(['python3', '.claude/skills/smooth-yoga/apply_smooth.py', str(n)],
                               capture_output=True, text=True)
            print(f'[apply {n}] {r.stdout.strip() or r.stderr.strip()}')
        vt, vd = batch_ids(n, 'vbatch')
        if vd < vt:
            states[n] = f'verifying({len(vd)}/{len(vt)})'
            pending_verify += [(n, b) for b in sorted(vt - vd)]
            continue
        r = subprocess.run(['python3', '.claude/skills/smooth-yoga/finalize_smooth.py', str(n)],
                           capture_output=True, text=True)
        print(f'[finalize {n}] {r.stdout.strip() or r.stderr.strip()}')
        for pat in [f'smooth_{n}_pairs.json', f'smooth_{n}_batch*.json',
                    f'smooth_{n}_applied.json', f'smooth_{n}_vbatch*.json']:
            for p in glob.glob(pat):
                os.remove(p)
        states[n] = 'done'

    print('\n== 状态汇总 ==')
    for n in range(start, end + 1):
        print(f'  {n}: {states[n]}')
    print(f'\n待派发校验批次 {len(pending_verify)} 个: {pending_verify}')
    print(f'待派发改写批次 {len(pending_rewrite)} 个: {pending_rewrite}')


if __name__ == '__main__':
    main()
