#!/usr/bin/env python3
"""
build_mindmap.py - 把 output/{N}.summary.md（层级列表笔记）转成单文件思维导图 HTML。

版式对齐幕布（mubu）导出风格：
- 节点为无框纯文字，仅根节点为胶囊；层级靠细灰肘形连接线
- 「**加粗小标题**：说明」富文本排版，加粗深墨、正文灰
- 子节点 x 跟随父节点实际宽度阶梯推进，行距紧凑

- 输入：output/{N}.summary.md（每个非空行是列表项，缩进 2 空格 = 一层）
- 输出：output/{N}.mindmap.html（零依赖：SVG，节点可折叠、滚轮缩放、拖拽平移，自动适配视图）

用法：
    python3 build_mindmap.py <N> [<M> ...]
"""

from __future__ import annotations
import html
import re
import sys
from pathlib import Path

OUTPUT_DIR = Path('output')
STUDY_DIR = Path('study')
ITEM_RE = re.compile(r'^( *)- (.*)$')

FONT = 13
LINE_H = 20
H_GAP = 30
V_GAP = 7
MAX_CHARS = 34

INK = '#3a3630'
BODY = '#6b6257'
LINE_C = '#d8cfbe'
ACCENT = '#9a3b2e'


def parse(path: Path):
    root = None
    stack = []
    offset = 0  # 首个顶层条目（总括）之后的顶层块整体下移一层并入总括之下
    for line in path.read_text(encoding='utf-8').split('\n'):
        if not line.strip():
            continue
        m = ITEM_RE.match(line)
        if not m:
            continue
        depth, text = len(m.group(1)) // 2, m.group(2).strip()
        node = {'text': text, 'children': []}
        if depth == 0 and root is None:
            root = node
            stack = [node]
            continue
        if depth == 0:
            offset = 1
            eff = 1
        else:
            eff = depth + offset
        while len(stack) > eff:
            stack.pop()
        stack[-1]['children'].append(node)
        stack.append(node)
    return root


def split_bold(text: str):
    segs = []
    for i, p in enumerate(re.split(r'\*\*(.+?)\*\*', text)):
        if p:
            segs.append((p, i % 2 == 1))
    return segs


def wrap_segments(segs, width: int):
    tokens = []
    for t, b in segs:
        for w in re.findall(r'[A-Za-z0-9]+|\S', t):
            tokens.append((w, b))
    lines, cur, cur_w = [], [], 0
    for tok, b in tokens:
        wl = len(tok) if re.fullmatch(r'[A-Za-z0-9]+', tok) else 1
        if cur and cur_w + wl > width:
            lines.append(cur)
            cur, cur_w = [], 0
        cur.append((tok, b))
        cur_w += wl
    if cur:
        lines.append(cur)
    return lines


def measure(node, depth):
    width = 56 if depth == 0 else MAX_CHARS
    lines = wrap_segments(split_bold(node['text']), width)
    node['_lines'] = lines
    pad_x = 18 if depth == 0 else 4
    node['_w'] = max(sum(len(t) if re.fullmatch(r'[A-Za-z0-9]+', t) else 1 for t, _ in l)
                     for l in lines) * FONT + pad_x
    node['_h'] = len(lines) * LINE_H + (12 if depth == 0 else 4)
    if not node['children']:
        node['_th'] = node['_h']
    else:
        node['_th'] = max(node['_h'], sum(c['_th'] for c in node['children'])
                          + V_GAP * (len(node['children']) - 1))


def layout(node, depth, x, y_top):
    node['_x'] = x
    node['_y'] = y_top + (node['_th'] - node['_h']) / 2
    if node['children']:
        cx = x + node['_w'] + H_GAP
        cy = y_top
        for c in node['children']:
            layout(c, depth + 1, cx, cy)
            cy += c['_th'] + V_GAP


def total_size(node):
    w = node['_x'] + node['_w']
    h = node['_th']
    if node['children']:
        for c in node['children']:
            cw, ch = total_size(c)
            w, h = max(w, cw), max(h, ch)
    return w, h


def esc(s):
    return html.escape(s, quote=True)


def merge_runs(line):
    runs = []
    for t, b in line:
        if runs and runs[-1][1] == b:
            runs[-1][0] += t
        else:
            runs.append([t, b])
    return runs


