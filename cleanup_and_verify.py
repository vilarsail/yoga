#!/usr/bin/env python3
"""批量校对与清理 output/{N}.md

1. 移除 origin/{20,40,60,80}.txt 和 output/{20,40,60,80}.md 末尾的 CBETA 元数据
2. 清理 output 中的多余空行、行尾空白
3. 重新校验字符流一致性
"""
import os
import re
import sys

ORIGIN_DIR = '/Users/zhangwei/work/yoga/origin'
OUTPUT_DIR = '/Users/zhangwei/work/yoga/output'

# CBETA 元数据特征行（出现在文件末尾）
CBETA_FOOTER_PATTERNS = [
    re.compile(r'^第1164-\d+部'),
    re.compile(r'^大乘论·第\d+部'),
    re.compile(r'^瑜伽师地论一百卷'),
    re.compile(r'^弥勒菩萨说'),
]

WHITESPACE_CHARS = set(' \t\r\n　＀\xa0')


def is_cbeta_footer_line(line):
    """判断一行是否是 CBETA 元数据行"""
    s = line.strip()
    if not s:
        return False
    for pat in CBETA_FOOTER_PATTERNS:
        if pat.match(s):
            return True
    return False


def strip_cbeta_footer_origin(path):
    """从 origin 文件移除末尾 CBETA 元数据"""
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')
    # 找到最后一个非空非 CBETA 行
    last_content = -1
    for i, line in enumerate(lines):
        s = line.rstrip()
        if s and not is_cbeta_footer_line(s):
            last_content = i
    if last_content < 0:
        return False, 0
    # 保留到 last_content，去掉其后所有行
    new_lines = lines[:last_content + 1]
    removed = len(lines) - len(new_lines)
    if removed <= 0:
        return False, 0
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    return True, removed


def strip_cbeta_footer_output(path):
    """从 output 文件移除末尾 CBETA 元数据（## 标题形式）"""
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')
    # 找到最后一个非空非 CBETA 行
    last_content = -1
    for i, line in enumerate(lines):
        s = line.rstrip()
        if not s:
            continue
        # 去掉 ## 前缀后判断
        stripped = s.lstrip('#').lstrip()
        is_footer = False
        for pat in CBETA_FOOTER_PATTERNS:
            if pat.match(stripped):
                is_footer = True
                break
        if not is_footer:
            last_content = i
    if last_content < 0:
        return False, 0
    new_lines = lines[:last_content + 1]
    removed = len(lines) - len(new_lines)
    if removed <= 0:
        return False, 0
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    return True, removed


def cleanup_output_format(path):
    """清理 output 中的格式问题：
    - 行尾空白
    - 连续多个空行 -> 单个空行
    """
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.split('\n')
    # 去行尾空白
    lines = [line.rstrip() for line in lines]
    # 合并连续空行：最多保留 1 个空行
    new_lines = []
    prev_blank = False
    for line in lines:
        if line == '':
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        new_lines.append(line)
    # 去掉末尾空行
    while new_lines and new_lines[-1] == '':
        new_lines.pop()
    new_content = '\n'.join(new_lines) + '\n'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)


def extract_chars(content, is_output=False):
    """提取实质字符流（与 split_origin.py 一致）"""
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
    """校验字符流一致性"""
    with open(origin_path, 'r', encoding='utf-8') as f:
        origin_content = f.read()
    with open(output_path, 'r', encoding='utf-8') as f:
        output_content = f.read()
    origin_chars = extract_chars(origin_content, is_output=False)
    output_chars = extract_chars(output_content, is_output=True)
    if origin_chars == output_chars:
        return True, 0, 0, -1
    diff_pos = -1
    for i in range(min(len(origin_chars), len(output_chars))):
        if origin_chars[i] != output_chars[i]:
            diff_pos = i
            break
    if diff_pos == -1:
        diff_pos = min(len(origin_chars), len(output_chars))
    return False, len(origin_chars), len(output_chars), diff_pos


def main():
    start, end = 1, 100
    print('=' * 60)
    print(f'阶段 1: 移除 CBETA 元数据（origin + output）')
    print('=' * 60)
    for n in range(start, end + 1):
        origin_path = os.path.join(ORIGIN_DIR, f'{n}.txt')
        output_path = os.path.join(OUTPUT_DIR, f'{n}.md')
        if not os.path.exists(origin_path) or not os.path.exists(output_path):
            continue
        # origin
        o_changed, o_removed = strip_cbeta_footer_origin(origin_path)
        # output
        u_changed, u_removed = strip_cbeta_footer_output(output_path)
        if o_changed or u_changed:
            print(f'  [{n}] origin 移除 {o_removed} 行, output 移除 {u_removed} 行')

    print()
    print('=' * 60)
    print(f'阶段 2: 清理 output 格式（行尾空白、多余空行）')
    print('=' * 60)
    for n in range(start, end + 1):
        output_path = os.path.join(OUTPUT_DIR, f'{n}.md')
        if not os.path.exists(output_path):
            continue
        cleanup_output_format(output_path)
    print(f'  全部 {end - start + 1} 章已清理')

    print()
    print('=' * 60)
    print(f'阶段 3: 字符流校验')
    print('=' * 60)
    all_ok = True
    failed = []
    for n in range(start, end + 1):
        origin_path = os.path.join(ORIGIN_DIR, f'{n}.txt')
        output_path = os.path.join(OUTPUT_DIR, f'{n}.md')
        if not os.path.exists(origin_path) or not os.path.exists(output_path):
            print(f'  [{n}] ✗ 文件缺失')
            all_ok = False
            failed.append(n)
            continue
        ok, o_len, u_len, diff_pos = verify_chapter(origin_path, output_path)
        if ok:
            pass  # 静默
        else:
            print(f'  [{n}] ✗ 差异位置 {diff_pos} (origin={o_len}, output={u_len})')
            all_ok = False
            failed.append(n)
    if all_ok:
        print(f'  全部 {end - start + 1} 章字符流校验通过 ✓')
    else:
        print(f'  失败章节: {failed}')
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
