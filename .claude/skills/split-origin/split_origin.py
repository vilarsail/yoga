#!/usr/bin/env python3
"""分割 origin/{N}.txt 到 output/{N}.md，使用 LLM 做语义分割。

四个子命令配合使用：

    prepare        - 读取 origin，生成 output/{N}.draft.md（颂偈已合并，
                     长段已按 。 切成单行句子，待 LLM 决定分组）
    list-sentences - 从 draft.md 提取长段落的句子，输出带编号的紧凑列表
                     output/{N}.sentences.txt，供 LLM 快速决策
    apply-splits   - 读取 output/{N}.splits.txt（LLM 写的编号分割点列表），
                     在 draft.md 的长段落中自动插入空行
    finalize       - 读取 output/{N}.draft.md（已插入空行），
                     合并同组句子为一段，生成 output/{N}.md，并校验字符流一致性

用法:
    python3 split_origin.py prepare <start> <end> [--base-dir DIR] [--output-dir DIR]
                                    [--max-len N]
    python3 split_origin.py list-sentences <start> <end> [--base-dir DIR] [--output-dir DIR]
    python3 split_origin.py apply-splits <start> <end> [--base-dir DIR] [--output-dir DIR]
    python3 split_origin.py finalize <start> <end> [--base-dir DIR] [--output-dir DIR]
                                    [--verbose]

每章生成:
    output/{N}.draft.md        中间文件（prepare 生成，apply-splits 编辑）
    output/{N}.sentences.txt   带编号的长段落句子列表（list-sentences 生成）
    output/{N}.splits.txt      编号分割点列表（LLM 写，apply-splits 读取）
    output/{N}.md               最终分割结果（finalize 生成）
    output/{N}.check_split.md  校验报告（finalize 生成）

splits.txt 格式（编号格式，极紧凑）:
    每行一个编号，如 P1S5 表示第 1 个长段落的第 5 句后插入空行
    示例:
        P1S5
        P1S12
        P2S3

退出码:
    0 - 所有章节校验通过
    1 - 发现校验失败或文件缺失
    2 - 参数错误
"""

import argparse
import os
import sys


# 常量
INDENT = '　　'  # U+3000 × 2，正文段落前缀
MAX_LEN_DEFAULT = 200  # 段落最大字符数（超过则需切分）
WHITESPACE_CHARS = ' \t\n\r　'  # 校验时视为空白的字符（含全角空格）
LONG_PARA_START = '<!-- LONG_PARA_START -->'
LONG_PARA_END = '<!-- LONG_PARA_END -->'


# ============================================================
# 通用工具
# ============================================================

def read_lines(path):
    """读取文件，返回行列表（去行尾空白）。"""
    with open(path, 'r', encoding='utf-8') as f:
        return [line.rstrip() for line in f.readlines()]


def is_verse_strict(line):
    """严格判定颂偈行：以 　　 开头，去除前缀后不含句号，且含中间的 　　 分隔（对句结构）。"""
    if not line.startswith(INDENT):
        return False
    body = line[len(INDENT):]
    if not body:
        return False
    if '。' in body:
        return False
    return INDENT in body


def is_verse_loose(line):
    """宽松判定颂偈行：以 　　 开头，去除前缀后不含句号，长度较短（≤30 字符）。

    用于识别颂偈中不含中间 　　 分隔的尾句，如 '彼寂为乐'。
    """
    if not line.startswith(INDENT):
        return False
    body = line[len(INDENT):]
    if not body:
        return False
    if '。' in body:
        return False
    return len(body) <= 30


def find_verse_segments(lines):
    """识别颂偈段，返回 [(start_idx, end_idx), ...]（左闭右开）。

    规则：连续的 verse_loose 行中，至少有一行是 verse_strict，整段才视为颂偈段。
    """
    body_indices = [i for i, line in enumerate(lines) if line.startswith(INDENT)]
    segments = []
    i = 0
    while i < len(body_indices):
        idx = body_indices[i]
        if not is_verse_loose(lines[idx]):
            i += 1
            continue
        j = i
        while j < len(body_indices) and is_verse_loose(lines[body_indices[j]]):
            j += 1
        if any(is_verse_strict(lines[body_indices[k]]) for k in range(i, j)):
            segments.append((body_indices[i], body_indices[j - 1] + 1))
        i = j
    return segments


