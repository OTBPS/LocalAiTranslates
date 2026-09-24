# v0.2 验证记录

## UI 重构第二阶段（2026-09-23）

### 自动化

- Ruff 通过；完整测试 **946 passed / 6 skipped**，覆盖率 **86.05%**。三个构建脚本的 `--cov-fail-under` 由 40 提到 **55**。
- 新增门槛测试，全部机器可判、毫秒级：
  - `test_contrast_ratios_meet_wcag_aa`（浅色 + 深色两套全跑，**无豁免清单**）
  - `test_no_colour_literals_outside_the_primitive_layer`（只看字符串常量，不误伤注释与 URL）
  - `test_layout_metrics_come_from_tokens`（`setContentsMargins` / `setSpacing` / `setFixedSize` 等的实参必须是 token，0 除外）
  - `test_the_design_package_imports_nothing_from_the_application` 与层内方向表
  - `test_object_names_and_stylesheet_rules_agree`（双向）
  - `test_focus_rules_never_change_geometry`
  - `test_graphics_never_imports_the_design_package`
  - `test_the_token_document_matches_the_code` 与 MASTER.md 版本号 == `__version__`

### 对比度测试当场抓到的三个真实缺陷

这三个肉眼都看不出来，评审也抓不到，是这条门槛最直接的回报：

1. Apple 的深绿 `#248A3D` 在白底 4.40:1、在画布 3.94:1，**两处都不达 AA**。改成 `#1F7A35`（5.39 / 4.83）。
2. Apple 的发丝线 `#C6C6C8` 只有 1.7:1，用作控件边框不满足 WCAG 1.4.11 的 3:1。拆成两个角色：`stroke_separator` 继续做内容分隔（装饰，豁免），`stroke_control` 加深到 `#8A8A8E`（3.44 / 3.08）。
3. 深色模式蓝 `#0A84FF` 压白字只有 3.65:1，与浅色模式 `#007AFF` 是同一个问题。深色模式改用同一枚 `#0066DB` 填充（白字 5.35:1），它在 `#1C1C1E` 上仍有 3.18:1 的边界对比度。

### 颜色普查（Tier 2 视觉回归）

明确不做像素基线：离屏文字渲染依赖本机 `msyh.ttc` 版本、Qt 构建与 ClearType 设置，必然误报、必然被绕过。改为断言**渲染结果中占面积的每一种颜色都必须是主题声明过的**——字体渲染只影响像素分布，不会凭空造出主题里没有的颜色。

- 翻转前后各跑一次：`#F8F1E2 39.886% / #E9DFC8 27.166% / #FFFDFC 16.811% / #151515 6.827% / #C51D23 6.280% / #E8BC35 1.559%`，QSS 生成器接管后颜色集合完全一致，各自占比差异 **< 0.15 个百分点**。这条数据是"P3 组件重构如果把界面搞坏了，一定不是配色的锅"的依据。
- 场景表覆盖三个标签页 + 680×600 最小尺寸，深色主题单独一份。附带一个"能不能失败"的自检测试。

### 目视核对

- 翻转前的构成主义界面存进 `artifacts/ui/before-liquid-glass/`，是 ADR 0002 承诺的 before/after 的前一半。
- 翻转后：`settings-v0.8.0.png`（截图页）、`settings-system.png`（系统设置页）、`settings-dark.png`（深色）、`overlay-*.png` 五态。
- 状态条的真玻璃在离屏渲染里就能看出来：胶囊下方的渐变被糊开了，不是贴图。

### 打包验收（完整链路）

- `scripts/build.ps1` 全绿：ruff → 946 passed / 6 skipped、覆盖率 86.05%（门槛已提到 55）→ Paddle GPU 预检 → PyInstaller → Inno Setup → 发布清单。
- `ScreenTranslator-0.8.0-Setup.exe` **4,063,313,914 字节（3875.08 MB）**，SHA-256 `E29455D7965B597E1F09FBF30EC03DBF3321DFE726DF5A34441B18C3E27B8A5B`，`schema_version: 2`、`edition: full`，未签名（开发产物）。
- `ScreenTranslator.exe` 41,761,820 字节（v0.7.0 为 41,617,726，+141 KB）。`ScreenTranslator.spec` 一行未改：第二阶段新增的 `design/` 与 `widgets/` 都是纯 Python，随 PYZ 进 exe。
- 打好的 exe 跑 `--self-test D:\AI\Models`：真实 PaddleOCR（CUDA）+ 真实 llama.cpp 两轮全绿，冷 32.08 s、热 0.92 s / OCR 47 ms / 4 块，四种语言方向译文正确。
- `installer.update.iss` 的两条 Source 未变，assets 目录是通配投递，因此规范化后的图标与新增的 `check-dark.svg` 都能随增量包送达；`test_the_incremental_package_ships_only_the_launcher_and_ui_assets` 仍然通过。`check.svg` 保留原名，`build_update.ps1` 的完整性哨兵不受影响。

### 应用图标（P8）

