# PyQt 桌面宠物

使用 dsh-web“鲸鱼娘（精致版）”素材的原生 PyQt6 桌宠：透明背景、无边框、请求置顶、拖动、点击互动、右键切换动作、滚轮缩放、暂停动画，以及 agent 的 MCP 通知气泡。运行时完全离线，不需要浏览器或原项目服务。

## 安装与运行

环境要求：

- Python 3.10 或更新（PyQt6 与 mcp 均要求 `>=3.10`；开发与验证使用 CPython 3.12 / 3.14）
- 图形桌面会话：Windows、macOS，或 Linux 的 X11 / XWayland（见「Linux 桌面」）
- 素材已随仓库提交在 `assets/`（约 2.3 MB），运行本身不需要联网

```bash
git clone <本仓库地址> && cd desktop_companion

# 1. 创建虚拟环境（uv 与标准库 venv 二选一）
uv venv .venv
python3 -m venv .venv          # 不用 uv 时

# 2. 安装依赖
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m pip install -r requirements.txt   # 不用 uv 时

# 3. 素材缺失或校验失败时重新拉取（按 Git blob SHA-1 校验，可重复执行）
.venv/bin/python scripts/fetch_assets.py

# 4. 无桌面自检：9 条动画轨道、57 帧透明精灵、无边框窗口
.venv/bin/python pet.py --check

# 5. 运行
.venv/bin/python pet.py
```

Windows 把 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`。

两个依赖文件的区别：`requirements.txt` 只列直接依赖及其允许区间，适合日常安装和升级；`requirements.lock.txt` 是开发机（CPython 3.14 / Linux x86_64）的完整锁定版本（含传递依赖），用于逐位复现当前环境。在其他平台或其他 Python 版本上若某个包没有可用 wheel，请改用 `requirements.txt`，或在本机重新生成锁定文件：`python -m pip freeze > requirements.lock.txt`。

### 系统依赖（Linux）

PyQt6 的 wheel 自带 Qt 运行时，但 xcb（X11 / XWayland）平台插件仍依赖系统的 Xcb、OpenGL、fontconfig 等库。桌面环境内一般已经装齐，最常缺的是 `libxcb-cursor`：

| 发行版 | 安装命令 |
| --- | --- |
| Debian / Ubuntu | `sudo apt install libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-util1 libxcb-xfixes0 libxcb-xkb1 libxkbcommon-x11-0 libx11-xcb1 libegl1 libgl1 libfontconfig1 libdbus-1-3` |
| Fedora | `sudo dnf install xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm libxkbcommon-x11 libX11-xcb mesa-libEGL mesa-libGL fontconfig dbus-libs` |

缺库时以自检命令为准（有输出表示还缺这些库）：

```bash
find .venv -name libqxcb.so -path "*platforms*" -exec ldd {} \; | grep "not found"
```

没有显示器的 CI 或 SSH 会话可以用 `QT_QPA_PLATFORM=offscreen` 运行 `--check` 和各检查脚本（`--check` 会自动使用该模式），但真正显示窗口仍需要一个桌面会话。

### 运行参数

```bash
.venv/bin/python pet.py                                  # 默认尺寸 320
.venv/bin/python pet.py --size 240                       # 窗口最长边像素数
.venv/bin/python pet.py --check                          # 离屏自检，不打开桌面窗口
.venv/bin/python pet.py --socket 名称                     # 指定本机通知 IPC 名称（默认按项目路径和用户生成）
.venv/bin/python pet.py --history-db /path/to/messages.sqlite3   # 指定历史数据库路径
```

左键拖动，单击播放互动动作，右键打开原生菜单，滚轮调整大小，通过菜单的“退出”退出。选择某个动作后会按原始清单循环或回到待机。当前没有实现上游的养成数值、语音、自动 AI 对话和自动行走；agent 可以主动通过 MCP 发送通知。

桌宠设置为不接受键盘焦点、显示时不激活。移除了 Esc 退出，不注册全局热键；鼠标悬停或离开时均不主动接管其他应用的键盘输入。主动打开右键菜单时，保留标准菜单的临时键盘抓取，Esc 只关闭菜单；菜单关闭后释放抓取。

右键菜单的“历史消息”会列出最近 20 条通知的接收时间、标题与正文摘要。选择一条可查看完整消息，“查看 / 管理全部消息…”打开完整历史列表，支持加载更早消息、选择复制正文，以及重新显示气泡。历史窗口打开时，新收到的通知会出现在列表顶部，并保留正在阅读的消息。历史窗口由用户主动打开，可以使用键盘操作和复制文本。

历史列表中的复选框用于批量选择，“删除选中”会永久删除勾选的记录。“全选已显示”选择当前已加载的消息；可以加载更早消息后继续勾选，新收到的消息默认不勾选。“清空全部”确认后会删除数据库内全部历史，包括尚未加载的消息。删除会同步更新列表、条数、详情和下次打开的右键菜单；重启后也会保留删除结果。

所有成功接收的通知（包括排队中的消息）都会立即提交到 SQLite 数据库，默认路径为项目内的 `data/messages.sqlite3`。记录包含通知 ID、UTC 接收时间、标题、完整正文、显示时长及提示音设置；界面显示本地时间。退出或重启后历史仍保留，未显示完的通知不会自动弹出；从历史重新显示只生成气泡，不重复写入历史，也不播放提示音。队列已满或参数无效的请求不会存入历史；数据库写入失败时通知会返回错误。

数据库及其 WAL / SHM 辅助文件属于运行数据，默认 `data/` 已加入 `.gitignore`。数据库使用 Python 内置的 `sqlite3`，无需安装额外依赖。历史与菜单检查：`.venv/bin/python scripts/check_history.py`，使用临时数据库，不写入实际消息历史。

右键“退出”会关闭宠物、气泡与历史窗口，停止动画计时器，关闭本机 IPC 连接及 SQLite 数据库，并结束 Qt 事件循环。已经返回成功的通知均已提交到数据库；退出时取消尚未开始的存储任务，等待当前存储操作结束后关闭连接，未确认的请求不会在退出期间弹出气泡。主宠物窗口显式启用 `WA_QuitOnClose`，避免 Qt 默认将 `Tool` 窗口排除在最后窗口退出判断之外。Codex 启动的 stdio MCP 是由 MCP 客户端管理的独立进程，生命周期跟随客户端连接；桌宠退出后，相关工具会返回离线错误。

退出回归检查：`.venv/bin/python scripts/check_shutdown.py`；加 `--desktop` 可在真实桌面验证。检查会通过右键菜单点击“退出”，确认普通宠物、气泡显示中、历史窗口打开这三种情况的子进程正常结束并被回收，同时验证 IPC 文件与数据库锁已释放。

`--check` 使用 Qt 离屏平台检查鲸鱼娘（精致版）的 9 条动画轨道、57 帧精灵、透明通道、动作 fallback，以及无边框窗口的透明绘制。离屏后端的 `does not support raise()` 提示是正常的。

## MCP：把桌宠当作 terminal bell

桌宠默认接收本机通知。先启动桌宠，再配置 MCP 客户端（已在运行的旧版本需要退出后重启）：

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python pet.py
```

