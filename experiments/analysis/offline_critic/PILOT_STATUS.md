# Offline Critic Pilot Status (2026-07-22)

## 已完成

- 对 `trial_101-300` 全量构包：200 轮、1,084 个窗口；其中 884 个是终局前可干预窗口。
- 触发来源：716 个 `time_interval`、168 个 `message_count`、200 个 `trial_end`。
- 因果边界审计：消息、任务声明、命令和库存变化均未越过各自 cutoff；0 个违规。
- 参与者覆盖：907 个双 Agent 窗口，177 个三 Agent 窗口。
- 单元测试：9 个通过，覆盖 hybrid 触发、安静窗口、未来泄漏、低置信度归因、首窗 score 压缩、schema、建议字段一致性，以及消息接收者/本地命令执行者拆分。

## 模型 pilot

按对照用途选取了三个窗口，但不把事后标签放入 critic 输入：

- `trial_114_w002`：用于检查对互补执行的误报；
- `trial_115_w002`：用于检查执行集中能否被发现；
- `trial_201_w001`：用于检查正常 crafting 交接是否被误判。

三次正式调用均固定为 `gpt-5.6-sol`、reasoning effort `high`，并通过仓库现有的 `selectAPI/createModel/GPT.sendRequest` 调用链发送到自定义 URL 的 `chat.completions` 接口。三个结果都通过本地 JSON Schema、窗口身份和建议字段一致性校验：

| 窗口 | critic 结论 | 置信度 | 给上级的建议 |
|---|---|---:|---|
| `trial_114_w002` | `unknown` | 0.72 | 不发送；共同建造动作的可靠归因覆盖率只有 35.9%，现有证据更像互补材料分工，但不足以认定 Bob 空闲 |
| `trial_115_w002` | `imbalance_detected` | 0.97 | 发送；让 Bob 立即转交或放置其金块、石英柱和萤石，Andy 继续普通材料修补并复查 |
| `trial_201_w001` | `no_imbalance_observed` | 0.91 | 不发送；Andy 做工作台、Bob 交付木棍，是已完成的互补依赖交接 |

`trial_115_w002` 中的检出不是由消息数或命令数单独触发：截至 180 秒，Andy 已消耗全部常规建材并有 104 次可靠归因的正确放置；Bob 只有 1 次，同时仍持有蓝图检查所需的稀缺材料。该窗口的目标方块变化归因覆盖率是 88.2%。

更早使用 Codex CLI `/responses` 路径的六条失败记录仍保存在 `derived/pilot_results.jsonl`，用于审计接口切换原因；文件末尾三条是共享模型适配器的成功结果。

## 当前结论边界

这三个样本说明调用链和最小判断逻辑已经跑通，并展示了 critic 能区分“明显失衡”“合理互补”和“证据不足”。样本由已知现象分层选择，不能据此报告 precision 或 recall。下一步仍需对截断窗口做盲态人工标注和更大规模分层抽样，再比较触发频率、误报、首次发现提前量和调用成本。

后续对 `trial_106` 和 `trial_162` 的全部 10 个窗口测试显示，接口与结构校验全部成功，但判断质量尚不适合自动向上级 Agent 下发建议：`trial_106` 出现连续过度报警，`trial_162` 暴露了 `(To bob)` 会话路由与本地命令所有权混淆，以及长动作完成前不可见的问题。完整结果和修正建议见 `TRIAL_106_162_TEST.md`。

```bash
python3 experiments/analysis/offline_critic/run_critic.py \
  --critic-id trial_114_w002 \
  --critic-id trial_115_w002 \
  --critic-id trial_201_w001 \
  --output experiments/analysis/offline_critic/derived/pilot_results.jsonl \
  --max-windows 3 --resume
```