- 新图标：蓝色渐变圆角方块 + 白色 译。旧标同时塞了红底、黑斜切、黄圆盘、四个裁切角标和字，16 px 下是一团。
- **九个尺寸各自渲染，不是从 1024 缩下来的**：译 有十三笔，缩到 16 px 会糊成灰块。小图标把字放大到方块的 80%（256 px 时是 62%），高光描边在 48 px 以下直接不画——那里它不足一个像素，只会看起来像脏边。Pillow 的 ICO 写入器只在缺某个尺寸时才降采样，九个都给了就一个都不是猜的。
- 实测字形占比：256 px 下墨迹 153×152 / 256 = **59.8%**，居中偏差 ≤ 2 px。
- 三种底色（浅任务栏 `#F3F3F3`、深任务栏 `#202020`、中间调壁纸 `#6E7A86`）× 五个小尺寸目视全部可辨，产物 `artifacts/ui/app-icon-v080-contexts.png`、`app-icon-v080-sizes.png`。
- 颜色从 `design.primitives` 导入，测试断言生成脚本里没有色值字面量——旧图标正是因为写死了四个色值，才比它所属的设计方向多活了两个版本。
- **修掉一处文档与代码不符**：v0.5.1 的发布说明写了"安装或更新后通知 Explorer"，但没有任何 iss 脚本包含该调用。新增共享的 `installer.shell.iss`（`SHChangeNotify` + `SHCNE_ASSOCCHANGED`），完整版 / 客户端 / 增量三个脚本都在 `ssPostInstall` 调用，并加了断言。三个版本没被发现，是因为图标一直没变过。
- **PyInstaller 会复用缓存的 exe**：它对 EXE 阶段的陈旧判断比的是路径不是内容，所以同路径重新生成 ICO 之后，exe 旁边的 assets 更新了，**烤进 exe 里的图标没更新**——重新打包会报成功并装上旧图标。三个构建脚本已加 `--clean`，并有断言。这个只能靠直接读 exe 的 RT_ICON 资源才看得见：`ExtractAssociatedIcon` 走 shell，返回的是缓存里那份，会跟着一起错。
- **三个发布包（2026-09-23 11:24–11:28，图标与滚轮修复之后重打）**：

  | 类型 | 文件 | 字节 | SHA-256 | 基线 |
  |---|---|---|---|---|
  | 完整版 | `ScreenTranslator-0.8.0-Setup.exe` | 4,063,357,431 | `A26FDA247E29E6522FDE88FDB3D464C2697641D45DB9F25032910C863CA0EDA1` | — |
  | 客户端版 | `ScreenTranslator-Client-0.8.0-Setup.exe` | 106,960,536 | `202C37AB815C581BBE2DC2E8C5153AAAE43A2621D55CB6DA0D5C0A2A7F1BCAEA` | — |
  | 增量包 | `ScreenTranslator-0.8.0-Update.exe` | 43,431,750 | `FDA83A1044E3877E10876FDD875DC10F153AE8B0A2D5A24B37C53D3B1DC0C054` | 0.7.0 |

  （**配置拒绝提示**修复后于 15:35–15:39 第三次重打，为最终产物：完整版 `40664535DE8BF7DABAC8E4B3A9A0853CA86BEB3A5D343DAE1AD97E5E6FA906FE`（4,063,361,114 字节）、客户端版 `D08B92BF40668E2B…`（106,961,827 字节）、增量包 `1429AE184CBC1887…`（43,433,093 字节，基线 0.7.0）。三份 manifest 记录的字节数与磁盘实际大小逐一核对一致。打好的 exe 跑 `--self-test D:\AI\Models` 两轮全绿：冷 38.92 s、热 0.75 s、4 块、CUDA。）

  （每页独立滚动修复后于 12:17–12:21 重打，已被上述取代：完整版 `5631D673D71664B5D82F35C6194DF322F3DD351A4DF4761B110CB1CB27B2B98D`、客户端版 `878285B3A41B1ABA5BFB794E89FF515021D1F156D371D3154B9208AE539F640A`、增量包 `AA2561348000ABB092B649D1B63853AA261C8AD4A6AA1A176533A80497CC1F0F`。）

  三者均未签名（开发产物）。客户端载荷 296.76 MB，仍在 400 MB 上限内。增量包基线取 0.7.0：本分支未改动 `.spec`、`requirements*.txt`、`pyproject.toml` 与 `runtime/`，改的全是 Python 代码与 assets，正落在增量通道适用范围内。
- 完整版载荷复验：exe 内嵌图标 256 px 取样 `(0, 103, 219)`、包内 ICO 与源文件逐字节一致、`check-dark.svg` 已投递、`screen_translator.widgets.inputs` 在 PYZ 内。
- **构建前置检查**：`scripts/build.preflight.ps1`，三脚本共用，在任何慢活之前拦截"载荷目录里的应用还在跑"。`--clean` 要整个删掉载荷目录，应用一跑就锁住自己的 `.pyd`，原先的表现是 shutil 深处抛 `PermissionError`，最后一行是本地化的 Windows 报错，完全不指向真实原因。实测三种情形：空闲静默通过、能真的检出、**不会**因仓库内那份已安装的 0.7.0 在托盘而误拦（匹配的是 `dist\<载荷>` 而非项目根）。
- 写这个前置检查时踩到并修掉一个约定问题：提示最初写成中文，而 **Windows PowerShell 5.1 在无 BOM 时按 ANSI 读 `.ps1`**，结果不是消息乱码而是整份文件解析失败。现有三个构建脚本本来都是纯 ASCII 无 BOM，已改回英文并加 `test_build_scripts_stay_ascii` 盯住。
- `ISCC.exe` 实编译 `installer.update.iss` 与 `installer.client.iss`（后者 include 完整版脚本）均 exit 0，产出 43,389,774 / 106,775,978 字节的真实安装包。第一次编译**失败**并被抓到：`installer.shell.iss` 的头部注释用了 `;`，那在 `[Code]` 段里不是注释而是空语句。已改为 `//`。