def split_to_sentences(text):
    """按 。 切分成句子（保留分隔符在每句末尾）。

    输入：'　　abc。def。ghi。' 或 'abc。def。ghi。'
    输出：['abc。', 'def。', 'ghi。']（或带前缀版本）
    """
    prefix = INDENT
    body = text[len(prefix):] if text.startswith(prefix) else text

    sentences = []
    current = ''
    for ch in body:
        current += ch
        if ch == '。':
            sentences.append(current)
            current = ''
    if current:
        sentences.append(current)

    return sentences


# ============================================================
# prepare 子命令
# ============================================================

def prepare_chapter(origin_path, draft_path, max_len=MAX_LEN_DEFAULT):
    """生成 draft.md。

    返回 (ok, stats)。
    """
    lines = read_lines(origin_path)
    if not lines:
        return False, {'error': 'empty file'}

    verse_segments = find_verse_segments(lines)
    verse_segment_map = {}
    for start, end in verse_segments:
        for i in range(start, end):
            verse_segment_map[i] = (start, end)

    output_lines = []
    stats = {
        'title': '',
        'subtitle_count': 0,
        'verse_count': 0,
        'short_para_count': 0,
        'long_para_count': 0,
        'long_para_sentence_count': 0,
    }

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue

        if i == 0:
            # 主标题
            output_lines.append(f'# {line}')
            output_lines.append('')
            stats['title'] = line
            i += 1
            continue

        if not line.startswith(INDENT):
            # 副标题
            output_lines.append(f'## {line}')
            output_lines.append('')
            stats['subtitle_count'] += 1
            i += 1
            continue

        # 正文
        if i in verse_segment_map:
            start, end = verse_segment_map[i]
            verse_lines = lines[start:end]
            merged = '\n'.join(verse_lines)
            output_lines.append(merged)
            output_lines.append('')
            stats['verse_count'] += 1
            i = end
            continue

        body_text = line[len(INDENT):]
        if len(body_text) > max_len:
            # 长段落：切分成句子，每句一行带 INDENT 前缀
            sentences = split_to_sentences(line)
            stats['long_para_count'] += 1
            stats['long_para_sentence_count'] += len(sentences)
            output_lines.append(LONG_PARA_START)
            for s in sentences:
                output_lines.append(INDENT + s)
            output_lines.append(LONG_PARA_END)
            output_lines.append('')
        else:
            output_lines.append(line)
            output_lines.append('')
            stats['short_para_count'] += 1
        i += 1

    with open(draft_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))

    return True, stats


# ============================================================
# finalize 子命令
# ============================================================

def finalize_chapter(draft_path, output_path):
    """把 draft.md 转换为最终 output/{N}.md。

    规则：
    - 在 <!-- LONG_PARA_START --> 和 <!-- LONG_PARA_END --> 之间：
      * 空行表示分割点
      * 连续的 　　 前缀行合并为一段（首行保留 　　 前缀，后续行去掉前缀后拼接）
    - 标记行本身去除
    - 其他行原样保留

    返回 (output_lines, stats)。
    """
    with open(draft_path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.split('\n')

    output_lines = []
    stats = {
        'title': '',
        'subtitle_count': 0,
        'verse_count': 0,
        'short_para_count': 0,
        'long_para_count': 0,
        'long_para_group_count': 0,  # 分割后的段落数
    }

    i = 0
    while i < len(lines):
        line = lines[i]

        if line == LONG_PARA_START:
            stats['long_para_count'] += 1
            i += 1
            # 收集到 LONG_PARA_END 之间的所有行，按空行分组
            groups = []  # 每个组是若干句子（已去掉 　　 前缀）
            current_group = []
            while i < len(lines) and lines[i] != LONG_PARA_END:
                if lines[i] == '':
                    # 空行：分割点
                    if current_group:
                        groups.append(current_group)
                        current_group = []
                elif lines[i].startswith(INDENT):
                    current_group.append(lines[i][len(INDENT):])
                else:
                    # 不应该出现：原样保留
                    current_group.append(lines[i])
                i += 1
            # 跳过 LONG_PARA_END
            if i < len(lines) and lines[i] == LONG_PARA_END:
                i += 1
            # 收尾
            if current_group:
                groups.append(current_group)

            # 把每个组合并为一段
            for group in groups:
                if group:
                    merged = INDENT + ''.join(group)
                    output_lines.append(merged)
                    output_lines.append('')
                    stats['long_para_group_count'] += 1
            continue

        # 主标题
        if line.startswith('# ') and not line.startswith('## '):
            stats['title'] = line[2:]
            output_lines.append(line)
            i += 1
            continue

        # 副标题
        if line.startswith('## '):
            stats['subtitle_count'] += 1
            output_lines.append(line)
            i += 1
            continue

        # 正文段落（带 　　 前缀）
        if line.startswith(INDENT):
            # 判断是颂偈段（多行，行间无空行）还是短段落（单行）
            # 颂偈段：当前行带 　　 前缀，且紧接的下一行（不跳过空行）也带 　　 前缀
            if i + 1 < len(lines) and lines[i + 1].startswith(INDENT):
                # 多行段落：颂偈
                stats['verse_count'] += 1
                # 输出整个颂偈段（连续的 　　 前缀行）
                output_lines.append(line)
                i += 1
                while i < len(lines) and lines[i].startswith(INDENT):
                    output_lines.append(lines[i])
                    i += 1
                output_lines.append('')
            else:
                # 单行段落：短段落
                stats['short_para_count'] += 1
                output_lines.append(line)
                output_lines.append('')
                i += 1
            continue

        # 其他行（空行等）：原样输出
        output_lines.append(line)
        i += 1

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))

    return output_lines, stats


