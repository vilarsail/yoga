#!/usr/bin/env python3
"""校验 study/{N}-study.html 的结构完整性与内容规范。

用法: python3 .claude/skills/study-yoga/check_study.py <N> [<M> ...]
exit 0 = 全部通过; exit 1 = 有失败项（逐条打印）。
"""
import sys
import re
import os

REQUIRED = [
    ('class="hero"', "hero 头部"),
    ('path-box', "学习路径区块"),
    ('id="toc"', "导航"),
    ('<script>', "脚本"),
    ('initStepper', "流程推演组件定义"),
    ('initSorter', "归类练习组件定义"),
    ('renderPath();', "进度初始化调用"),
    ('@@CUSTOM_JS@@', "定制 JS 占位符（应已被替换）"),
]
FORBIDDEN = [
    ('{{', "未替换的占位符"),
    ('quizArea', "测验区块（本 skill 不产出）"),
    ('quiz', "测验链接/区块"),
]


def check(n: int) -> list:
    path = f"study/{n}-study.html"
    errs = []
    if not os.path.exists(path):
        return [f"文件不存在: {path}"]

    with open(path, encoding="utf-8") as f:
        s = f.read()

    for needle, desc in REQUIRED:
        if needle == '@@CUSTOM_JS@@':
            if needle in s:
                errs.append("占位符未替换: @@CUSTOM_JS@@")
        elif needle not in s:
            errs.append(f"缺少组件: {desc} ({needle})")

    for needle, desc in FORBIDDEN:
        if needle in s:
            errs.append(f"不应出现: {desc} ({needle})")

    # 导航锚点与章节 id 对应
    for m in re.finditer(r'href="#(s\d+)"', s):
        if f'id="{m.group(1)}"' not in s:
            errs.append(f"导航锚点 #{m.group(1)} 无对应章节")

    # 学习路径步骤的 data-target 有效
    for m in re.finditer(r'data-target="#(s\d+)"', s):
        if f'id="{m.group(1)}"' not in s:
            errs.append(f"路径步骤 data-target #{m.group(1)} 无对应章节")

    # 交互组件初始化（CUSTOM_JS 中应有实际调用）
    calls = len(re.findall(r'initStepper\(|initSorter\(|condUpdate|addEventListener\("change"', s))
    if calls < 1:
        errs.append("定制交互未初始化（无 initStepper/initSorter/simulator 调用）")

    # 案例块数量
    cases = s.count('class="case"')
    if cases < 15:
        errs.append(f"案例块仅 {cases} 个，要求 ≥15")

    # 章节数
    chapters = len(re.findall(r'<section class="chapter"', s))
    if chapters < 5:
        errs.append(f"章节数仅 {chapters} 个，要求 ≥5")

    # localStorage key
    if f"yoga{n}-study-progress" not in s:
        errs.append("localStorage key 与卷号不符")

    kb = len(s.encode("utf-8")) / 1024
    if kb < 25:
        errs.append(f"篇幅过短（{kb:.0f} KB < 25 KB），案例可能不足")

    if not errs:
        print(f"[{n}] ✓ {path} ({kb:.0f} KB, 章节 {chapters}, 案例 {cases}, 交互调用 {calls})")
    else:
        print(f"[{n}] ✗ {path}")
        for e in errs:
            print(f"   - {e}")
    return errs


def main():
    ns = sys.argv[1:]
    if not ns:
        print(__doc__)
        sys.exit(1)
    failed = False
    for n in ns:
        if check(int(n)):
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
