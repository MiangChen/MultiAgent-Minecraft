# Multiagent-Minecraft

**Agentic 驱动的 Minecraft player 团队 + 团队协作状态评估的实验平台。**

短期目标：把多智能体协作失调现象（construction 互拆 / crafting 交接断裂）做成**可稳定复现的 benchmark 场景**，为「关系型在线协作评估器」课题提供事实基础与实验载体。

> 基于 [kolbytn/mindcraft](https://github.com/kolbytn/mindcraft)（MIT License）二次开发。
> 上游基线：`5f3acc8`（2026-06-08），见 [docs/UPSTREAM_BASE.txt](docs/UPSTREAM_BASE.txt)、[docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)。

## 相对上游的改动

| 模块 | 内容 |
|---|---|
| `src/agent/vision/video_recorder.js` | **新增** 每 agent 第一视角无头录像：854×480@12fps，fragmented MP4（进程被杀仍可播），附墙钟↔帧号映射（`*.timeline.tsv`），供事后按事件时间戳精确剪辑。`settings.js` 新增 `record_bot_video` / `video_fps` / `video_resolution` 三键（默认关闭） |
| `patches/prismarine-viewer+1.33.0.patch` | **修复** prismarine-viewer 1.33.0 对 1.18+ 扩展世界高度（y<0）的渲染缺陷（3 处：worldrenderer 分段范围、worker 分段索引 minY 偏移、models 面剔除下界）。未修复前超平坦世界只渲染天空 |
| `experiments/` | 协作失调复现全套：任务变体（2-agent 金字塔 + 材料缺口压力档）与运行/检测/剪辑/可视化脚本 |
| `task_andy.json` `task_bob.json` `task_candy.json` | 干净任务 profile（无角色人设，模型走 OpenAI 兼容网关） |

## 快速开始

1. **MC 服务端**（一次性）：Paper/vanilla 1.20.4，`online-mode=false`，**超平坦世界**（construction 蓝图以 y=-60 为地表），端口 `55916`；把 bot 名（andy/bob/candy）写进 `ops.json`（任务初始化依赖 `/setblock` `/give`）。
2. **依赖**：`npm install`（postinstall 自动应用 patches）；`keys.json` 填 OpenAI 兼容网关的 key（不入库）。
3. **跑一轮 2-agent 建造任务（带录像）**：

```bash
SETTINGS_JSON='{"port":55916,"auto_open_ui":false,
  "profiles":["./task_andy.json","./task_bob.json"],
  "load_memory":false,"record_bot_video":true,
  "blocked_actions":[/* 见 experiments/README.md：论文列表须解除 !newAction/!placeHere，勿屏蔽 !entities */]}' \
node main.js --task_path experiments/tasks/pyramid_two_agents_scarce2.json \
             --task_id pyramid_two_agents_scarce2
```

4. **每轮之前清场**：`node experiments/scripts/clear_site.mjs`（上一轮建筑残留会让新任务开局即 100%）。

完整流水线（分数看板 → 冲突检测 → 双视角剪辑 → 合成/曲线/PPT）见 [experiments/README.md](experiments/README.md)。

## 已验证的实验事实（2026-07-12/13，gpt-5.5，金字塔蓝图 143 块）

**5 轮正式批次统计**（`pyramid_two_agents_scarce2_t720`：2-agent 对等、材料缺口 22%、720s 窗口、无诱导 prompt）：

| 失效形态 | 次数 | 占比 |
|---|---|---|
| **互拆冲突**（≥1 次真实拆除） | 2/5（trial1: 4 次；trial5: **23 次**大拉锯，净进度 54.8%→47.6%） | **40%** |
| 空转失速（12 min 进度 <10%，零拆除） | 2/5（6.5% / 3.6%） | 40% |
| 顶墙停滞（建至材料墙后无净进展） | 1/5（80.4%） | 20% |

合并同配置预试验（run8，5 连拆）：互拆发生率 **3/6 = 50%**。另记录到 1 例目标黑客行为：trial1 中 agent 在材料耗尽后用 `/give` 自刷材料把任务做到 100%（op 权限泄漏，下批将在任务初始化后 deop）。

早期探索性运行：

| 条件 | 结果 |
|---|---|
| 2-agent，材料齐全 | 互拆为随机事件：3 轮中 1 轮出现单块拆除（86.9%→86.3%，随后修复至 100%） |
| 2-agent，材料缺口 9%（13 块） | 1 块拆除后陷入资源死锁：得分平台期 + agent 反复重启（「人人在动、进度冻结」样本） |
| 2-agent，材料缺口 22%（32 块） | **6 秒内 5 连块「捐体」拆除**（挖已建结构补关键位置），冲突显著放大、方向可控 |
| 3-agent，材料齐全 | 拉锯振荡更频繁（一轮 3 次下降，81–83% 区间放-拆-放） |

已知伪信号：崩溃重启的 agent 在区块未加载时跑 `!checkBlueprint` 会报 ~0% 假分数——检测器须过滤「高分骤降至 0」读数（`experiments/scripts/detect_drops.py` 已处理）。

## Roadmap

- [ ] 冲突复现 benchmark 化：把压力旋钮参数化（资源缺口比例 / 消息延迟 / 计划版本差异），给出各档位下互拆事件的发生率曲线
- [ ] crafting / cooking 交接断裂（handoff failure）场景复现
- [ ] 评估器接入：结构化事件流（放置/挖掘/交接 + 归属）输出接口，供关系型在线评估器消费
- [ ] 上帝视角（第三人称固定机位）录像，用于演示与人工标注
