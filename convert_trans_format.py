#!/usr/bin/env python3
"""
convert_trans_format.py — 一次性迁移：output/{N}.md 译文从斜体块改为引用块。

旧格式（译文块，两种合法形态）：
  格式A：每行独立包裹（*行1* / *行2*）
  格式B：跨行包裹（首行 * 开头，末行 * 结尾，中间行裸行）
新格式（ahan 式）：译文块每行都以 "> " 开头，无包裹符；原文段与引用块之间留一个空行
（pandoc 的 markdown 中 blockquote 不打断段落，无空行会把 ">" 当作字面文本）。

解析规则与 check-yoga.prepare_check.extract_pairs 保持一致（块边界判定相同），
仅处理 output/{1..100}.md，不碰 0.md（其 ** 为真实粗体）。

自校验：原文行逐字不变；每卷用旧 extract_pairs 重提取，
orig 与基线一致、trans 与「基线 trans 去包裹符」一致。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / '.claude/skills/check-yoga'))
from prepare_check import extract_pairs


def strip_asterisks(lines: list[str]) -> list[str]:
    """译文块内各行去包裹符：行首 * 去掉；行尾 * 仅在「本行以 * 开头（A 式）」
    或「是块末行（B 式收尾）」时去掉。"""
    out = []
    last = len(lines) - 1
    for i, line in enumerate(lines):
        s = line
        starts = s.startswith('*')
        if starts:
            s = s[1:]
        if s.endswith('*') and (starts or i == last):
            s = s[:-1]
        out.append(s)
    return out


def convert_text(text: str) -> str:
    lines = text.split('\n')
    out = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.startswith('　　'):
            out.append(line)
            i += 1
            while i < n and lines[i].startswith('　　'):
                out.append(lines[i])
                i += 1
            # 收集译文块（与 extract_pairs 的块边界判定一致）
            trans_lines = []
            while i < n:
                cur = lines[i]
                if cur.startswith('*'):
                    trans_lines.append(cur)
                    i += 1
                elif cur.startswith('　　') or cur.lstrip().startswith('#'):
                    break
                elif cur.strip() == '':
                    j = i
                    while j < n and lines[j].strip() == '':
                        j += 1
                    if j < n and lines[j].startswith('*'):
                        i = j  # 跳过空行继续（空行不进译文块，与 extract_pairs 一致）
                    else:
                        break
                else:
                    trans_lines.append(cur)
                    i += 1
            if trans_lines:
                # 引用块前需空行分隔（pandoc 的 markdown 中 blockquote 不打断段落）
                if out and out[-1].strip() != '' and not out[-1].startswith('> '):
                    out.append('')
                out.extend('> ' + s for s in strip_asterisks(trans_lines))
        else:
            out.append(line)
            i += 1
    return '\n'.join(out)


def main():
    baseline_counts = json.load(open('/tmp/baseline_counts.json'))
    fail = []
    for n in range(1, 101):
        path = Path(f'output/{n}.md')
        orig_text = path.read_text(encoding='utf-8')
        new_text = convert_text(orig_text)

        # 校验1：原文行（　　开头）逐字不变
        old_orig = [l for l in orig_text.split('\n') if l.startswith('　　')]
        new_orig = [l for l in new_text.split('\n') if l.startswith('　　')]
        assert old_orig == new_orig, f'{n}: 原文行发生变化'

        # 校验2：旧 extract_pairs 在新文件上提取，orig 与基线一致，
        # trans 与基线 trans 去包裹符后一致
        base_pairs = json.load(open(f'/tmp/baseline_orig_{n}.json'))
        # extract_pairs 读文件，先写临时再提取
        tmp = Path(f'/tmp/conv_{n}.md')
        tmp.write_text(new_text, encoding='utf-8')
        new_pairs = extract_pairs(str(tmp))
        assert len(new_pairs) == len(base_pairs), f'{n}: 段对数 {len(new_pairs)} != 基线 {len(base_pairs)}'
        for k, bp in base_pairs.items():
            np = new_pairs[k]
            assert np['orig'] == bp['orig'], f'{n} 段{k}: orig 不一致'
            expect_trans = '\n'.join('> ' + s for s in strip_asterisks(bp['trans'].split('\n'))) if bp['trans'] else ''
            assert np['trans'] == expect_trans, f'{n} 段{k}: trans 不一致\n旧: {bp["trans"][:60]}\n新: {np["trans"][:60]}'
        tmp.unlink()

        path.write_text(new_text, encoding='utf-8')
        if '*' in new_text and any(l.startswith('*') for l in new_text.split('\n')):
            fail.append(n)
    if fail:
        print('残留 * 行的文件:', fail)
        sys.exit(1)
    print('✓ 100 卷全部转换并校验通过（段对总数 %d）' % sum(baseline_counts.values()))


if __name__ == '__main__':
    main()
