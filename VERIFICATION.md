# v0.2 验证记录

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