将下面配置合并到支持 stdio 的 MCP 客户端配置中，重新连接 MCP server。项目内也提供了 `mcp-config.example.json`。两处路径都要换成本机的绝对路径：`command` 指向虚拟环境里的 Python（Windows 为 `.venv\Scripts\python.exe`），`args` 指向本项目的 `mcp_server.py`。

```json
{
  "mcpServers": {
    "desktop-pet": {
      "command": "/ABSOLUTE/PATH/TO/desktop_companion/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/desktop_companion/mcp_server.py"]
    }
  }
}
```

MCP server 使用[官方 Python SDK](https://py.sdk.modelcontextprotocol.io/v1/) 的 stdio transport。客户端启动 `mcp_server.py`，通过本机 Qt local socket 将通知交给正在运行的 `pet.py`；不会额外启动一只宠物，不监听 HTTP 端口。默认 IPC 名称按项目路径和当前用户生成，Linux/Windows 设置为当前用户访问。支持多个 agent 连接同一只宠物。

| 工具 | 用途 |
| --- | --- |
| `desktop_pet_bell` | 在宠物旁显示动漫风格的对话气泡，返回通知 ID、`displayed` / `queued` 状态及等待条数 |
| `desktop_pet_status` | 检查桌宠是否运行、当前通知 ID、等待条数、当前动作与暂停状态；未运行时返回工具错误 |
| `desktop_pet_list_actions` | 查询当前宠物支持的动作名称、中文标签、循环属性和单轮时长 |
| `desktop_pet_play_action` | 立即播放指定动作，默认播放一次后回到待机；自动恢复暂停的动画 |

`desktop_pet_bell` 调用示例：

```json
{
  "message": "任务完成啦！\n测试全部通过，可以回来看看结果了。",
  "title": "Coding Agent",
  "sound": false
}
```

`message` 必填，支持 1–2000 字符的纯文本、中文、换行与 emoji。`title` 默认 `Agent`，最多 60 字符且为单行。气泡一直显示到用户手动关闭；`duration_seconds` 仅为兼容旧调用保留，仍接受 3–120 秒，但不再控制自动关闭。默认安静显示；`sound: true` 同时请求系统提示音，是否有声音取决于桌面的 bell 设置。

agent 也可以先调用 `desktop_pet_list_actions`，再调用 `desktop_pet_play_action` 播放某个动作。例如让宠物招手一次：

```json
{
  "action": "waving",
  "once": true
}
```

当前鲸鱼娘支持 `idle`（待机）、`running-right`（向右跑）、`running-left`（向左跑）、`waving`（招手）、`jumping`（跳跃）、`failed`（失落）、`waiting`（等待）、`running`（忙碌）、`review`（思考）。使用查询工具返回的名称作为 `action`，不要传中文标签。

`once` 默认 `true`，播放完整一轮后回到待机。设为 `false` 时遵循素材原有的循环 / fallback 规则，例如 `running` 会循环，`jumping` 仍只播放一轮；使用 `{"action": "idle", "once": false}` 恢复待机。动作立即替换当前动画、不排队，播放指令会恢复暂停的动画；向左 / 向右跑只播放动画，不移动窗口。未知动作返回错误并保留当前动作和暂停状态。动作工具与气泡工具可独立使用。

更新后重启桌宠并重新加载 MCP server，即可发现新增工具，原有连接配置可继续使用。

气泡使用奶白 / 粉色渐变、描边、阴影和指向角色的尾巴，保持置顶且不抢键盘焦点。移动或缩放宠物时气泡跟随，并在屏幕边缘调整位置。长消息可滚动阅读，气泡不会自动消失，只有点击 `×` 或右键菜单“收起通知 / 下一条”才关闭当前通知。有消息排队时，气泡标题旁显示红色计数角标，数字表示等待中的消息数（不含当前消息）；关闭当前消息后按先后顺序显示下一条，计数随之减少，没有排队消息时角标隐藏，关闭最后一条后气泡消失。最多等待 20 条；队列已满、文字无效或桌宠未运行时，工具明确返回错误。通知确认表示桌宠已接收，不表示用户已阅读。退出桌宠会清除未读队列。

![动漫风格的 MCP 通知气泡](docs/notification-preview.png)

可以在 agent 的指令中加入：

> 完成任务、需要我处理问题或等待我提供信息时，调用 desktop_pet_bell，用中文发送两三句简短通知。避免对每个操作都发送进度提示。

需要指定不同实例时，在桌宠和 MCP 配置的 `env` 中设置相同的 `DESKTOP_PET_SOCKET`，或为桌宠使用 `--socket 名称`。同一个 IPC 名称只运行一只宠物。

实例使用 `QLockFile` 持有与用户及 IPC 名称对应的进程间锁，锁文件放在系统临时目录。探测、清理残留 socket 和监听均在持锁期间进行；连接超时或权限错误不会触发端点删除。启动时也会检测尚未使用实例锁的旧版本桌宠。

完整链路检查（不打开桌面窗口，包含真实 MCP 客户端握手、动作查询与播放、中文通知、排队角标、手动关闭、参数校验与 IPC 错误）：

```bash
.venv/bin/python scripts/check_notifications.py
.venv/bin/python scripts/check_notifications.py --preview /tmp/desktop-pet-preview.png
```

原生 Wayland 通常不允许客户端定位独立窗口，因此气泡跟随和贴边定位应使用支持窗口定位的桌面后端；GNOME 下默认使用下节说明的 XWayland。

## Linux 桌面

GNOME + Wayland 且存在 DISPLAY 时，默认使用 XWayland（Qt xcb），让 GNOME 实际处理 `_NET_WM_STATE_ABOVE`，保持桌宠在普通应用窗口之上。保留用户显式设置的 `QT_QPA_PLATFORM`。其他 Wayland 桌面仍使用 Qt 的系统拖动和窗口管理器支持的置顶行为。不能承诺覆盖其他置顶窗口、全屏应用或系统界面。

手动选择 XWayland：

```bash
QT_QPA_PLATFORM=xcb .venv/bin/python pet.py
```

此模式需要系统安装 XWayland 以及 Qt xcb 平台插件的运行库（见「系统依赖（Linux）」）。若发行版没有提供 `libxcb-cursor.so.0`，可以把该库文件放到项目根的 `.native/usr/lib64/`：程序只在 xcb 模式下预加载它，不修改系统安装，`.native/` 已列入 `.gitignore`。这只是兵底方案，优先用包管理器安装。

真实桌面回归检查：`.venv/bin/python scripts/check_window_behavior.py`，会短暂打开测试窗口，验证普通窗口反复激活时的层级、不接收焦点属性、原始右键菜单与 Esc 关闭行为。

窗口透明区域目前仍属于窗口输入区域，没有实现按角色轮廓点击穿透。

## 代码结构与开发检查

`pet.py` 中的 `create_pet()` 负责装配各组件，`DesktopPet` 负责绘制、鼠标操作和窗口展示。业务模块通过显式依赖与 Qt 信号连接。

| 模块 | 职责 |
| --- | --- |
| `contracts.py` | 通知与历史数据类型、MCP 返回类型、共享参数校验和容量规则 |
| `history_store.py` / `history_service.py` | 独立 SQLite 仓库、专用存储线程及主线程结果交付 |
| `notification_controller.py` | 持久化后确认、容量预留、FIFO 队列和静默历史重放 |
| `pet_assets.py` / `animation.py` | 素材加载校验、实例帧缓存和动画播放状态 |
| `pet_commands.py` / `pet_ipc.py` | 应用命令分发、本机 socket 协议和实例锁 |
| `message_history.py` / `speech_bubble.py` | 异步历史管理界面和通知气泡 |

SQLite 连接在存储线程中创建、使用和关闭；运行中的查询、提交和删除不会阻塞 Qt 事件循环。通知写入与历史重放查询在完成前就预留容量，写入失败会释放预留；异步完成后仍按接收顺序显示。右键菜单使用已提交历史的最近消息缓存。

内部的 `HistoryService` 存储方法、`NotificationController.notify()` 和 `replay()` 返回 `concurrent.futures.Future`；结果回调在 Qt 主线程执行。界面使用完成回调，不能在 Qt 主线程上等待尚未完成的 `Future.result()`。启动前的数据库初始化和退出时的连接关闭会等待存储线程。MCP 工具名称、参数、返回 JSON 和 SQLite 表结构保持兼容，无需迁移现有历史数据库。

素材加载时检查动作、idle / fallback、帧数、正整数时长、精灵图裁切范围及所有分帧图片。`sprite2d` 保留上游固定九行布局；帧缓存属于每个素材实例，最多保存 100 帧。

重构专项检查使用临时数据库、随机 IPC 名称与离屏窗口，验证并发启动、残留端点、数据库锁定时的界面响应、未完成写入的容量预留、FIFO、重放和无效素材：

```bash
.venv/bin/python scripts/check_refactor.py
```

现有 `check_history.py`、`check_notifications.py`、`check_shutdown.py` 和 `check_window_behavior.py` 保留各自的端到端检查；`check_support.py` 提供仅用于检查脚本的 Qt 事件循环等待工具。

## 素材来源与许可

### 来源

本项目没有自绘美术，唯一的美术素材是 dsh-web 的「鲸鱼娘（精致版）」桌宠图集：

- 上游仓库：[zhu1090093659/dsh-web](https://github.com/zhu1090093659/dsh-web)（`packages/dsh-pet`，npm 包名 `@linxin666/dsh-pet`）
- 上游目录：[packages/dsh-pet/assets/whale-refined](https://github.com/zhu1090093659/dsh-web/tree/bd6c2bb67d9f88e1190c6884982c03c88205aa39/packages/dsh-pet/assets/whale-refined)
- 固定版本：`bd6c2bb67d9f88e1190c6884982c03c88205aa39`（下载、哈希校验和归因都锁定该 commit，不跟随 `main`）

`assets/` 只保存这一种宠物的 `pet.json`、精灵图和预览，加上两份上游许可证，共约 2.3 MB。精灵图为 1536×1872 的 8 列 × 9 行图集（单元格 192×208，使用 alpha），行序沿用上游 `sprite2d` 契约：idle / running-right / running-left / waving / jumping / failed / waiting / running / review。

上游记录的衍生关系（摘自 `packages/dsh-pet/README.zh.md` 的内置宠物表与来源说明）：

| 层级 | 内容 |
|---|---|
| 鲸鱼娘（原版）`whale` | dsh-web 仓库原有的鲸鱼娘图集，其 `pet.json` 标注 `license: BSD-3-Clause` |
| 鲸鱼娘（精致版）`whale-refined` | **本项目所用素材**：以上述设计方向为基础，经 AI 辅助二次创作、修复与细节精修的衍生版本，`pet.json` 标注 `license: MIT` |
| 更早的灵感来源 | 上游说明精致版参考了 DreamSkin 的「DeepSeek-鲸鱼娘」主题（[dreamskin.cc](https://dreamskin.cc)，历史来源记录标注作者 `powerdog996`、主题 MIT，见 [dsh-web commit `87edd7f`](https://github.com/zhu1090093659/dsh-web/commit/87edd7ff4800dffd40bc93fb76e4ae450390facd)）。该记录只用于说明来源与衍生关系，精致版并非原作者的官方作品 |

### 许可声明现状（上游不一致，本项目按最严格口径处理）

上游对这批素材的授权声明并不统一：

| 位置 | 声明 |
|---|---|
| dsh-web 根 `LICENSE`、`packages/dsh-pet/LICENSE` | Apache License 2.0。两份内容完全相同，是未填写版权人的 Apache-2.0 原文，在本仓库分别保存为 `assets/UPSTREAM-LICENSE` 与 `assets/DSH-PET-LICENSE` |
| `packages/dsh-pet/package.json` | `"license": "Apache-2.0"` |
| `assets/whale-refined/pet.json` | `"license": "MIT"`，且**没有 `author` 字段**（上游其他宠物通常会声明作者，例如 `ouo-neko` → `Pessimist0906`、`jyn` → `11726`） |
| 上游 `packages/dsh-pet/THIRD_PARTY_NOTICES.md` | 逐项声明了喷水鲸鱼装饰（派生自 DeepSeek wordmark，MIT © 2026 DeepSeek）、`ouo-neko`（MIT © Pessimist0906）、Miku（MIT © stushansusu，另受 Piapro 角色许可约束）等，但**未包含 `whale-refined`** |

结论：精致版素材同时被上游标为 Apache-2.0（仓库 / 包级）与 MIT（清单级），且缺少可署名的版权人。在作者本人澄清之前，本项目按约束更强的 **Apache-2.0** 对待这批素材：保留两份许可证原文、保留 `pet.json` 原样（不修改、不覆盖其 `license` 字段）、保留 `assets/source.json` 的来源与哈希记录，并在再分发时一并附上本节链接。Apache-2.0 相比 MIT 额外要求保留专利条款并标注修改，因此再分发或做衍生时请连同本文件与整个 `assets/` 一起附带，不要只取走 `spritesheet.webp`。

本项目自身的代码（`*.py`、`scripts/`、`docs/`）与素材许可相互独立；仓库当前没有声明自身许可证，若计划开源请自行选择并补充根 `LICENSE`，同时不要把素材的 Apache-2.0 约束误当作代码的许可结论。

补充提醒：上游 `packages/dsh-pet/assets/` 下还有其它宠物，其中星夜人偶（Starry Doll）为 CC-BY-NC-SA-4.0、Miku 受 Piapro 角色许可约束。本项目未使用这些素材；若以后扩展宠物，需要逐个核对清单与 `THIRD_PARTY_NOTICES.md`，不能沿用本节的结论。

### 复现与校验

```bash
python3 scripts/fetch_assets.py
```

脚本通过 GitHub API 读取固定 revision 的 tree，只抓取 `whale-refined` 目录与两份 `LICENSE`，按 Git blob SHA-1 校验后写入 `assets/`。`assets/source.json` 记录 5 个上游文件的路径、大小和 blob SHA-1；已完整的文件会被跳过，失败后可以直接重跑。更换素材版本时，需要同步更新 `scripts/fetch_assets.py` 里的 `REVISION`、`assets/source.json` 和本节的固定版本号。

若要把上游的第三方声明一并归档，可在 `fetch_assets.py` 的白名单中加入 `packages/dsh-pet/THIRD_PARTY_NOTICES.md`（当前未抓取）。
