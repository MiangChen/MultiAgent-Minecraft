# 轨迹格式与存储实测

## 架构

**采集与渲染完全解耦**：数据运行只记录轨迹（零视频、零渲染开销）；需要视频时用 `replay.mjs` 在 MC 中重演轨迹，任意挂载镜头（固定上帝视角 / `--follow` 第三人称跟随 / 傀儡 FPV）反复重录。

```
experiments/out/trial_N/trace/
  meta.json            # task、agents、蓝图/清场区域、起始 epoch、世界说明
  world_events.jsonl   # 观察者（世界真值）：pose/block/chat/join/leave
  <agent>.trace.jsonl  # agent 侧：cmd(含耗时与结果)/chat_out/inv 快照
  prompts/<agent>/     # LLM 完整输入输出（复用 log_all_prompts）
  scores.tsv           # 蓝图完成度时间线（epoch_ms \t score）
```

## 事件格式（JSONL，均含 `t` 毫秒 epoch）

| type | 字段 | 来源 |
|---|---|---|
| `pose` | name, x,y,z, yaw,pitch（弧度） | observer，entityMoved 10Hz 节流；**静止不产生事件** |
| `block` | x,y,z, from, to（`name[k=v,…]` 可直接 /setblock） | observer，world blockUpdate |
| `chat`/`whisper` | from, text | observer |
| `cmd` | cmd, args, ms, result（截断 500） | agent tracer，executeCommand 中枢 |
| `chat_out` | text [, to] | agent tracer，聊天出口 |
| `inv` | items{name:count}（变更才记） | agent tracer，5s 轮询 |

## 存储实测

单 agent 8 分钟建造轮（2026-07-13，`trace_trial_solo`，198 方块事件 / 1798 pose / 29 cmd）：

| 流 | raw | gzip |
|---|---|---|
| world_events.jsonl | 211 KB | 22 KB |
| andy.trace.jsonl | 9 KB | 1.7 KB |
| prompts/（LLM 全量 I/O） | 381 KB | 47 KB |
| scores.tsv | 37 KB | 4.9 KB |
| **合计** | **~700 KB** | **~77 KB** |

双 agent 7 分钟建造轮（245 方块事件 / 605 pose / 186 chat / 37 cmd+inv）：raw 504 KB / **gzip 51 KB**。

**回放保真验证**（2026-07-13）：该轨迹 2× 速回放，1036 事件 0 跳过；固定上帝机位重录 145s 视频，建筑按原时序逐步成型至完整；双傀儡 FPV 重录正常（视角随录制 yaw/pitch）。同一轨迹已验证可反复重渲。

对比：三机位视频同一轮约 30–80 MB。**轨迹 gzip 后约为视频体积的 0.3–1%**；1000 条轨迹 ≈ 0.1–0.3 GB。事前分析性预估（2–8 MB raw）偏保守，主因：pose 为运动驱动稀疏事件、prompts 模板重复度带来 8:1 压缩比。

## 回放

```bash
# 无真身 agent 运行时：
node experiments/scripts/replay.mjs --trace experiments/out/trial_1/trace \
  [--speed 2] [--from 300 --to 420]（秒，只放冲突窗口） [--mute-chat] \
  [--fpv andy,bob]（傀儡第一视角重录 → experiments/out/replay/<name>/videos）

# 并行挂机位（另开进程，用 watcher 身份避免与 director=candy 冲突）：
node experiments/scripts/god_camera.mjs --username watcher --out <dir>            # 固定等轴测
node experiments/scripts/god_camera.mjs --username watcher --follow andy --offset 8,7,8  # 第三人称跟随
```

回放机制：傀儡 bot 以原名登录（关闭客户端物理），pose→`/tp @s`+`bot.look`，block→director `/setblock`（air 时最近傀儡挥臂），chat→傀儡原文发言（`/` 开头跳过）。前置检查拒绝与真身同时运行。

## 已知边界

- 观察者只覆盖其视距内区块（12 chunks ≈ ±192 格，覆盖全部常规活动）
- 回放假设起始场地为空（meta.clear_region 先 /fill air）；非空初始场景需先扩展 region 快照
- agent 崩溃重启会在 trace 中留下多段（trace_start 重复），回放按 pose 流无感衔接
- 玩家实体在 prismarine-viewer 中渲染为占位模型（品红色块），位置/朝向正确，皮肤渲染待补
