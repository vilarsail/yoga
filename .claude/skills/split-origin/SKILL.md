---
name: split-origin
description: 把《瑜伽师地论》origin/*.txt 按语义分割到 output/*.md。脚本做切句、长度强制、字符流校验等确定性工作；LLM 只判断语义边界（不数字符）。当用户输入 /split-origin <start> <end> 或要求"分割第 X-Y 章原文"时使用。
---

# 分割原文（语义分割）

## 用途

把 `origin/{N}.txt` 按语义段落分割到 `output/{N}.md`。

**核心设计**：
- **脚本**做确定性工作：颂偈合并、按 `。` 切句、长度强制（`enforce-length`）、字符流校验
- **LLM** 只判断语义边界（在哪里分），**不数字符**--`enforce-length` 自动兜底切分超 300 字的段
- **三步流程**：`prepare` → LLM 写 `splits.txt` → `apply-splits` + `enforce-length`

## 调用方式

```
/split-origin <start> <end>
```

例如 `/split-origin 21 25` 分割 `origin/21.txt` ~ `origin/25.txt`。

## 原文格式

- 每行一个段落，`　　`（U+3000 × 2）前缀为正文
- 第 1 行主标题，其余非 `　　` 开头行为副标题
- 标点只有 `。`（分割点只能在此处）
- **颂偈**：以 `　　` 开头、不含 `。`、含中间 `　　` 分隔的诗体，脚本自动合并为一段
- **长段落**（>200 字）按 `。` 切成单句，待 LLM 决定分组

## 三步流程

### 第 1 步：prepare（脚本，生成 draft.md + sentences.txt）

```bash
python3 .claude/skills/split-origin/split_origin.py prepare <s> <e>
```

生成 `output/{N}.draft.md`（颂偈已合并，长段已切句）和 `output/{N}.sentences.txt`（带编号的紧凑句子列表）。

sentences.txt 格式：
```
== 长段落 1 (45句) ==
P1S1 云何总标。
P1S2 谓此地中略有四种。
...
== 长段落 2 (60句) ==
P2S1 复次初静虑中。
...
```

### 第 2 步：LLM 写 splits.txt（语义分割决策）

对每章 `output/{N}.sentences.txt`：

1. **Read** sentences.txt（一次读完）
2. **在语义边界处标记分割点**，写入 `output/{N}.splits.txt`
3. **不用数字符数**--`enforce-length` 会自动切分超 300 字的段

**splits.txt 格式**（每行一个编号，表示在该句后插入空行作为分割点）：
```
P1S5
P1S12
P1S20
P2S3
P2S15
```

编号按文档顺序排列（先 P1 所有分割点，再 P2，...）。

#### 语义边界提示

| 边界类型 | 识别特征 |
|---------|---------|
| 新论点 | "复次..."、"又..."、"...论者。" 等列举式开头 |
| 问答 | "问..." / "答..." 可分开 |
| 定义 | "云何...谓..." 短的合并，长的分 |
| 列举 | "一...二...三..." 同属一段；列举项 ≥5 时每 2-3 项一段 |
| 因果 | "由此因缘...是故..." 同属一段 |
| 小结 | "当知是名此中略义。" 等单独成段 |
| 审问 | "应审问彼。汝何所欲。" 常开始新论证 |
| 颂偈解释 | "今此颂中。" / "此颂所明。" 常开始新解释 |

**长度原则**：目标每段 100-200 字，但**不必精确计数**。LLM 负责语义边界，`enforce-length` 负责硬上限（300 字）。即使 LLM 漏分，脚本也会在句子边界自动补刀，不会破坏语义单元。

#### 防输出过长纪律

**绝对不要在对话中输出分析过程、段落解读、分割点列表的复述。** 这是导致"输出过长"的唯一根因。

- ❌ 不输出"长段落 1 分析：... 分割点：P1S5, P1S12"
- ❌ 不复述句子内容或分割点编号列表
- ❌ 不输出"正在处理第 X 章..."等进度说明
- ✅ 只输出极简状态（如"第 21 章 splits.txt 已写入，62 个分割点"）

**正确做法**：内心分析后直接用 Write 工具写 splits.txt，工具调用前后只输出极简状态。

### 第 3 步：apply-splits + enforce-length（脚本，应用分割 + 长度兜底 + 校验）

```bash
python3 .claude/skills/split-origin/split_origin.py apply-splits <s> <e> && \
python3 .claude/skills/split-origin/split_origin.py enforce-length <s> <e>
```

- **apply-splits**：按 splits.txt 在 draft.md 的长段落中插入空行（幂等）
- **enforce-length**：自动切分超过 300 字的段（安全网），然后 finalize 生成 `output/{N}.md` + 字符流校验 + 校验报告

`enforce-length` 会在句子边界（`。` 处）切分，不破坏句子。它只切分 LLM 漏分的超长段，不影响 LLM 已有的语义分割。

## LLM 操作清单

### 小范围（≤5 章）：主代理直接处理

在一个 turn 内逐章处理，无需子代理：

1. `prepare <s> <e>`（脚本）
2. 对每章：
   - Read `output/{n}.sentences.txt`
   - Write `output/{n}.splits.txt`
   - 输出一行状态
3. `apply-splits <s> <e> && enforce-length <s> <e>`（脚本）

**为什么不用子代理**：sentences.txt 和 splits.txt 都很紧凑（每章 ~1000 行输入、~100 行输出），5 章的 context 完全可控。主代理直接处理 = 1 次 LLM 调用处理全部章节；用子代理 = N 次独立 LLM 调用（每个子代理独立加载 context + 系统提示）。

### 大范围（≥6 章）：分批处理

每批 5-8 章，主代理逐章 Read + Write。或对每章启动 Task 子代理（subagent_type=Explore），子代理只返回"章号 + 分割点数"，不输出分析过程。

**分批写 splits.txt 的注意事项**：
- 超长章节（长段落 ≥8 或总句数 ≥500）可分批：前几段 Write，后续 Edit 追加
- Edit 追加示例：old_string 用上批最后一个分割点（如 `P4S44`），new_string 为 `P4S44\nP5S3\nP5S15`

## 校验逻辑

### 字符流校验（enforce-length 自动做）

去除所有空白字符（含全角空格）和 markdown `#` 前缀后，origin 与 output 的实质字符流必须完全一致（字符级精确比对）。

校验能捕获：漏字、错字、多字、标点丢失、颂偈合并漏行、句子顺序错乱等。

校验**不会**因以下变化失败：段落分隔/合并、`　　` 前缀增减、markdown 标题标记。

### 长度校验（enforce-length 自动做）

`enforce-length` 切分所有超过 300 字的段。完成后所有段 ≤ 300 字，无需额外扫描或第二轮 LLM 修复。

**重要**：不要用 `awk 'length'` 扫描超长段--awk 在多字节 locale 下算字节不算字符，会误报（中文每字 3 字节，300 字 ≈ 900 字节）。长度校验已由 `enforce-length` 完成。

## 失败处理

### enforce-length 报告 ✗

读取 `output/{N}.check_split.md`，查看差异位置和上下文。通常是 draft.md 被意外修改或 origin 文件有问题。splits.txt 只指定分割点位置，不改变字符，不会导致校验失败。

### apply-splits 报告"未找到"

检查 splits.txt 中的编号是否正确（段落号、句子号是否超出范围）。编号格式：`P` + 段落号 + `S` + 句子号。

## 示例输出

### prepare

```
============================================================
prepare: 共 5 章
============================================================
  [21] ✓ prepared: 标题=瑜伽师地论卷第二十一, 副标题=2, 颂偈=3, 短段=21, 长段=10(713句)
  [22] ✓ prepared: 标题=瑜伽师地论卷第二十二, 副标题=1, 颂偈=10, 短段=19, 长段=5(546句)
  ...

draft 文件: output/21.draft.md ~ output/25.draft.md
sentences 文件: output/21.sentences.txt ~ output/25.sentences.txt
```

### apply-splits + enforce-length

```
============================================================
apply-splits: 共 5 章
============================================================
  [21] ✓ 分割点=62, 新增=62, 已存在=0
  ...

============================================================
enforce-length: 共 5 章, 最大 300 字
============================================================
  [21] ✓ 强制分割 3 组, 分割后=75 段      ← enforce-length 补了 3 处漏分
  [22] ✓ 无超长组, 分割后=70 段           ← LLM 分割已合格，无需补刀
  ...

最终文件: output/21.md ~ output/25.md
校验报告: output/21.check_split.md ~ output/25.check_split.md
```

全部 ✓ 即完成。有 ✗ 则读 `output/{N}.check_split.md` 查看差异。

## 退出码

- `0`: 所有章节校验通过
- `1`: 校验失败或文件缺失
- `2`: 参数错误（如 start > end）

## 重要注意事项

1. **不修改原文**：脚本只做格式变换和段落合并，不改任何字符。splits.txt 只指定分割点位置（编号），不改变任何字符。

2. **颂偈合并**：脚本用确定性规则自动合并颂偈（连续宽松判定 + 至少一行严格判定）。如发现误判，可扩展 `is_verse_strict` / `is_verse_loose` 规则，但不要在 draft.md 中手动改颂偈段。

3. **enforce-length 是安全网**：LLM 不需要完美--只管语义边界，长度由脚本兜底。这消除了"第二轮修复"的 LLM 调用（旧流程的最大浪费）。

4. **草稿文件**：`output/{N}.draft.md`、`output/{N}.sentences.txt`、`output/{N}.splits.txt` 是中间文件，可保留供复查；也可在完成后删除。

5. **批量处理**：脚本支持 `start end` 区间，但 LLM 写 splits.txt 需逐章进行（语义决策不能批量）。对大区间（如 1-100），建议分批处理，每批 5-10 章。

6. **`--max-len` 参数**：`prepare` 的 `--max-len`（默认 200）决定哪些段落算"长段落"需切句；`enforce-length` 的 `--max-len`（默认 300）是段落硬上限。通常不需要调整。
