# v0.2 验证记录

## v0.6.0 文本输入翻译工作区（2026-09-20）

### 训练适配器门槛结论

- 训练工作区 `D:\AI\Training\screen-translator` 共 16.25 GB / 873 文件，含 17 个已训练 LoRA 适配器与 36 个 checkpoint（13.78 GB）。全部为 `r=16 / alpha=32 / dropout=0.05 / use_rslora=true / peft 0.21.0`，7 个 target modules。
- 13 个 4B 适配器的基础模型是 `qwen3-4b-hf-1cfa9a7`（`Qwen/Qwen3-4B` rev `1cfa9a7208…`，权重 132,187,888 B）；2 个 8B 适配器是 `qwen3-8b-hf-b968826`（`Qwen/Qwen3-8B` rev `b968826d9c…`，权重 174,655,536 B）。`qwen3-4b-instruct-2507-teacher-v1` 只有 manifest，无权重也无基础模型，不可复现。
- 新增 `scripts/training/check_release_gate.py` 对真实评测报告判定门槛，结果与人工结论一致：
  - `runs\full-eval-v1\qwen3-4b-teacher-v2`（300 条不可变集）：block_alignment 1.0000 PASS、duplicate 0 PASS、**usable 0.8367 FAIL**，退出码 1。
  - `runs\final-eval-v1 + final-judge-v1\qwen3-8b-teacher-v1`（300 条）：block_alignment 1.0000 PASS、duplicate 0 PASS、**usable 0.9000 FAIL**，退出码 1。全部适配器中最高为 dev 集 0.9111，仍低于 0.94。

  > **口径提示（2026-09-21 补记）**：以上 usable 数字来自旧判官协议（`--batch-size 10`、不打乱）。
  > 后续实测发现该协议受批内上下文污染，同一批数据仅改变批次组成，usable 可在 ±2 个百分点内摆动，
  > 并**系统性低估约 3 个点**；改用单条判分（`--batch-size 1`）后结果完全确定。
  > 这些数字因此**不可与 2026-09-21 之后的任何分数直接比较**，也不应被引用为适配器的真实水平。
  > 结论本身不变：即使按低估幅度上修，0.8367 / 0.9000 仍远低于 0.94 门槛。
  > 修正后的协议、指标定义与全部重测基线见 `D:\AI\Training\screen-translator\runs\REPORT-enzh-v1.md`。
- `D:\AI\Models\registry.json` 共 9 条记录，kind 只有 `base-inference` / `base-training` / `auxiliary`，**零条 adapter/derived**；`D:\AI\Models\adapters` 与 `derived` 不存在。
- 因此本版本不接入任何适配器：`models.SUPPORTED_ADAPTERS` 与 `model-requirements.json` 的 `adapters` 均为空，应用只加载 `production` 基础模型。适配器加载通路已实现并测试（registry 解析 → kind/status/format/依赖/尺寸五道校验 → `--lora-scaled`），任一条不满足都会报错而非静默回退。
- 转换缺口：适配器为 HF PEFT safetensors，工作区内无任何 GGUF 转换产物或脚本，`.train-venv` 未安装 `gguf` 包，机器上无 `convert_lora_to_gguf.py`。`llama-server` b10964 已确认支持 `--lora` / `--lora-scaled` / `POST /lora-adapters`。`use_rslora=true` 时 PEFT 有效缩放为 `alpha/sqrt(r)=8.0` 而 llama.cpp 默认 `alpha/r=2.0`，转换后必须用实测验证缩放等价性。
- 所有语义指标均由 `qwen3-14b-q5-k-m` 自评并标记 `judge_is_provisional: true`，发布前仍需人工 gold 集。
- 同理，本节的 `protected token` 相关判断使用的是旧指标定义，它会把 `3-1`→"3比1"、`FBI`→"联邦调查局"、
  `10:15`→"上午10点15分" 这类**正确的本地化**误判为丢失 token。指标已于 2026-09-21 收紧，
  重测后 8B 与 4B 均为 1.0000、14B 为 0.9900。

