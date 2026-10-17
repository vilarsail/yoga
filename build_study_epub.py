#!/usr/bin/env python3
"""
build_study_epub.py - 把 study/N-study.html 交互式学习模块 + output/N.summary.md
思维导图（层级列表笔记）合并打包为墨水屏友好的 EPUB / PDF。

语义降级规则（交互 → 静态）：
  翻转卡片 fn-card  → 标题+副题+正文的定义条目（去掉「点击展开」提示）
  条件模拟器        → 条件清单 + 从 JS 提取的各情形推演结论
  流程推演 stepper  → JS 数据提取为时间线列表
  归类练习 sorter   → 「题目 → 答案：解析」静态测验清单
  学习路径复选框    → 静态编号清单（去掉进度条与保存提示）
  details.dict     → 直接展开
  nav.toc / 进度条 / 按钮 / script / inline style → 移除

每卷两个章节：学习模块（N-study.html 降级版）→ 思维导图（N.summary.md 列表）。
前言取自 study-preface.md。

用法：
    python3 build_study_epub.py            # 默认卷 1
    python3 build_study_epub.py 1 100      # 打包指定区间为一本 EPUB + PDF
    python3 build_study_epub.py -o xx.epub # 自定义输出
    python3 build_study_epub.py --no-pdf   # 只生成 EPUB
"""

from __future__ import annotations
import argparse
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import cast

from lxml import etree, html as lxml_html

STUDY_DIR = Path('study')
SUMMARY_DIR = Path('output')
CSS_FILE = Path('study-epub.css')
PREFACE_FILE = Path('study-preface.md')
OUT_DIR = Path('study/epub')
DEFAULT_OUT = Path('瑜伽师地论(学习模块版).epub')
AUTHOR = '弥勒菩萨说 玄奘译'


# ---------- JS 数据提取 ----------

def _unescape(s: str) -> str:
    return s.replace("\\'", "'").replace('\\\\', '\\')


def _extract_call_args(js: str, func: str) -> list[str]:
    """提取 func( 的实参列表（括号配平），返回顶层参数字符串列表。"""
    out = []
    for m in re.finditer(re.escape(func) + r'\s*\(', js):
        i = m.end()
        depth = 1
        in_str = False
        while i < len(js) and depth > 0:
            c = js[i]
            if in_str:
                if c == '\\':
                    i += 1
                elif c == "'":
                    in_str = False
            else:
                if c == "'":
                    in_str = True
                elif c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
            i += 1
        out.append(js[m.end():i - 1])
    return out


def _split_top(args: str) -> list[str]:
    """按顶层逗号切分实参。"""
    parts, depth, cur, in_str = [], 0, [], False
    for c in args:
        if in_str:
            cur.append(c)
            if c == '\\':
                continue
            if c == "'":
                in_str = False
        elif c == "'":
            in_str = True
            cur.append(c)
        elif c in '([{':
            depth += 1
            cur.append(c)
        elif c in ')]}':
            depth -= 1
            cur.append(c)
        elif c == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
    if cur:
        parts.append(''.join(cur).strip())
    return parts


def _parse_str(s: str) -> str:
    s = s.strip()
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    return _unescape(s)


STR_RE = r"'((?:[^'\\]|\\.)*)'"


def extract_steppers(js: str) -> dict[str, list[dict]]:
    """initStepper(trackId, detailId, prevId, nextId, [{t, d}, ...]) → {trackId: steps}"""
    result = {}
    for args in _extract_call_args(js, 'initStepper'):
        parts = _split_top(args)
        if len(parts) < 5:
            continue
        track = _parse_str(parts[0])
        steps = []
        for om in re.finditer(r"\{\s*t\s*:\s*" + STR_RE + r"\s*,\s*d\s*:\s*" + STR_RE + r"\s*\}", parts[4]):
            steps.append({'t': _unescape(om.group(1)), 'd': _unescape(om.group(2))})
        if steps:
            result[track] = steps
    return result