### 真机截图暴露的问题（2026-09-23 中午）

- **文本翻译页的「翻译」按钮在默认窗口尺寸下位于折叠线以下**，截图页则留了一大片空白。根因不是编辑框最小高度（文本页自身 `minimumSizeHint` 只有 509，视口 761），而是 `QTabWidget.minimumSizeHint` 取所有页面的最大值：系统设置页真实需要 819，这个下限泄漏到了每一页，把文本页撑到 808。**量过才发现这不是本次间距改动造成的**——旧的构成主义间距下按钮在 956，改版反而好了 53 px，只是没修好。改为每页各自持有 `QScrollArea` 后，820×840 下截图页与文本页均无需滚动，系统设置页滚 183 px。页头、通知横幅、标签栏留在滚动区之外（横幅报的是三页共用的页脚按钮，让它滚走等于把当初的缺陷换个地方再犯）。
- **构建前置检查经受了一次真实检验**：重打时已安装的 0.7.0 正在 `Install test\` 下运行，前置检查正确放行——它匹配的是 `dist\<载荷>`，不是项目根目录。

### 已修复：更新版本的配置会静默杀死应用

- **更新版本的配置会让应用静默死掉，而不是给出提示。** `Config._migrate` 在 `version > CURRENT_CONFIG_VERSION` 时抛裸 `ValueError`，而 `Config.load()` 的 `except` 只捕获 `(JSONDecodeError, UnicodeDecodeError, TypeError)`——`JSONDecodeError` 是 `ValueError` 的子类，反过来不成立。异常穿过 `ConfigStore.__init__` → `Controller.__init__` → `app.main()` 无人接管。后果是双击应用毫无反应：没有弹窗，也没有日志，因为 `configure_logging()` 在读配置之后才执行。对一个存在意义就是"告诉用户去升级"的保护机制而言，这是最差的失败形态。实测复现：写一个 version 6 的配置交给 version 5 读取即抛出。该缺陷在 0.7.0 与 0.8.0 中同样存在。

  **已修**：新增具名异常 `ConfigTooNew`，`Config.load` 明确放行它（文件完好、装着用户的设置，挪走或覆盖正是版本检查要拒绝的那种静默降级），由 `app.main` 在取单实例锁之前捕获、弹出同时写明两个版本号的对话框、返回 1。同时把 `ValueError` 加进 `load()` 的损坏分支——`_migrate` 对非法版本号（`"abc"`、`0`、`-1`、`1.5`）也抛 `ValueError`，那属于损坏，之前同样会逃出去杀死进程，现在走备份重建。
  拿**你机器上真实的 v5 配置**做过验证：以 v4 应用的身份读取，被具名拒绝，文件未被移动也未被改写，没有产生 `.corrupt-*` 副本。

### 文本框自适应高度后重打的 0.8.0 三个包（2026-09-23 夜）

由提交 `bdcd67e` 的干净工作树构建，构建前 `ruff check` 通过、**1061 条测试通过 / 6 跳过，覆盖率 87.09%**（门槛 55%）。三份清单里的 `size_bytes` 都与磁盘上的实际文件核对过。

- **完整安装包** `ScreenTranslator-0.8.0-Setup.exe` — 4,063,365,036 字节（3875.13 MB），SHA-256 `7AAA23465169A407A6FF29B76F37483969D37634060F0EC434A518F735A75817`，`minimum_base_version` 无（完整安装），未签名。
- **增量补丁** `ScreenTranslator-0.8.0-Update.exe` — 43,436,256 字节（41.42 MB），SHA-256 `916769C70FBCF027F8D91FE82CADFFE5F42DAE40D92A32E47914F1E70FC25A39`，`minimum_base_version` 0.7.0，未签名。
- **客户端版** `ScreenTranslator-Client-0.8.0-Setup.exe` — 106,965,029 字节（102.01 MB），SHA-256 `9B902AD79F6C39F05E9848E2B7E84E52FB5B5E6BB84320786BF1005DD1DE5A8A`，`minimum_base_version` 无（完整安装），未签名。

新载荷做过隔离冷启动（覆盖 `LOCALAPPDATA` 指向临时目录，不干扰正在运行的安装）：进程存活、44 线程、618 MB 工作集。日志里唯一一条是远程服务监听 8765 失败——该端口被机器上另一个实例占用，而配置存放在 `APPDATA` 不随 `LOCALAPPDATA` 隔离，属于测试环境所致而非缺陷；应用按预期降级继续运行。

### 复测后重打的 0.8.0 三个包（2026-09-23 傍晚）

全部由提交 `64a6d5d` 的干净工作树构建，每个包构建前都跑过 `ruff check` 与 1046 条测试（覆盖率门槛 55%，实测 87%）。

- **完整安装包** `ScreenTranslator-0.8.0-Setup.exe` — 4,063,361,730 字节（3875.12 MB），SHA-256 `2E4270CD08209D1D301BA98CF3B9D0A5C7FE47363EE974C53264425630845BAB`，`minimum_base_version` 无（完整安装），未签名。
- **增量补丁** `ScreenTranslator-0.8.0-Update.exe` — 43,434,148 字节（41.42 MB），SHA-256 `2EE70667A7A411215EC72637A9C5AB94525F08CAC24B1A75AF507D0A24C5D502`，`minimum_base_version` 0.7.0，未签名。
- **客户端版** `ScreenTranslator-Client-0.8.0-Setup.exe` — 106,963,112 字节（102.01 MB），SHA-256 `759FAF5C3024D412623AC6458C2168B481373CB1B3736495BA4DA324F416C2B5`，`minimum_base_version` 无（完整安装），未签名。

构建纪律上踩到并修正的一点：期间两次在 PyInstaller 已经开跑之后改了源码，都主动中止重来了——注释增删会移动行号表，产出的 `.pyc` 与提交树不再一致，那样的产物不能算数。

### 复测一轮发现并修掉的缺陷（2026-09-23 傍晚）

- **静默自启动后的第一条错误会被首次运行提示盖掉。** 复现路径：开机静默拉起，设置窗口一次都没打开过；此时截图失败，唯一可用面是托盘（而 Windows 可能整个屏蔽气泡）；用户随后打开设置窗口，`showEvent` 调 `NoticeCenter.replay()` 把失败补到横幅上，紧接着同一次显示触发的刷新又贴上首次运行的 WARNING——横幅只有一个槽位，ERROR 就此从所有面上消失。两条消息本身都没错，错的是一个单槽位面被两条互不知情的路径写，而谁最后写谁赢。这正是反馈层当初要消灭的那类故障（`error_notice` 的注释写着"用户错过的失败就是他无法处理的失败"）。

  **已修**：领域层新增纯函数 `outranks(incoming, showing)` 决定谁能占据单槽位面——同 id 视为自身更新、PROGRESS 因为是用户刚发起且会自行结束所以放行、非持久消息本来就要走、其余按严重度比较。`BannerSink.present` 据此拦截，被拦下的消息不丢：中心仍持有它，槽位空出时 `replay` 会把它放回来。为此给 `NoticeBanner` 加了 `cleared` 信号，由设置窗口接到 `center.replay`。`PROGRESS` 与 `ERROR` 同级是有意的——下载进行中不该被环境性警告挤掉，但可以被真实失败打断。14 条回归测试钉住规则本身、钉住经由控件的行为、并钉住两种到达顺序必须收敛到同一结果。

- **文本翻译页在截图进行中会静默锁死三个语言控件。** 源语言、目标语言、对调按钮都只调 `setEnabled(False)`。"有截图在别处跑"是这一页上用户唯一看不见的状态，却恰恰是唯一没有说明的。**已修**：三者改走 `set_enabled_with_reason`，与「翻译」按钮共用同一句原因。

- **MASTER.md 那条禁用态规则原本写成了绝对句**（"禁用控件一律在 tooltip 里给出原因"），与同一份文档里"不要重复相邻控件已可见的值"直接冲突：在一个空输入框旁边挂一句"输入框是空的"正是被禁的那种文案。规则已改为按**原因是否可见**划线，并注明豁免范围很窄；`tests/test_disabled_controls_explain_themselves.py` 同时钉住两边——不可见原因必须说，自解释状态必须闭嘴。

- **丢包重传会让主机把一次配对当成两次。** `PairingBroker.claim` 本身是对的：同一 `(nonce, peer)` 重试直接返回原来的 grant，不签发第二把密钥。错的是传输层——`_handle_pair_claim` 不区分新签发与重传，一律调 `on_paired`。而主机对这个回调的反应并不幂等：`on_device_paired` 会写一次配置、调一次 `apply_host_service()`（在对端还在握手时二次重配活着的监听器）、再弹一次"设备已配对"。客机分不清"回复丢了"和"被拒绝"，所以重传是常规路径而非罕见情形。**根因是覆盖缺口**：配对路由此前完全没有经过真实传输层的重传测试，broker 层的幂等性测了，传输层的副作用没测。**已修**：broker 新增纯谓词 `already_granted(nonce, peer)`，处理器在 `claim` 之前问——之后再问已经晚了，两种情况返回的 grant 完全相同。新增的测试经真实 loopback 监听器验证，并确认去掉修复后它会失败。

- **增量构建脚本会默默承诺它兑现不了的兼容性。** 本轮裸调 `scripts/build_update.ps1` 打出的包，清单里写着 `minimum_base_version: 0.3.0`。那是脚本的**默认值**——写这个脚本时（0.4.0 前后）它是对的，此后每个版本都显式传参（0.6.0 的补丁传 0.5.0，0.7.0 的传 0.6.0），默认值就再没人走过，于是烂在原地。问题在于增量包只投递两项：`ScreenTranslator.exe` 与 `assets\*`；Python 运行时、PySide6、PaddleOCR、llama.cpp 全部沿用底座安装。把 0.8.0 的可执行文件盖到五个版本前的 `_internal` 上，装出来的就是坏的——而清单会像模像样地宣称这是检查过的。**已修**：去掉默认值，缺失时直接报错并说明该传什么；新增 `test_the_incremental_build_will_not_guess_which_installs_it_can_patch` 同时钉住"没有默认值"和"空值会被拒绝"两件事（验证过：把默认值填回去测试立刻失败）。清单错误的那个产物已删除，用 `-MinimumBaseVersion 0.7.0` 重打。

### 本轮其他复测（均通过，未发现问题）

- **配对与协议协商**（真实 loopback 监听器，14 条）：未开配对时直接 403 且不透露主机是否在配对；6 位码、180 秒窗口、5 次机会；不同失败原因对外是同一句话，真实原因只进主机日志；错误尝试会消耗次数；签发的是每设备独立密钥而非主机自己的；v1 客机↔v2 主机谈成 v1，v2↔v2 谈成 v2，完全不兼容的版本被明确拒绝。
- **配置迁移与往返**（11 条）：真实形状的 v4 配置迁到当前版本，快捷键、语言对、主机设置一项不丢（`zh` 归一成 `zh-Hans` 是刻意的语言码规范化）；旧 `service_token` 被额外映射成一条 `paired_devices` 且**原字段保留**，所以回退安装 v0.7.0 仍可用；存盘再读后 `paired_devices` 仍是对象而非 dict；缺字段用默认值补齐，未知字段被忽略。
- **异步任务契约**（10 条，对应 `/goal` 里"取消/超时/异常/安全退出"一条）：worker 抛异常只记日志不杀进程且线程从追踪表登出；正常结束同样登出，无泄漏；`CancellationToken` 合作式停止且取消单向可重复读；卡死的任务不会让 `shutdown` 永久挂住（1 秒超时实测 1.0 秒返回）；关闭后拒绝新任务并给出中文原因；`shutdown` 可重复调用。

### 已知但判定为无害：测试全量运行时的 access violation

`faulthandler` 会在整套测试运行期间打印一到两次 `Windows fatal exception: access violation`。定位过程值得记一笔：第一次读转储时我按里面出现的 `socketserver` 栈帧去查套接字关闭，那是**读错了**——faulthandler 会转储**所有**线程，那几个只是当时恰好活着的旁观者。拿构建日志重读才看清，转储打在第一个测试点**之前**，出错线程的栈是 `shibokensupport/signature/loader.py`，即 PySide6 的 shiboken 惰性签名加载器在自己的后台线程里。

判定为无害的依据：**先于本轮所有改动就存在**；转储里没有 `Current thread`，出错线程没有 Python 栈帧，应用代码不在栈上；从不导致任何断言失败，也从不终止进程；1039 条测试全通过。另外对应用侧真实 `ThreadingHTTPServer`（`RemoteService`）做了 8 轮启停 + 自检压测，全部干净——顺带排除了最初那条错误线索。保持监视，不做规避：压掉这条输出只会让将来真正的故障也看不见。

### 仍待真机目视确认

- Mica 窗口材质（离屏渲染拿不到 DWM 合成）。
- 深色模式下的原生标题栏是否跟着变深。
- 新图标在真实任务栏、开始菜单、Alt-Tab 与桌面快捷方式上的观感；以及原地更新后 Explorer 是否确实刷掉了旧图标缓存。
- 150% DPI（`QT_SCALE_FACTOR` 是进程级变量，只能 subprocess 跑）。

## 操作流程重构第一阶段（2026-09-23）

### 自动化

- Ruff 通过；完整测试 **861 passed / 6 skipped**，覆盖率 **86.07%**。第一阶段开始时的基线是 **377 passed / 4 skipped、74%**（v0.7.0 交付后同一工作区实测为 558 / 78.43%）。
- `controller.py` 从 **464 语句、48% 覆盖** 降到 **203 语句、82% 覆盖**。剩下的是构造函数与三个顶层命令；再往下拆只会是发明间接层而不是移除它。
- 四个用假 `self` 的测试文件全部改成真实对象构造：`test_warmup_scheduling`（`BackendService`）、`test_backend_switching`（同上）、`test_controller_ui`（`TrayIcon`）、`test_capture_preemption`（`CaptureController`，经 `tests/capture_harness.py`）。`test_sessions` 与 `test_capture_interaction` 一并改掉。仓库中已不存在对未绑定 `Controller` 方法的调用。
- 新增纯函数单测，均不需要 `QApplication`：选区模型 20、命令允许集 35、`onboarding.evaluate` 13、协议协商 18、配对 36。
- 端到端配对在 `127.0.0.1` 上跑**真实** HTTP 服务：取码、领取、用新签发的每设备密钥重新连上并通过 `/v1/health`，同时确认主机共享密钥仍然可用（降级安全）。

### 实跑发现并修掉的缺陷

1. **应用自第 3 步起根本无法启动。** 设置窗口在构造文本翻译页时调用 `occupancy()`，而 `occupancy()` 读的 `downloads` 在两条语句之后才创建。测试没抓到，是因为它们要么用读得极少的假窗口，要么用自带 `occupancy` 的假控制器。改为窗口最后构造，并加了用**真实** `Settings` 跑构造的 `test_the_real_settings_window_can_be_built_during_startup`。
2. **选区尺寸角标滑到状态胶囊底下。** 角标只跟屏幕顶边比较，没考虑后画的胶囊，因此上三分之一的任何选区都看不到尺寸。渲染五种覆盖层状态时目视发现，已改成与胶囊矩形比较，并加了参数化测试。
3. **`negotiate` 的默认参数在定义时绑定**，测试无法替身一个只认 v1 的旧构建。改为调用时读模块常量。

### 覆盖层目视核对

`scripts/render_overlay_preview.py` 离屏渲染五种状态（selecting / adjusting / adjusting-too-small / processing / failed），背景是左亮右暗的渐变，两端对比度同时可判。产物签入 `artifacts/ui/overlay-*.png`。两行胶囊（消息行 + 常驻提示行）、八个可拖控制点、失败态保留选区框均已目视确认。

### 打包验收

- PyInstaller 用未改动的 `ScreenTranslator.spec` 重新打包成功，`ScreenTranslator.exe` 41,720,333 字节（v0.7.0 为 41,617,726，+102 KB）。第一阶段新增的十余个模块全部是纯 Python，随 PYZ 进 exe，不需要改 spec，也不影响增量补丁的投递面。
- 打好的 exe 跑 `--self-test D:\AI\Models`：真实 PaddleOCR（CUDA）+ 真实 llama.cpp 两轮全绿。首轮 16.03 s（含加载），次轮 0.94 s、OCR 63 ms、4 块。四种语言方向译文正确。这同时证明新的导入图在冻结环境下完整可解析——缺任何一个模块应用都起不来。
- `tests/test_thin_client_imports.py`、`test_client_edition_packaging.py`、`test_installer_boundaries.py`、`test_installer_shortcuts.py` 共 30 项通过，瘦身版边界与增量包哨兵未受影响。

### tailnet 设备发现（真机）

`scripts/remote_check.py devices` 对真实 `tailscale status --json` 输出：本机 `BoPeng9950x3d 100.100.119.102`，对端 `PBT14P 100.92.144.26`（当时离线）。解析走的是新的 `parse_status`，`parse_peer_route` 现在是它的薄封装，只有一份解析逻辑。

### 仍待真机验收

- 双设备配对码全流程（主机 `remote_check.py host --offer`，客机 `remote_check.py pair --url <URL> --code <六位>`）——需要另一台设备开机。
- v1 客机 ↔ v2 主机、v2 ↔ v1 的跨版本矩阵。
- 关闭 Windows 通知权限后确认截图失败仍然可见。
- 多屏与 125%/150% 混合缩放下的覆盖层交互。

## v0.7.0 跨设备翻译与客户端版（2026-09-21）

### 功能与质量

- Ruff 通过；完整测试 **558 passed / 4 skipped**，覆盖率 **78.43%**。改动前在同一工作区实测的基线为 **377 passed / 4 skipped、74%**（高于 v0.6.0 记录的 290 passed / 73.85%，因为其后又有提交补充了测试）。跳过项仍为可选训练环境。
- 新增测试 181 项：线格式 25、鉴权与 tailnet 解析 32、服务端与主机生命周期 24、端到端往返 14、后端选择 9、后端切换 5、跨设备配置 22、设置卡片 15、能力探测 7、瘦身版导入 5、客户端打包 11、其余为既有文件的补充。
- 端到端往返测试在 `127.0.0.1` 上启动**真实** HTTP 服务（假引擎替代 PaddleOCR 与 llama.cpp），覆盖鉴权、事件分帧、取消、错误映射、协议版本不一致与体积上限。中间除引擎外全部是生产代码路径。
- **取消确实跨设备生效**：客户端在收到首条 progress 后取消并关闭连接，主机在心跳写失败时取消自己的 token，假引擎观测到取消并抛出 `Cancelled`（`test_cancelling_on_the_client_cancels_the_work_on_the_host`）。这是唯一一处依赖心跳的行为——推理期间没有 progress 输出，没有心跳就检测不到断连。
- **隐私边界保持**：往返测试在 DEBUG 级别断言日志中不出现原文、译文与密钥；服务端只记录文本块数量、设备与耗时。
- **鉴权不可探测**：白名单未命中与密钥错误对外都返回同一句话，精确原因码只进主机日志（`test_an_unlisted_device_is_refused_indistinguishably_from_a_wrong_secret`）。
- 修复了实现过程中自查发现的缺陷：后端切换失败时原先会连旧后端一起 `stop()`，远程后端的 session 关闭后无法复用；改为新后端构造成功后才停旧的，并加了回归测试。

### 真引擎验收（`scripts/remote_check.py`，本机回环）

- `host --address 127.0.0.1 --self-check`：用**真实** PaddleOCR、真实 llama.cpp（`qwen3-8b-q5-k-m`）、真实 HTTP 服务与真实本地渲染跑完整条链路，输入是脚本生成的合成 fixture 图（四行 ASCII），不读取任何真实截图。
- 结果 `status: ok`，报告 `build/remote-check-loopback.json`：预热 16,718 ms（含 OCR 与 8B 加载）、OCR **63 ms**（4 行，CUDA）、翻译 **328 ms**（1 块，1 批，0 重试）、本地渲染 **78 ms**（1100×260，1 块绘制成功）。译文四行全部正确，段内换行保持。
- `tailnet.discover_address()` 对真实 `tailscale ip -4` 返回本机地址 `100.100.119.102`，此前列为"未测"的 subprocess 分支已实测通过。
- 首次运行时脚本在渲染步骤被 Qt 在 C++ 层直接 abort（退出码 9，Python 的 `except` 接不住）：`OverlayRenderer` 用 `QFontMetrics`，而脚本没有创建 `QApplication`。已修。顺带确认了一件事：进程硬崩时 `native.Job` 仍然回收了它派生的 `llama-server`，没有留下孤儿进程或端口占用。

### 真引擎验收（真实 Tailscale 地址）

- `host --self-check --allow 100.92.144.26`，绑定 `100.100.119.102:8765`，结果 `status: ok`，报告 `build/remote-check-tailnet.json`：预热 7,687 ms（OCR 已热）、OCR **79 ms**、翻译 **328 ms**、渲染 **32 ms**，译文与回环一致。这证明监听真实 tailnet 地址、在该地址上完成鉴权与全链路都成立。
- 该轮暴露并修复了两个只有实跑才会出现的缺陷：
  1. `remote_check.py` 的自检硬编码连 `127.0.0.1`，而服务只绑定单个接口地址，导致自检必然 `ConnectionError`。改为连 `status.url`。
  2. 更实质的一个：`--allow` 指定设备白名单后，**主机连自己的服务会被自己的白名单拒绝**——源地址是主机自己的 tailnet 地址而非 `127.0.0.1`。`AccessPolicy` 新增 `local_address`，由 `RemoteService.start()` 在解析出绑定地址后填入，使"本机访问自己的服务"与回环同等对待；密钥校验不受影响，仍然必须通过。
- `route` 字段为 `unknown` 属预期：查询的是主机自己的地址，不是 peer。真正的 direct/relay 判定要在客户端那侧跑才有意义。

### 真机双设备验收（2026-09-22）

- 拓扑：主机 `bopeng9950x3d`（`100.100.119.102`，RTX 4090，`qwen3-8b-q5-k-m`）；客户端 `pbt14p`（`100.92.144.26`）。主机以 `--allow 100.92.144.26` 启动，只允许这一台设备。
- 客户端**只安装了四个依赖**（PySide6 6.11.2、numpy 2.5.3、opencv-contrib-python 4.10.0.84、requests 2.34.2），没有 PaddleOCR、没有 CUDA、没有 llama.cpp，跨设备链路即可跑通。这实测确认了客户端版的依赖边界。
- 主机侧四个请求全部 `status=ok`：warmup 47 ms 与 0 ms（主机已热，未重新加载模型）、OCR **78 ms**（上传 71,736 字节，识别 4 行）、翻译 **625 ms**（推理 609 ms）。
- Tailscale 会话计数 `tx 9124 rx 82036`：主机收 82 KB、回 9 KB，下行约为上行的 11%，与"只回传 `{block_id: text}`、polygon 不出截屏设备"的设计一致。
- 连接为 `direct 172.20.6.156:41641`，未走 DERP 中继。
- 文件分发用 Taildrop（`tailscale file cp`）；Windows 版 Tailscale 直接落盘到下载目录，`tailscale file get` 取不到待取项，这是客户端部署时的一个易踩点。

### 增量补丁与主机 GUI 验收（2026-09-22）

- 增量补丁 `ScreenTranslator-0.7.0-Update.exe`，**43,245,850 字节**，SHA-256 `3D4DC7B2A8AD398FF47A3F73826C345B4BA90A9B903E15B9511A2F503956453A`，`-MinimumBaseVersion 0.6.0`，未签名。以 `/SILENT` 装到既有的 0.6.0（`D:\AI\AiTranslate\Install test\ScreenTranslator\`），安装日志 `build/update-0.7.0-install.log` 记录 `Installation process succeeded` 且无需重启。
- **增量通道足以承载本次改动**，这一点此前只是推断，现已实测：新代码引入 `http.server`、`queue`、`ipaddress` 等标准库模块，它们是纯 Python，随 PYZ 打进 `ScreenTranslator.exe`，而补丁正好替换该文件。这些模块位于 `controller` 的导入链上，缺任何一个应用都会启动失败——补丁后应用正常启动即为证据。exe 由 41,559,033 增至 41,617,726 字节（+57 KB）。
- 共享目录边界成立：安装前后 `D:\AI\Models` 均为 83 文件 / 45,148,701,927 字节，`registry.json` SHA-256 保持 `4DC2113948FED7A95C316783D4CDF61A55A308343F7E938A9FF575876D146564`；`config.json` 未被安装器触碰。
- **主机角色的 GUI 开关实测通过**：在设置窗口打开"作为主机为其他设备翻译"、生成密钥、白名单填 `100.92.144.26` 并保存后，`8765` 端口由 `ScreenTranslator.exe`（而非脚本）监听在 `100.100.119.102`，`auto` 正确解析为 Tailscale 地址。
- 配置从 version 3 迁移到 4 正确：既有字段（`Ctrl+Alt+Q`、模型目录、所选模型）原样保留，新增 `service_enabled: true`、`service_address: "auto"`、`service_port: 8765`、`service_token`、`service_allowed_peers: ["100.92.144.26"]`。
- 经 GUI 主机完成的真实跨设备截图：上传 **959,358 字节**、OCR **37 行 / 703 ms**、翻译 **18 块 / 3 批 / 8,594 ms / 0 重试**（zh-Hans → en）。会话累计收 3.4 MB、回 536 KB。
- **鉴权拒绝路径被真实触发**：t14p 先用旧密钥连接，主机日志记录 `Rejected remote request from 100.92.144.26: invalid-token`；更新密钥后立即成功。这验证了三件事——白名单内的设备仍需通过密钥校验、精确原因码只落在主机日志、对端收到的是统一措辞。此前该路径只有单元测试覆盖。

### 真机 GUI 验收（2026-09-22）

- 客户端安装包 `ScreenTranslator-Client-0.7.0-Setup.exe`（101.83 MB，负载 296.58 MB，SHA-256 `B0F1866510FFB795E88380B5AA3B1C1913791B06BA764FDCE8811E56A6127EA1`）在 t14p 上**实装成功**并正常启动，设置窗口的"跨设备"卡片渲染正确。
- 在 GUI 里选择"远程主机"、填入 `100.100.119.102:8765` 与配对密钥并保存后，后端切换到远程、状态刷新为就绪，按快捷键框选真实屏幕内容翻译成功。
- 真实截图一次的主机侧数据：上传 **708,765 字节**、OCR **29 行 / 594 ms**（检测 78 + 识别 516）、翻译 **16 块 / 3 批 / 2437 ms / 0 重试**。会话累计收 2.0 MB、回 162 KB，下行为上行的 **7.9%**。
- 本轮暴露并修复了一个只有长时间真实运行才会出现的缺陷：`Controller.on_readiness_tick` 每 15 秒调用一次 `schedule_ocr_warmup()`，而预热完成后令牌即被清除，导致**每个 tick 都重新预热一次**。本地是廉价空操作所以无感，远程则变成每 15 秒一次 HTTP 往返加一行主机日志。改为按后端记录 `warmup_completed`，成功后不再重复，失败或更换后端时重置以便重试。新增 `tests/test_warmup_scheduling.py` 6 项覆盖。

### 打包与安装

- 客户端负载 `dist/ScreenTranslatorClient`：**296.58 MB**，完整版 `dist/ScreenTranslator` 为 **6473.17 MB**，缩小约 22 倍。按 `paddle` / `paddleocr` / `nvidia` / `llama-server.exe` 四个关键字递归搜索，客户端负载**零命中**。
- 两个安装器均用 `ISCC.exe` 实编译通过（退出码 0）：
  - 客户端 `ScreenTranslator-Client-0.7.0-Setup.exe`，**106,774,905 字节**，SHA-256 `DE52BD40D7A2D43C5FDC6C67F606E6D39484F624887BC1D07C0EC9DBDC19C26E`，未签名。
  - 完整版 `ScreenTranslator-0.7.0-Setup.exe`，**4,062,917,159 字节**，未签名。编译产物仅用于验证共享脚本参数化未造成回退，随后已删除；正式发布仍应走 `scripts/build.ps1` 以生成发布清单。
- `installer.common.iss` 通过 `ClientEdition` 切换标识，`installer.client.iss` 只有 6 行并 `#include "installer.iss"`，因此安装、升级、降级保护与卸载逻辑两版共用一份，测试断言客户端脚本内不含任何 `[Setup]` / `[Files]` / `[Icons]` / `[Code]` 段。
- 发布清单 schema 升至 2 并新增 `edition` 字段（`full` / `client`）；增量包仍限定完整版，`create_manifest` 会拒绝 `incremental + client` 组合。

