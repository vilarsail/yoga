#!/usr/bin/env python3
"""
build_epub.py - 把 output/ 下的导读、原文、注释打包为《瑜伽师地论》epub。

顺序：前言(0.md) → 各卷 guide/md/notes，共 100 卷。
使用 pandoc 转换为 epub，带封面、目录。

用法：
    python3 build_epub.py                  # 打包 output/0-100，封面 cover.jpg
    python3 build_epub.py 1 50             # 打包指定区间（不含前言）
    python3 build_epub.py -o 瑜伽.epub     # 自定义输出文件名
    python3 build_epub.py -c cover.png     # 自定义封面
    python3 build_epub.py --no-cover       # 不使用封面（用 -c "" 触发）
"""

from __future__ import annotations
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OUTPUT_DIR = Path('output')
DEFAULT_OUT = '瑜伽师地论.epub'
TITLE = '瑜伽师地论'
AUTHOR = '弥勒菩萨说 玄奘译'
LIST_CSS = Path('epub-list.css')  # 显式列表样式，保证阅读器正确显示列表


def collect_files(start: int, end: int) -> list[Path]:
    """收集文件，顺序：前言(0.md) → 各卷 guide/md/notes。跳过缺失的。"""
    files = []
    # 前言
    preface = OUTPUT_DIR / '0.md'
    if preface.exists():
        files.append(preface)
    # 各卷
    for n in range(start, end + 1):
        for suffix in ('guide.md', 'md', 'notes.md'):
            p = OUTPUT_DIR / f'{n}.{suffix}'
            if p.exists():
                files.append(p)
    return files


# 带圈数字（圈码）1~50，作为原文标注与注释条目的唯一编号依据
# 顺序即编号：①=1, ⑩=10, ⑳=20, ㉑=21, ㉟=30, ㊱=31, ㊿=50
CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿'
CIRCLED_RE = re.compile('[' + CIRCLED + ']')


def glyph_index(ch: str) -> int | None:
    """圈码 → 编号（1 起）。非圈码返回 None。"""
    i = CIRCLED.find(ch)
    return (i + 1) if i >= 0 else None


def note_indicies(notes_text: str) -> set[int]:
    """从注释文件提取注释条目的圈码编号集合（以圈码开头的行）。"""
    idxs = set()
    for line in notes_text.splitlines():
        m = re.match(r'^\s*' + CIRCLED_RE.pattern + r'\s', line)
        if m:
            idx = glyph_index(m.group(0).strip()[0])
            if idx is not None:
                idxs.add(idx)
    return idxs


def add_text_links(text: str, vol: int, note_idxs: set[int]) -> str:
    """原文：把每个圈码包裹为锚点，并链接到同名注释条目。
    首次出现的圈码同时作为「回到原文」的锚点目标。"""
    seen: set[int] = set()
    def repl(m: re.Match) -> str:
        ch = m.group(0)
        idx = glyph_index(ch)
        if idx is None or idx not in note_idxs:
            return ch
        link = f'[^{ch}^](#v{vol}n{idx})'
        if idx in seen:
            return link
        seen.add(idx)
        return f'<a id="v{vol}t{idx}"></a>{link}'
    return CIRCLED_RE.sub(repl, text)


def add_notes_links(text: str, vol: int) -> str:
    """注释：给每个注释条目加锚点，并在行末加「↩ 回原文」链接。"""
    pat = re.compile(r'^(' + CIRCLED_RE.pattern + r')\s+(.*)$')
    lines = []
    for line in text.splitlines():
        m = pat.match(line)
        if m:
            ch, rest = m.group(1), m.group(2)
            idx = glyph_index(ch)
            lines.append(f'<a id="v{vol}n{idx}"></a>{ch} {rest}　[↩ 回原文](#v{vol}t{idx})')
        else:
            lines.append(line)
    return '\n'.join(lines)


def transform_file(f: Path, note_idxs_by_vol: dict[int, set[int]]) -> str:
    """按文件类型套用双向链接转换，返回处理后的文本。"""
    text = f.read_text(encoding='utf-8')
    name = f.name
    m = re.match(r'^(\d+)\.md$', name)           # 原文
    if m:
        vol = int(m.group(1))
        return add_text_links(text, vol, note_idxs_by_vol.get(vol, set()))
    m = re.match(r'^(\d+)\.notes\.md$', name)    # 注释
    if m:
        vol = int(m.group(1))
        return add_notes_links(text, vol)
    return text


