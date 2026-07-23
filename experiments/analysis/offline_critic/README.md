# Offline Coordination Critic

这个原型先回答一个窄问题：在 `trial_101-300` 的某个因果截面上，只看当时已经出现的执行者消息和可观察行动，critic 能否发现值得上级 Agent 介入的分工失衡，并给出一句低风险建议。

它不把“工作量相等”当作目标。合理的材料分工、阶段性串行、交接等待都可能造成贡献不均；只有当不均衡伴随可行动的问题，例如重复范围、空闲者未分担、依赖未解除、交接失败或角色与行动错位时，才建议介入。

## 结构

- `build_windows.py`：从已有 `open_world_coordination/derived/unified_events.jsonl` 构造无未来泄漏的证据包。
- `critic_prompt.md`：critic 的角色、最小判断标准和证据纪律。
- `critic_output.schema.json`：固定输出契约。
- `critic_model_profile.json`：critic 独立模型配置，不保存 key；固定 `gpt-5.6-sol` 和 `reasoning.effort=high`。
- `model_bridge.mjs`：复用项目的 `selectAPI/createModel/GPT.sendRequest`，走与 Andy/Bob 相同的自定义 URL `chat.completions` 接口。
- `run_critic.py`：组织批次、把 JSON Schema 放入 prompt，并在本地严格校验模型返回值。
- `PILOT_STATUS.md`：当前小样本调用状态及尚不能下结论的边界。
- `TRIAL_106_162_TEST.md`：两个完整案例的逐窗测试、对照审计和已发现的数据语义问题。
- `MESSAGE_OWNERSHIP_AB_TEST.md`：只修改消息接收者/命令执行者语义后的单变量 A/B 结果。
- `tests/`：触发边界、未来泄漏和低置信度归因测试。

原始轨迹保持只读；生成结果只写入本目录的 `derived/`。

## 触发设计

支持三种策略：

- `time`：每隔固定秒数审查一次，即使团队安静也会触发。
- `messages`：累计固定数量的 `chat_out` 后审查，适合对话密集阶段，但安静失速可能永远不触发。
- `hybrid`：时间或消息阈值先到者触发。初始默认值是 90 秒或 8 条消息。

默认值只是 pilot 起点，不是研究结论。需要在同一批人工标注窗口上比较例如 `60/90/120s` 和 `6/8/12 messages`，重点看可行动问题的发现提前量、误报和调用成本。

每轮的最后一个不足窗口仍会以 `trial_end` 输出，便于离线审计；它不能被计作可实时干预的成功发现。

## 证据包

每个窗口包含：

- 交错排列的执行者消息及 `source_file:line`；
- 每个 Agent 截止当时最近的任务声明、初始/最近库存、窗口内命令与结果、库存净变化；
- construction 中保守归因的正确放置、修复、正确状态损失等；
- 压缩后的窗口起止得分和距最近进度增长的时间；
- 归因覆盖率与明确的不确定性说明。

critic 看不到 cutoff 之后的事件，也不读取带终局状态的承诺账本或事后现象标签。消息和命令中的文本只作为被观察材料，不能成为对 critic 的指令。

## 使用

先构造全部 200 轮证据包，不调用模型：

```bash
python3 experiments/analysis/offline_critic/build_windows.py
```

只构造少量 trial 或替换触发策略：

```bash
python3 experiments/analysis/offline_critic/build_windows.py \
  --start 106 --end 106 --trigger hybrid --time-interval-s 90 --message-count 8 \
  --output /tmp/trial_106_critic_windows.jsonl
```

先检查模型调用配置，不实际请求模型：

```bash
python3 experiments/analysis/offline_critic/run_critic.py \
  --input /tmp/trial_106_critic_windows.jsonl --max-windows 1 --dry-run
```

运行一个有上限的 pilot：

```bash
python3 experiments/analysis/offline_critic/run_critic.py \
  --input /tmp/trial_106_critic_windows.jsonl \
  --output /tmp/trial_106_critic_results.jsonl --max-windows 3
```

runner 默认要求 `--max-windows`；只有显式传入 `--all` 才允许跑完选中窗口。`--resume` 会跳过结果文件中已经成功的 `critic_id`。
可以重复传入 `--trial trial_114` 筛选整轮，或用 `--critic-id trial_114_w002` 精确选择窗口。

## 如何验证“能不能发现”

离线阶段只能验证检测与建议质量，不能验证建议实施后的因果效果。建议分四步：

1. 从 construction/crafting、早中晚窗口、已知失调/互补/unknown 中分层抽样；给标注者的材料同样截断到 cutoff。
2. 标注“此刻是否存在可行动的分工失衡”、最低风险干预和证据；不把事后成败倒灌到标注。
3. 报告 actionable precision/recall、对合理专门化的误报率、`unknown` 比例、证据引用准确率、首次发现提前量和每轮调用次数。
4. 只有离线 precision 足够高后，再做新的随机对照实验：同一任务条件下比较 `critic advice delivered` 与 `advice withheld`。历史 `trial_101-300` 没有真实 commander，不能用来声称干预有效。

已知现象标签只用于运行后审计，不进入 critic 输入。例如可用 `trial_114` 的互补分工窗口检查误报，用 `trial_115/120/162` 的单 Agent 执行集中窗口检查发现能力，再用 crafting 的交接成功与失败窗口检查是否能区分正常串行和阻塞。
