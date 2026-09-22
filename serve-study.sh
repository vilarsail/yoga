#!/bin/bash
# 一键启动《瑜伽师地论》学习网页静态服务（含交互学习网页与思维导图）
# 用法: ./serve-study.sh  (Ctrl+C 停止)

set -e
cd "$(dirname "$0")"

PORT=8000
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

# 生成 study/index.html（学习网页 + 思维导图目录）
python3 - <<'PYEOF'
import re
from pathlib import Path

study = Path('study')
study.mkdir(exist_ok=True)
snums = sorted({int(m.group(1)) for f in study.glob('*-study.html')
                if (m := re.match(r'(\d+)-study\.html', f.name))})
mnums = sorted({int(m.group(1)) for f in study.glob('*-mindmap.html')
                if (m := re.match(r'(\d+)-mindmap\.html', f.name))})
nums = sorted(set(snums) | set(mnums))

rows = []
for n in nums:
    s = (f'<a href="{n}-study.html">学习网页</a>' if n in snums else '<span class="na">—</span>')
    m = (f'<a href="{n}-mindmap.html">思维导图</a>' if n in mnums else '<span class="na">—</span>')
    rows.append(f'<tr><td class="no">第 {n} 卷</td><td>{s}</td><td>{m}</td></tr>')

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>瑜伽师地论 · 学习目录</title>
<style>
body{{margin:0;background:#f7f3ec;color:#2b2620;line-height:1.8;
  font-family:"Songti SC","Noto Serif SC","Source Han Serif SC",serif}}
header{{background:linear-gradient(135deg,#2e4a62,#5a4632);color:#f5efe2;
  text-align:center;padding:44px 16px 36px}}
header h1{{font-size:1.6rem;letter-spacing:.12em;margin:0 0 8px}}
header p{{opacity:.85;margin:0;font-size:.95rem}}
main{{max-width:860px;margin:26px auto 80px;padding:0 18px}}
table{{width:100%;border-collapse:collapse;background:#fffdf8;
  border:1px solid #e4dccc;border-radius:14px;overflow:hidden}}
th,td{{padding:9px 14px;border-bottom:1px solid #efe9db;text-align:left}}
th{{background:#e2eaf1;color:#2e4a62;font-weight:600}}
tr:last-child td{{border-bottom:none}}
td.no{{width:30%;color:#9a3b2e;font-weight:600}}
a{{color:#2e4a62;text-decoration:none}}
a:hover{{color:#9a3b2e}}
.na{{opacity:.3}}
</style>
</head>
<body>
<header><h1>瑜伽师地论 · 学习目录</h1>
<p>{len(snums)} 份交互学习网页 · {len(mnums)} 份思维导图</p></header>
<main><table>
<tr><th>卷</th><th>交互学习</th><th>思维导图</th></tr>
{chr(10).join(rows)}
</table></main>
</body>
</html>
'''
(study / 'index.html').write_text(html, encoding='utf-8')
print(f'已生成 study/index.html：{len(nums)} 卷目录')
PYEOF

if lsof -i :$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 $PORT 已被占用，服务可能已在运行："
  echo "  目录:       http://localhost:$PORT/study/index.html"
  echo "  思维导图:   http://localhost:$PORT/study/1-mindmap.html"
  [ -n "$IP" ] && echo "  局域网:     http://$IP:$PORT/study/index.html"
  exit 0
fi

echo "服务已启动，按 Ctrl+C 停止"
echo "  目录:       http://localhost:$PORT/study/index.html"
echo "  学习网页:   http://localhost:$PORT/study/1-study.html"
echo "  思维导图:   http://localhost:$PORT/study/1-mindmap.html"
[ -n "$IP" ] && echo "  局域网:     http://$IP:$PORT/study/index.html"
echo ""

exec python3 -m http.server $PORT --bind 0.0.0.0
