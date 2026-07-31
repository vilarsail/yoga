# 瑜伽师地论长文本段落提取与分割设计说明书 (Specification of Long Paragraph Extraction and Segmenting)

## 1. 项目背景与设计理念 (Background & Design Philosophy)

本项目旨在处理并校勘经典《瑜伽师地论》的原文与译文，以利于读者阅读和学者研究。由于《瑜伽师地论》原文（存储于 `origin/x.txt`，如 `origin/6.txt` 等）包含较多超长段落（长度超过 300 字），直接阅读体验较差，且不利于后续更细粒度的文本对齐、智能校勘和 AI 语义翻译。

为了提高长段落的可读性，我们设计了**长段落集中提取与分步骤拆分方案**：
1. **第一阶段（当前阶段）**：使用精确、鲁棒的离线脚本，自动识别出 `origin/x.txt` 中所有长度大于 300 字的超长段落。将其统一提取，并以结构化的格式输出到 `output/x.long.json` 中。
2. **第二阶段（后续阶段）**：借助大型语言模型（LLM）的深度语义理解能力，对提取出的超长段落进行智能语义切分。分割后的子段落将回填至该 JSON 结构中。
3. **最终目标**：根据 JSON 中记录的原文长段落 (`origin`) 与分割后的段落 (`split`) 的映射关系，对原文中的超长段落进行精确的替换与回填，最终生成如 `split/6.md` 的高质量排版 Markdown 文档。

---

## 2. 字段设计与 JSON Schema (Fields Design & JSON Schema)

为了保证后续模型分割以及回填替换的精确无误，我们将 `output/x.long.json` 的数据结构设计如下。

每个 JSON 文件都是一个包含多个对象的 JSON 数组，每个对象代表一个被提取出来的超长段落。

### 字段说明
- **`origin`** (string, 必填): 对应原文中完整、未作任何修改（保留原始开头空格、尾部换行或特殊排版字符）的原始长段落文本。这作为回填替换时的**精确查找键 (Lookup Key)**。
- **`split`** (array of strings, 必填): 用于存储在未来阶段由大模型语义切分后的子段落列表。在当前的第一步提取中，此列表初始化为空数组 `[]`。

### JSON 示例
以 `output/6.long.json` 为例，其具体内容结构如下：

```json
[
  {
    "origin": "　　因中有果论者。谓如有一若沙门若婆罗门。起如是见立如是论。常常时恒恒时。于诸因中具有果性。...（此处省略文字）...如是由施设故求取故。所作决定故。生故。彼见因中常有果性。 ",
    "split": []
  },
  {
    "origin": "　　应审问彼。汝何所欲。何者因相。何者果相。因果两相。为异不异。...（此处省略文字）...由此因缘。彼所立论。非如理说。如是不异相故。异相故。未生相故。已生相故。不应道理。 ",
    "split": []
  }
]
```

---

## 3. 提取脚本实现逻辑 (Extraction Script Implementation)

提取脚本采用 Python 编写（名为 `extract_long_paragraphs.py`），具有极高的精确性与容错能力。

### 核心逻辑
1. **扫描与目录创建**：脚本自动遍历 `origin/` 目录下所有以 `.txt` 结尾的原始文本文件。如不存在目标输出目录 `output/`，将自动创建。
2. **段落划分**：将读取的文本内容按换行符 `\n` 进行划分，获得原始的段落列表。
3. **长度过滤阈值**：
   - 对每一个段落进行首尾空白字符去除（`p.strip()`），并计算其字符长度。
   - 当去除首尾空白字符后的长度**严格大于 300 字**（`len(p_stripped) > 300`）时，判定其为目标长段落。
4. **保留原始排版**：在提取出的 `"origin"` 字段中，我们保留了段落原汁原味的字符（包括可能存在的中文全角空格 `　　` 和末尾空格），以确保后续的字符串查找与替换操作（`text.replace(item['origin'], "\n\n".join(item['split']))`）能够实现 100% 精确的一对一无损匹配。
5. **结构化持久化**：将提取出的数据以 UTF-8 编码写入 `output/{base_name}.long.json`，并使用双空格美化排版（`indent=2`），且通过 `ensure_ascii=False` 保证中文中文字符不被转义，便于人工校对与查看。

---

## 4. 后续步骤规划与替换机制 (Future Segementation & Replacement Strategy)

### 步骤一：语义分割 (Semantic Segmentation)
由于佛学经典《瑜伽师地论》文意深奥、句式复杂，传统的按标点符号等物理长度切分容易割裂完整的句义（例如复杂的因明论证和主客问答）。
后续将编写脚本调用大语言模型（如 GPT-4 或 Claude 3.5），输入 `"origin"` 字段的原文长段，结合前后文语境和佛教因明学背景，进行合理的语义分割，并将分割后的子段落存入 `"split"` 数组中。

### 步骤二：原地匹配与无损替换 (In-place Replacement)
当 `output/x.long.json` 中的 `"split"` 字段填充完毕后，将通过一个自动化的回填脚本，执行以下替换动作：
1. 读取原始文件 `origin/x.txt` 中的全文内容 `text`。
2. 载入对应的 `output/x.long.json`。
3. 遍历其中的每个长段落记录：
   ```python
   for item in long_paragraphs_data:
       original_paragraph = item["origin"]
       split_paragraphs = item["split"]
       if split_paragraphs:
           # 用两个换行符连接分割后的子段落，替换原文中对应的长段落
           replacement = "\n\n".join(split_paragraphs)
           text = text.replace(original_paragraph, replacement)
   ```
4. 将最终替换后的文本保存为 Markdown 格式（输出至 `split/x.md`）。由于我们在 `"origin"` 中完整、精确地保留了段落的物理原样，该替换算法能保证绝对的安全、无遗漏和无任何副作用。

---

通过该科学的数据流设计，我们为后续 AI 语义分割与《瑜伽师地论》数字排版的无损升级打下了坚实的技术基础。
