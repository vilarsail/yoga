---
name: read-yoga
description: 通读《瑜伽师地论》一篇 output/*.md 的原文（文言文，不读译文），产出 output/{N}.guide.md 导读（400-1200字，1200左右或略超均可接受）与 output/{N}.notes.md 重难点词语注释表；圈号标注（① ②）直接写入 output/{N}.md 的原文词语首次出现处。序号定位与全部校验由确定性脚本完成，LLM 只做语义，原文永不进入 LLM 写入路径。当用户输入 /read-yoga <start> <end> 或要求"生成第 X-Y 卷的导读与注释"、"为第 X-Y 卷写阅读指南"时触发。
---

# 角色与目标

你是《瑜伽师地论》阅读辅助 Agent。任务是为 `output/` 目录下（如 `output/1.md` ~ `output/100.md`）的每一卷，产出两份阅读辅助文件：

1. **导读** `output/{N}.guide.md`——让没读过此卷的人最快上手：内容总览、**结构层次（文章骨架与逻辑推进）**、关键结论、易混辨析，400-1200 字（1200 左右或略超均可接受，不必为压字数而牺牲内容）。
2. **重难点词语注释**——在 `output/{N}.md` 的**原文**中，于词语**首次出现处**以 ① ② ③… 圈号标注；注释表 `output/{N}.notes.md` 统一收存，与圈号一一对应。

**只读原文文言文，不读译文**——译文是同一流水线的下游产物，不携带独立信息。原文已包含导读与注释所需的全部信息。

# 架构设计（重要）

**原文永不进入 LLM 写入路径。** LLM 只输出一个 JSON（导读 + 术语列表），圈号定位、插入、校验全部由确定性脚本完成：

```
prepare_reading.py → reading_{N}_orig.txt → [LLM] → notes_{N}.json → build_reading.py → output/{N}.guide.md + output/{N}.notes.md + output/{N}.md(写入圈号标注)
```

- `prepare_reading.py <N>`：从 `output/{N}.md` 提取**原文-only 紧凑文本**（标题 + 带 P 段号的 　　 段，跳过 * 译文行、空行）→ `output/reading_{N}_orig.txt`
- LLM：通读原文，写 `output/notes_{N}.json`（`{"guide": "...", "terms": [{"term": "...", "note": "..."}]}`）
- `build_reading.py <N>`：校验术语 → 按首次出现位置分配 ①-㊿ → 在 `output/{N}.md` 的**原文**中插入标注 → 生成 `output/{N}.guide.md`（导读）+ `output/{N}.notes.md`（注释表）→ 字符流/圈号/对应校验 → 打印汇总

**标注写入 `output/{N}.md` 的原文**（译文、标题、空行原样保留）；`output/{N}.notes.md` 只含注释表，`output/{N}.guide.md` 为导读。

# 核心原则（LLM 与脚本的职责边界）

1. **LLM 不做任何序号工作**——不给术语编号、不数位置。圈号由脚本按「原文中首次出现位置」自动分配，术语在 JSON 里的先后顺序无关紧要。
2. **术语必须是原文精确子串**——不含 P 编号、不含空格/换行、不含 　　 前缀。脚本逐词校验，找不到即构建失败并列出，需修正轮。
3. **术语数量 15-40 个/卷，上限 50**（圈号 ①-㊿，①-⑳=1-20、㉑-㉟=21-35、㊱-㊿=36-50 共 50 个），不求穷尽。
4. **宁缺毋滥**——选词为帮读者，不为凑数；无把握的词宁可少选。

# 自动化执行工作流

## 步骤一：准备（确定性脚本）

对每个目标文件 `N`：
```
python3 .claude/skills/read-yoga/prepare_reading.py <N> [<M> ...]
```
生成 `output/reading_{N}_orig.txt`（LLM 的输入）。若提示该文件段数很多，不影响——LLM 单次通读即可。

## 步骤二：LLM 生成 notes_{N}.json

读取 `output/reading_{N}_orig.txt`，按 `AGENT_INSTRUCTIONS.md` 的要求撰写导读与术语，写入 `output/notes_{N}.json`。

### 小范围（≤5 卷）：主代理直接处理

在一个 turn 内逐卷处理：Read 原文 → Write `notes_{N}.json` → 一行状态。不需要子代理。

### 大范围（≥6 卷）：并行子 Agent

对每卷派发一个子 Agent（`subagent_type: general-purpose`），**所有子 Agent 在同一轮消息中并行派发**。prompt 精简（指令在 AGENT_INSTRUCTIONS.md，子 Agent Read 一次命中缓存）：

```
读取 .claude/skills/read-yoga/AGENT_INSTRUCTIONS.md 获取导读与词语注释生成指令，按其要求撰写。

输入文件：output/reading_{N}_orig.txt
输出文件：output/notes_{N}.json
```

子 Agent 只写 `notes_{N}.json`，不校验、不插入圈号——这些由脚本完成。

## 步骤三：构建 + 校验（确定性脚本）

所有 `notes_{N}.json` 就绪后：
```
python3 .claude/skills/read-yoga/build_reading.py <start> <end>
```
- 校验：guide 非空、术语 ≤50、无重复、每个术语出现在原文中
- 分配圈号、在 `output/{N}.md` 原文中插入标注、生成 `output/{N}.guide.md` 与 `output/{N}.notes.md`（注释表）
- 内置校验：字符流完整性（标注后原文-圈号-空白 == 原文-空白）、圈号连续递增、注释表与正文圈号 1:1 对应

## 步骤四：修正轮

`build_reading.py` 报错（exit 1）时，读取打印的错误行：
- **「术语未在原文中找到：『XX』」** → 打开 `output/notes_{N}.json`，把该 term 改为原文中确实存在的片段，或直接删除该条；
- **「术语 X 个超过上限 50」** → 精简到 40 个以内；
- **「guide 为空 / terms 为空」** → 补写。

修完重跑 `build_reading.py <N>`。同一文件最多两轮修正，仍失败则报告用户（列出失败的术语），不要无限重试。

**「术语被丢弃（重叠且无独立出现位）」** 是 ⚠ 警告（exit 0），不阻断：该术语与另一个更长术语重叠且无处安放，已从注释表移除并打印告知，无需修正。

## 步骤五：清理

成功后删除临时文件：`output/reading_{N}_orig.txt`、`output/notes_{N}.json`。

# 注意事项

- **原文 100% 由脚本保留**：LLM 写 JSON 时完全接触不到原文；`output/{N}.md` 仅由脚本插入圈号，译文/标题/空行不动。
- **重跑幂等**：`parse_md` 会先剥离旧圈号再插入新标注，重复运行不会叠加圈号。
- **与翻译流水线的关系**：`output/{N}.md` 写入圈号后，若日后重跑 `translate-yoga`（`merge_translations.py` 会用原始原文覆写该文件），标注会丢失，需重新生成 `notes_{N}.json` 后重跑 `build_reading.py`。`check-yoga`/`fix-yoga` 按 　　/* 行识别段落，圈号位于原文段内部，不影响段落识别。
- 导读字数 400-1200 均可接受（1200 左右或略超不需精简），脚本会打印实际字数，仅明显偏短（<400）或异常偏长（>1500）时以 ⚠ 提示。**不要为压字数而触发额外的精简轮次**——资源消耗不值得。
- 圈号上限 50，对应 Unicode 圈号数字 ①-㊿（①-⑳=1-20、㉑-㉟=21-35、㊱-㊿=36-50）。

# 交互反馈

- 启动时，简要确认要处理的卷范围。
- ≥6 卷时告知将并行派发 N 个子 Agent。
- 处理中保持静默高效。
- 结束后输出简明报告：卷数、每卷术语数、校验结果（全部 ✓ / 有 ✗ 需修正）。
