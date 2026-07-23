# Offline Critic Test: trial_106 and trial_162

测试日期：2026-07-22

## 范围

- 模型：`gpt-5.6-sol`
- reasoning effort：`high`
- 调用链：仓库现有 `selectAPI -> createModel -> GPT.sendRequest -> chat.completions`
- 触发策略：每 90 秒或 8 条 `chat_out`，先到者触发；每轮额外保留一个终局审计窗口
- 输入边界：只使用各窗口 cutoff 之前的 critic evidence packet
- 结果：10/10 调用成功，全部通过 JSON Schema、窗口身份和 advisory 一致性校验

原始结果：

- `derived/trial_106_results.jsonl`
- `derived/trial_162_results.jsonl`

## 模型输出时间线

| Trial | Cutoff | Verdict | Confidence | Send | 建议摘要 |
|---|---:|---|---:|---|---|
| 106 | 90s | `imbalance_detected` | 0.66 | yes | Andy 负责普通石材，Bob 负责金/石英/萤石 |
| 106 | 180s | `imbalance_detected` | 0.82 | yes | 按库存拆分剩余修补范围 |
| 106 | 270s | `imbalance_detected` | 0.78 | yes | Andy 修最后两块，Bob 停止宽范围采集/放置 |
| 106 | 294.772s | `no_imbalance_observed` | 0.88 | no | 终局已完成，无当前可行动问题 |
| 162 | 90s | `no_imbalance_observed` | 0.88 | no | 两人早期按材料互补推进 |
| 162 | 180s | `imbalance_detected` | 0.78 | yes | Bob 处理仍持有的稀有材料，Andy 留在石材和复查 |
| 162 | 270s | `no_imbalance_observed` | 0.76 | no | Bob 执行补缺、Andy 等待验收，暂视为合理串行交接 |
| 162 | 360s | `imbalance_detected` | 0.74 | yes | 确认 Bob 收到交接并立即处理库存材料 |
| 162 | 450s | `imbalance_detected` | 0.78 | yes | Andy、Bob 各接一半坐标后统一复查 |
| 162 | 507.022s | `no_imbalance_observed` | 0.84 | no | 终局已完成，无当前可行动问题 |

## 对照审计

### trial_106：明显过度报警

独立时间线显示，这轮的初始库存天然互补：Andy 主要消耗普通石材，Bob 主要消耗金、石英和萤石；进度持续上升，没有正确状态损失，可确认的正确放置最终为 Andy 32、Bob 32。

critic 却在三个可干预窗口全部报警。90 秒窗口主要依据是两人的语言计划都覆盖整张蓝图；但同一窗口也显示 Andy 明确跳过稀有材料，且动作归因覆盖率只有 2/27。180 秒窗口已经观察到两人分别消耗互补材料并共同带来进度，仍把宽泛计划描述为 `duplicated_scope`。270 秒时只剩两个普通石材位置、Bob 刚完成大量稀有材料放置且进度仍在上升，critic 仍建议 Bob 停止。

按当前证据纪律，这三次都不应仅凭“双方认领完整任务”触发干预。它们是本次测试中最明确的 false-positive 风险：critic 识别了可以显式化的角色边界，但把“可优化的隐式分工”升级成了“正在发生的失衡”。

### trial_162：发现了平台期，但部分理由和建议不可靠

这轮前 90 秒判断为互补推进，与时间线一致。首次报警出现在 180 秒，距最后一次正向进度约 50 秒；它正确看到 Andy 已耗尽普通石材、Bob 仍持有稀有材料以及团队开始停滞，因此具备早期预警价值。

但 180 秒输出把 Bob 描述为近似空闲并不成立。Bob 在 97.9--236.8 秒执行一个长 `!newAction`；由于 `cmd` 事件只在动作完成后落盘，180 秒 evidence packet 只能看到 97.9 秒的 `chat_out` 意图，看不到“动作仍在运行”。更准确的判断应是“长动作持续但没有世界进度”，而不是“空闲”。

270 秒时，critic 认为刚发生约 33 秒的串行交接尚不足以判失败，这一保守判断合理。360 秒时得分仍停在 47.62%，critic 检出 `failed_handoff`，与独立时间线一致。不过它仍建议延续 Bob 放稀有材料、Andy 检查的原策略，没有明确建议升级缺失普通石材的获取或直接放置策略。

450 秒窗口正确注意到约 320 秒没有正向进度且发生了两处未归因的正确状态丢失，但错误地写成“Andy 把 `/setblock` 任务全部交给 Bob”。实际 `trace/andy.trace.jsonl:35-36` 是 Andy 自己在 377.1--477.5 秒执行本地长动作。终局窗口又把 Andy 的最后两块修复命令写成对 Bob 的任务分配；最终“不发送建议”是对的，但过程解释错误。

## 已确认的两个数据语义问题

### 1. 会话接收者不等于命令执行者

进入 Agent 间会话后，Andy 的出口文本会显示 `(To bob) ...`。代码中整段回复会通过 `sendToBot` 发给 Bob，但同一回复中的命令随后仍由 Andy 调用 `executeCommand(this, res)` 本地执行。因此：

- `(To bob)` 是会话路由信息；
- `trace/andy.trace.jsonl` 中的 `!newAction` 仍是 Andy 的本地动作；
- critic 不能从 `(To bob) !newAction(...)` 推断 Andy 把动作委派给 Bob。

相关实现位于 `src/agent/agent.js` 的响应路由和本地 `executeCommand` 调用，以及 `src/agent/conversation.js` 的 `sendToBot`。

### 2. 长动作在完成前不可见

`executeCommand` 在 `await command.perform(...)` 返回后才写入带 `ms` 的 `cmd` 事件。离线截断到动作执行中间时，只能看到较早的 `chat_out`，看不到一个明确的 `active_command`。这会把“正在执行但尚无进展”误判为“没有行动”。

## 下一版建议

1. 在 evidence packet 中把 `chat_out` 拆成 `recipient`、自然语言消息和 `local_command_intent`；本地命令的 owner 固定取 trace 所属 Agent，不从 `(To X)` 推断。
2. 为 runner trace 增加 `cmd_start`/`cmd_end`，或在离线构包时将尚未配对到完成事件的 `chat_out` 命令标记为 `active_or_unresolved_command`，但不得使用 cutoff 之后才知道的结果和持续时间。
3. 收紧 `duplicated_scope`：只有观察到同一坐标/资源竞争、重复采集、返工、状态损失或进度损害时才允许报警；宽泛承诺重叠只能作为监控信号。
4. advisory 必须检查库存和正在运行的动作。不能让只剩工具的 Andy “继续石材工作”，也不能把 Andy 正在执行的直接放置动作写成 Bob 的任务。
5. 修正证据包后重跑这 10 个窗口。最低验收目标是：`trial_106` 不再因计划范围本身连续报警；`trial_162` 仍能在平台期给出预警，但将“空闲”改为“长动作无可观察进展”，并正确识别 Andy 的后期接管和修复。

## 结论

本次测试证明模型接口和结构化输出链路稳定，也证明 critic 对长平台、未解除交接和资源错配有发现能力。但当前版本还不能直接接入上级 Agent 自动发建议：`trial_106` 暴露了较强的过度干预倾向，`trial_162` 暴露了消息路由与动作归属误读。在修正这两类输入语义前，建议只作为离线审计器使用。