### 功能与质量

- Ruff 通过；完整测试 **290 passed / 4 skipped**，覆盖率 **73.85%**（v0.5.3 为 141 passed、64.03%）。跳过项仍为可选训练环境。
- 新增测试：分段与重组 29 项、推理仲裁 9 项、文本翻译用例控制器 27 项、文本翻译页 22 项、适配器解析 18 项、llama.cpp 进程生命周期 9 项、发布门槛 17 项、日志隐私 4 项、离线 2 项、安装边界 8 项、截图抢占 4 项。
- 源码版真机检查 `scripts/manual_translation_check.py`（阻断全部非回环 socket，CUDA，`qwen3-8b-q5-k-m`，报告 `build/manual-translation-check.json`）：en→zh 2.953 s / ja→zh 0.266 s / ko→zh 7.984 s（8B 的韩文按既有规则路由到 14B）/ zh→en 2.875 s，四项 `structure_preserved` 均为 true；`capture_exclusion=enforced`、`cancel_returns_to_idle=true`、`device=CUDA`、`adapter_id=null`。
- 结构保真实测：229 字符、5 段、含三条编号项的英文清单译为中文后，编号、空行与换行逐字节保持（`1. / 2. / 3.` 与段间空行未变）。

### 打包与安装

- 增量包 `dist/updates/ScreenTranslator-0.6.0-Update.exe`，大小 **43,187,224 字节**，SHA-256 `519AA176457FE022445CCDE0AF5733A119A43E1AACFB7EAEE4B4C45DA9040BEE`，`-MinimumBaseVersion 0.5.0`，未签名。
- **首次安装被自身基线门槛拒绝**：`Install test\ScreenTranslator` 的卸载项记录 `DisplayVersion=0.2.0`，日志为 `Base version rejected: installed=0.2.0, minimum=0.5.0`。经核实该记录是陈旧的——已安装 exe 含 `model_registry` / `translation_quality`，运行中的 `llama-server` 使用 registry 解析出的 `D:\AI\Models\base\qwen\...` 路径，即实际代码为 0.5.x；0.4.7/0.4.8 补丁曾正确写入版本，此后 exe 于 21:54 被直接复制替换（无 setup 日志）。经用户确认，先用 `reg export` 备份到 `build/uninstall-entry-backup-before-0.6.0.reg`，再把 DisplayVersion 修正为 0.5.3，随后补丁正常安装（退出码 0），记录更新为 0.6.0。
- 原位升级，未创建平行安装目录。安装前后 `D:\AI\Models` 均为 83 文件 / 45,148,701,927 字节且 `registry.json` SHA-256 保持 `4DC2113948FED7A95C316783D4CDF61A55A308343F7E938A9FF575876D146564`；`D:\AI\Training` 均为 873 文件 / 17,445,459,266 字节。未复制或重新下载任何模型。
- 用户配置未丢失：仍为 version 3、`Ctrl+Alt+Q`、`D:\AI\Models`、`qwen3-8b-q5-k-m`、en → zh-Hans。本版本未新增配置字段，`CURRENT_CONFIG_VERSION` 保持 3。
- 安装后启动正常，主窗口标题为“屏译”，三个工作区构建成功；再次启动只唤醒既有窗口，进程数保持 1。
- 打包版自检（`--self-test`，14B Q5_K_M）：冷流程 12.70 s、热流程 1.08 s，OCR 与 Qwen 均为 CUDA。自检结束后无残留 `llama-server` 进程；安装器通过 Restart Manager 关闭应用时，子进程也随 Job Object 一并回收。
- 新增磁盘占用：新增源码约 55 KB，打包 EXE 由 41,533,812 增至 41,559,033 字节（+25 KB），无新依赖、无新模型字节。

### 未覆盖