### 未覆盖

- **未验证 DERP 中继路径**。真机验收拿到的是直连（`direct`），走中继时的实际耗时没有测量过。
- **取消路径未在 GUI 中验证**。跨设备取消有回环端到端测试，但没有在真机上按 Esc 确认主机会立即停止推理。
- **客户端安装器的拒绝路径未验证**。"检测到完整版即拒绝安装"这条分支只有脚本级断言；t14p 上没有装过完整版，实际未触发。
- **增量更新未覆盖客户端版**。客户端只能整包重装，`installer.update.iss` 仍限定完整版。
- **修复"已安装的应用"显示陈旧版本号**。`installer.update.iss` 此前只写 `DisplayVersion` 不写 `DisplayName`，列表里一直停留在最后一次完整安装的版本。补上 `DisplayName` 后重建补丁（**43,245,974 字节**，SHA-256 `94746C72C46E8524F2FA873D69397718664F3739F0404BA1B06BCDA7A221116C`）并实装：显示名由 `Screen Translator version 0.5.3` 修正为 `Screen Translator 0.7.0`，`D:\AI\Models` 仍为 45,148,701,927 字节且 registry 哈希不变。测试断言该值与 `installer.iss` 的 `AppVerName` 一致，防止两边再次跑偏。这是 0.6.0 之前的遗留问题，非本次引入。
- **补丁包只在本机基线上验证过**。两次安装的基线都是这台机器上的既有安装，没有在干净的 0.6.0 全新安装上试过增量升级。
- **未验证客户端安装器的实际安装行为**（包括"检测到完整版即拒绝安装"这条路径）。该逻辑有脚本级测试，但没有在干净机器上跑过 setup。
- `tailnet.py` 的 subprocess 分支覆盖率 52%：纯解析函数有测试，实际调用 `tailscale ip -4` / `tailscale status --json` 的路径未测。

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