def build_combined_md(files: list[Path], tmp_dir: Path) -> Path:
    """把所有 md 文件合并为一个临时 md，每卷之间用分页符隔开。
    原文与注释之间自动生成双向跳转链接。"""
    combined = tmp_dir / 'combined.md'
    # 预扫描各卷注释文件，得到每卷存在注释条目的圈码编号
    note_idxs_by_vol: dict[int, set[int]] = {}
    for f in files:
        m = re.match(r'^(\d+)\.notes\.md$', f.name)
        if m:
            vol = int(m.group(1))
            note_idxs_by_vol[vol] = note_indicies(f.read_text(encoding='utf-8'))
    with combined.open('w', encoding='utf-8') as out:
        for i, f in enumerate(files):
            text = transform_file(f, note_idxs_by_vol).rstrip()
            out.write(text)
            out.write('\n')
            # 卷之间插入分页（epub 的 page-break）
            out.write('\n\\newpage\n\n')
    return combined


def build_epub(combined: Path, out_path: Path, tmp_dir: Path, cover: Path | None = None) -> int:
    """调用 pandoc 生成 epub。"""
    # 生成一个简单的 metadata.yaml
    meta = tmp_dir / 'metadata.yaml'
    meta.write_text(
        f'title: "{TITLE}"\n'
        f'author: "{AUTHOR}"\n'
        f'lang: zh-CN\n'
        f'description: "《瑜伽师地论》一百卷·弥勒菩萨说·玄奘译，附导读与词语注释"\n',
        encoding='utf-8')

    cmd = [
        'pandoc',
        str(combined),
        '-o', str(out_path),
        '--metadata-file', str(meta),
        '--toc', '--toc-depth=1',
        '--split-level=1',
        '--epub-subdirectory=chapters',
    ]
    # 附加显式列表样式，保证各类 EPUB 阅读器都能显示列表
    if LIST_CSS.exists():
        cmd.extend(['--css', str(LIST_CSS.resolve())])
    if cover and cover.exists():
        cmd.extend(['--epub-cover-image', str(cover)])
    print('运行:', ' '.join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print('pandoc 错误:', result.stderr, file=sys.stderr)
    elif result.stderr:
        print('pandoc 警告:', result.stderr, file=sys.stderr)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description='打包《瑜伽师地论》epub')
    parser.add_argument('start', type=int, nargs='?', default=1, help='起始卷号（默认1）')
    parser.add_argument('end', type=int, nargs='?', default=100, help='结束卷号（默认100）')
    parser.add_argument('-o', '--output', default=DEFAULT_OUT, help=f'输出文件名（默认 {DEFAULT_OUT}）')
    parser.add_argument('-c', '--cover', default='cover.jpg', help='封面图片路径（默认 cover.jpg，不存在则跳过）')
    args = parser.parse_args()

    if not shutil.which('pandoc'):
        print('错误：未找到 pandoc，请先安装（macOS: brew install pandoc）', file=sys.stderr)
        return 1

    files = collect_files(args.start, args.end)
    if not files:
        print(f'错误：output/ 下未找到 {args.start}-{args.end} 卷的文件', file=sys.stderr)
        return 1

    cover = Path(args.cover)
    if not cover.exists():
        print(f'提示：封面图片 {cover} 不存在，将不使用封面')
        cover = None
    else:
        print(f'使用封面: {cover}')

    print(f'收集到 {len(files)} 个文件（前言 + 卷 {args.start}-{args.end}）')

    out_path = Path(args.output).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        combined = build_combined_md(files, tmp_dir)
        print(f'合并文件: {combined.stat().st_size // 1024} KB')
        code = build_epub(combined, out_path, tmp_dir, cover)
        if code == 0:
            size_mb = out_path.stat().st_size / (1024 * 1024)
            print(f'✓ 已生成: {out_path} ({size_mb:.1f} MB)')
        else:
            print(f'✗ 生成失败（退出码 {code}）', file=sys.stderr)
        return code


if __name__ == '__main__':
    sys.exit(main())
