# 屏译 · Screen Translator

Windows 11 本地截屏翻译，支持 Qwen3-4B-Instruct-2507 Q8_0、Qwen3-8B / Qwen3-14B Q5_K_M + PaddleOCR。

## 使用

运行安装器或 `dist/ScreenTranslator/ScreenTranslator.exe`。首次在设置中选择模型目录和 4B、8B 或 14B，点击“下载 / 校验模型”（4B Q8 约 4.3 GB、8B 约 5.8 GB、14B 约 10.5 GB，另有 OCR 权重）。三个翻译模型可以并存和随时切换。4B 是英文优化的极速模式：日文和韩文在已安装 14B 时自动使用 14B；8B 的韩文同样自动使用 14B。所选小模型处理失败时也会回退 14B，未安装 14B 时仍继续使用所选模型。模型下载完成后使用 `Ctrl+Alt+T` 框选文字，单击任意位置切换原图与译文，Esc 或同一快捷键退出。设置页可选择自动识别、中文、英语、日语或韩语作为输入，输出支持中英日韩；托盘菜单显示当前语言对并可一键对调。自动识别需成功识别一次后才能对调。

语言下拉框和“⇄”按钮会即时保存，无需再点击“保存设置”；翻译结果层可右键打开语言菜单并对调下一次截图的翻译方向。v0.5 使用 `D:\AI\Models\registry.json` 的稳定模型 ID 解析共享模型，训练资产位于 `D:\AI\Training\screen-translator`；应用更新和卸载不会修改这两个共享目录。旧版平面 `manifest.json` 仍可只读使用。默认不保存截图、原文、译文，无历史记录或遥测。只有用户主动下载时访问 Hugging Face；翻译 HTTP 端点只在本机回环地址监听，并要求随机密钥。

v0.3 使用面向 Windows 桌面工具重新设计的设置界面：语言方向作为首要操作，模型/OCR/Qwen 状态分开展示，下载进度与错误反馈保持在模型区域，保存与截图入口固定在窗口底部；界面支持键盘焦点、150% DPI 和垂直滚动。截图覆盖层使用更清晰的状态胶囊、选区尺寸标签及高对比边角标记。

## 增量更新

普通界面和业务代码修改使用 `scripts/build_update.ps1` 生成小型补丁包。补丁只包含 `ScreenTranslator.exe` 与应用 UI 资源，安装时通过 Windows Restart Manager 短暂关闭程序并覆盖变化文件，不重新安装 Paddle、CUDA、Qt、OCR、llama.cpp，也不复制模型。补丁安装器会读取完整安装版注册的目录、检查最低基线版本并拒绝降级或安装到其他位置。

```powershell
.\scripts\build_update.ps1
# 已经生成最新 dist/ScreenTranslator 时可跳过 PyInstaller：
.\scripts\build_update.ps1 -SkipAppBuild
```

修改 `requirements-lock.txt`、`ScreenTranslator.spec` 中的运行时依赖、`runtime/llama`、Paddle/CUDA/Qt 或 Python 版本时必须重新生成完整安装包；不能用补丁包替代依赖迁移。补丁更新保持手动、离线可控，不会新增后台联网或自动更新服务。每个安装包旁边都会生成 `*.manifest.json`，记录版本、适用平台、文件大小和 SHA-256，可用 `scripts/release_manifest.py` 验证文件是否被修改。

## 开发与构建

支持 Python 3.11–3.12 x64（当前主机使用 3.12 验证）。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]' --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cu129/
.\.venv\Scripts\python.exe scripts\prepare_runtime.py
.\.venv\Scripts\python.exe scripts\download_models.py D:\AI\Models
.\.venv\Scripts\python.exe run.py
.\.venv\Scripts\python.exe -m ruff check screen_translator tests scripts
.\.venv\Scripts\python.exe -m pytest --cov=screen_translator --cov-fail-under=40
.\scripts\build.ps1 -Iscc 'C:\path\to\ISCC.exe'
```

构建脚本要求安装 Inno Setup 6。打包包含 Python、Qt、PaddleOCR GPU、CUDA 12.9/cuDNN 运行库和 llama.cpp CUDA DLL，因此目标电脑只需兼容的 NVIDIA 驱动，不需要 CUDA Toolkit。模型由首次运行下载。运行时版本及校验值记录在 `runtime/llama/release.json`。下载记录固定仓库修订，校验权重 SHA-256；断点下载保留 `.part` 文件。“重新下载”只把当前翻译模型移至共享仓库的 `recovery` 目录，不会移动 OCR、训练权重或其他应用使用的模型。

完整安装默认按用户写入 `%LOCALAPPDATA%\Programs\ScreenTranslator`，无需管理员权限，支持 `/SILENT` 与 `/VERYSILENT`。安装器创建“已安装的应用”卸载项，并首次默认创建桌面快捷方式。交互式卸载会询问是否删除设置、日志和默认模型，默认可选择保留；静默卸载默认保留数据，传入 `/PURGEUSERDATA` 才会清理。生产发布应在 Inno Setup 中配置代码签名工具，并通过 `-SignToolName` 传给构建脚本。

## 架构与边界

`app.py` 只负责应用启动与依赖组装；`controller.py` 编排截图、OCR、翻译和结果层；`session.py` 以显式状态机管理一次截图会话；`tasks.py` 统一管理后台任务；`settings.py`、`overlay.py` 和 `theme.py` 负责界面。`ocr_engine.py` 与 `translation_engine.py` 分别实现 OCR 和本地翻译，均通过 `contracts.py` 中的接口注入；`layout.py` 负责阅读顺序和语义分块，`translation_quality.py` 负责无内容日志的结果校验；`engines.py` 仅保留旧导入路径兼容。`core.py` 定义稳定数据结构、取消令牌和配置迁移；`model_registry.py` 解析和校验共享模型；`models.py` 管理显式下载；`graphics.py` 做跨 DPI 拼接、背景修复和文字排版；`native.py` 注册 Win32 全局快捷键并通过 Job Object 回收子进程。

完整的依赖方向、会话生命周期和扩展约束见 [`docs/architecture.md`](docs/architecture.md)。版本只在 `screen_translator/version.py` 中定义；完整构建和补丁构建都会先执行 Ruff 与带覆盖率门槛的测试。

OCR 和 Qwen 均优先使用 CUDA，CPU 降级需在设置勾选。托盘启动后只在后台预热 OCR；Qwen 仍在按下截图快捷键后按需加载，避免空闲时长期占用大块显存。指定输入语言时 OCR 只运行一个识别器；自动模式抽样判断通用/韩文模型并仅对低置信度行补识别。4B/8B 长文使用两个有界推理槽，14B保持单槽；可疑结果只用当前模型单块重试。全屏截图是静态快照；结果层拦截点击，退出后才能操作原应用。横排印刷文字是主要场景；受保护的视频、UAC 安全桌面、HDR、竖排及复杂艺术字体不保证效果。

安装包未签名。5 秒热启动/20 秒冷启动是性能目标，不是未经测量的保证。CPU 降级不适用这些目标。

## 许可

Qwen3、PaddleOCR 与 PaddlePaddle 采用 Apache-2.0，llama.cpp 采用 MIT，PySide6/Qt 使用 LGPLv3 的动态链接版本。发布者需保留依赖许可证和版权声明；本项目的构建输出包含依赖元数据，模型目录包含 Qwen LICENSE。完整分发许可清单仍需随发布包核验。