def render_line(x, y, line, force_bold=False):
    spans = []
    for t, b in merge_runs(line):
        bold = b or force_bold
        color = INK if bold else BODY
        style = f'font-weight:700;fill:{color}' if bold else f'fill:{color}'
        spans.append(f'<tspan style="{style}">{esc(t)}</tspan>')
    return f'<text x="{x:.1f}" y="{y:.1f}" style="font-size:{FONT}px">{"".join(spans)}</text>'


def render(node, out):
    depth = node.get('_depth', 0)
    x, y, w, h = node['_x'], node['_y'], node['_w'], node['_h']
    y_mid = y + h / 2
    out.append(f'<g class="node{" root" if depth == 0 else ""}">')
    if depth == 0:
        out.append(f'<rect x="{x - 18:.1f}" y="{y:.1f}" width="{w + 36:.1f}" height="{h:.1f}" '
                   f'rx="{h / 2:.1f}" fill="{ACCENT}"/>')
        ty = y + 6 + FONT - 2
        for i, l in enumerate(node['_lines']):
            out.append(render_line(x, ty + i * LINE_H, l, force_bold=True)
                       .replace('style="font-size', 'style="fill:#fff;font-size'))
    else:
        out.append(f'<rect class="hit" x="{x - 4:.1f}" y="{y - 2:.1f}" width="{w + 4:.1f}" '
                   f'height="{h + 4:.1f}" rx="6" fill="transparent"/>')
        ty = y + 2 + FONT - 2
        for i, l in enumerate(node['_lines']):
            out.append(render_line(x, ty + i * LINE_H, l,
                                   force_bold=(depth == 1 and not node.get('_plain'))))

    if node['children']:
        stub = 14
        xs = x + w
        ys = [c['_y'] + c['_h'] / 2 for c in node['children']]
        out.append(f'<path class="edge" d="M{xs:.1f},{y_mid:.1f} H{xs + stub:.1f} '
                   f'M{xs + stub:.1f},{min(ys):.1f} V{max(ys):.1f} '
                   + ' '.join(f'M{xs + stub:.1f},{yy:.1f} H{c["_x"]:.1f}' for c, yy in zip(node['children'], ys))
                   + f'" fill="none" stroke="{LINE_C}" stroke-width="1.3"/>')
        out.append(f'<g class="badge" transform="translate({xs + stub + 2:.1f},{y_mid:.1f})">'
                   f'<circle r="9" fill="{ACCENT}"/>'
                   f'<text y="4" text-anchor="middle" fill="#fff" style="font-size:10px;font-weight:700">'
                   f'{len(node["children"])}</text></g>')
        for c in node['children']:
            render(c, out)
    out.append('</g>')


def prep(node, depth=0):
    node['_depth'] = depth
    for c in node['children']:
        prep(c, depth + 1)
    measure(node, depth)


def count_nodes(node):
    return 1 + sum(count_nodes(c) for c in node['children'])


def build(n: int) -> bool:
    src = OUTPUT_DIR / f'{n}.summary.md'
    if not src.exists():
        print(f'  [{n}] ✗ {src} 不存在')
        return False
    dst = STUDY_DIR / f'{n}-mindmap.html'
    STUDY_DIR.mkdir(exist_ok=True)
    parsed = parse(src)
    if parsed is None:
        print(f'  [{n}] ✗ 解析失败：没有任何列表项')
        return False
    title = ''
    md = OUTPUT_DIR / f'{n}.md'
    if md.exists():
        for line in md.read_text(encoding='utf-8').split('\n'):
            if line.startswith('#'):
                title = line.lstrip('#').strip()
                break
    if not title:
        title = f'瑜伽师地论卷{n}'
    root = {'text': title, 'children': [parsed]}
    parsed['_plain'] = True  # 总括节点不做整行强制加粗
    prep(root)
    layout(root, 0, 0, 0)
    w, h = total_size(root)

    parts = []
    render(root, parts)
    body = '\n'.join(parts)

    page = (TEMPLATE
            .replace('%%TITLE%%', html.escape(f'瑜伽师地论 卷{n} · 思维导图'))
            .replace('%%BODY%%', body))
    dst.write_text(page, encoding='utf-8')
    print(f'  [{n}] ✓ {dst.name}：{count_nodes(root)} 节点, 画布 {w:.0f}x{h:.0f}')
    return True


TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%%TITLE%%</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:#faf7f2;
  font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
#bar{position:fixed;top:0;left:0;right:0;z-index:9;padding:10px 18px;
  background:rgba(250,247,242,.95);border-bottom:1px solid #e8e1d3;
  font-size:14px;color:#6b6257;letter-spacing:.06em}