def extract_sorters(js: str) -> dict[str, list[dict]]:
    """initSorter(areaId, [{a, opts, ans, exp}, ...]) → {areaId: items}"""
    result = {}
    for args in _extract_call_args(js, 'initSorter'):
        parts = _split_top(args)
        if len(parts) < 2:
            continue
        area = _parse_str(parts[0])
        items = []
        for om in re.finditer(
                r"\{\s*a\s*:\s*" + STR_RE +
                r"\s*,\s*opts\s*:\s*\[([^\]]*)\]" +
                r"\s*,\s*ans\s*:\s*" + STR_RE +
                r"\s*,\s*exp\s*:\s*" + STR_RE + r"\s*\}", parts[1]):
            items.append({'a': _unescape(om.group(1)),
                          'ans': _unescape(om.group(3)),
                          'exp': _unescape(om.group(4))})
        if items:
            result[area] = items
    return result


SIM_RESULT_RE = re.compile(r"innerHTML\s*=\s*'<b>(.*?)</b>(.*?)'", re.S)


def extract_sim_outcomes(js: str) -> list[tuple[str, str]]:
    """自定义模拟器函数里的 innerHTML='<b>标题</b>正文' 字面量 → [(标题, 正文)]。"""
    # 只取函数体内的（跳过通用组件，通用组件用模板拼接而非 innerHTML='<b>'）
    return [(_unescape(m.group(1)).strip(), _unescape(m.group(2)).strip())
            for m in SIM_RESULT_RE.finditer(js)]


# ---------- DOM 变换 ----------

def drop(e: lxml_html.HtmlElement):
    e.getparent().remove(e)


def make_fn_item(card: lxml_html.HtmlElement) -> lxml_html.HtmlElement:
    front = card.find('.//div[@class="front"]')
    back = card.find('.//div[@class="back"]')
    cn = front.find('.//div[@class="cn"]') if front is not None else None
    sub = front.find('.//div[@class="sub"]') if front is not None else None
    item = lxml_html.Element('div')
    item.set('class', 'fn-item')
    head = lxml_html.Element('p')
    head.set('class', 'fn-head')
    b = lxml_html.Element('b')
    b.text = (cn.text_content() or '').strip() if cn is not None else ''
    head.append(b)
    if sub is not None and sub.text_content().strip():
        sp = lxml_html.Element('span')
        sp.set('class', 'fn-sub')
        sp.text = ' · ' + sub.text_content().strip()
        head.append(sp)
    item.append(head)
    if back is not None:
        for child in list(back):
            item.append(deepcopy(child))
        if back.text and back.text.strip():
            prepend = lxml_html.Element('span')
            prepend.text = back.text.strip()
            item.insert(1, prepend)
    return item


def make_yuan_item(card: lxml_html.HtmlElement) -> lxml_html.HtmlElement:
    tag = card.find('.//span[@class="y-tag"]')
    h4 = card.find('.//h4')
    p = card.find('.//p')
    item = lxml_html.Element('div')
    item.set('class', 'yuan-item')
    head = lxml_html.Element('p')
    b = lxml_html.Element('b')
    b.text = (tag.text_content().strip() if tag is not None else '')
    if h4 is not None:
        b.text = (b.text + '：' if b.text else '') + h4.text_content().strip()
    head.append(b)
    item.append(head)
    if p is not None:
        item.append(deepcopy(p))
    return item


def make_tl_item(item_src: lxml_html.HtmlElement) -> lxml_html.HtmlElement:
    t = item_src.find('.//div[@class="t"]')
    d = item_src.find('.//div[@class="d"]')
    item = lxml_html.Element('div')
    item.set('class', 'tl-item')
    if t is not None:
        b = lxml_html.Element('b')
        b.text = t.text_content().strip()
        item.append(b)
    if d is not None:
        for child in list(d):
            item.append(deepcopy(child))
        if d.text and d.text.strip():
            sp = lxml_html.Element('span')
            sp.text = d.text.strip()
            item.append(sp)
    return item


def append_html(parent: lxml_html.HtmlElement, text: str) -> None:
    """JS 提取的字符串按 HTML 片段插入（可能含 <br>/<b> 等标签）。"""
    if not text:
        return
    if '<' in text:
        try:
            frag = lxml_html.fragment_fromstring(f'<div>{text}</div>')
            if frag.text and frag.text.strip():
                sp = lxml_html.Element('span')
                sp.text = frag.text.strip()
                parent.append(sp)
            for child in list(frag):
                parent.append(child)
            return
        except etree.ParserError:
            pass
    sp = lxml_html.Element('span')
    sp.text = text
    parent.append(sp)


