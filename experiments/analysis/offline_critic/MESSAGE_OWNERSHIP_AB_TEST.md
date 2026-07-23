# Message Ownership A/B Test

测试日期：2026-07-22

## 唯一改动

本轮只修改消息路由和本地命令所有权的表达，不修改触发窗口、失衡定义、报警门槛、库存/得分/世界事件摘要、输出 schema 或 advisory 规则。

原来的 `message_timeline` 把整条出口文本放在一个 `text` 字段中。v2 将其拆为：

- `sender`：产生这条输出的 Agent；
- `message_recipient`：消息路由给谁；
- `message_text`：去掉路由前缀和本地命令后的自然语言部分；
- `local_command`：该输出中嵌入的本地命令名；
- `local_command_text`：本地命令调用文本；
- `command_executor`：执行本地命令的 Agent，固定为 trace 所属的 sender。

prompt 只增加一条对应说明：`message_recipient` 是消息受众，不是动作执行者；不得仅凭 recipient 推断任务委派。

## 控制检查

- 基线和 v2 的 10 个窗口具有完全相同的 trial、起止时间、触发原因和消息数量。
- v2 的消息、任务声明、命令和库存证据仍全部位于 cutoff 之前，0 个因果边界违规。
- 单元测试从 7 个增至 9 个，新增直接路由字段和命令执行者拆分测试。
- 两轮 v2 模型调用均使用 `gpt-5.6-sol`、reasoning effort `high` 和同一模型接口，10/10 返回成功。
- 基线结果和 v2 结果分别保存，没有互相覆盖。

## 逐窗结果

| Window | Baseline | Ownership v2 | Send 变化 |
|---|---|---|---|
| `trial_106_w001` | imbalance, 0.66 | imbalance, 0.82 | yes -> yes |
| `trial_106_w002` | imbalance, 0.82 | imbalance, 0.84 | yes -> yes |
| `trial_106_w003` | imbalance, 0.78 | imbalance, 0.82 | yes -> yes |
| `trial_106_w004` | no imbalance, 0.88 | no imbalance, 0.90 | no -> no |
| `trial_162_w001` | no imbalance, 0.88 | no imbalance, 0.88 | no -> no |
| `trial_162_w002` | imbalance, 0.78 | imbalance, 0.82 | yes -> yes |
| `trial_162_w003` | no imbalance, 0.76 | imbalance, 0.76 | no -> yes |
| `trial_162_w004` | imbalance, 0.74 | imbalance, 0.76 | yes -> yes |
| `trial_162_w005` | imbalance, 0.78 | unknown, 0.72 | yes -> no |
| `trial_162_w006` | no imbalance, 0.84 | no imbalance, 0.92 | no -> no |

## 目标问题是否修复

修复有效。

在 `trial_162_w005`，基线错误声称 Andy 把 `/setblock` 工作交给 Bob，并据此建议重新分工。v2 正确写成：

> Andy locally adopted responsibility for placing every remaining blueprint block via setblock.

它将 verdict 从 `imbalance_detected` 改为 `unknown`，不再向上级发送建立在错误执行者归属上的建议。

在 `trial_162_w006`，基线把最后两块写成 Andy 分配给 Bob；v2 正确识别为 Andy 自己发起两块修复动作，并将 Andy 描述为处理了集中收尾和验证。终局仍然不发送建议。

因此，结构化区分 recipient 和 executor 直接消除了已知的两处动作所有权误读。

## 没有改善的部分

`trial_106` 的三个可干预窗口仍然全部报警，且置信度没有下降。这符合控制变量预期：这些误报来自 critic 把“宽泛计划重叠”当成实际冲突，和消息发给谁无关。要解决它必须单独调整报警证据门槛，本轮没有这样做。

`trial_162_w002` 仍把 Bob 评为 underloaded。Bob 当时正在执行一个直到 236.8 秒才完成记录的长动作，而 180 秒 packet 仍看不到明确的 active command。这属于 `cmd_start/cmd_end` 可见性问题，本轮也没有修改。

## 新变化与边界

`trial_162_w003` 从不报警变成报警，理由是 Andy 在交接后只等待验证，而 Bob 承担全部采集和建造。这个建议可能有管理价值，但一次模型重跑不足以证明它由 ownership 字段导致，也不能证明它稳定正确。当前接口没有为这组运行固定随机种子，所以除已直接核对文本归属的 w005/w006 外，其他 verdict 差异都应视为单次样本波动，需重复运行或人工标注后判断。

## 结论

第一项优化达到了窄目标：critic 现在能正确区分“消息发给 Bob”和“命令由 Andy 执行”。它修复了 `trial_162` 后期的动作归属与错误建议，但没有降低 `trial_106` 的范围重叠误报，也没有解决长动作被视为空闲的问题。应保留这一改动；下一项优化继续单独实验，不与本轮结果混合。

## 产物

- v2 窗口：`derived/trial_106_windows_message_ownership_v2.jsonl`
- v2 窗口：`derived/trial_162_windows_message_ownership_v2.jsonl`
- v2 结果：`derived/trial_106_results_message_ownership_v2.jsonl`
- v2 结果：`derived/trial_162_results_message_ownership_v2.jsonl`
- 基线结果：`derived/trial_106_results.jsonl`
- 基线结果：`derived/trial_162_results.jsonl`
