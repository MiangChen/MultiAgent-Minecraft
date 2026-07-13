# experiments — 协作失调复现流水线

目标：稳定复现 MineCollab（arXiv 2504.17950）附录 10.1 的 construction 互拆现象，并产出可用于评估器研究与展示的素材（双 FPV 视频、得分曲线、事件时间戳）。

## tasks/

| 文件 | 说明 |
|---|---|
| `pyramid_two_agents.json` | 2-agent 金字塔（143 块 / 5 层），材料按石材系 vs 金/石英系互补拆分，timeout 1800s |
| `pyramid_two_agents_scarce.json` | 材料缺口 9%（石砖 41→33、石头 23→18）：轻压力档 |
| `pyramid_two_agents_scarce2.json` | 材料缺口 22%（石砖 41→20、石头 23→12）：**推荐档**，稳定诱发成片「捐体」拆除 |
| `pyramid_three_agents_1800s.json` | 3-agent 原版任务加长超时 |

压力设计原则（沿用课题方法论）：**只改任务级资源条件，不加任何诱导性 prompt**——超平坦世界无石材来源、合成被屏蔽，材料耗尽后「从已建结构拆料挪用」是 agent 的自然选择。

## scripts/

按一轮实验的时间顺序：

1. `clear_site.mjs` — 每轮前清场（op bot 发 /fill + /kill 掉落物）
2. `score_watcher.py <run.log> <scores.tsv>` — tail 运行日志，给每条 Task score 打墙钟时间戳
3. `detect_drops.py --tsv scores.tsv` — 检测得分下降事件（>0.3pp；过滤 0% 假读数与开局噪声）
4. `make_clips.py --tsv ... --videos-root bots --agents andy,bob --out <dir>` — 按 [首降−40s, 末降+50s] 窗口切双 FPV 片段；agent 崩溃重启产生多段 mp4 时自动选覆盖窗口的段
5. `make_curve.py` — 得分曲线 + 拆除事件标注（matplotlib，Noto CJK）
6. `make_composite.py` — 顶部任务横幅 + 双 FPV 并排的单文件合成 mp4
7. `render_chat_panel.py` / `make_pptx.py` — 讲解版对话面板 PNG 与 page-4 风格 PPTX（python-pptx 嵌视频）

Python 依赖：`python-pptx matplotlib pillow`（uv venv 即可）；系统依赖：`ffmpeg`。

## blocked_actions（construction）

以 MineCollab 评测列表为基础，两处必要修正（当前代码版命令集与论文 fork 不同）：

- **解除** `!newAction` `!placeHere`——本版仅有的放方块途径，照抄论文列表得分恒为 0
- **勿屏蔽** `!entities`——prompter.js 内部调用，屏蔽即崩溃

完整列表见仓库根 README 的启动命令或 git log 中的运行记录。

## god_camera.mjs — 等轴测上帝视角（防晕镜头）

FPV 会随 agent 转向令人眩晕；此脚本提供**固定等轴测俯拍机位**（论文 YouTube 视频同款构图）：

```bash
# 在任务运行的同时另开一个进程（candy 需在 ops.json 中；以旁观模式悬停，agent 不可见）
node experiments/scripts/god_camera.mjs \
  --username candy --center -55.5,-58,10.5 --distance 42 --fov 38 \
  --res 1280x720 --fps 12 --out experiments/out
```

- 相机固定在工地斜上方 45° 对角线方向，全程不动；`--distance/--fov` 控制取景范围
- 输出 `experiments/out/god/videos/<epoch>.mp4` + timeline.tsv，目录结构与 agent 录像一致——
  剪辑时直接 `make_clips.py --videos-root experiments/out --agents god` 即可按同一冲突窗口切片
- 建议合成版用 god 视角做主画面、双 FPV 做副画面