# ============================================================
# list-sentences 子命令
# ============================================================

def list_sentences(draft_path, sentences_path):
    """从 draft.md 提取长段落的句子，输出带编号的紧凑列表到 sentences.txt。

    格式：
        == 长段落 1 (45句) ==
        P1S1 云何总标。
        P1S2 谓此地中略有四种。
        ...
        P1S45 灭尽定等三摩钵底。

        == 长段落 2 (60句) ==
        P2S1 复次初静虑中。
        ...

    返回 (ok, stats)。
    """
    with open(draft_path, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')

    output_lines = []
    stats = {
        'long_para_count': 0,
        'total_sentences': 0,
    }

    para_idx = 0
    sent_idx = 0
    in_long_para = False
    para_start_line = 0

    for line in lines:
        if line == LONG_PARA_START:
            para_idx += 1
            sent_idx = 0
            in_long_para = True
            para_start_line = len(output_lines)
            output_lines.append(f'== 长段落 {para_idx} ==')
            continue

        if line == LONG_PARA_END:
            if in_long_para:
                # 补充句数信息到段落标题
                output_lines[para_start_line] = f'== 长段落 {para_idx} ({sent_idx}句) =='
                output_lines.append('')  # 段落间空行
            in_long_para = False
            stats['long_para_count'] += 1
            continue

        if in_long_para and line.startswith(INDENT):
            sent_idx += 1
            sentence = line[len(INDENT):]
            output_lines.append(f'P{para_idx}S{sent_idx} {sentence}')
            stats['total_sentences'] += 1

    with open(sentences_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))

    return True, stats


# ============================================================
# apply-splits 子命令
# ============================================================

