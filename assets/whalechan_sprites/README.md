# whalechan sprite sheets

角色：whalechan

包含 12 组独立动作；PNG 均带透明 Alpha 通道。图片为重绘成品，未包含旧图与中间生成版本。

| 文件 | 动作 | 帧数 | 排列（列 × 行） |
|---|---|---:|---|
| whalechan_idle.png | 待机 | 6 | 3 × 2 |
| whalechan_walk_right.png | 向右行走 | 8 | 4 × 2 |
| whalechan_walk_left.png | 向左行走 | 8 | 4 × 2 |
| whalechan_wave.png | 招手 | 4 | 2 × 2 |
| whalechan_jump.png | 跳跃 | 5 | 3 × 2 |
| whalechan_sad.png | 低落 | 8 | 4 × 2 |
| whalechan_happy.png | 开心 | 6 | 3 × 2 |
| whalechan_sleepy.png | 困倦 | 6 | 3 × 2 |
| whalechan_think.png | 思考 | 6 | 3 × 2 |
| whalechan_notification.png | 新消息提醒 | 6 | 3 × 2 |
| Whalechan’s puzzled head-scratch animation.png | 扣扣脑袋 | 6 | 3 × 2 |
| Whalechan’s Goodbye into a Cosmic Vortex.png | 返回潜空间 | 8 | 4 × 2 |

阅读顺序：从左到右，再从上到下。跳跃图右下角为空，忽略该格。

提醒动作：注意新消息 → 抬手 → 食指向上 → 黄色灯泡出现 → 灯泡亮起。

桌宠现已使用本组素材：`pet.json` 与 `spritesheet.webp` 为运行文件，12 条轨道共 77 帧，统一为 560 × 560 的透明单元格。切帧沿实际透明间隙分离上下行，统一角色比例与锚点，并保留跳跃腾空。漩涡帧使用统一缩放和原点，保留原画的角色移动与漩涡缩小；第 5 帧越过标称格子的边缘归回该帧，避免在第 6 帧留下残影。原始 PNG 尺寸不同，不能直接作为原图的 192 × 208 像素格子替换。

所有轨道均为 `loop: false`。有未关闭的消息气泡时，消息状态持续重复播放 `notification`，每轮约 2.5 秒；关闭最后一条消息后恢复待机组。排队角标变化不会重启动画。待机组默认排除低落、困倦、新消息提醒，其余动作（含扣扣脑袋）均参与加权随机播放：待机占 90%，其余已选动作平分 10%，允许连续重复。右键「设置 → 待机组表情」可调整并保存选择，底部「出现概率权重…」可修改相对权重、预览实际概率或恢复默认。

原 MCP 动作名保持兼容，`waiting` 对应开心，`running` 对应困倦，新增 `head-scratch` 对应扣扣脑袋，菜单与动作查询使用新素材的中文标签。

启动时以一基帧号播放漩涡素材的 8、7、6、5、4、1 帧，随后招手一次，并从招手开始显示「解码中～返回显空间」5 秒。退出时显示「正在返回潜空间」，播放漩涡素材完整 8 帧后关闭。`goodbye` 默认不参与待机组，启动/退出提示使用独立的临时气泡，不加入消息历史。

更新 PNG 后运行 `python3 scripts/prepare_whalechan_assets.py` 重新生成运行文件（准备脚本需要 Pillow，桌宠运行时不需要）。本次接入仅针对此仓库的 PyQt 桌宠。
