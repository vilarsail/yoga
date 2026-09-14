---
name: study-yoga
description: 为《瑜伽师地论》某一卷（output/{N}.md 校对版）生成单文件交互式学习网页 study/{N}-study.html——由易到难的学习路径、核心概念拆解（原文引用+一句话+比喻三件套）、丰富的生活案例、流程推演/条件模拟/归类练习等交互组件。结构与模板固定，仅内容随卷变化。无测验区。当用户输入 /study-yoga <start> <end> 或要求"生成第 X-Y 卷的交互学习网页/学习模块"时触发。
---

# 角色与目标

为 `output/{N}.md`（校对版，原文+译文对照）生成**交互式学习网页** `study/{N}-study.html`：让没有佛学基础的读者不读文言也能弄懂这一卷在说什么。已完成的样例：`study/3-study.html`。

# 架构

**结构与交互骨架 100% 固定，只有内容变化。**

```
template.html（CSS + 固定 JS + HTML 外壳，占位符）
        │  原样复制，替换占位符
        ▼
study/{N}-study.html
        │
        ▼
check_study.py（确定性校验：组件齐全、无占位符残留、案例≥15、无测验等）
```

- 骨架来源：`.claude/skills/study-yoga/template.html`——CSS、进度条 JS、initStepper、initSorter **一字不改**。
- 内容规范：`.claude/skills/study-yoga/AGENT_INSTRUCTIONS.md`——占位符表、章节划分、三件套（quote+plain+analogy）、案例要求、交互组件选型、忠实性规则、自检清单。**写内容前必须先读它。**
- 校验：`.claude/skills/study-yoga/check_study.py`。

# 工作流

## 步骤一：准备

```
mkdir -p study
```

## 步骤二：生成（LLM 全文通读 output/{N}.md 后撰写）

### 小范围（≤5 卷）：主代理直接处理

逐卷处理：Read `output/{N}.md` 全文 → Read `template.html` 与 `AGENT_INSTRUCTIONS.md` → Write `study/{N}-study.html`。

### 大范围（≥6 卷）：并行子 Agent

对每卷派发一个子 Agent（`subagent_type: general-purpose`），**所有子 Agent 在同一轮消息中并行派发**。prompt：

```
读取 .claude/skills/study-yoga/AGENT_INSTRUCTIONS.md 获取交互学习网页的内容撰写规范，严格按其要求执行。

输入：output/{N}.md（通读全文）
模板：.claude/skills/study-yoga/template.html（骨架原样复制，替换占位符）
输出：study/{N}-study.html
```

子 Agent 只写 HTML，不跑校验——校验由步骤三完成。

## 步骤三：校验（确定性脚本）

```
python3 .claude/skills/study-yoga/check_study.py <start> <end>
```

校验项：文件存在、组件齐全（hero/path-box/toc/stepper/sorter）、无占位符残留、无测验区块、导航锚点与章节对应、案例 ≥15、章节 ≥5、localStorage key 卷号一致、篇幅 ≥25 KB。

## 步骤四：修正轮

校验 exit 1 时，按打印的错误逐条修复：
- 缺组件 → 检查是否遗漏模板区块；
- 案例 <15 → 在对应章节补 `.case` 块（每章 ≥2）；
- 交互未初始化 → 在 `{{CUSTOM_JS}}` 位置补调用；
- 锚点不对应 → 核对 `id="sK"` 与 nav/data-target。

修完重跑 `check_study.py`。同一文件最多两轮修正，仍失败则报告用户（列出失败项），不要无限重试。

## 步骤五：交付

- 报告：卷数、每卷文件路径、校验结果。
- 单卷时可 `open study/{N}-study.html` 在浏览器中打开（先询问或按用户习惯）。

# 注意事项

- **法义忠实**：所有解释以 `output/{N}.md` 的原文与译文为准，不引入该卷没有的内容；文言引文必须是原文精确子串。
- **比喻边界**：比喻只作理解辅助，映射必须准确；拿不准的义理直接用译文释义，不用比喻。
- **无测验**：不产出任何 quiz/自测区；测试类交互只有「归类练习」(initSorter) 这种嵌在章节内的案例练习。
- **重跑幂等**：整文件重写，不存在叠加问题；localStorage key 含卷号，互不干扰。
- 案例块（`.case`）是本 skill 与其他产物的主要差异点：**全页 ≥15 个，每章 ≥2 个**，具体、现代、对应关系点明。
