---
name: translate-yoga
description: 批量且高精度翻译《瑜伽师地论》古文（output/*.md）。超过20段的大文件自动拆分为每20段一个批次，通过并行子Agent独立翻译，避免上下文衰减。应用滑动窗口机制（每次5段，参考前2段上下文）确保语义连贯及唯识宗名词准确。原文与译文通过确定性脚本分合，LLM 只做翻译，无需校验。当用户输入 /translate-yoga <start> <end> 或要求"翻译第 X-Y 个文件"时触发。
---

# 角色与目标
你是一个运行在 Claude Code CLI 环境下，专门用于古文佛典翻译的自动化 Agent。你的任务是将 `output/` 目录下（如 `output/1.md` 到 `output/100.md`）的《瑜伽师地论》原文，翻译为典雅、流畅的现代汉语。

# 架构设计（重要）

**原文永不进入 LLM 写入路径。** 拆段和合并由确定性脚本完成，LLM 只负责翻译。

```
split_paragraphs.py  →  paragraphs_{N}.json  →  [LLM 翻译]  →  translations_{N}.json  →  merge_translations.py  →  output/{N}.md
```

- `split_paragraphs.py`：从 `output/{N}.md` 提取段落 → JSON
- LLM：读 JSON，滑动窗口翻译，写 JSON
- `merge_translations.py`：读原文 + 译文 JSON → 覆写 `output/{N}.md`

# 核心翻译原则
1. **信达雅与专业性**：准确理解句读逻辑，将古文转换为现代白话文，精准保留唯识宗法相名词（如：嗢拖南、阿赖耶识、三摩呬多地、等无间依等）。
2. **免译清单**：**绝对不要翻译任何标题**（即带有 `#`, `##`, `###` 等 Markdown 标记的行）。标题不参与分块、不翻译。
3. **格式要求**：所有翻译出的正文内容，必须以**斜体**（Markdown 中的 `*翻译内容*`）格式化。**仅包含译文本身，不得添加任何前缀标记**（如"译文"、"翻译"、"译"等）。
4. **逐段对照**：每段原文后紧跟其译文（斜体），形成"原文段 → 译文段 → 原文段 → 译文段 ..."的交替结构。
5. **颂偈必须真正翻译**：不要照抄原文，要将偈颂翻译为有韵律的现代白话。多行段落每行单独用 `*` 包裹，行间 `\n` 分隔。

# 段落定义（重要）
- **段落 = `output/{N}.md` 中以 `　　` 开头的一个连续文本块**，无论它是单行还是多行（颂偈等多行段也算 1 段）
- **标题行（`#`/`##`/`###`）不算段落**，不参与分块、不翻译、合并时原样保留
- 空行不算段落，仅作分隔

# 自动化执行工作流 (Workflow)
当你被触发处理文件时（例如用户输入 `/translate-yoga 1 5`），请对每一个目标文件严格执行以下步骤：

## 步骤一：拆段（确定性脚本）
对每个目标文件 `N`，运行：
```
python3 .claude/skills/translate-yoga/split_paragraphs.py <N>
```
这会生成 `paragraphs_{N}.json`，格式为 `{"1": "原文段落1", "2": "原文段落2\n多行", ...}`。

## 步骤二：滑动窗口翻译（LLM 核心工作）
读取 `paragraphs_{N}.json`，按段落顺序，将**每 5 个段落**划分为一个翻译块（Chunk）。

- 最后一个 Chunk 不足 5 段也单独成块。

依次对每个 Chunk 进行翻译，遵循"滑动窗口"机制：
- **引入上下文**：提取当前 Chunk 前方的 2 个段落作为 `<context>`（语境参考，**不翻译**，仅给你参考），以防断章取义造成的幻觉或漏译。若文件开头不足 2 段，则用实际可得的段落。
- **翻译目标**：将当前的 5 个段落作为 `<target>` 进行翻译，保持段落数量一一对应（5 段原文 → 5 段译文）。
- **输出要求**：
  - 确保偈颂等特殊文体真正翻译为富有韵律的现代白话，**不要照抄原文**。
  - **多行段落（颂偈等）**：译文也是多行，每行单独用 `*` 包裹斜体，行与行之间保持换行（不要把多行段压成一行）。
  - 每段译文独立成段，与原文段落顺序严格对应。
  - **译文仅包含翻译内容本身，不得添加任何前缀文字**（如"译文"、"翻译"等）。

## 步骤三：累积写入 translations_{N}.json
每翻译完一个 Chunk，将译文以 **JSON 追加**方式写入 `translations_{N}.json`。最终文件格式：
```json
{
  "1": "*译文段落1*",
  "2": "*译文行1*\n*译文行2*\n*译文行3*",
  "3": "*译文段落3*",
  ...
}
```
- 键为段落编号（字符串），与 `paragraphs_{N}.json` 严格对应
- 值为完整的斜体 Markdown 字符串（含 `*` 包裹）
- 多行段落的每一行单独用 `*` 包裹，换行符 `\n` 分隔

## 步骤四：合并（确定性脚本）
翻译完成后，运行：
```
python3 .claude/skills/translate-yoga/merge_translations.py <N>
```
这会读取 `paragraphs_{N}.json` 和 `translations_{N}.json`，将译文逐段插入原文之后，覆写 `output/{N}.md`。

最终文件结构：
```markdown
# 标题（原样保留）

## 小标题（原样保留）

　　原文段落1
*译文段落1...*

　　原文段落2（颂偈，多行）
*译文第1行...*
*译文第2行...*

　　原文段落3
*译文段落3...*
```

**要点**：
- 原文与译文之间**不要**加 `---` 分割线
- 译文紧跟原文，中间仅一个空行
- 标题行后不加译文
- 原文 100% 由脚本保留，无需 LLM 校验

## 步骤五：清理
翻译成功后，删除 `paragraphs_{N}.json` 和 `translations_{N}.json`（临时文件）。

# 大文件分批机制（关键）

**问题**：当单个文件段落数超过约 20 段时，LLM 在单次会话中处理全部段落会出现**上下文注意力衰减（context degradation）**：前半部分翻译质量正常，后半部分逐渐退化为仅做标点替换而非真正的古文→白话翻译。部分文件可能长达 200-300 段，必须分批处理。

**机制**：以 **每 20 段为一个批次**，使用 `Task` 工具（`subagent_type: general_purpose_task`）将每个批次派发给独立的子 Agent，**所有批次并行执行**。

## 执行流程

### 步骤 2.0：判断是否需要分批
1. 运行 `split_paragraphs.py <N>` 得到总段落数 `P`
2. 若 `P <= 20`：按正常流程（步骤二至步骤五）在当前会话中一次性处理，跳过以下分批步骤
3. 若 `P > 20`：执行以下分批流程

### 步骤 2.1：生成批次文件
用 Python 脚本将段落按每 20 段拆分为多个批次，每个批次生成独立的 JSON 文件：

```bash
python3 -c "
import json
data = json.load(open('paragraphs_{N}.json'))
P = len(data)
batch_size = 20
batch_num = 0
for start in range(1, P + 1, batch_size):
    batch_num += 1
    end = min(start + batch_size - 1, P)
    batch = {}
    # 注入前 2 段上下文（如果存在）
    ctx_start = max(1, start - 2)
    if start > 1:
        batch['_context_keys'] = [str(i) for i in range(ctx_start, start)]
        for i in range(ctx_start, start):
            batch[f'_context_{i}'] = data[str(i)]
    # 目标段落
    batch['_target_keys'] = [str(i) for i in range(start, end + 1)]
    for i in range(start, end + 1):
        batch[str(i)] = data[str(i)]
    batch['_start'] = start
    batch['_end'] = end
    batch['_batch'] = batch_num
    batch['_total_batches'] = (P + batch_size - 1) // batch_size
    json.dump(batch, open(f'paragraphs_{N}_batch{batch_num}.json', 'w'), ensure_ascii=False, indent=2)
    print(f'Batch {batch_num}: paragraphs {start}-{end} ({len(batch[\"_target_keys\"])} paragraphs)')
"
```

### 步骤 2.2：并行派发子 Agent
**关键**：所有批次必须在**同一轮消息中并行派发**（使用多个 `Task` 工具调用），确保每个子 Agent 拥有独立的上下文窗口，互不污染。

对每个批次，使用 `Task` 工具派发（`subagent_type: general_purpose_task`）。

**子 Agent prompt 必须精简**（不内联完整指令，指令由 AGENT_INSTRUCTIONS.md 提供，子 Agent Read 一次即可，后续命中 prompt cache）。

**占位符替换**：下方模板中的 `{N}` 替换为实际章节号，`{batch_num}` 替换为实际批次号。例如章节 21 的第 2 批次：`paragraphs_21_batch2.json`。

**工作目录**：以下路径均相对于项目根目录（即 `.claude/` 所在的目录）。子 Agent 工作目录默认为项目根，直接使用相对路径即可。

```
读取 .claude/skills/translate-yoga/AGENT_INSTRUCTIONS.md 获取翻译指令，按其要求翻译。

批次文件：paragraphs_{N}_batch{batch_num}.json
输出文件：translations_{N}_batch{batch_num}.json
```

**为什么这样省 token**：完整翻译指令（~900 tokens）写一次在 AGENT_INSTRUCTIONS.md 里，所有子 Agent Read 同一文件，主 Agent 派发 N 个 Task 时每个 prompt 仅 ~80 tokens。相比旧方案每个 Task prompt 内联 ~1500 tokens 指令，N 个批次省下 (N-1) × 1500 tokens。

### 步骤 2.3：合并批次 + 过滤元数据 + 格式修复 + 未翻译检查
所有子 Agent 完成后，运行以下脚本一次性完成合并、过滤、修复、检查：

```bash
python3 -c "
import json, re, copy, difflib, os

N = '{N}'  # 章节号，需替换

# 1. 合并所有批次文件，过滤 _ 前缀的元数据键
merged = {}
batch_num = 1
batches_found = 0
while True:
    path = f'translations_{N}_batch{batch_num}.json'
    if not os.path.exists(path):
        break
    batch = json.load(open(path))
    for key, value in batch.items():
        if key.startswith('_'):
            continue  # 跳过元数据键（_context_*, _target_keys, _start 等）
        merged[key] = value
    batches_found = batch_num
    batch_num += 1

if batches_found == 0:
    print('ERROR: 未找到任何批次文件')
    exit(1)

# 2. 格式修复（保存副本用于统计）
original = copy.deepcopy(merged)
fixed = 0
for key, value in merged.items():
    if not isinstance(value, str):
        print(f'WARNING: paragraph {key} value is not string: {type(value).__name__}')
        continue
    # 修复1: 去掉 '译文' 等前缀标记
    value = re.sub(r'^\*译文\*\s*', '*', value)
    value = re.sub(r'^\*翻译\*\s*', '*', value)
    value = re.sub(r'^\*译\*\s*', '*', value)
    # 修复2: 确保每行都以 * 开头和结尾（多行段落的每行）
    if '\n' in value:
        lines = value.split('\n')
        cleaned = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('*'):
                line = '*' + line
            if line and not line.endswith('*'):
                line = line + '*'
            cleaned.append(line)
        value = '\n'.join(cleaned)
    # 修复3: 确保以 * 开头结尾
    if value and not value.startswith('*'):
        value = '*' + value
    if value and not value.endswith('*'):
        value = value + '*'
    merged[key] = value
    if value != original[key]:
        fixed += 1

json.dump(merged, open(f'translations_{N}.json', 'w'), ensure_ascii=False, indent=2)
print(f'Merged {batches_found} batches -> {len(merged)} translations, {fixed} entries fixed')

# 3. 检查未翻译的段落（译文与原文相同或仅标点差异）
paragraphs = json.load(open(f'paragraphs_{N}.json'))
warnings = 0
for key, value in merged.items():
    if key in paragraphs and isinstance(value, str):
        orig = paragraphs[key].replace('　　', '').replace('。', '').replace('，', '').replace(' ', '')
        trans = value.replace('*', '').replace('。', '').replace('，', '').replace(' ', '')
        ratio = difflib.SequenceMatcher(None, orig, trans).ratio()
        if ratio > 0.8 and len(orig) > 20:
            print(f'WARNING: paragraph {key} may not be translated (similarity {ratio:.1%})')
            warnings += 1
if warnings:
    print(f'Total untranslated warnings: {warnings}')
"
```

**脚本要点**：
- **过滤元数据键**：`if key.startswith('_'): continue` 防止子 Agent 误输出的 `_context_*`、`_target_keys` 等进入合并结果（元数据值多为 list/int，会让后续格式修复脚本的 `re.sub` 崩溃）
- **类型检查**：`isinstance(value, str)` 跳过非字符串值（防御性）
- **一次读写**：合并 + 修复 + 检查在一次脚本中完成，减少 JSON 读写

修复后，人工检查 WARNING 提示的段落，确认是否需要重新翻译。

### 步骤 2.4：继续执行步骤四和步骤五
合并完成后，继续执行步骤四（`merge_translations.py`）和步骤五（清理，包括所有批次临时文件）。

## 注意事项
- **并行是关键**：所有子 Agent 必须在同一轮消息中派发，不要顺序处理
- 每 20 段一个 Agent，超过 200 段的大文件会有 10+ 个 Agent 并行，效率极高
- 每个子 Agent 有独立上下文，不会出现注意力衰减
- 上下文段落（`_context_*`）仅用于帮助子 Agent 理解语义连续性，不翻译、不输出

# 交互反馈
- 启动时，简要向用户确认将要处理的文件范围。
- 检测到段落数 > 20 时，告知用户将拆分为 N 个批次、派发 N 个并行子 Agent。
- 处理过程中，保持静默和高效运作。
- 所有子 Agent 完成后，告知用户合并结果。
- 任务结束时，输出一份简明的处理报告，说明成功处理的文件数量。