#bar b{color:#9a3b2e}
#bar button{margin-left:12px;padding:3px 14px;border:1px solid #d8cfbe;border-radius:999px;
  background:#fff;color:#6b6257;font-size:12px;cursor:pointer}
#bar button:hover{border-color:#9a3b2e;color:#9a3b2e}
#bar .hint{float:right;font-size:12px;opacity:.65}
svg{position:fixed;top:42px;left:0;width:100vw;height:calc(100vh - 42px);cursor:grab}
svg.dragging{cursor:grabbing}
.node{cursor:pointer}
.node .hit{transition:fill .12s}
.node:hover .hit{fill:rgba(0,0,0,.045)}
.node .badge{opacity:0;transition:opacity .15s}
.node.collapsed>.badge{opacity:1}
.node.collapsed>.edge{opacity:0}
.node.collapsed text{fill:#9a3b2e}
.node.collapsed text tspan{fill:#9a3b2e !important}
.node.root{cursor:default}
text{user-select:none;dominant-baseline:auto}
</style>
</head>
<body>
<div id="bar"><b>%%TITLE%%</b><button id="reset">复位</button><span class="hint">单击节点折叠/展开 · 双指滚动平移 · 捏合缩放 · 拖拽平移</span></div>
<svg id="mm"><g id="vp">%%BODY%%</g></svg>
<script>
const svg=document.getElementById('mm'),vp=document.getElementById('vp');
let scale=1,tx=0,ty=0;
function apply(){vp.setAttribute('transform',`translate(${tx},${ty}) scale(${scale})`)}
function fit(){const r=vp.getBBox(),W=innerWidth,H=innerHeight-42;
  scale=Math.min(W/(r.width+60),H/(r.height+60),1.3);
  tx=(W-r.width*scale)/2-r.x*scale;ty=42+(H-r.height*scale)/2-r.y*scale;apply()}
const clampS=s=>Math.min(6,Math.max(0.05,s));
function zoomAt(px,py,k){
  const ns=clampS(scale*k),kk=ns/scale;
  tx+=scale*px*(1-kk);ty+=scale*py*(1-kk);scale=ns;apply()}
svg.addEventListener('wheel',e=>{e.preventDefault();
  const unit=e.deltaMode===1?16:1;
  if(e.ctrlKey){
    const pt=new DOMPoint(e.clientX,e.clientY).matrixTransform(vp.getScreenCTM().inverse());
    zoomAt(pt.x,pt.y,Math.exp(-e.deltaY*unit*0.01));
  }else{
    tx-=e.deltaX*unit;ty-=e.deltaY*unit;apply();
  }},{passive:false});
let gscale=1;
svg.addEventListener('gesturestart',e=>{e.preventDefault();gscale=scale});
svg.addEventListener('gesturechange',e=>{e.preventDefault();
  const pt=new DOMPoint(e.clientX,e.clientY).matrixTransform(vp.getScreenCTM().inverse());
  zoomAt(pt.x,pt.y,e.scale*gscale/scale)});
svg.addEventListener('gestureend',e=>e.preventDefault());
let drag=null;
svg.addEventListener('pointerdown',e=>{if(e.target.closest('.node'))return;
  drag={x:e.clientX,y:e.clientY,tx,ty};svg.classList.add('dragging')});
addEventListener('pointermove',e=>{if(drag){tx=drag.tx+e.clientX-drag.x;ty=drag.ty+e.clientY-drag.y;apply()}});
addEventListener('pointerup',()=>{drag=null;svg.classList.remove('dragging')});
document.getElementById('reset').addEventListener('click',fit);
svg.addEventListener('click',e=>{
  const g=e.target.closest('.node');if(!g||g.classList.contains('root'))return;
  g.classList.toggle('collapsed');
  (function walk(node,ancHidden){
    [...node.children].filter(el=>el.classList&&el.classList.contains('node')).forEach(k=>{
      const hid=ancHidden||node.classList.contains('collapsed');
      k.style.display=hid?'none':'';walk(k,hid)});
  })(g,false);});
addEventListener('resize',fit);fit();
</script>
</body>
</html>
'''


def main():
    args = sys.argv[1:]
    if not args:
        print('用法: python3 build_mindmap.py <N> [<M> ...]')
        return 2
    ok = all(build(int(a)) for a in args)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