def parse_split_id(sid):
    """解析编号格式 P{段落号}S{句子号}，返回 (para_idx, sent_idx) 或 None。"""
    sid = sid.strip()
    if not sid.startswith('P') or 'S' not in sid:
        return None
    parts = sid[1:].split('S', 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def apply_splits(draft_path, splits_path):
    """根据 splits 文件在 draft.md 的长段落中插入空行。

    splits 文件格式（编号格式）：每行一个编号，如 P1S5。
    P1S5 表示第 1 个长段落的第 5 句后插入空行。

    返回 (ok, stats)。
    """
    with open(splits_path, 'r', encoding='utf-8') as f:
        raw_lines = [line.strip() for line in f if line.strip()]

    # 解析编号
    parsed_splits = []
    parse_errors = []
    for sid in raw_lines:
        parsed = parse_split_id(sid)
        if parsed:
            parsed_splits.append((parsed[0], parsed[1], sid))
        else:
            parse_errors.append(sid)

    with open(draft_path, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')

    stats = {
        'total': len(parsed_splits),
        'applied': 0,
        'already_present': 0,
        'not_found': [],
        'parse_errors': parse_errors,
    }

    split_idx = 0
    i = 0
    para_idx = 0
    sent_idx = 0
    in_long_para = False

    while i < len(lines) and split_idx < len(parsed_splits):
        line = lines[i]

        if line == LONG_PARA_START:
            para_idx += 1
            sent_idx = 0
            in_long_para = True
            i += 1
            continue

        if line == LONG_PARA_END:
            in_long_para = False
            i += 1
            continue

        if in_long_para and line.startswith(INDENT):
            sent_idx += 1
            target_p, target_s, target_sid = parsed_splits[split_idx]
            if para_idx == target_p and sent_idx == target_s:
                # 找到分割点，在该行后插入空行
                if i + 1 < len(lines) and lines[i + 1] == '':
                    stats['already_present'] += 1
                else:
                    lines.insert(i + 1, '')
                    stats['applied'] += 1
                split_idx += 1

        i += 1

    stats['not_found'] = [sid for _, _, sid in parsed_splits[split_idx:]]

    with open(draft_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return len(stats['not_found']) == 0 and not parse_errors, stats


# ============================================================
# 校验
# ============================================================

def extract_chars(content, is_output=False):
    """提取实质字符流。

    - 去除所有空白字符（含全角空格 U+3000）
    - 对 output：去除 markdown 标题行的 # 前缀
    """
    if is_output:
        lines = content.split('\n')
        new_lines = []
        for line in lines:
            if line.startswith('#'):
                line = line.lstrip('#').lstrip()
            new_lines.append(line)
        content = '\n'.join(new_lines)

    return ''.join(ch for ch in content if ch not in WHITESPACE_CHARS)


def verify_chapter(origin_path, output_path):
    """校验一个章节，返回 (ok, origin_chars, output_chars, diff_pos)。"""
    with open(origin_path, 'r', encoding='utf-8') as f:
        origin_content = f.read()
    with open(output_path, 'r', encoding='utf-8') as f:
        output_content = f.read()

    origin_chars = extract_chars(origin_content, is_output=False)
    output_chars = extract_chars(output_content, is_output=True)

    if origin_chars == output_chars:
        return True, origin_chars, output_chars, -1

    diff_pos = -1
    for i in range(min(len(origin_chars), len(output_chars))):
        if origin_chars[i] != output_chars[i]:
            diff_pos = i
            break
    if diff_pos == -1:
        diff_pos = min(len(origin_chars), len(output_chars))

    return False, origin_chars, output_chars, diff_pos


# ============================================================
# 报告
# ============================================================

def write_report(report_path, n, ok,
                 origin_chars, output_chars, diff_pos, stats, error=None):
    """为单个章节生成校验报告。"""
    lines = []
    lines.append(f'# 分割校验 - 第 {n} 章')
    lines.append('')
    lines.append('## 概览')
    lines.append('')
    lines.append(f'- 章节号: {n}')
    lines.append(f'- origin 文件: `origin/{n}.txt`')
    lines.append(f'- output 文件: `output/{n}.md`')
    lines.append(f'- 状态: {"✓ 校验通过" if ok else "✗ 校验失败"}')

    if error:
        lines.append(f'- 错误: {error}')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return report_path

    if stats.get('title'):
        lines.append(f'- 标题: {stats["title"]}')
    lines.append(f'- 副标题数: {stats.get("subtitle_count", 0)}')
    lines.append(f'- 颂偈段数: {stats.get("verse_count", 0)}')
    lines.append(f'- 短段落数: {stats.get("short_para_count", 0)}')
    lines.append(f'- 长段落数: {stats.get("long_para_count", 0)}')
    if 'long_para_sentence_count' in stats:
        lines.append(f'- 长段落总句数: {stats["long_para_sentence_count"]}')
    if 'long_para_group_count' in stats:
        lines.append(f'- 长段落分割后段数: {stats["long_para_group_count"]}')
    lines.append('')

    if ok:
        lines.append('字符流校验通过：origin 与 output 的实质字符流完全一致。')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return report_path

    # 校验失败详情
    lines.append('## 字符流差异')
    lines.append('')
    lines.append(f'- origin 实质字符数: {len(origin_chars)}')
    lines.append(f'- output 实质字符数: {len(output_chars)}')
    lines.append(f'- 首处差异位置: 第 {diff_pos} 字符')
    lines.append('')

    context_before = 20
    context_after = 40
    o_start = max(0, diff_pos - context_before)
    u_start = max(0, diff_pos - context_before)
    o_context = origin_chars[o_start:diff_pos + context_after]
    u_context = output_chars[u_start:diff_pos + context_after]
    o_marker_pos = diff_pos - o_start
    u_marker_pos = diff_pos - u_start

    lines.append('**origin 上下文** (差异位置用 ← 标记):')
    lines.append('')
    lines.append('```')
    lines.append(o_context[:o_marker_pos] + '←' + o_context[o_marker_pos:])
    lines.append('```')
    lines.append('')
    lines.append('**output 上下文** (差异位置用 ← 标记):')
    lines.append('')
    lines.append('```')
    lines.append(u_context[:u_marker_pos] + '←' + u_context[u_marker_pos:])
    lines.append('```')
    lines.append('')

    if len(origin_chars) != len(output_chars):
        diff = len(output_chars) - len(origin_chars)
        if diff > 0:
            lines.append(f'**output 比 origin 多 {diff} 个字符**')
            lines.append('')
            lines.append('output 尾部多出的字符:')
            lines.append('')
            lines.append('```')
            tail_start = max(0, len(output_chars) - 200)
            lines.append(output_chars[tail_start:])
            lines.append('```')
        else:
            lines.append(f'**output 比 origin 少 {-diff} 个字符**')
            lines.append('')
            lines.append('origin 尾部缺失的字符:')
            lines.append('')
            lines.append('```')
            tail_start = max(0, len(origin_chars) - 200)
            lines.append(origin_chars[tail_start:])
            lines.append('```')
        lines.append('')

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return report_path


# ============================================================
# 命令入口
# ============================================================

def cmd_prepare(args):
    if args.start > args.end:
        print(f'错误: start ({args.start}) 不能大于 end ({args.end})', file=sys.stderr)
        sys.exit(2)
    if args.start < 1:
        print(f'错误: start ({args.start}) 不能小于 1', file=sys.stderr)
        sys.exit(2)

    os.makedirs(args.output_dir, exist_ok=True)

    print('=' * 60)
    print(f'prepare: 共 {args.end - args.start + 1} 章')
    print('=' * 60)

    for n in range(args.start, args.end + 1):
        origin_path = os.path.join(args.base_dir, 'origin', f'{n}.txt')
        draft_path = os.path.join(args.output_dir, f'{n}.draft.md')

        if not os.path.exists(origin_path):
            print(f'  [{n}] ✗ 缺失 origin/{n}.txt')
            continue

        ok, stats = prepare_chapter(origin_path, draft_path, args.max_len)
        if not ok:
            print(f'  [{n}] ✗ {stats.get("error", "unknown error")}')
            continue

        # 同时生成 sentences.txt（省去单独调用 list-sentences）
        sentences_path = os.path.join(args.output_dir, f'{n}.sentences.txt')
        list_sentences(draft_path, sentences_path)

        print(f'  [{n}] ✓ prepared: '
              f'标题={stats["title"][:20]}, '
              f'副标题={stats["subtitle_count"]}, '
              f'颂偈={stats["verse_count"]}, '
              f'短段={stats["short_para_count"]}, '
              f'长段={stats["long_para_count"]}({stats["long_para_sentence_count"]}句)')

    print()
    print(f'draft 文件: {args.output_dir}/{args.start}.draft.md ~ {args.output_dir}/{args.end}.draft.md')
    print(f'sentences 文件: {args.output_dir}/{args.start}.sentences.txt ~ {args.output_dir}/{args.end}.sentences.txt')
    print()
    print('下一步：读取 sentences.txt，写 splits.txt（每行一个编号如 P1S5），')
    print('然后运行 apply-splits + enforce-length 完成分割。')


def cmd_finalize(args):
    if args.start > args.end:
        print(f'错误: start ({args.start}) 不能大于 end ({args.end})', file=sys.stderr)
        sys.exit(2)
    if args.start < 1:
        print(f'错误: start ({args.start}) 不能小于 1', file=sys.stderr)
        sys.exit(2)

    os.makedirs(args.output_dir, exist_ok=True)

    results = []
    for n in range(args.start, args.end + 1):
        origin_path = os.path.join(args.base_dir, 'origin', f'{n}.txt')
        draft_path = os.path.join(args.output_dir, f'{n}.draft.md')
        output_path = os.path.join(args.output_dir, f'{n}.md')
        report_path = os.path.join(args.output_dir, f'{n}.check_split.md')

        if not os.path.exists(draft_path):
            print(f'  [{n}] ✗ 缺失 {args.output_dir}/{n}.draft.md', file=sys.stderr)
            write_report(report_path, n, False,
                         '', '', 0, {}, error=f'draft/{n}.draft.md missing')
            results.append({'chapter': n, 'ok': False, 'stats': {}})
            continue

        if not os.path.exists(origin_path):
            print(f'  [{n}] ✗ 缺失 origin/{n}.txt', file=sys.stderr)
            write_report(report_path, n, False,
                         '', '', 0, {}, error=f'origin/{n}.txt missing')
            results.append({'chapter': n, 'ok': False, 'stats': {}})
            continue

        _, stats = finalize_chapter(draft_path, output_path)
        ok, origin_chars, output_chars, diff_pos = verify_chapter(origin_path, output_path)

        write_report(report_path, n, ok,
                     origin_chars, output_chars, diff_pos, stats)

        results.append({
            'chapter': n,
            'ok': ok,
            'stats': stats,
            'diff_pos': diff_pos,
            'origin_len': len(origin_chars),
            'output_len': len(output_chars),
        })

    # 汇总
    print('=' * 60)
    total = len(results)
    ok_count = sum(1 for r in results if r['ok'])
    fail_count = total - ok_count
    print(f'finalize: 共 {total} 章, 通过 {ok_count} 章, 失败 {fail_count} 章')
    print('=' * 60)
    print()

    for r in results:
        n = r['chapter']
        ok = r['ok']
        stats = r.get('stats', {})
        status = '✓' if ok else '✗'
        if not ok:
            print(f'  [{n}] {status} 校验失败 (diff@{r.get("diff_pos")}, '
                  f'origin={r.get("origin_len")}, output={r.get("output_len")})')
        else:
            print(f'  [{n}] {status} 长段={stats.get("long_para_count", 0)} '
                  f'-> 分割后={stats.get("long_para_group_count", 0)} 段')

    print()
    print(f'最终文件: {args.output_dir}/{args.start}.md ~ {args.output_dir}/{args.end}.md')
    print(f'校验报告: {args.output_dir}/{args.start}.check_split.md ~ {args.output_dir}/{args.end}.check_split.md')

    has_fail = any(not r['ok'] for r in results)
    sys.exit(1 if has_fail else 0)


def cmd_enforce_length(args):
    """强制切分超过长度限制的段落。

    直接读取 draft.md（已 apply-splits），在超长组中插入空行，
    然后重新 finalize。不通过 splits.txt，避免 ID 不一致问题。
    """
    if args.start > args.end:
        print(f'错误: start ({args.start}) 不能大于 end ({args.end})', file=sys.stderr)
        sys.exit(2)

    os.makedirs(args.output_dir, exist_ok=True)

    print('=' * 60)
    print(f'enforce-length: 共 {args.end - args.start + 1} 章, 最大 {args.max_len} 字')
    print('=' * 60)

    has_fail = False
    for n in range(args.start, args.end + 1):
        draft_path = os.path.join(args.output_dir, f'{n}.draft.md')
        output_path = os.path.join(args.output_dir, f'{n}.md')
        origin_path = os.path.join(args.base_dir, 'origin', f'{n}.txt')

        if not os.path.exists(draft_path):
            print(f'  [{n}] ✗ 缺失 {n}.draft.md')
            has_fail = True
            continue

        # 读取 draft.md
        with open(draft_path, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')

        modified = False
        enforced_count = 0

        in_long_para = False
        group_start = -1  # 当前组在 lines 中的起始索引
        group_texts = []

        i = 0
        while i < len(lines):
            line = lines[i]

            if line == LONG_PARA_START:
                in_long_para = True
                group_start = -1
                group_texts = []
                i += 1
                continue

            if line == LONG_PARA_END:
                # 处理最后一个组
                if group_start >= 0 and group_texts:
                    total_len = sum(len(t) for t in group_texts)
                    if total_len > args.max_len:
                        _insert_splits(lines, group_start, i, group_texts, args.max_len)
                        enforced_count += 1
                        modified = True
                in_long_para = False
                group_start = -1
                group_texts = []
                i += 1
                continue

            if in_long_para and line == '':
                # 空行：分割点，结束当前组
                if group_start >= 0 and group_texts:
                    total_len = sum(len(t) for t in group_texts)
                    if total_len > args.max_len:
                        _insert_splits(lines, group_start, i, group_texts, args.max_len)
                        enforced_count += 1
                        modified = True
                group_start = -1
                group_texts = []
                i += 1
                continue

            if in_long_para and line.startswith(INDENT):
                if group_start < 0:
                    group_start = i
                text = line[len(INDENT):]
                group_texts.append(text)
                i += 1
                continue

            i += 1

        if modified:
            # 写回 draft.md
            with open(draft_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')

        # 总是 finalize + 校验（无论是否修改）
        _, finalize_stats = finalize_chapter(draft_path, output_path)
        ok, origin_chars, output_chars, diff_pos = verify_chapter(origin_path, output_path)

        report_path = os.path.join(args.output_dir, f'{n}.check_split.md')
        write_report(report_path, n, ok, origin_chars, output_chars, diff_pos, finalize_stats)

        if not ok:
            has_fail = True
            print(f'  [{n}] ✗ 校验失败 (diff@char={diff_pos})')
        elif modified:
            print(f'  [{n}] ✓ 强制分割 {enforced_count} 组, '
                  f'分割后={finalize_stats.get("long_para_group_count", "?")} 段')
        else:
            print(f'  [{n}] ✓ 无超长组, '
                  f'分割后={finalize_stats.get("long_para_group_count", "?")} 段')

    print()
    print(f'最终文件: {args.output_dir}/{args.start}.md ~ {args.output_dir}/{args.end}.md')
    print(f'校验报告: {args.output_dir}/{args.start}.check_split.md ~ {args.output_dir}/{args.end}.check_split.md')
    sys.exit(1 if has_fail else 0)


def _insert_splits(lines, group_start, before_end, group_texts, max_len):
    """在超长组中插入空行。

    在 lines 中从 group_start 到 before_end-1 之间，在适当位置插入空行。
    group_texts 是组内句子的文本列表（不含 　　 前缀）。
    每句在 lines 中占一行，格式为 　　 + text。
    """
    # 找到组内所有句子行
    sent_lines = []
    for j in range(group_start, before_end):
        if lines[j].startswith(INDENT):
            sent_lines.append(j)

    if len(sent_lines) != len(group_texts):
        return  # 不匹配，跳过

    # 按字符数插入分割点
    running = 0
    inserts = []  # 需要插入空行的位置（在 sent_lines[i] 之后）
    for i in range(len(sent_lines) - 1):
        running += len(group_texts[i])
        next_len = len(group_texts[i + 1])
        if running + next_len > max_len and running > 0:
            inserts.append(sent_lines[i] + 1)  # 在该行后插入空行
            running = 0

    # 从后往前插入（避免索引偏移）
    for pos in reversed(inserts):
        lines.insert(pos, '')


def cmd_list_sentences(args):
    if args.start > args.end:
        print(f'错误: start ({args.start}) 不能大于 end ({args.end})', file=sys.stderr)
        sys.exit(2)

    os.makedirs(args.output_dir, exist_ok=True)

    print('=' * 60)
    print(f'list-sentences: 共 {args.end - args.start + 1} 章')
    print('=' * 60)

    for n in range(args.start, args.end + 1):
        draft_path = os.path.join(args.output_dir, f'{n}.draft.md')
        sentences_path = os.path.join(args.output_dir, f'{n}.sentences.txt')

        if not os.path.exists(draft_path):
            print(f'  [{n}] ✗ 缺失 {n}.draft.md')
            continue

        ok, stats = list_sentences(draft_path, sentences_path)
        if not ok:
            print(f'  [{n}] ✗ 失败')
            continue

        print(f'  [{n}] ✓ 长段落={stats["long_para_count"]}, '
              f'总句数={stats["total_sentences"]}')

    print()
    print(f'sentences 文件: {args.output_dir}/{args.start}.sentences.txt ~ {args.output_dir}/{args.end}.sentences.txt')
    print()
    print('下一步：读取 sentences.txt，在编号列表中标记分割点，')
    print('写入 splits.txt（每行一个编号如 P1S5），')
    print('然后运行 apply-splits 子命令应用分割。')


def cmd_apply_splits(args):
    if args.start > args.end:
        print(f'错误: start ({args.start}) 不能大于 end ({args.end})', file=sys.stderr)
        sys.exit(2)

    os.makedirs(args.output_dir, exist_ok=True)

    print('=' * 60)
    print(f'apply-splits: 共 {args.end - args.start + 1} 章')
    print('=' * 60)

    for n in range(args.start, args.end + 1):
        draft_path = os.path.join(args.output_dir, f'{n}.draft.md')
        splits_path = os.path.join(args.output_dir, f'{n}.splits.txt')

        if not os.path.exists(draft_path):
            print(f'  [{n}] ✗ 缺失 {n}.draft.md')
            continue

        if not os.path.exists(splits_path):
            print(f'  [{n}] ✗ 缺失 {n}.splits.txt（请先创建分割点文件）')
            continue

        ok, stats = apply_splits(draft_path, splits_path)

        if ok:
            print(f'  [{n}] ✓ 分割点={stats["total"]}, '
                  f'新增={stats["applied"]}, 已存在={stats["already_present"]}')
        else:
            not_found = stats['not_found']
            parse_errors = stats.get('parse_errors', [])
            if parse_errors:
                print(f'  [{n}] ✗ 解析错误 {len(parse_errors)} 个（格式应为 P{{段号}}S{{句号}}）:')
                for s in parse_errors[:5]:
                    print(f'       - {s[:50]}')
            if not_found:
                print(f'  [{n}] ✗ 未找到 {len(not_found)}/{stats["total"]} 个分割点:')
                for s in not_found[:5]:
                    print(f'       - {s[:50]}')
                if len(not_found) > 5:
                    print(f'       ... (共 {len(not_found)} 个)')

    print()
    print(f'draft 文件: {args.output_dir}/{args.start}.draft.md ~ {args.output_dir}/{args.end}.draft.md')
    print()
    print('下一步：运行 finalize 子命令生成最终 output/{N}.md。')


def main():
    parser = argparse.ArgumentParser(
        description='分割 origin/*.txt 到 output/*.md，使用 LLM 做语义分割'
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    prepare_parser = subparsers.add_parser('prepare', help='生成 draft.md')
    prepare_parser.add_argument('start', type=int, help='起始章节号 (包含)')
    prepare_parser.add_argument('end', type=int, help='结束章节号 (包含)')
    prepare_parser.add_argument('--base-dir', default='.', help='项目根目录 (默认当前目录)')
    prepare_parser.add_argument('--output-dir', default='output', help='输出目录 (默认 output)')
    prepare_parser.add_argument('--max-len', type=int, default=MAX_LEN_DEFAULT,
                               help=f'段落最大字符数 (默认 {MAX_LEN_DEFAULT})')

    list_sentences_parser = subparsers.add_parser('list-sentences',
                                                   help='从 draft.md 提取长段落句子带编号列表')
    list_sentences_parser.add_argument('start', type=int, help='起始章节号 (包含)')
    list_sentences_parser.add_argument('end', type=int, help='结束章节号 (包含)')
    list_sentences_parser.add_argument('--base-dir', default='.', help='项目根目录 (默认当前目录)')
    list_sentences_parser.add_argument('--output-dir', default='output', help='输出目录 (默认 output)')

    apply_splits_parser = subparsers.add_parser('apply-splits', help='应用 splits.txt 到 draft.md')
    apply_splits_parser.add_argument('start', type=int, help='起始章节号 (包含)')
    apply_splits_parser.add_argument('end', type=int, help='结束章节号 (包含)')
    apply_splits_parser.add_argument('--base-dir', default='.', help='项目根目录 (默认当前目录)')
    apply_splits_parser.add_argument('--output-dir', default='output', help='输出目录 (默认 output)')

    finalize_parser = subparsers.add_parser('finalize', help='把 draft.md 转换为最终 .md 并校验')
    finalize_parser.add_argument('start', type=int, help='起始章节号 (包含)')
    finalize_parser.add_argument('end', type=int, help='结束章节号 (包含)')
    finalize_parser.add_argument('--base-dir', default='.', help='项目根目录 (默认当前目录)')
    finalize_parser.add_argument('--output-dir', default='output', help='输出目录 (默认 output)')

    enforce_parser = subparsers.add_parser('enforce-length', help='强制切分超过长度限制的段落')
    enforce_parser.add_argument('start', type=int, help='起始章节号 (包含)')
    enforce_parser.add_argument('end', type=int, help='结束章节号 (包含)')
    enforce_parser.add_argument('--base-dir', default='.', help='项目根目录 (默认当前目录)')
    enforce_parser.add_argument('--output-dir', default='output', help='输出目录 (默认 output)')
    enforce_parser.add_argument('--max-len', type=int, default=300, help='段落最大字符数 (默认 300)')

    args = parser.parse_args()

    if args.command == 'prepare':
        cmd_prepare(args)
    elif args.command == 'list-sentences':
        cmd_list_sentences(args)
    elif args.command == 'apply-splits':
        cmd_apply_splits(args)
    elif args.command == 'finalize':
        cmd_finalize(args)
    elif args.command == 'enforce-length':
        cmd_enforce_length(args)


if __name__ == '__main__':
    main()
