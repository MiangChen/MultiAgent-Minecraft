# `trial_106` 与 `trial_162` 原始过程时间线

> 目的：把两轮最终同为 100 分的实验，按相对时间重新梳理为可阅读、可复核的过程记录。完整研究结论见[技术报告](COLLABORATION_PROCESS_ANALYSIS.md)，公众讲解见[讲解版报告](COLLABORATION_PROCESS_ANALYSIS_PUBLIC.md)。

## 阅读说明

两轮各有数千条事件。`trial_106` 包含 2,802 条世界事件和 1,957 行得分采样；`trial_162` 包含 3,099 条世界事件和 3,372 行得分采样。逐行抄入 Markdown 会被高频 pose 和重复 score 淹没，因此本文采用以下保留规则：

- 完整保留所有关键承诺、`!newAction`、蓝图检查、求助和策略改变；
- 将 5 秒一次的库存快照合并为资源消耗阶段；
- 将约 0.2 秒一次的得分采样压缩为 10% 里程碑、平台和下降事件；
- 保留所有“正确方块丢失→恢复”事件；
- 方块贡献只报告满足距离和时间窗规则的保守归因，其余保持未知。

时间 `t=0` 取每轮 Agent `trace_start`。引用格式如 `andy:10` 表示该 trial 的 `trace/andy.trace.jsonl` 第 10 行，`world:2612` 表示 `trace/world_events.jsonl` 第 2612 行。

还有一个重要前提：两轮不是同一个资源条件。

| Trial | 条件 | 初始资源压力 | 最终结果 |
|---|---|---|---|
| `trial_106` | `2a_d0` | 0% 缺口，材料按类型分给两人 | 294.8s，100 分 |
| `trial_162` | `2a_d33` | 33% 缺口，常用石材明显不足 | 507.0s，100 分 |

因此，下文可以比较“同样满分如何由不同过程产生”，但不能把全部差异直接归因于团队协作质量。

---

## 一、`trial_106`：两条长执行窗并行推进

### 初始状态

