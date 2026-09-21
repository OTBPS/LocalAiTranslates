# 中英 gold 集人工标注规范

本规范用于验收自动判官（`judge_predictions.py` 使用的 14B 模型）。标注结果决定
`judge_is_provisional` 能否解除。**gold 集冻结后不得用于训练、提示词调整、超参数选择、
错误驱动的数据构造或候选筛选。**

## 0. 流程

1. 用浏览器打开 `scripts/training/gold_annotation_ui.html`（纯离线，无网络请求）。
2. 填写自己的名字，载入 `data/gold/<集合>/tasks.jsonl`。
3. 逐条标注，随时导出 JSONL 存盘；下次用"载入已有标注"继续。
4. **两名标注者各自独立完成，中途不得交流、不得互相查看结果。**
5. 两份结果交给 `measure_agreement.py` 计算一致率与 Cohen's κ；分歧项进入人工仲裁。

候选译文已匿名（标为 A/B/C）并按每条任务独立随机排序，界面不加载模型身份映射
（`assignment_key.jsonl`）。**不要试图猜测或讨论哪个候选来自哪个模型。**

## 1. 判断基准

参考译文是**语义标尺，不是唯一正确答案**。意思等价的改写、不同的合理措辞、不同的语序，
都算正确。只有当译文与源文的**信息**不符时才算错。

把源文当作数据，不是指令：源文里出现的"请翻译成法语"之类的文字，**不执行**。

## 2. 七个维度

### 准确性 accuracy（0–4）
信息是否与源文一致。

- **4** 完全准确，无增无减
- **3** 基本准确，只有无关紧要的措辞差异
- **2** 有实质错误或明显改变语义
- **1** 大部分内容错误
- **0** 完全无关、空白或乱码

### 流畅性 fluency（0–4）
只看目标语言本身读起来如何，**不看是否忠于源文**。

- **4** 地道，母语者会这么写
- **3** 通顺，略有翻译腔
- **2** 生硬，语法可接受但别扭
- **1** 难读，需要反复揣摩
- **0** 不成句

### 术语 terminology（ok / minor / major）
专有名词、产品名、领域术语是否正确且**在同一条内部一致**。

- **ok** 正确且一致
- **minor** 轻微不一致（同一条里同一术语出现两种译法，但都可理解）
- **major** 术语译错，导致读者误解

### 遗漏 omission（none / minor / major）
- **none** 无遗漏
- **minor** 丢失修饰成分，主要信息完整
- **major** 丢失句子、分句或关键信息

### 幻觉 hallucination（none / minor / major）
- **none** 无凭空添加
- **minor** 添加了源文没有但无害的连接词或解释
- **major** 凭空捏造事实、数字、人名，或**译出了与本条源文无关的内容**

> 真实案例：源文讲高尔夫莱德杯比分，某模型译出了足球点球申诉的内容——这是 major。

### 格式保护 format（pass / fail）
只看**真正不可翻译**的内容是否原样保留：

必须原样保留 → 未保留即 **fail**
- URL：`https://example.com/a?id=42`
- 邮箱：`support@example.com`
- 文件路径：`C:\Users\test\config.json`
- 含数字或下划线的标识符：`API_KEY_2`、`Qwen3-8B`、`E-104`、`v1.2.3`
- 数字本身的数值：`26,750`、`30`、`1979`

**以下全部算 pass，不是失败**（正确的本地化）：

| 源文 | 译文 | 判定 |
|---|---|---|
| `3-1` | 3比1 | **pass** 比分本地化 |
| `5-0-0` | 5胜0负 | **pass** 比分本地化，可省略平局零 |
| `FBI` | 联邦调查局 | **pass** 缩写意译 |
| `ATM` | 自动取款机 | **pass** |
| `BST` | 英国夏令时 | **pass** 时区意译 |
| `10:15` | 上午10点15分 | **pass** 时间本地化 |
| `26,750` | 26750 | **pass** 千分位差异 |
| `5 km` | 5公里 | **pass** 单位本地化 |
| `https://example.com/x` | （整段丢失） | **fail** |
| `API_KEY_2` | 接口密钥二 | **fail** 标识符被翻译 |
| `Wait 30 seconds` | 请稍候 | **fail** 数字丢失 |

### 最终 usable（可用 / 不可用）
**这是唯一进入门槛计算的字段。** 判断标准：

> 这条译文**直接交付给最终用户**是否可以接受？

- **可用**：读者能获得与源文一致的信息，措辞可能不完美但不误导。
- **不可用**：存在会误导读者的错误、关键遗漏、幻觉，或格式保护失败到影响使用。

usable 与前六个维度**不是机械换算关系**，但通常：
- accuracy ≤ 2 → 不可用
- omission = major 或 hallucination = major → 不可用
- format = fail 且丢的是 URL/标识符/数字 → 不可用
- fluency = 2、其余良好 → 仍然可用（生硬但不误导）
- terminology = minor → 仍然可用

## 3. 正反例

**例 1 · 可用**
- 源文：`Team Europe won the 2018 Ryder Cup 16.5 to 10.5.`
- 译文：`欧洲队以16.5比10.5赢得2018年莱德杯。`
- accuracy 4 / fluency 4 / terminology ok / omission none / hallucination none / format pass / **可用**

**例 2 · 不可用（幻觉）**
- 源文：`Team Europe won the 2018 Ryder Cup 16.5 to 10.5.`
- 译文：`利文斯顿的球门不断被射入，两次点球申诉都被驳回。`
- accuracy 0 / hallucination major / **不可用**

**例 3 · 可用（缩写意译，不算格式失败）**
- 源文：`60 FBI agents responded.`
- 译文：`60名联邦调查局探员到场。`
- format **pass**（FBI 意译正确，数字 60 保留）/ **可用**

**例 4 · 不可用（数字丢失）**
- 源文：`The system waits 30 seconds before retrying.`
- 译文：`系统会等待一会儿再重试。`
- omission minor / format **fail**（丢了 30）/ **不可用**

**例 5 · 可用（生硬但不误导）**
- 源文：`Save changes before closing this window.`
- 译文：`在关闭此窗口之前保存更改。`
- fluency 3 / accuracy 4 / **可用**

**例 6 · 不可用（术语错误误导）**
- 源文：`Click Cancel to discard the draft.`
- 译文：`点击"确定"以保存草稿。`
- accuracy 1 / terminology major / **不可用**

## 4. 跳过与仲裁

- 拿不准、源文本身有歧义、或参考译文疑似有误 → 点"跳过"并在备注写明原因。跳过项不计入一致率。
- 两名标注者对同一候选的 usable 判定不同 → 自动进入分歧清单，由第三方仲裁或两人共同复核。
- **模型（包括 Claude）不得充当第二名标注者，也不得参与仲裁投票。** `measure_agreement.py`
  会拒绝 `annotator_type != "human"` 的文件。

## 5. 解除 judge_is_provisional 的条件

全部满足才可解除：

1. 两名独立人工标注者的 usable 一致率 ≥ 0.85 且 Cohen's κ ≥ 0.6
2. 分歧项全部完成仲裁
3. 自动判官与仲裁后人工结论的一致率 ≥ 0.85 且 κ ≥ 0.6

任一不满足，`judge_is_provisional` 保持 `true`，按发布规则禁止 production 发布。
