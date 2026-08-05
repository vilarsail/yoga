#!/usr/bin/env python3
"""
apply_fix.py - 合并各批修复判断，对 output/{N}.md 应用 ACCEPT 的修复，
生成 output/{N}.fix.md 修复记录。

读取：
- fix_{N}_pairs.json（全部问题 + 原文 + 当前译文，由 prepare_fix.py 生成）
- fix_{N}_batch*.verdict.json（子 Agent 判断结果：verdict / reason / new_trans）

输出：
- 更新 output/{N}.md（用 new_trans 替换 ACCEPT 的译文段；MISSING 情况在原文段后插入）
- 生成 output/{N}.fix.md（格式化修复记录）

替换策略：按段落号定位原文段（　　 开头），找到其后紧跟的译文段（* 开头块），
整体替换为 new_trans。MISSING 情况（无译文块）在原文段后插入 new_trans。
从后往前处理以避免行索引偏移。
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

# 状态标签
STATUS_LABEL = {
    'applied': '✅ 已修复',
    'rejected': '❌ 不成立，未修复',
    'validation_failed': '⚠️ 校验失败，未修复',
    'application_failed': '⚠️ 应用失败',
    'batch_failed': '⚠️ 批次解析失败',
}


def load_verdicts_json(path: str) -> dict | None:
    """读取子 Agent 判断 JSON，失败时尝试自动修复。

    修复策略（三段）：
    1. 直接 json.load（主路径，绝大多数情况命中）
    2. 按段落号键切分，对每个对象单独 json.loads（处理整体 JSON 损坏但单个对象合法的情况）
    3. 字段级正则提取（最后兜底，处理单个对象内部也有语法错误的情况）
    """
    # 路径 1：直接解析
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

    # 按段落号键边界切分
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

        # 路径 2：对单个对象尝试 json.loads
        # obj_raw 已经是 {...} 形式（含外层花括号），直接解析即可
        try:
            obj = json.loads(obj_raw)
            result[key] = obj
            continue
        except (json.JSONDecodeError, ValueError):
            pass

        # 路径 3：字段级正则提取（兜底）
        fields = {}
        # verdict：值不含引号，用严格正则
        vm = re.search(r'"verdict"\s*:\s*"([^"]*)"', obj_raw)
        if vm:
            fields['verdict'] = vm.group(1)
        # reason / new_trans：值可能含转义字符，用 (?:[^"\\]|\\.)* 匹配跨行值
        rm = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"', obj_raw, flags=re.DOTALL)
        if rm:
            fields['reason'] = rm.group(1).replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n')
        ntm = re.search(r'"new_trans"\s*:\s*"((?:[^"\\]|\\.)*)"', obj_raw, flags=re.DOTALL)
        if ntm:
            fields['new_trans'] = ntm.group(1).replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n')

        if fields:
            result[key] = fields

    if result:
        print(f'  [repair] {os.path.basename(path)}: JSON 损坏，已自动修复 {len(result)} 条')
        return result
    print(f'  [WARN] {os.path.basename(path)}: 无法解析，跳过此批次')
    return None


def validate_new_trans(new_trans: str, orig: str) -> tuple[bool, str]:
    """校验 new_trans 格式是否合规。

    检查项：
    1. 非空且长度 >= 2（至少 *x*）
    2. 以 * 开头且以 * 结尾
    3. 颂偈行数匹配：若原文多行（颂偈），新译文行数必须与原文一致
       （格式 A 每行 * 和格式 B 整块 * 的行数都与原文相同）

    注：不校验格式 A/B 与原 trans 的一致性--check-yoga 视两种格式均为合法，
    强制一致会误拒合法的格式转换。仅做基本结构与行数校验。
    """
    if not new_trans or len(new_trans) < 2:
        return False, 'new_trans 为空或过短'
    if not new_trans.startswith('*'):
        return False, 'new_trans 未以 * 开头'
    if not new_trans.endswith('*'):
        return False, 'new_trans 未以 * 结尾'
    orig_lines = orig.split('\n') if orig else []
    if len(orig_lines) > 1:
        new_lines = new_trans.split('\n')
        if len(new_lines) != len(orig_lines):
            return False, f'颂偈行数不匹配：原文 {len(orig_lines)} 行，新译文 {len(new_lines)} 行'
    return True, ''


def find_trans_block_range(lines: list[str], orig_end_idx: int) -> tuple[int, int] | None:
    """从原文段结束行后，定位译文块的起止行索引（含）。"""
    n = len(lines)
    i = orig_end_idx + 1
    while i < n and lines[i].strip() == '':
        i += 1
    if i >= n or not lines[i].startswith('*'):
        return None
    start = i
    i += 1
    while i < n:
        line = lines[i]
        if line.startswith('*'):
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
            i += 1
    return start, i - 1


def locate_paragraph_block(lines: list[str], para_num: int) -> tuple[int, int, int, int] | None:
    """定位第 para_num 个原文段 + 译文块的行索引范围。

    返回 (orig_start, orig_end, trans_start, trans_end)，行号 0-based。
    orig_end / trans_end 含（即该行属于块）。
    若译文块不存在（MISSING），trans_start = trans_end = -1。
    """
    n = len(lines)
    idx = 0
    i = 0
    while i < n:
        if lines[i].startswith('　　'):
            idx += 1
            if idx == para_num:
                orig_start = i
                orig_end = i
                i += 1
                while i < n and lines[i].startswith('　　'):
                    orig_end = i
                    i += 1
                rng = find_trans_block_range(lines, orig_end)
                if rng is None:
                    return orig_start, orig_end, -1, -1
                return orig_start, orig_end, rng[0], rng[1]
            else:
                i += 1
                while i < n and lines[i].startswith('　　'):
                    i += 1
        else:
            i += 1
    return None


def replace_trans_block(lines: list[str], trans_start: int, trans_end: int,
                        new_trans: str) -> list[str]:
    """用 new_trans 替换 [trans_start, trans_end] 的译文块。"""
    new_lines = new_trans.split('\n')
    return lines[:trans_start] + new_lines + lines[trans_end + 1:]


def insert_trans_block(lines: list[str], orig_end: int, new_trans: str) -> list[str]:
    """在原文段后插入新译文块（MISSING 情况）。

    在 orig_end 后插入：空行 + new_trans + 空行，替换原有的空行区域。
    确保原文与译文之间、译文与下一段之间各有一个空行。
    """
    n = len(lines)
    j = orig_end + 1
    while j < n and lines[j].strip() == '':
        j += 1
    new_lines = new_trans.split('\n')
    # lines[:orig_end+1] = 原文段及之前
    # [''] = 原文与译文之间的空行
    # new_lines = 新译文
    # [''] = 译文与下一段之间的空行
    # lines[j:] = 下一段内容（跳过原有空行，由插入的 ['' ] 替代）
    return lines[:orig_end + 1] + [''] + new_lines + [''] + lines[j:]


def main():
    if len(sys.argv) < 2:
        print("Usage: python apply_fix.py <N>", file=sys.stderr)
        sys.exit(1)
    n = int(sys.argv[1])

    pairs_path = f'fix_{n}_pairs.json'
    if not os.path.exists(pairs_path):
        print(f"Error: {pairs_path} not found. Run prepare_fix.py first.", file=sys.stderr)
        sys.exit(1)

    pairs = json.load(open(pairs_path, encoding='utf-8'))
    if not pairs:
        out_path = f'output/{n}.fix.md'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(f'# output/{n}.md 译文修复报告\n\n')
            f.write(f'- 修复时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}\n')
            f.write(f'- 校对问题数：0\n\n')
            f.write('✅ 校对报告未发现问题，本文件无需修复。\n')
        print(f'No issues. Generated {out_path}.')
        return

    # 合并各批 verdicts（扫描 .verdict.json 文件，保留原始批次文件）
    verdicts = {}
    batch_files_failed = []
    for path in sorted(glob.glob(f'fix_{n}_batch*.verdict.json')):
        batch = load_verdicts_json(path)
        if batch is None:
            batch_files_failed.append(os.path.basename(path))
            continue
        for key, value in batch.items():
            if key.startswith('_'):
                continue
            verdicts[key] = value

    # 读取 output/{n}.md
    md_path = f'output/{n}.md'
    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')

    def sort_key(k):
        try:
            return int(k)
        except ValueError:
            return 10 ** 9

    # 全部问题段落号（以 pairs 为基准，确保批次解析失败的段落也出现在报告中）
    all_keys = sorted(pairs.keys(), key=sort_key)

    # 第一遍：确定每条状态（不修改 lines）
    # status: k -> (status_code, type, detail)
    # status_code: applied / rejected / validation_failed / application_failed / batch_failed
    status = {}
    to_apply = []  # 待应用的段落号（ACCEPT + 校验通过）
    for k in all_keys:
        t = pairs.get(k, {}).get('type', 'OTHER')
        if k not in verdicts:
            status[k] = ('batch_failed', t, '批次解析失败：该段所在批次文件无法解析')
            continue
        v = verdicts[k]
        verdict = v.get('verdict', '').upper()
        new_trans = v.get('new_trans', '').strip()
        reason = v.get('reason', '')
        if verdict != 'ACCEPT':
            status[k] = ('rejected', t, reason)
        elif not new_trans:
            status[k] = ('validation_failed', t, 'ACCEPT 但 new_trans 为空')
        else:
            is_valid, val_reason = validate_new_trans(
                new_trans, pairs[k].get('orig', ''))
            if not is_valid:
                status[k] = ('validation_failed', t, val_reason)
            else:
                to_apply.append(k)
                status[k] = ('pending', t, reason)

    # 第二遍：从后往前应用（避免行索引偏移）
    for k in sorted(to_apply, key=sort_key, reverse=True):
        try:
            para_num = int(k)
        except ValueError:
            status[k] = ('application_failed', status[k][1], '段落号无效')
            continue
        result = locate_paragraph_block(lines, para_num)
        if result is None:
            status[k] = ('application_failed', status[k][1], '段落未在 .md 中找到')
            continue
        _, orig_end, trans_start, trans_end = result
        new_trans = verdicts[k].get('new_trans', '').strip()
        if trans_start == -1:
            # MISSING 情况：原文段后无译文，插入新译文
            lines = insert_trans_block(lines, orig_end, new_trans)
        else:
            lines = replace_trans_block(lines, trans_start, trans_end, new_trans)
        status[k] = ('applied', status[k][1], status[k][2])

    # 写回 output/{n}.md
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    # 统计
    total = len(all_keys)
    counts = {s: 0 for s in STATUS_LABEL}
    for k, (st, _, _) in status.items():
        counts[st] = counts.get(st, 0) + 1
    applied_count = counts['applied']
    pct = 100.0 * applied_count / total if total else 0

    # 按类型统计
    by_type = {}  # type -> {status: count}
    for k, (st, t, _) in status.items():
        by_type.setdefault(t, {s: 0 for s in STATUS_LABEL})
        by_type[t][st] += 1

    # 生成 fix.md 报告
    out_path = f'output/{n}.fix.md'
    L = []
    L.append(f'# output/{n}.md 译文修复报告')
    L.append('')
    L.append(f'- 修复时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}')
    L.append(f'- 校对问题数：{total}')
    L.append(f'- 成立并修复：{applied_count}（占 {pct:.1f}%）')
    L.append(f'- 不成立：{counts["rejected"]}')
    L.append(f'- 校验失败：{counts["validation_failed"]}')
    L.append(f'- 应用失败：{counts["application_failed"]}')
    L.append(f'- 批次解析失败：{counts["batch_failed"]}')
    if batch_files_failed:
        L.append(f'- 解析失败批次文件：{", ".join(batch_files_failed)}')
    L.append('')

    if total == 0:
        L.append('✅ 无校对问题，本文件无需修复。')
    else:
        L.append('## 修复记录')
        L.append('')
        for k in all_keys:
            pair = pairs.get(k, {})
            t = pair.get('type', 'OTHER')
            label = TYPE_LABEL.get(t, '其它质量')
            st_code, _, detail = status[k]
            st_label = STATUS_LABEL.get(st_code, st_code)

            L.append(f'### 段落 {k} 【{label}】 {st_label}')
            L.append('')
            orig = pair.get('orig', '')
            old_trans = pair.get('trans', '')
            problem = pair.get('problem', '')
            suggestion = pair.get('suggestion', '')

            if orig:
                L.append(f'- **原文**：{orig}')
            if old_trans:
                L.append(f'- **原译文**：{old_trans}')
            elif t == 'MISSING':
                L.append('- **原译文**：（无）')
            if problem:
                L.append(f'- **校对问题**：{problem}')
            if suggestion:
                L.append(f'- **修改建议**：{suggestion}')

            v = verdicts.get(k, {})
            reason = v.get('reason', '')
            new_trans = v.get('new_trans', '').strip()

            if st_code == 'applied':
                if reason:
                    L.append(f'- **判断依据**：{reason}')
                if new_trans:
                    L.append(f'- **新译文**：{new_trans}')
            elif st_code == 'rejected':
                if reason:
                    L.append(f'- **判断依据**：{reason}')
            elif st_code == 'validation_failed':
                if reason:
                    L.append(f'- **判断依据**：{reason}')
                L.append(f'- **校验失败原因**：{detail}')
            elif st_code == 'application_failed':
                if reason:
                    L.append(f'- **判断依据**：{reason}')
                L.append(f'- **应用失败原因**：{detail}')
            elif st_code == 'batch_failed':
                L.append(f'- **批次失败说明**：{detail}')
            L.append('')

        L.append('## 汇总')
        L.append('')
        L.append(f'- 总问题数：{total}')
        L.append(f'- 已修复：{applied_count}')
        L.append(f'- 不成立：{counts["rejected"]}')
        L.append(f'- 校验失败：{counts["validation_failed"]}')
        L.append(f'- 应用失败：{counts["application_failed"]}')
        L.append(f'- 批次解析失败：{counts["batch_failed"]}')
        L.append('')
        L.append('按问题类型统计：')
        for t in TYPE_ORDER:
            if t not in by_type:
                continue
            stats = by_type[t]
            parts = []
            for s in ['applied', 'rejected', 'validation_failed', 'application_failed', 'batch_failed']:
                if stats.get(s, 0) > 0:
                    parts.append(f'{STATUS_LABEL[s]} {stats[s]}')
            if parts:
                L.append(f'- {TYPE_LABEL[t]}（{t}）：{" / ".join(parts)}')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')

    print(f'Applied {applied_count}/{total} fixes to {md_path}')
    print(f'Generated {out_path}')
    if counts['validation_failed']:
        print(f'  Validation failed: {counts["validation_failed"]}')
    if counts['application_failed']:
        print(f'  Application failed: {counts["application_failed"]}')
    if counts['batch_failed']:
        print(f'  Batch parse failed: {counts["batch_failed"]}')


if __name__ == '__main__':
    main()