def make_sim_block(title: str, outcomes: list[tuple[str, str]]) -> lxml_html.HtmlElement:
    div = lxml_html.Element('div')
    div.set('class', 'sim-outcomes')
    if title:
        h4 = lxml_html.Element('h4')
        h4.text = title
        div.append(h4)
    for head, body in outcomes:
        p = lxml_html.Element('p')
        b = lxml_html.Element('b')
        b.text = head
        p.append(b)
        append_html(p, body)
        div.append(p)
    return div


def make_quiz_block(items: list[dict]) -> lxml_html.HtmlElement:
    div = lxml_html.Element('div')
    div.set('class', 'quiz')
    for i, it in enumerate(items, 1):
        q = lxml_html.Element('div')
        q.set('class', 'quiz-q')
        b = lxml_html.Element('b')
        b.text = f'{i}. {it["a"]}'
        q.append(b)
        div.append(q)
        a = lxml_html.Element('div')
        a.set('class', 'quiz-a')
        ab = lxml_html.Element('b')
        ab.text = f'答案：{it["ans"]}'
        a.append(ab)
        if '<' in it['exp']:
            sp = lxml_html.Element('span')
            sp.text = ' —— '
            a.append(sp)
            append_html(a, it['exp'])
        else:
            sp = lxml_html.Element('span')
            sp.text = ' —— ' + it['exp']
            a.append(sp)
        div.append(a)
    return div


def make_timeline(steps: list[dict]) -> lxml_html.HtmlElement:
    div = lxml_html.Element('div')
    div.set('class', 'timeline')
    for s in steps:
        item = lxml_html.Element('div')
        item.set('class', 'tl-item')
        b = lxml_html.Element('b')
        b.text = s['t']
        item.append(b)
        frag = lxml_html.fragment_fromstring(f'<div>{s["d"]}</div>')
        for child in list(frag):
            item.append(child)
        if frag.text and frag.text.strip():
            sp = lxml_html.Element('span')
            sp.text = frag.text.strip()
            item.append(sp)
        div.append(item)
    return div


CN_DIGITS = '零一二三四五六七八九'