- 打包版的鼠标点击交互（在真实窗口中点击“翻译 / 取消 / 复制译文 / 清空”）未做程序化验证，需人工点击确认；源码版的等价路径已由 `manual_translation_check.py` 与 Qt 离屏测试覆盖。
- `runs\final-routed-v1` 只有 `predictions.jsonl`，没有 `summary.json`，因此发布中的路由配置无法由门槛脚本给出机械指标，只有 judge 侧数据。

## v0.5.3 托盘退出入口（2026-09-20）

- 托盘右键菜单现在按“设置 → 当前语言对 → 退出”排列，退出固定为第三个可见选项和菜单最底部。
- 托盘退出复用设置页的确认提示与 `Controller.quit()` 资源清理流程，不绕过任务取消、llama.cpp 停止和托盘回收。
- Ruff 与完整测试通过：141 passed / 4 skipped，覆盖率 64.03%。
- 增量包为 `dist/updates/ScreenTranslator-0.5.3-Update.exe`，大小 43,162,578 字节，SHA-256 为 `3D98A6166AD7DA947B2C4EDA24710157F5CB9D35CF168CF20ADB737EB42621AC`。

## v0.5.2 截图准星稳定性（2026-09-20）

- 选择区域时不再依赖会在全屏遮罩切换中闪烁的 Windows 原生十字光标，改由 Qt 遮罩层绘制高对比度双描边准星。
- 准星在按下鼠标前持续可见；跨显示器拖动使用全局逻辑坐标同步，进入处理和结果状态后分别恢复等待光标与箭头光标。
- Ruff 通过，完整测试为 140 passed / 4 skipped，覆盖率 63.97%；新增准星绘制、拖动前跟踪和状态切换回归测试。
- v0.5.2 增量包已原位安装；当前模型、语言和 `D:\AI\Models` 共享模型根目录保持不变。
- 增量包为 `dist/updates/ScreenTranslator-0.5.2-Update.exe`，大小 43,162,504 字节，SHA-256 为 `D681FD8A408090243FBDC7B50E88E73E80706032F2A3B0839E25291D16D84A66`。

## v0.5.0 共享模型迁移（2026-09-20）

- v0.5.0 增量包已构建并原位安装；安装记录为 0.5.0，第二次启动保持单实例。
- 17 项资产已通过同盘移动迁入 `D:\AI\Models` 与 `D:\AI\Training\screen-translator`；旧项目模型和训练目录不再残留副本。
- Registry 共 9 条记录。三个 GGUF、四个 PaddleOCR 资产和两个 Hugging Face 基础权重全部通过完整 SHA-256 复验；4B/8B 训练权重记录了精确 upstream revision。
- 79 份 PEFT 配置和训练 manifest 已改为新路径，并在文件内及 `migration-audit` 中保留旧路径与原文件。
- 合成文本、外部网络连接拦截条件下，8B 的 OCR → 翻译 → 渲染链路使用 CUDA 成功完成：首次进程 40.58 秒，热流程 0.44 秒，热 OCR 0.05 秒。首次时间包括 Paddle 与模型冷加载。
- 14B Q5_K_M 与 4B Q8_0 均通过 llama.cpp CUDA 启动/停止测试，结束后无残留 `llama-server` 进程。
- 迁移后 Ruff 通过，完整测试为 128 passed / 4 skipped；4 个跳过项依赖未安装的可选训练环境。
- 迁移日志位于 `D:\AI\screen-translator-model-migration.json`，配置和元数据恢复材料位于训练工作区的 `migration-audit`。

本机：Windows 11 22631、RTX 4090 24GB。开发/打包运行时为 Python 3.12.14。模型：官方 Qwen3-14B Q5_K_M，llama.cpp b10964 CUDA 12.4，PaddleOCR 3.7.0 / PaddlePaddle GPU 3.3.0 CUDA 12.9。

## v0.5.1 长文质量与性能（2026-09-20）

