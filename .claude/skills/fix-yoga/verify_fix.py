#!/usr/bin/env python3
"""
verify_fix.py - 校验所有 output/{N}.md 的修复是否已正确应用。

校验项（纯文本匹配，不调用 LLM）：
1. 每个 N (1-100) 都有对应的 .check.md 和 .fix.md
2. .fix.md 头部「成立并修复」数 与 正文「✅ 已修复」段落数一致
3. .fix.md 中每个「✅ 已修复」段落的「新译文」内容必须出现在 output/{N}.md 中
4. 可选：用 git diff 校验 output/{N}.md 在 fix 提交后确有改动（--git 模式）

用法：
    python verify_fix.py              # 校验 1-100
    python verify_fix.py 85 86 87     # 校验指定文件
    python verify_fix.py --git        # 同时做 git 改动校验
"""

from __future__ import annotations
import os
import re
import sys
import subprocess
from pathlib import Path

OUTPUT_DIR = Path('output')


def parse_fix_md(path: Path):
    """解析 .fix.md，返回 (header_stats, applied_entries)。

    header_stats: dict，头部统计字段
    applied_entries: list[(para_num_str, new_trans_str)]，「✅ 已修复」段落
    """
    text = path.read_text(encoding='utf-8')

    header_stats = {
        'total': 0, 'applied': 0, 'rejected': 0,
        'validation_failed': 0, 'application_failed': 0, 'batch_failed': 0,
    }
    for key, pat in [
        ('total', r'校对问题数：(\d+)'),
        ('applied', r'成立并修复：(\d+)'),
        ('rejected', r'不成立：(\d+)'),
        ('validation_failed', r'校验失败：(\d+)'),
        ('application_failed', r'应用失败：(\d+)'),
        ('batch_failed', r'批次解析失败：(\d+)'),
    ]:
        m = re.search(pat, text)
        if m:
            header_stats[key] = int(m.group(1))

    # 按 "### 段落 N 【" 切分
    applied_entries = []
    parts = re.split(r'^### 段落 (\d+) 【', text, flags=re.MULTILINE)
    # parts[0] 是头部，之后两两一组 (num, body)
    for i in range(1, len(parts), 2):
        para_num = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ''
        first_line = body.split('\n', 1)[0]
        if '✅ 已修复' not in first_line:
            continue
        # 提取「新译文」：从 - **新译文**： 开始，到下一个 - **字段 或 ### 或文末
        m = re.search(
            r'- \*\*新译文\*\*：(.*?)(?=\n- \*\*|\n### |\n## |\Z)',
            body, flags=re.DOTALL,
        )
        if m:
            new_trans = m.group(1).rstrip()
            applied_entries.append((para_num, new_trans))
        else:
            # 标记为已修复但找不到新译文字段
            applied_entries.append((para_num, None))

    return header_stats, applied_entries


def check_git_modified(n: int) -> tuple[bool, str]:
    """用 git 判断 output/{n}.md 在最近一次 fix 提交中是否被改动。

    返回 (是否改动, 说明)。
    """
    try:
        # 找最近一次 "fix trans" 提交
        r = subprocess.run(
            ['git', 'log', '--pretty=format:%H', '--grep=fix trans', '-1'],
            capture_output=True, text=True, check=True,
        )
        fix_commit = r.stdout.strip().split('\n')[0] if r.stdout.strip() else ''
        if not fix_commit:
            return False, '未找到 fix trans 提交'
        # 检查该提交是否改动 output/{n}.md
        r = subprocess.run(
            ['git', 'show', '--stat', '--pretty=format:', fix_commit, f'output/{n}.md'],
            capture_output=True, text=True, check=True,
        )
        changed = bool(r.stdout.strip())
        return changed, '' if changed else 'fix 提交未改动此 .md'
    except subprocess.CalledProcessError as e:
        return False, f'git 命令失败: {e}'