def num_to_cn(n: int) -> str:
    """1-100 → 汉字数字（卷号用）。"""
    if n < 10:
        return CN_DIGITS[n]
    if n == 10:
        return '十'
    if n < 20:
        return '十' + CN_DIGITS[n % 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        return CN_DIGITS[tens] + '十' + (CN_DIGITS[ones] if ones else '')
    return '一百'


def cn_to_int(s: str) -> int:
    """汉字数字（1-100）→ 整数。"""
    if s == '一百':
        return 100
    if s == '十':
        return 10
    total = 0
    for unit, val in (('百', 100), ('十', 10)):
        if unit in s:
            head, _, s = s.partition(unit)
            total += (CN_DIGITS.index(head) if head else 1) * val
    if s:
        total += CN_DIGITS.index(s)
    return total


def transform_volume(path: Path) -> tuple[str, str]:
    """返回 (卷标题, 变换后的 body 内部 HTML 字符串)。"""
    doc = lxml_html.fromstring(path.read_text(encoding='utf-8'))
    title = '瑜伽师地论'
    tm = re.search(r'卷[第\s]*([一二三四五六七八九十百\d]+)', doc.findtext('.//title') or '')
    if tm:
        raw = tm.group(1)
        n = int(raw) if raw.isdigit() else cn_to_int(raw)
        title = f'瑜伽师地论 卷第{num_to_cn(n)}'

    js = ' '.join(s.text or '' for s in doc.xpath('.//script'))
    steppers = extract_steppers(js)
    sorters = extract_sorters(js)
    sim_outcomes = extract_sim_outcomes(js)

    # 移除：script、toc 导航、交互提示、空占位、按钮组
    for sel in ('script', 'nav'):
        for e in doc.xpath(f'.//{sel}'):
            drop(e)
    for cls in ('tap', 'progress-bar', 'progress-text', 'flow-ctrl', 'divider', 'acts'):
        for e in doc.xpath(f'.//*[contains(@class,"{cls}")]'):
            drop(e)
    # 学习路径 → 静态清单
    path_box = doc.find('.//div[@class="path-box"]')
    if path_box is not None:
        for e in path_box.findall('.//div[@id="steps"]'):
            ol = lxml_html.Element('ol')
            ol.set('class', 'steps')
            for si in e.findall('.//div[@class="step-item"]'):
                txt = si.find('.//span[@class="txt"]')
                li = lxml_html.Element('li')
                if txt is not None:
                    bb = txt.find('b')
                    if bb is not None:
                        b2 = lxml_html.Element('b')
                        b2.text = bb.text_content().strip()
                        li.append(b2)
                    sub = txt.find('span')
                    if sub is not None and sub.text_content().strip():
                        sp = lxml_html.Element('span')
                        sp.text = ' —— ' + sub.text_content().strip()
                        li.append(sp)
                ol.append(li)
            e.getparent().replace(e, ol)


    for e in doc.xpath('.//input'):
        parent = e.getparent()
        while parent is not None and parent.tag == 'label':
            e, parent = parent, parent.getparent()
        drop(e)
    for e in doc.xpath('.//*[@style]'):
        del e.attrib['style']
    for e in doc.xpath('.//p[@class="hint"]'):
        drop(e)

    # hero → 卷首块
    hero = doc.find('.//header')
    if hero is not None:
        hero.tag = 'div'
        hero.set('class', 'hero')
        for sub in hero.xpath('.//p[@class="sub"]'):
            sub.tag = 'div'

    # 翻转卡片
    for grid in doc.xpath('.//div[@class="fn-grid"]'):
        for card in grid.findall('.//div[@class="fn-card"]'):
            card.getparent().replace(card, make_fn_item(card))

    # 元喻卡片
    for grid in doc.xpath('.//div[@class="yuan-grid"]'):
        for card in grid.findall('.//div[@class="yuan-card"]'):
            card.getparent().replace(card, make_yuan_item(card))

    # 正文散文里的操作指引从句删除。规则：
    #   1) 句边界（句首/。？！；）后紧跟的「点击…」整句删除
    #   2) 「点击节点/选项/标签/按钮/下面/你认为…」「按顺序点击…」等固定指引搭配删除
    #   3) 括号提示（点击节点查看）删除
    # 比喻正文（如卷93「，点击「立即付款」」）不属于以上搭配，保留。
    CLICK_RE = re.compile(
        r'(^|[。？！；])点击[^。？！]*[。？！]?'
        r'|[，；]?\s*点击(节点|选项|标签|按钮|下面|你认为)[^。？！]*[。？！]?'
        r'|按顺序点击[^。？！]*[。？！]?'
        r'|（点击[^）]*）')
    for e in doc.xpath('.//p|.//div[@class="plain"]|.//div[@class="case"]'):
        for node in [e] + list(e.iter()):
            for attr in ('text', 'tail'):
                t = getattr(node, attr)
                if t and '点击' in t:
                    setattr(node, attr, CLICK_RE.sub('', t))

    # 时间线
    for tl in doc.xpath('.//div[@class="timeline"]'):
        for item in tl.findall('.//div[@class="tl-item"]'):
            item.getparent().replace(item, make_tl_item(item))

    # details 展开
    for d in doc.xpath('.//details'):
        body = d.find('.//div[@class="body"]')
        if body is not None:
            d.getparent().replace(d, body)
        else:
            d.tag = 'div'

    # 引文
    for q in doc.xpath('.//div[@class="quote"]'):
        q.tag = 'blockquote'

    # 偈颂
    for g in doc.xpath('.//div[@class="gatha"]'):
        lines = g.find('.//div[@class="lines"]')
        mean = g.find('.//div[@class="mean"]')
        block = lxml_html.Element('blockquote')
        block.set('class', 'gatha')
        if lines is not None:
            lines_html = cast(str, lxml_html.tostring(lines, encoding='unicode'))
            for br_line in re.split(r'<br\s*/?>', lines_html):
                text = lxml_html.fromstring(br_line or '<p></p>').text_content().strip()
                if not text:
                    continue
                p = lxml_html.Element('p')
                p.text = text
                block.append(p)
        g.getparent().replace(g, block)
        if mean is not None:
            p = lxml_html.Element('div')
            p.set('class', 'mean')
            b = lxml_html.Element('b')
            b.text = '目录注：'
            p.append(b)
            sp = lxml_html.Element('span')
            sp.text = mean.text_content().strip()
            p.append(sp)
            block.getparent().insert(list(block.getparent()).index(block) + 1, p)

    # 章节头：num + h2 → h2
    for head in doc.xpath('.//div[@class="sec-head"]'):
        num = head.find('span[@class="num"]')
        h2 = head.find('h2')
        if h2 is not None:
            h2.text = ((num.text_content().strip() + '　') if num is not None else '') + h2.text_content().strip()
            head.getparent().replace(head, h2)

    # 占位符：stepper / sorter / 模拟器
    def placeholder_root(eid: str):
        for e in doc.xpath(f'.//*[@id="{eid}"]'):
            return e
        return None

    for track, steps in steppers.items():
        ph = placeholder_root(track)
        if ph is None:
            continue
        parent = ph.getparent()
        idx = list(parent).index(ph)
        parent.remove(ph)
        parent.insert(idx, make_timeline(steps))
    for area, items in sorters.items():
        ph = placeholder_root(area)
        if ph is None:
            continue
        parent = ph.getparent()
        idx = list(parent).index(ph)
        parent.remove(ph)
        parent.insert(idx, make_quiz_block(items))

    if sim_outcomes:
        block = make_sim_block('各情形推演', sim_outcomes)
        target = placeholder_root('condResult')
        if target is not None:
            parent = target.getparent()
            idx = list(parent).index(target)
            parent.remove(target)
            parent.insert(idx, block)
        else:
            row = doc.find('.//div[@class="cond-row"]')
            if row is not None:
                row.getparent().insert(list(row.getparent()).index(row) + 1, block)

    # 标题/正文中的交互提示（如「点击卡片翻转」「点击翻转」）对静态版无意义，删除
    HINT_RE = r'[（(]点击[^）)]*[）)]|[:：]?\s*点击(卡片)?(展开|翻转|推进|折叠)[。.]?'
    for h in doc.xpath('.//h3|.//h4'):
        if h.text and '点击' in h.text:
            h.text = re.sub(HINT_RE, '', h.text).strip() or h.text

    # footer → 普通块
    for f in doc.xpath('.//footer'):
        f.tag = 'div'
        f.set('class', 'footer-note')

    # 条件行的开关已随 input/label 移除，仅保留文字
    body = doc.find('body')
    inner = ''.join(
        cast(str, lxml_html.tostring(c, encoding='unicode')) for c in body if isinstance(c.tag, str))
    return title, inner


def _inline_md_html(text: str) -> str:
    """行内 markdown（**加粗**）→ HTML，其余字符转义。"""
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)