- 固定 954×1825 英文协议截图保持 64 行、4298 个 OCR 字符；第 3 条合并为单个四行语义块，译文无相邻重复或包含。
- 8B 双槽、6 批次三轮测试的热流程平均 7.328 秒，其中翻译 6.398 秒；单槽热流程平均 11.820 秒。
- OCR 后台预热后的首次完整流程为 9.796 秒，OCR 为 0.578 秒；测试全程阻止非回环网络连接。
- 1080p/20 行短文本回归的热流程为 3.06 秒、热 OCR 为 0.12 秒，保持在 5 秒门槛内；冷进程中的 Paddle 初始化由托盘后台预热承担。
- 基准记录为 `build/v051-professional-standards-8b-dual-tuned.json` 与 `build/v051-professional-standards-8b-prewarmed.json`。
- Ruff 与完整测试通过：138 passed / 4 skipped，覆盖率 62.28%；跳过项仍为可选训练环境。
- v0.5.1 增量包已原位安装，打包版合成自检的冷/热流程为 17.61/0.77 秒，OCR 与 14B 均使用 CUDA，结束后无残留 llama.cpp 进程。
- 最终增量包为 `dist/updates/ScreenTranslator-0.5.1-Update.exe`，大小 43,161,072 字节，SHA-256 为 `CEF0CCA7F1BE019248D84941162B73CA963C99B7A3EB3DDC32B616051A119422`。

## 已验证

- 单元及 Qt 交互测试：配置迁移、JSON 缺项/重复 ID、数字原样保留、OCR 分块与语种边界、取消和过期结果隔离、快捷键冲突、模型续传/取消、四种 DPI 的跨屏负坐标拼接、长译文排版、原图/译图鼠标切换与 Esc 退出。
- 单元及 Qt 测试：33 项通过（`pytest -q`）。
- 中、英、日、韩四张合成截图均由自动模式识别出正确主语言，结果记录在 `build/fixtures/languages/report.json`。
- 1080p/20 行测试：显式语言热 OCR 约 0.09 秒，自动语言热 OCR 约 0.13–0.20 秒；完整流程并行预热后冷启动 7.44 秒、热启动 2.86 秒，记录在 `build/fixtures/benchmark.json`。
- 本地模型下载及 SHA-256 校验完成，模型放在项目的 `models` 目录。
- 源码版与独立 EXE 的 OCR → Qwen CUDA → 原位绘制链路已验证；合成图片不包含用户内容。
- 最终 v0.2.0 安装器已静默安装到隔离目录，自检确认 OCR 与 Qwen 均为 CUDA；随后卸载成功且无残留推理进程。报告为 `build/final-installed-v02-report.json` 和 `build/final-packaged-v02-report.json`。
- 最终安装器为 `dist/installer/ScreenTranslator-0.2.0-Setup.exe`，大小 4,063,976,333 字节，SHA-256 为 `6DB722F7B3DC81A0059E0BECD522809A3F3B97E297CB9EAE67323F610088C784`。
- 自检期间 Python 外部 socket 连接被拦截，只允许本机回环推理连接。此项是进程内网络防护测试，不等同于物理断网抓包验证。
- 退出推理后确认 llama-server 子进程回收。
- 设置页和翻译结果已渲染并检查。测试图片、速度数据位于 `build/fixtures` 和 `build/*report.json`。

## 边界与待人工验证

- 未在干净的另一台 Windows 机器/虚拟机验证；真实混合 DPI 多屏交互仍需人工验收，现有测试使用合成屏幕。
- 深色复杂背景、真实游戏/漫画小字号、HDR/受保护画面未完成系统性人工质量评测。当前识别器置信度选优可能在复杂字体下误判语言。

## 使用现有模型

安装后进入设置，将模型目录改为 `D:\AI\AiTranslate\models`，保存后即可使用，避免重新下载。`Ctrl+Alt+T` 框选，单击切换原图/译文，Esc 退出。应用正常退出使用托盘菜单。

安装器未签名；代码签名和另一台干净 Windows 机器的人工验证仍未完成。