- 任务：`pyr_2a_d0`，双 Agent 建造 168 块蓝图。
- Andy 初始库存：1 polished_granite、34 polished_andesite、21 polished_diorite、23 stone、41 stone_bricks，以及工具（[原始行](../../out/trial_106/trace/andy.trace.jsonl#L3)）。
- Bob 初始库存：27 gold_block、16 quartz_block、2 quartz_pillar、3 glowstone，以及工具（[原始行](../../out/trial_106/trace/bob.trace.jsonl#L3)）。
- 两人的材料类型基本互补；没有确认的物品交接。

### 按时间排序的过程

| 时间 | 原始事件 | 同期世界/进度 | 只基于证据的说明 |
|---:|---|---|---|
| 0.0s | Andy、Bob trace 同时开始（`andy:1`; `bob:1`） | 得分尚未采样 | 两名 Agent 正常启动。 |
| 1.0s | 两人都收到 `!goal("Make a structure with the blueprint below")`（`andy:2`; `bob:2`） | 0% | 这是共同任务目标，不是分工协议。 |
| 6.5–7.8s | Bob、Andy 分别运行 `!checkBlueprint`（`bob:4–5`; `andy:4–5`） | 蓝图仍为空 | 两人各自读取同一份蓝图需求。trace 中命令结果被截断到约 500 字符，不能从这两行恢复全部缺块清单。 |
| 12.6s | Bob 发出第一个长承诺：`"Build the full blueprint ... gather or craft any missing blocks ... use existing gold_block, quartz_block..."`（[原文](../../out/trial_106/trace/bob.trace.jsonl#L6)） | 0% | Bob 认领整张蓝图，并计划优先使用自己持有的稀有材料。 |
| 12.6–125.1s | Bob 的第一次 `!newAction` 执行；完成记录显示耗时 112.5s（[完成行](../../out/trial_106/trace/bob.trace.jsonl#L14)） | 约 98.4s 达 10%；103.8s 达 20%；110.0s 达约 31%；115.8s 达约 40% | Bob 的执行窗从其承诺发出时开始，并与 Andy 后续执行窗重叠。不能把窗口内全部方块都自动归给 Bob。 |
| 22.9s | Andy 再次检查蓝图（`andy:6–7`） | 0% | Andy 尚未进入大规模放置。 |
| 25.7s | 自动 `!startConversation` 使用了 `[object Object]`，返回 `is not a bot`（[原文](../../out/trial_106/trace/andy.trace.jsonl#L8)） | 0% | 这次自动会话没有建立有效同伴沟通。全轮没有定向同伴消息。 |
| 41.1s | Andy 发出长承诺：只用库存中的 granite/andesite/diorite/stone/stone_bricks，明确跳过缺少的 gold/quartz/glowstone（[原文](../../out/trial_106/trace/andy.trace.jsonl#L10)） | 0% | Andy 的语言范围仍覆盖蓝图，但材料范围与 Bob 不同，形成可观察的材料互补。 |
| 41.1–155.3s | Andy 的第一次 `!newAction` 执行；库存从整套石材逐步降到少量余料（`andy:11–25`） | 122.4s 达约 51%；127.4s 达约 60%；139.4s 达约 70%；148.4s 达约 80% | 这是全轮主要建造阶段。库存消耗与世界得分同步上升。 |
| 128.1–139.5s | Bob 检查蓝图、查看库存，再承诺补剩余材料（`bob:15–19`） | 约 60%→70% | Bob 此时仍有 9 gold、7 quartz、2 quartz_pillar；开始第二次补缺行动。 |
| 139.5–265.8s | Bob 第二次长 `!newAction` 执行 126.3s（`bob:19–24`） | 255.7s 达约 90.5%；265.8s 达约 98.8% | Bob 的稀有材料在这一阶段基本消耗完；最后库存只剩工具和 1 dirt。 |
| 155.3–165.6s | Andy 第一轮完成后检查蓝图，并声明先补自己手里的精确坐标，再寻找 gold/quartz（`andy:25–28`） | 155.0s 约 85.1%；165.6s 约 85.7% | 初次大规模放置结束后，任务进入逐点补缺。 |
| 165.6–215.5s | Andy 第二次 `!newAction` 执行 50.0s（`andy:28–31`） | 进度升至约 88.1% | Andy 消耗最后的 granite、diorite，并留下 1 stone、1 stone_bricks。 |
| 218.6–229.6s | Andy 再次检查并提出寻找剩余 gold/quartz/pillar（`andy:32–34`） | 得分保持约 88.1% | 语言计划更新，但这一小段没有明显得分增长。 |
| 269.2s | Bob 运行蓝图检查：Level 0、3、4 完成；Level 1 缺 1 个 stone_bricks，Level 2 缺 1 个 stone（[原文](../../out/trial_106/trace/bob.trace.jsonl#L26)） | 98.81% | 此时只剩两个普通石材位置。 |
| 277.4s | Bob 承诺只修最后两个方块，并明确不破坏完成区域（[原文](../../out/trial_106/trace/bob.trace.jsonl#L30)） | 98.81% | 最后一条 `!newAction` 的 cmd 完成行没有来得及写入 trace。 |
| 294.5–294.8s | 得分先记录 99.40%，随后到 100%；run log 标记 `Task successful`（[最后得分行](../../out/trial_106/trace/scores.tsv#L1957)） | 100% | 任务完成。 |

### 库存流向

Andy 的石材库存从完整配额持续下降：在约 90–155 秒的 14 个快照中，polished_andesite、polished_diorite、stone 和 stone_bricks 几乎连续减少（`andy:11–24`）。到 205.1 秒，只剩工具、1 stone 和 1 stone_bricks（`andy:30`）。

Bob 的稀有材料主要分两段消耗：约 100–125 秒使用 gold/quartz/glowstone；约 255–270 秒使用剩余 gold/quartz 和 2 个 quartz_pillar（`bob:8–13,21–27`）。没有观察到 Andy↔Bob 的确认交接。

### 世界变化和归因

- 蓝图相关世界变化中，只有 33.3% 满足严格 Agent 归因条件。
- 在能够归因的正确放置中，Andy 32、Bob 32。
- 另有 128 个蓝图相关事件不能安全归因，因此 32:32 是“可确认部分的平衡”，不是对全部劳动的精确拆分。
- 全轮没有观察到“正确方块后来变错”的序列，也就没有修复事件。

按 60 秒窗口看，可归因正确放置为：

| 时间窗 | Andy | Bob |
|---|---:|---:|
| 60–120s | 22 | 12 |
| 120–180s | 2 | 12 |
| 180–240s | 1 | 2 |
| 240–300s | 7 | 6 |

这说明 32:32 不是两人始终同步各放一半，而是不同阶段的贡献相加后达到平衡。

### `trial_106` 的最小结论

**观察事实**：两人没有有效定向对话；两条长执行窗口大量重叠；初始材料互补；可归因正确放置最终为 32:32；没有正确状态丢失；约 295 秒完成。

**合理解释**：这轮表现出较平衡的并行执行，但平衡主要由材料配置和行动结果支持，不能据此证明两名 Agent 建立了共享的角色模型。

---

## 二、`trial_162`：资源耗尽、长平台、求助与策略升级

### 初始状态

- 任务：`pyr_2a_d33`，同一张 168 块蓝图，但属于 33% 资源缺口条件。
- Andy 初始库存：1 polished_granite、18 polished_andesite、12 polished_diorite、12 stone、22 stone_bricks，以及工具（[原始行](../../out/trial_162/trace/andy.trace.jsonl#L3)）。
- Bob 初始库存仍为 27 gold_block、16 quartz_block、2 quartz_pillar、3 glowstone，以及工具（[原始行](../../out/trial_162/trace/bob.trace.jsonl#L3)）。
- 初始石材不足意味着完成任务需要额外采集、复用或改变执行方式。

### 按时间排序的过程

| 时间 | 原始事件 | 同期世界/进度 | 只基于证据的说明 |
|---:|---|---|---|
| 0.0–1.0s | 两人 trace 启动并收到共同 `!goal`（`andy:1–2`; `bob:1–2`） | 0% | 与 `trial_106` 相同，共同目标不是分工。 |
| 5.6–7.4s | Andy、Bob 分别检查蓝图（`andy:4–5`; `bob:4–5`） | 0% | 两人都读取需求。 |
| 13.1s | Bob：`"I’ll build it now"`，承诺完整建造、采集缺料、逐层检查（[原文](../../out/trial_162/trace/bob.trace.jsonl#L6)） | 0% | Bob 首先认领全任务。 |
| 13.1–81.3s | Bob 第一轮 `!newAction` 执行 68.2s（`bob:6–11`） | 81.3s 约 8.9% | Bob 使用一部分 gold/quartz，但没有完成全任务。 |
| 25.8s | 自动 `!startConversation` 再次因 `[object Object]` 失败（`andy:9`） | 0% | 初始阶段仍没有有效对话。 |
| 31.6s | Andy 承诺完整建造，先放自己的石材，再寻找 gold/quartz/glowstone（[原文](../../out/trial_162/trace/andy.trace.jsonl#L11)） | 0% | 两人的任务范围发生重叠。 |
| 31.6–131.8s | Andy 第一轮 `!newAction` 执行 100.1s；石材库存连续下降（`andy:11–22`） | 82.7s 达约 10%；94.2s 达约 20%；105.8s 达约 30%；116.4s 达约 40%；129.8s 达 47.62%，131.8s 行动结束 | 主要初始进度来自两条重叠执行窗。 |
| 97.9s | Bob 说“Need more materials”，启动不作弊的采集/补缺计划（`bob:15`） | 24.4% | Bob 已识别缺料问题。 |
| 97.9–236.8s | Bob 的第二轮采集/补缺计划执行 138.9s（`bob:15–17`） | 仍为 47.62% | Bob 也执行了长计划，但得分没有前进。 |
| 131.8–138.4s | Andy 第一轮结束；随后提出从蓝图外采集所有缺料（`andy:22–23`） | 47.62% | Andy 的初始常用石材已经耗尽。 |
| 138.4–210.4s | Andy 的采集/补缺 `!newAction` 执行 72.0s（`andy:23–24`） | 始终 47.62% | 有动作执行记录，但没有得分增长。 |
| 210.4–226.4s | Andy 检查蓝图和库存；库存只剩三件工具（`andy:25–28`） | 47.62% | 资源阻塞变得直接可见。 |
| 236.7s | Andy 首次有效向 Bob 求助：`"can you help gather/place the missing gold, quartz, glowstone, and stone blocks"`（[原文](../../out/trial_162/trace/andy.trace.jsonl#L29)） | 47.62% | 从各自执行转为显式请求同伴帮助。 |
| 244.3s | Bob 回复：`"On it, andy — I’m handling the missing blocks now"`（[原文](../../out/trial_162/trace/bob.trace.jsonl#L18)） | 47.62% | 这是可观察的响应，但不能仅凭语言视为任务已经推进。 |
| 254.6s | Bob 声称“Almost there”，发出覆盖剩余层的长 `!newAction`（`bob:20`） | 47.62% | Bob 的 cmd 完成行未出现在 trace；得分继续不变，所以“Almost there”没有得到同期世界进度支持。 |
| 264.0s | Andy 回复“Thanks bob, I’ll verify after your pass”并检查蓝图（`andy:31–32`） | 47.62% | 检查结果仍显示大量缺块；语言上的接棒没有解除阻塞。 |
| 292.1–304.2s | Andy 将策略升级为“normal placement 不行则 direct world/block placement”，但这一轮生成代码只检查可用 API（`andy:33–34`） | 47.62% | 计划发生明显变化，第一次尝试没有带来得分增长。 |
| 304.2–377.1s | 没有新得分 | 47.62% 平台 | 从 129.8s 首次到达 47.62% 算起，直到策略改变已约 247 秒没有正向进度。 |
| 377.1s | Andy 明确提出用 Minecraft chat commands / `/setblock` 完成精确坐标（[原文](../../out/trial_162/trace/andy.trace.jsonl#L35)） | 47.62% | 这是第二次、更具体的策略升级。这里只能确认声明和后续执行窗，不能假定每个方块都由 `/setblock` 完成。 |
| 377.1–477.5s | Andy 的策略升级 `!newAction` 执行 100.4s（`andy:35–36`） | 467.6s 达 50%；469.8s 达 60%；471.8s 达 70%；473.8s 达 80%；475.8s 达 90%；477.5s 达 97.62% | 在该执行窗内，世界进度集中跃升；从 466.8s 起，世界聊天连续记录 Andy 的精确坐标变更反馈（[首条示例](../../out/trial_162/trace/world_events.jsonl#L2851)，[顶层示例](../../out/trial_162/trace/world_events.jsonl#L3041)）。420–480s 有 70 个正确放置满足统一归因规则。 |
| 380.0s | 正确的 stone_bricks `(-341,64,251)` 变为 air（[世界事件](../../out/trial_162/trace/world_events.jsonl#L2612)） | 47.62%→47.02% | 最近姿态候选为 Bob，归因置信度仅 0.60；不能视为确定执行者。 |
| 389.8s | 正确的 quartz_block `(-339,64,251)` 变为 air（[世界事件](../../out/trial_162/trace/world_events.jsonl#L2666)） | 47.02%→46.43% | 同样只有 0.60 的 Bob 候选归因。第二处正确状态丢失。 |
| 480.6s | Andy 检查蓝图：Level 1–4 完成，Level 0 只缺前面丢失的 stone_bricks 和 quartz_block（[原文](../../out/trial_162/trace/andy.trace.jsonl#L38)） | 98.81% | 最后两个缺块正好对应 380/390s 丢失的两个位置。 |
| 484.2s | Andy 发出“只修最后两个方块”的承诺（`andy:39`） | 98.81% | 最后一次 cmd 完成行没有来得及写入 trace。 |
| 506.1s | Andy 的世界聊天先报告精确坐标变更（[消息](../../out/trial_162/trace/world_events.jsonl#L3093)），34ms 后 `(-341,64,251)` 恢复为 stone_bricks（[方块事件](../../out/trial_162/trace/world_events.jsonl#L3094)） | 约 99% | 距离丢失约 126.1s。消息与方块事件高度对齐，支持 Andy 发起直接修改；但日志没有独立的 command-executor ID。 |
| 506.2s | Andy 再次报告精确坐标变更（[消息](../../out/trial_162/trace/world_events.jsonl#L3095)），11ms 后 `(-339,64,251)` 恢复为 quartz_block（[方块事件](../../out/trial_162/trace/world_events.jsonl#L3096)） | 随后到 100% | 距离丢失约 116.4s。单看位置会把附近的 Bob 列为 0.60 候选，但消息—事件配对更支持 Andy 的直接修改；仍保留日志链路限制。 |
| 507.0s | run log 标记 `Task successful`（[最后得分行](../../out/trial_162/trace/scores.tsv#L3372)） | 100% | 任务完成。 |

### 进度分成了三个阶段

1. **0–130s：初始库存快速转化为 47.62% 进度。** Bob 使用部分稀有材料，Andy 用完其初始常用石材。
2. **130–377s：约 247 秒没有正向进度。** 两人都执行采集/补缺计划；Andy 的库存已经只剩工具；236.7s 后开始显式求助，但世界进度没有变化。
3. **377–507s：策略升级、集中补齐和修复。** Andy 的长执行窗内得分由 47.62% 升到 97.62%；期间两个正确位置丢失；最后恢复这两处后到 100%。

### 库存流向

Andy 的常用石材在约 85–130 秒持续减少，到 130.0 秒全部耗尽，只剩工具（`andy:12–21`）。之后没有观察到队友向 Andy 的确认交接。

Bob 在约 70–85 秒使用 11 gold_block 和 4 quartz_block，之后长期保留 16 gold、12 quartz、2 pillar、3 glowstone。到约 385–405 秒，他获得少量 stone_bricks、cobblestone、dirt，quartz 还增加 1（`bob:21–24`）。这些库存变化可能来自环境采集或掉落物，轨迹中没有确认的 Agent 间交接。

### 世界变化和归因

- 蓝图相关世界变化的严格归因覆盖率为 66.3%，高于 `trial_106`，但仍有约三分之一不能归因。
- 在能够归因的正确放置中，Andy 110、Bob 18。
- Andy 的 110 个可归因放置中，有 70 个集中在 420–480 秒；因此“Andy 主导”主要来自后期集中补齐，而不是从开局到结束始终保持同一比例。
- 两个正确状态丢失都得到恢复，最终未留下未修复位置。

这里的 110:18 采用统一分析中的“3 秒内姿态、5.5 格距离及唯一邻近者”规则，便于跨 trial 比较；它不读取 Minecraft 的命令反馈。因而下表把 480–540 秒的一次恢复机械地列给 Bob，而原始世界聊天在两次恢复前都记录了 Andy 的精确坐标变更。两类证据发生冲突时，本文保留统一统计，同时在上面的事件级时间线中展示更强的消息—方块配对证据。

按 60 秒窗口看，可归因正确放置为：

| 时间窗 | Andy | Bob |
|---|---:|---:|
| 60–120s | 38 | 13 |
| 120–180s | 2 | 4 |
| 180–420s | 0 | 0 |
| 420–480s | 70 | 0 |
| 480–540s | 0 | 1 |

### `trial_162` 的最小结论

**观察事实**：两人早期都认领全任务；初始材料用尽后约 247 秒没有正向进度；Andy 求助后有 7 条定向消息，但同期进度没有立刻恢复；Andy 后来升级执行策略，进度集中跃升；两个正确位置一度丢失并在结束前恢复；约 507 秒完成。

**合理解释**：这轮不是简单的“一人从头包办”。更准确的描述是：前期多人投入，资源耗尽后长时间阻塞，随后由 Andy 主导后期补齐，并通过最后的状态恢复完成任务。

---

## 三、把两轮放在同一条对照线上

| 维度 | `trial_106` | `trial_162` |
|---|---|---|
| 资源条件 | 0% 缺口 | 33% 缺口 |
| 首个实质承诺 | Bob，12.6s | Bob，13.1s |
| 有效定向消息 | 0 | 7 |
| 主要进度形态 | 约 98–148s 连续升至 80%，后期补尾 | 约 130–377s 没有正向进度，后期集中跃升 |
| 确认的物品交接 | 0 | 0 |
| 可归因正确放置 | Andy 32 / Bob 32 | Andy 110 / Bob 18 |
| 方块归因覆盖 | 33.3% | 66.3% |
| 正确状态丢失 | 0 | 2 |
| 恢复 | 不适用 | 2/2 均恢复 |
| 完成时间 | 294.8s | 507.0s |
| 最终分数 | 100 | 100 |

### 这份原始过程支持什么

1. 两轮相同的 100 分确实掩盖了不同的工作分布、进度形状和异常史。
2. `trial_106` 的 32:32 来自不同阶段贡献的累计，不代表逐时平均协作。
3. `trial_162` 的 110:18 主要由后期集中补齐形成，不代表 Bob 全程没有工作。
4. 更多定向消息没有对应更快完成；但两轮资源条件不同，不能据此推断“沟通使任务变慢”。
5. `trial_162` 的最终成功包含一次可观察的恢复过程；只看最终 100 分会看不到这 116–126 秒的状态损伤。

### 这份原始过程不支持什么

- 不能说 `trial_106` 的团队“天然更会合作”；它面对的是无缺口条件。
- 不能说 `trial_162` 的所有 110 个方块都由正常生存采集完成；后期计划明确包含直接放置 fallback，日志只能说明执行窗与得分跃升对齐。
- 不能把两次方块丢失确定归因给 Bob；0.60 只代表最近姿态候选，不是执行者真值。
- 不能把零消息解释成零协调，也不能把 7 条消息解释成更高合作质量。

## 四、原始文件索引

### `trial_106`

- [meta.json](../../out/trial_106/trace/meta.json)
- [Andy trace](../../out/trial_106/trace/andy.trace.jsonl)
- [Bob trace](../../out/trial_106/trace/bob.trace.jsonl)
- [world events](../../out/trial_106/trace/world_events.jsonl)
- [scores.tsv](../../out/trial_106/trace/scores.tsv)
- [完整 prompts 目录](../../out/trial_106/trace/prompts)
- [完整运行日志 run.log.gz](../../out/trial_106/run.log.gz)

### `trial_162`

- [meta.json](../../out/trial_162/trace/meta.json)
- [Andy trace](../../out/trial_162/trace/andy.trace.jsonl)
- [Bob trace](../../out/trial_162/trace/bob.trace.jsonl)
- [world events](../../out/trial_162/trace/world_events.jsonl)
- [scores.tsv](../../out/trial_162/trace/scores.tsv)
- [完整 prompts 目录](../../out/trial_162/trace/prompts)
- [完整运行日志 run.log.gz](../../out/trial_162/run.log.gz)

为了复核本文中的衍生数字，还可查看[统一事件流](derived/unified_events.jsonl)、[过程指标](derived/trial_process_metrics.jsonl)和[现象证据](derived/trial_phenomena.jsonl)。