def summary_to_html(path: Path) -> str:
    """output/N.summary.md 层级列表（2 空格缩进）→ 嵌套 <ul> HTML。"""
    root = lxml_html.Element('div')
    root.set('class', 'mindmap-md')
    stack: list[tuple[int, lxml_html.HtmlElement]] = [(-1, root)]
    for raw in path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^(\s*)[-*]\s+(.*)$', raw)
        if not m:
            continue
        level = len(m.group(1).expandtabs(2)) // 2
        li = lxml_html.fragment_fromstring(
            f'<li>{_inline_md_html(m.group(2).strip())}</li>')
        while stack[-1][0] >= level:
            stack.pop()
        holder = stack[-1][1]
        ul = holder.find('ul')
        if ul is None:
            ul = etree.SubElement(holder, 'ul')
        ul.append(li)
        stack.append((level, li))
    return cast(str, lxml_html.tostring(root, encoding='unicode'))


def read_preface_html(tmp: Path) -> str:
    """study-preface.md 经 pandoc 转为 HTML 片段（去掉首个 h1，由外层统一加标题）。"""
    text = PREFACE_FILE.read_text(encoding='utf-8')
    text = re.sub(r'^#\s+前言\s*\n', '', text)
    src = tmp / 'preface.md'
    src.write_text(text, encoding='utf-8')
    r = subprocess.run(
        ['pandoc', '-f', 'gfm', '-t', 'html', str(src)],
        capture_output=True, text=True, check=True)
    return r.stdout


