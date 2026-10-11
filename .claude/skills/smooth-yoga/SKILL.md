---
name: smooth-yoga
description: 明晰化《瑜伽师地论》译文（output/*.md）。针对「内容正确但表达晦涩」的段落——译文只做了标点/个别词替换或半文半白改写，仍保留文言句式、紧缩省略，读者难以读懂——在假定原译文内容正确的前提下，保持原意不变，改写为顺畅的现代白话；改写后自动逐段校验忠实性（防错/漏），不通过则修正或回退。产出报告 output/{N}.smooth.md。当用户输入 /smooth-yoga <start> <end> 或要求"明晰化第 X-Y 个文件"、"修复晦涩译文"、"把第 X-Y 卷译文改顺畅"时触发。
---

# 角色与目标

你是《瑜伽师地论》译文明晰化 Agent。任务是把 `output/{N}.md` 中「内容正确但表达晦涩」的译文段改写为顺畅的现代白话，改写后逐段校验，最终生成 `output/{N}.smooth.md` 报告。

**与 check-yoga 的分工**：check-yoga 抓的是 NEAR-COPY（几乎照抄原文、连标点都没换）。本 Skill 抓的是另一类更普遍的退化——译文已经动了几个词、加了几个"的"，但骨架仍是文言：`谓…`、`由…故`、`尔所`、`无间`、省略主语、紧缩复句、逐字直译语序。翻译"对了"，但读者读不懂，等于没翻译。本 Skill 的目标：**假设原译文内容正确，只换表达，不动含义。**

# 架构设计

```
prepare_smooth.py → smooth_{N}_pairs.json + smooth_{N}_batch*.json
    → [阶段A：LLM 逐段判定晦涩 + 改写] → smooth_{N}_batch*.rewrite.json
    → apply_smooth.py → output/{N}.md（应用改写） + smooth_{N}_applied.json + smooth_{N}_vbatch*.json
    → [阶段B：LLM 逐段校验忠实性] → smooth_{N}_vbatch*.result.json
    → finalize_smooth.py → output/{N}.md（修正/回退） + output/{N}.smooth.md
```

- `prepare_smooth.py`：机械提取「原文段→译文段」对并分批（含前 2 段上下文）。不做任何判断。
- **阶段A（改写子 Agent）**：读批次文件全量原文+译文，逐段判定是否「晦涩难懂」（判定标准见 AGENT_INSTRUCTIONS.md），晦涩的段落直接改写为新译文。**判定与改写在同一次读取中完成**——先扫描判定、再改写是一个判断动作的两面，拆开只会多读一遍文本。
- `apply_smooth.py`：校验新译文格式（每行 `> ` 开头、颂偈行数），应用到 `output/{N}.md`；同时由 pairs + 改写结果**机械拼装**出阶段B的校验批次文件（含原文、原译文、新译文），**不需要任何人重读 output/{N}.md**。
- **阶段B（校验子 Agent）**：读校验批次文件，逐段对照「原文 vs 原译文 vs 新译文」，检查改写是否引入错译、漏义，或仍未白话化。能修复的直接给出 corrected_trans，不能修复的标记 FAIL（由脚本回退到原译文）。
- `finalize_smooth.py`：合并校验结果——PASS 保留；FAIL 带 corrected_trans 且格式合规的应用修正；FAIL 无修正的**回退为原译文**（宁可保留晦涩但正确的译文，不可留下错误译文）；生成 `output/{N}.smooth.md`。

# 段落定义

与 check-yoga 完全一致：
- 段落对 = `output/{N}.md` 中「以 `　　` 开头的原文段（可多行颂偈）」+「紧跟其后的译文段（`> ` 引用块，可多行）」
- 译文段为引用块格式（每行 `> ` 开头），改写时保持行数一致即可
- `trans` 为空的段落（MISSING 问题）**不属于本 Skill 处理范围**，跳过

# 改写纪律（详见 AGENT_INSTRUCTIONS.md，此为要点）

1. **内容以原译文为准**：原译文视为正确，只改表达。不增义、不减义、不歪曲、不添加原文没有的注解或例子。
2. **白话化到位**：主谓宾完整、现代语序、文言虚词转为白话连接词（谓→意思是、故→所以、尔所→那么多、无间→紧接着）、紧缩句拆为短句。
3. **专有名词清单保留**：阿赖耶识、三摩呬多地、补特伽罗、那落迦、嗢拖南、萨迦耶见、奢摩他、毗钵舍那、等无间依、俱有依、种子依、羯罗蓝、健达缚、预流果、一来果、不还果、薄伽梵。清单外术语白话化。
4. **格式保持**：每行 `> ` 开头、颂偈行数一致、无"译文"前缀。
5. **宁缺毋滥**：不确定改写是否会改变含义时，保留原表达，不记录该段。

# 自动化执行工作流

## 步骤一：准备（确定性脚本）
对每个目标文件 `N`：
```
python3 .claude/skills/smooth-yoga/prepare_smooth.py <N>
```
生成 `smooth_{N}_pairs.json` 和 `smooth_{N}_batch{b}.json`（每批 20 段，含前 2 段上下文）。

## 步骤二：并行派发改写子 Agent（阶段A）

**关键**：所有批次必须在同一轮消息中并行派发（`subagent_type: general-purpose`），prompt 精简：

```
读取 .claude/skills/smooth-yoga/AGENT_INSTRUCTIONS.md 获取判定与改写指令，按其要求逐段判定并改写晦涩译文。

批次文件：smooth_{N}_batch{batch_num}.json
输出文件：smooth_{N}_batch{batch_num}.rewrite.json
```

上下文衰减控制：每批 ≤ 20 段、每批独立子 Agent。批次多时（>8）分轮派发。

## 步骤三：应用改写 + 生成校验批次
所有改写子 Agent 完成后：
```
python3 .claude/skills/smooth-yoga/apply_smooth.py <N>
```
- 合并各批 `.rewrite.json`（含 JSON 容错修复）
- 格式校验（每行 `> ` 开头、颂偈行数匹配），校验失败的不应用
- 应用到 `output/{N}.md`（按段落号定位译文块整体替换，从后往前避免行偏移）
- 生成 `smooth_{N}_applied.json`（改写记录，供报告使用）和 `smooth_{N}_vbatch{b}.json`（校验批次：原文 + 原译文 + 新译文）

若整批无任何段落被判晦涩（输出 `{}`），该批次不出现在校验批次中，属正常。

## 步骤四：并行派发校验子 Agent（阶段B）
```
读取 .claude/skills/smooth-yoga/VERIFY_INSTRUCTIONS.md 获取校验指令，按其要求逐段校验改写译文。

校验批次文件：smooth_{N}_vbatch{batch_num}.json
输出文件：smooth_{N}_vbatch{batch_num}.result.json
```

## 步骤五：合并校验结果 + 生成报告
```
python3 .claude/skills/smooth-yoga/finalize_smooth.py <N>
```
- PASS → 保留改写
- FAIL 带 corrected_trans → 格式校验通过则应用修正
- FAIL 无 corrected_trans → **回退为原译文**
- 生成 `output/{N}.smooth.md`

## 步骤六：清理
删除临时文件：`smooth_{N}_pairs.json`、`smooth_{N}_batch*.json`、`smooth_{N}_batch*.rewrite.json`、`smooth_{N}_applied.json`、`smooth_{N}_vbatch*.json`、`smooth_{N}_vbatch*.result.json`。

# 报告格式（output/{N}.smooth.md）

```markdown
# output/{N}.md 译文明晰化报告

- 时间：<日期>
- 段落总数：X
- 判定晦涩并改写：Y（占 Z%）
- 校验通过：A
- 校验不通过、已修正：B
- 校验不通过、已回退：C
- 格式校验失败：D
- 批次解析失败：E

## 改写记录

### 段落 3 ✅ 改写并通过校验
- **原文**：……
- **原译文**：……
- **判定理由**：……
- **新译文**：……
- **校验意见**：……

### 段落 15 ⚠️ 改写有误，已修正
- ……（同上，另含校验意见与修正后译文）

### 段落 27 ❌ 改写有误，已回退原译文
- ……

## 汇总
……
```

若没有任何段落被判晦涩：报告输出「✅ 全部译文表达清晰，无需明晰化。」

# 辅助工具：术语盲点扫描与统一整改

针对「义理复合术语被裸保留」这类盲点（可按字面解义却原样照搬，如 `无见有对`、`俱相违`、`任运`），提供两个确定性脚本：

```
python3 .claude/skills/smooth-yoga/scan_terms.py <start> <end> [--min-count N] [--top M]
```
扫描「原文与译文逐字共现」的片段（照搬未译的嫌疑对象），输出候选表 `terms_scan.json` 与控制台摘要。共现≠必改：白话句式与原文的正常重合（"如有一""有四种"）属噪音，需人工甄别出真正的紧凑术语。

```
python3 .claude/skills/smooth-yoga/rewrite_terms.py <start> <end>
```
按脚本内的替换表（REPLACE/GLOSS/PROTECT）对**译文块**做统一整改：只动译文不动原文；固定术语先保护（如 `现法涅槃`）；每文件首次出现可加括注释义（GLOSS）。改表前先人工核实每个术语的全部上下文，替换后必须复查译文块无意外残留。

# Token 节省要点

- **全文只进入子 Agent 一次**：改写 Agent 只读批次文件（原文+译文+上下文）；校验 Agent 只读校验批次文件（原文+原译文+新译文，由脚本拼装）。任何阶段都不重读 `output/{N}.md` 全文。
- 指令放在 AGENT_INSTRUCTIONS.md / VERIFY_INSTRUCTIONS.md，子 Agent Read 一次命中缓存，prompt 本身保持极简。
- 段落合格则改写 Agent 不输出该段 → 校验批次只含改写段，阶段B工作量自动最小化。

# 交互反馈

- 启动时简要确认文件范围。
- 派发后保持静默高效。
- 结束时输出：每文件判定晦涩段数、改写应用数、校验通过/修正/回退数。
