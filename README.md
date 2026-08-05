# 瑜伽师地论

本项目是《瑜伽师地论》（弥勒菩萨说·玄奘译）的现代汉语重译本，附有导读与词语注释，目的是方便阅读、便利学习。

## 项目简介

本书为《瑜伽师地论》的重译版本。初版因 AI 技术与工程实践所限，越到后期章节问题越多；本次 V2.0 重译借助更成熟的大语言模型与工程能力，进行了全面优化与校对。主要更新：

1. 三轮翻译、检查与校对，最大程度保证原文与译文的准确性；
2. 基于语义理解对原文进行智能化段落重划，解决原文段落过长、对照阅读困难的问题；
3. 每卷增设导读，总括内容、梳理逻辑架构；
4. 新增专业术语对照表，对难点、重点术语补充详细译注。

详细说明请阅读[前言](output/0.md)。

## 成品下载

仓库内已附带打包好的电子书，可直接下载阅读：

- [瑜伽师地论(重译版).epub](瑜伽师地论(重译版).epub)
- [瑜伽师地论(重译版).pdf](瑜伽师地论(重译版).pdf)

如需自行打包，见下方[打包脚本](#打包脚本)一节。

## 目录结构

```
.
├── origin/                # 原文（txt，100 卷）
├── docs/                  # 早期版本的译文/原文 markdown（100 卷）
├── output/                # 最终成品（100 卷，每卷 3 个文件）
│   ├── 0.md               # 前言
│   ├── N.md               # 第 N 卷原文 + 译文（中英对照式排版）
│   ├── N.guide.md         # 第 N 卷导读
│   └── N.notes.md         # 第 N 卷词语注释
├── .claude/skills/        # 翻译/校对/修复/导读生成的 AI skill 定义与脚本
├── build_epub.py          # epub 打包脚本
├── cover.jpg              # epub 封面
└── 瑜伽师地论(重译版).epub  # 打包成品
```

每卷包含三类文件：

| 文件 | 内容 |
|---|---|
| `N.guide.md` | 导读，约 1200 字，概述本卷主旨与逻辑架构 |
| `N.md` | 原文与译文，原文段以全角空格缩进、译文段以 `*` 起首，原文段中以 ①②③… 标注术语位置 |
| `N.notes.md` | 词语注释，按圈号顺序列出本卷术语的释义 |

## 打包脚本

使用 [build_epub.py](build_epub.py) 将 `output/` 下的文件打包为 epub。需先安装 pandoc（macOS: `brew install pandoc`）。

```bash
python3 build_epub.py                  # 打包全部：前言 + 100 卷，封面 cover.jpg
python3 build_epub.py 1 50             # 只打包卷 1-50（不含前言）
python3 build_epub.py -o 自定义.epub    # 自定义输出文件名
python3 build_epub.py -c cover.png     # 自定义封面图片
python3 build_epub.py -c ""            # 不使用封面
```

打包顺序：前言 → 各卷导读 → 原文译文 → 注释，卷间分页。

## AI 工程链路

本项目借助以下 AI skill 完成翻译与校对，定义于 `.claude/skills/` 下：

| Skill | 作用 |
|---|---|
| `translate-yoga` | 原文 → 现代汉语翻译，三轮流程 |
| `check-yoga` | 译文校对，标出问题段落 |
| `fix-yoga` | 校对问题的人工/智能判定与改写 |
| `read-yoga` | 导读与词语注释生成，带圈号位置校验 |
| `split-origin` | 原文按语义段落拆分 |

各 skill 内的 Python 脚本均使用相对路径，clone 后即可运行。

## 参与贡献

欢迎参与校对勘误或格式调整。可在以下托管站点提 MR 或 issue：

- GitHub: https://github.com/vilarsail/yoga
- Gitee: https://gitee.com/vilarsail/yoga

## 版本信息

- 版本：V2.0
- 整理人：君言
- 辅助 AI：deepseek-v4 / glm5.2
- 联系邮箱：[vilarsail@163.com](mailto:vilarsail@163.com)

**广大第一常，其心不颠倒**

**利益深心往，此乘功德满**