def build_epub(volumes: list[tuple[str, str, str]], out_path: Path, tmp: Path) -> None:
    parts = [f'<section><h1>前言</h1>\n{read_preface_html(tmp)}\n</section>']
    for title, inner, mm in volumes:
        parts.append(f'<section><h1>{title}</h1>\n{inner}\n</section>')
        parts.append(f'<section><h1>{title} · 思维导图</h1>\n{mm}\n</section>')
    main_title = volumes[0][0] if len(volumes) == 1 else '瑜伽师地论 · 交互式学习模块'
    html_doc = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{main_title}</title></head><body>
{"".join(parts)}
</body></html>'''
    src = tmp / 'study.html'
    src.write_text(html_doc, encoding='utf-8')
    cmd = [
        'pandoc', str(src), '-o', str(out_path),
        f'--css={CSS_FILE}',
        '--metadata', f'title={main_title}',
        '--metadata', f'author={AUTHOR}',
        '--metadata', 'lang=zh-CN',
        '--toc', '--toc-depth=2',
        '--epub-chapter-level=1',
    ]
    subprocess.run(cmd, check=True)


def build_pdf(epub_path: Path) -> int:
    """调用 calibre 的 ebook-convert 把 epub 转为同名 pdf。"""
    pdf_path = epub_path.with_suffix('.pdf')
    result = subprocess.run(
        ['ebook-convert', str(epub_path), str(pdf_path)],
        capture_output=True, text=True)
    if result.returncode != 0:
        print('ebook-convert 错误:', result.stderr[-2000:], file=sys.stderr)
    return result.returncode


def main():
    ap = argparse.ArgumentParser(description='把 study 模块 + 思维导图打包为 EPUB/PDF')
    ap.add_argument('start', nargs='?', type=int, default=1)
    ap.add_argument('end', nargs='?', type=int, default=None)
    ap.add_argument('-o', '--out', default=None, help='输出文件路径')
    ap.add_argument('--no-pdf', action='store_true', help='只生成 EPUB，不转换 PDF')
    args = ap.parse_args()
    end = args.end or args.start
    full = (args.start, end) == (1, 100)

    missing = [
        n for n in range(args.start, end + 1)
        if not (STUDY_DIR / f'{n}-study.html').exists()
        or not (SUMMARY_DIR / f'{n}.summary.md').exists()]
    if missing:
        sys.exit(f'缺少文件: {missing[:10]}{"..." if len(missing) > 10 else ""}')
    if not PREFACE_FILE.exists():
        sys.exit(f'缺少前言文件: {PREFACE_FILE}')

    volumes, failed = [], []
    for n in range(args.start, end + 1):
        try:
            title, inner = transform_volume(STUDY_DIR / f'{n}-study.html')
            mm = summary_to_html(SUMMARY_DIR / f'{n}.summary.md')
            volumes.append((title, inner, mm))
            print(f'  卷 {n} 转换完成')
        except Exception as e:
            failed.append((n, repr(e)))
    if failed:
        print('失败：', failed, file=sys.stderr)
    if not volumes:
        sys.exit('无可转换内容')

    if args.out:
        out_path = Path(args.out)
    elif len(volumes) == 1:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUT_DIR / f'{volumes[0][0]}.epub'
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUT_DIR / f'瑜伽师地论·学习模块·卷{args.start:03d}-{end:03d}.epub'
    if full and not args.out:
        out_path = DEFAULT_OUT

    with tempfile.TemporaryDirectory() as td:
        build_epub(volumes, out_path, Path(td))
    print(f'输出: {out_path} ({out_path.stat().st_size // 1024}K)')

    if not args.no_pdf:
        if build_pdf(out_path) == 0:
            print(f'输出: {out_path.with_suffix(".pdf")} '
                  f'({out_path.with_suffix(".pdf").stat().st_size // 1024}K)')


if __name__ == '__main__':
    main()