def verify_file(n: int, use_git: bool = False):
    """校验单个文件，返回 (issues, summary)。"""
    issues = []
    summary = {
        'total': 0, 'applied_header': 0, 'applied_parsed': 0,
        'verified': 0, 'missing': 0, 'git_changed': None,
    }

    check_md = OUTPUT_DIR / f'{n}.check.md'
    fix_md = OUTPUT_DIR / f'{n}.fix.md'
    md = OUTPUT_DIR / f'{n}.md'

    if not check_md.exists():
        issues.append(f'缺少 {check_md.name}')
    if not fix_md.exists():
        issues.append(f'缺少 {fix_md.name}')
        return issues, summary
    if not md.exists():
        issues.append(f'缺少 {md.name}')
        return issues, summary

    header_stats, applied_entries = parse_fix_md(fix_md)
    summary['total'] = header_stats['total']
    summary['applied_header'] = header_stats['applied']
    summary['applied_parsed'] = len(applied_entries)

    # 头部统计与实际解析数一致性
    if header_stats['applied'] != len(applied_entries):
        issues.append(
            f'头部「成立并修复」={header_stats["applied"]}，'
            f'正文「✅ 已修复」段落数={len(applied_entries)}，不一致'
        )

    # 校验新译文是否出现在 .md 中
    md_text = md.read_text(encoding='utf-8')
    for para_num, new_trans in applied_entries:
        if new_trans is None:
            issues.append(f'段落 {para_num} 标记已修复但缺少「新译文」字段')
            summary['missing'] += 1
            continue
        # 正常态：new_trans 以 * 开头，直接做整串匹配
        if new_trans.startswith('*'):
            if new_trans in md_text:
                summary['verified'] += 1
            else:
                summary['missing'] += 1
                issues.append(f'段落 {para_num} 的新译文未在 {md.name} 中找到')
            continue
        # 描述态（手动应用，如颂偈行数不匹配）：从描述里提取 *...* 片段，
        # 取「改为」之后的作为新译文片段，校验是否出现在 .md 中
        after_change = new_trans.split('改为')[-1]
        snippets = re.findall(r'\*[^*\n]+\*', after_change)
        if snippets and any(s in md_text for s in snippets):
            summary['verified'] += 1
        else:
            summary['missing'] += 1
            issues.append(
                f'段落 {para_num} 为描述型新译文，未能从描述中匹配到已应用片段'
            )

    # 可选：git 改动校验
    if use_git and summary['applied_parsed'] > 0:
        changed, why = check_git_modified(n)
        summary['git_changed'] = changed
        if not changed:
            issues.append(f'git 校验：{why}')

    return issues, summary


def main():
    use_git = False
    args = sys.argv[1:]
    if '--git' in args:
        use_git = True
        args = [a for a in args if a != '--git']

    files = [int(x) for x in args] if args else list(range(1, 101))
    files.sort()

    total_files = len(files)
    files_ok = 0
    files_with_issues = 0
    total_applied = 0
    total_verified = 0
    total_missing = 0
    failed_files = []

    print(f'校验 {total_files} 个文件{"（含 git 校验）" if use_git else ""}\n')
    print(f'{"文件":<8}{"问题数":<8}{"已修复":<8}{"已验证":<8}{"缺失":<8}状态')
    print('-' * 50)

    for n in files:
        issues, summary = verify_file(n, use_git=use_git)
        total_applied += summary['applied_parsed']
        total_verified += summary['verified']
        total_missing += summary['missing']

        if issues:
            files_with_issues += 1
            failed_files.append((n, issues))
            status = '❌'
        else:
            files_ok += 1
            status = '✅'

        # 仅打印有问题的文件，避免输出过长
        if issues:
            print(f'{n:<8}{summary["total"]:<8}{summary["applied_parsed"]:<8}'
                  f'{summary["verified"]:<8}{summary["missing"]:<8}{status}')

    print('-' * 50)
    print(f'\n汇总：')
    print(f'  文件总数：  {total_files}')
    print(f'  通过文件：  {files_ok}')
    print(f'  有问题文件：{files_with_issues}')
    print(f'  已修复条目：{total_applied}')
    print(f'  已验证条目：{total_verified}')
    print(f'  缺失条目：  {total_missing}')

    if failed_files:
        print(f'\n问题详情：')
        for n, issues in failed_files:
            print(f'\n  文件 {n}.md：')
            for issue in issues:
                print(f'    - {issue}')

    return 0 if not failed_files else 1


if __name__ == '__main__':
    sys.exit(main())
