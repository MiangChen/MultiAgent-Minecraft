#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';


const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXED_RESULTS_ROOT = path.resolve(HERE, '../derived/timeline_106_162_v2/results');
const EVENT_RESULTS_ROOT = path.resolve(HERE, '../derived/event_lease_v1/results');
const OUTPUT = path.resolve(HERE, 'timeline_data.js');

const TRIGGER_NAMES = {
    action_closed_without_verified_progress: '行动结束，无可验证进展',
    request_verification_still_unresolved: '求助后的验证仍未解除阻塞',
    score_regression: '世界得分回退',
    terminal_review: '终局复盘',
    time_interval: '固定时间截点',
};

function readJsonl(filePath) {
    return fs.readFileSync(filePath, 'utf8')
        .split('\n')
        .filter(line => line.trim())
        .map(line => JSON.parse(line));
}

function event(time, lane, type, title, text, evidence, extra = {}) {
    return { time, lane, type, title, text, evidence, certainty: 'O', ...extra };
}

const CASES = {
    trial_106: {
        id: 'trial_106',
        title: '安静并行，随后逐点补缺',
        subtitle: '两条长执行窗在互补库存的约束下同时推进',
        duration: 294.772,
        outcome: '100 分 · 294.8 秒完成',
        condition: '2 Agents · 2a_d0 · 0% 资源缺口',
        synopsis: '两人没有形成明确语言分工，但常用石材与稀有材料分散在不同库存中，实际行动逐渐形成互补。',
        media: {
            video: '../../../out/render_trial_106/trial_106_god_2x.mp4',
            poster: '../../../out/render_trial_106/frame_middle.png',
            playbackRate: 2,
            frames: [
                { time: 0, src: '../../../out/render_trial_106/frame_start.png', label: '任务开始' },
                { time: 150, src: '../../../out/render_trial_106/frame_middle.png', label: '主要建造阶段' },
                { time: 294.772, src: '../../../out/render_trial_106/frame_final.png', label: '完成状态' },
            ],
        },
        metrics: [
            { label: '最终分数', value: '100' },
            { label: '完成时间', value: '294.8s' },
            { label: '定向消息', value: '0' },
            { label: '归因放置', value: '32 / 32' },
        ],
        phases: [
            { start: 0, end: 41.052, title: '各自认领', summary: '共同目标尚未变成明确分工。' },
            { start: 41.052, end: 155.3, title: '并行铺设', summary: '互补库存转化为两条重叠执行窗。' },
            { start: 155.3, end: 265.8, title: '逐点补缺', summary: '大规模铺设结束，双方处理剩余坐标。' },
            { start: 265.8, end: 294.772, title: '最后两块', summary: '蓝图从 98.8% 收尾至完成。' },
        ],
        storyConclusion: '这支团队没有通过聊天完成明确分工，但材料差异让两条长任务在行动层面形成互补；事件 Critic 最有价值的决定是没有打断他们。',
        fixedStoryConclusion: '固定策略在顺利推进期间两次建议介入；完整轨迹却持续接近完成，说明按百分比截点检查容易把语言范围重叠误当成需要立即重分工的问题。',
        chapters: [
            {
                id: 'shared-goal', start: 0, end: 41.052,
                title: '两人拿到同一目标，却没有真正分工',
                narrative: 'Bob 先认领整张蓝图；Andy 随后也准备处理完整目标。此时能确认的是语言范围重叠，不能确认行动冲突。',
                andy: { headline: '检查目标，尚未开始长任务', detail: '直到 41 秒才启动第一条建造行动。' },
                bob: { headline: '先认领整张蓝图', detail: '计划收集缺料并逐层完成所有坐标。' },
                relation: { kind: 'overlap', symbol: '↔', label: '计划范围重叠', detail: '共同目标还没有被拆成职责边界。', certainty: 'I' },
                world: { headline: '建筑进度仍为 0%', detail: '还没有观察到目标竞争或世界状态损害。', score: '0% → 0%' },
                managerMeaning: '先观察行动结果；仅凭两人都认领完整任务，不足以判定冲突。',
                eventIndexes: [0, 1],
                evidence: ['trace/andy.trace.jsonl:2', 'trace/bob.trace.jsonl:2', 'trace/bob.trace.jsonl:6'],
            },
            {
                id: 'material-complement', start: 41.052, end: 155.3,
                title: '库存差异把重叠计划变成了实际互补',
                narrative: 'Andy 明确跳过自己没有的稀有材料，Bob 的行动覆盖这些缺口。两人仍没有语言协议，但得分开始持续增长。',
                andy: { headline: '铺设现有普通石材', detail: '使用花岗岩、安山岩、闪长岩、石头和石砖。' },
                bob: { headline: '处理稀有材料与剩余缺口', detail: '长任务与 Andy 的执行窗重叠，但材料侧重点不同。' },
                relation: { kind: 'complementary', symbol: '⇄', label: '行动形成互补', detail: '计划重叠没有转化为可观察的资源竞争。', certainty: 'I' },
                world: { headline: '约 50 秒内由 10% 升至 85.1%', detail: '库存消耗与得分增长同步出现。', score: '0% → 85.1%' },
                managerMeaning: '可验证进度正在产生，此时打断有效执行的收益没有证据支持。',
                eventIndexes: [3, 4, 5, 6],
                evidence: ['trace/andy.trace.jsonl:10', 'trace/andy.trace.jsonl:25', 'trace/bob.trace.jsonl:16', 'trace/scores.tsv'],
            },
            {
                id: 'gap-filling', start: 155.3, end: 265.8,
                title: '大规模铺设结束，双方转入逐点补缺',
                narrative: 'Andy 用最后一批普通石材处理精确位置；Bob 的较长任务继续覆盖其他余项。旧清单风险存在，但世界进度仍在向完成靠近。',
                andy: { headline: '处理库存仍能覆盖的位置', detail: '第二轮行动在 215.5 秒结束。' },
                bob: { headline: '继续执行较长的补缺清单', detail: '行动持续到约 265.8 秒。' },
                relation: { kind: 'parallel', symbol: '∥', label: '并行补缺', detail: '有范围接近的风险，但没有观察到可归因冲突。', certainty: 'I' },
                world: { headline: '进度由 85.7% 升至 98.8%', detail: '团队没有陷入长平台，也没有出现持续状态损失。', score: '85.7% → 98.8%' },
                managerMeaning: '风险可以记录，但持续进展说明管理者不必把所有范围重叠都升级为告警。',
                eventIndexes: [7, 8],
                evidence: ['trace/andy.trace.jsonl:28', 'trace/andy.trace.jsonl:31', 'trace/bob.trace.jsonl:24', 'trace/scores.tsv'],
            },
            {
                id: 'final-two', start: 265.8, end: 294.772,
                title: 'Bob 收下最后两块，团队安静完成',
                narrative: '蓝图只剩一块石砖和一块石头。Bob 将范围缩到两个精确坐标，得分随后到达 100%。',
                andy: { headline: '没有再启动全范围行动', detail: '前一轮普通石材补缺已经结束。' },
                bob: { headline: '只处理最后两个坐标', detail: '明确要求不破坏已经完成的区域。' },
                relation: { kind: 'converging', symbol: '→', label: '工作自然收束', detail: '收尾集中到一人不自动构成工作失衡。', certainty: 'I' },
                world: { headline: '任务达到 100%', detail: 'runner 在 294.772 秒标记成功。', score: '98.8% → 100%' },
                managerMeaning: '终局复盘没有发现仍需处理的问题；Critic 的沉默是本案例的重要结果。',
                eventIndexes: [9, 10, 11],
                evidence: ['trace/bob.trace.jsonl:26', 'trace/bob.trace.jsonl:30', 'trace/scores.tsv:1957'],
            },
        ],
        progress: [
            [0, 0], [73.693, 0], [98.4, 10], [103.8, 20], [110, 31],
            [115.8, 40], [122.4, 51], [127.4, 60], [139.4, 70],
            [147.386, 79.17], [148.4, 80], [155, 85.1], [165.6, 85.7],
            [200.26, 88.1], [221.079, 88.1], [255.7, 90.5], [265.8, 98.8],
            [294.5, 99.4], [294.772, 100],
        ],
        events: [
            event(1.0, 'world', 'goal', '共同目标下达', 'Andy 与 Bob 同时收到完整蓝图目标；共同目标本身不是分工协议。', ['trace/andy.trace.jsonl:2', 'trace/bob.trace.jsonl:2']),
            event(12.59, 'bob', 'action', 'Bob 认领整张蓝图', '计划收集缺料并逐层完成全部坐标。', ['trace/bob.trace.jsonl:6', 'trace/bob.trace.jsonl:14'], { end: 125.128, command: '!newAction' }),
            event(25.711, 'world', 'system', '自动目标刷新', '一条瞬时 !goal 与 Bob 的长任务重叠；v2 按 command_id 保留外层执行状态。', ['trace/bob.trace.jsonl:7'], { compact: true }),
            event(41.052, 'andy', 'action', 'Andy 只使用现有石材', '放置花岗岩、安山岩、闪长岩、石头和石砖，明确跳过自己没有的稀有材料。', ['trace/andy.trace.jsonl:10', 'trace/andy.trace.jsonl:25'], { end: 155.264, command: '!newAction' }),
            event(98.4, 'world', 'progress', '进度开始持续增长', '约 50 秒内由 10% 上升到 80%，库存消耗与得分同步。', ['trace/scores.tsv'], { score: 10 }),
            event(128.105, 'bob', 'check', 'Bob 读取剩余缺口', '完成第一轮后重新检查蓝图，随后启动第二次补缺。', ['trace/bob.trace.jsonl:16']),
            event(139.468, 'bob', 'action', 'Bob 补齐剩余材料', '继续处理稀有材料，同时尝试获取普通石材。', ['trace/bob.trace.jsonl:19', 'trace/bob.trace.jsonl:24'], { end: 265.789, command: '!newAction' }),
            event(155.3, 'andy', 'check', 'Andy 转入逐点补缺', '检查剩余坐标并使用最后一批常用石材。', ['trace/andy.trace.jsonl:25', 'trace/andy.trace.jsonl:28']),
            event(165.575, 'andy', 'action', 'Andy 执行第二轮补缺', '完成自己库存仍能覆盖的精确位置。', ['trace/andy.trace.jsonl:28', 'trace/andy.trace.jsonl:31'], { end: 215.525, command: '!newAction' }),
            event(269.206, 'bob', 'check', '蓝图只剩两个普通石材位置', 'Level 0、3、4 已完成，只缺一块石砖和一块石头。', ['trace/bob.trace.jsonl:26']),
            event(277.398, 'bob', 'action', 'Bob 认领最后两块', '限制范围为两个精确坐标，并要求不要破坏完成区域。', ['trace/bob.trace.jsonl:30'], { end: 294.772, command: '!newAction' }),
            event(294.772, 'world', 'success', '任务完成', '得分到达 100%，runner 标记成功。', ['trace/scores.tsv:1957']),
        ],
        criticNarrative: {
            trial_106_online_t000073693: {
                summaryZh: '两条长任务都在执行，但语言范围重叠；库存已经支持按材料划分职责。',
                adviceZh: 'Andy 负责全部普通石材坐标；Bob 负责金块、石英、石英柱和萤石，并在继续前确认边界。',
                posthoc: {
                    status: 'possible_over_alert',
                    label: '可能偏早报警',
                    summary: '随后两人的库存消耗呈互补，得分持续升至 79.17%；范围风险存在，但没有证据证明此时打断优于继续观察。',
                },
            },
            trial_106_online_t000147386: {
                summaryZh: '两人都在执行，材料消耗互补，得分刚刚增长到 79.17%；暂不介入。',
                adviceZh: '',
                posthoc: {
                    status: 'supported',
                    label: '保持观察得到支持',
                    summary: '团队随后继续推进，未观察到可归因的冲突；不打断与后续进展一致。',
                },
            },
            trial_106_online_t000221079: {
                summaryZh: 'Bob 仍在执行较早的补缺清单，Andy 刚完成另一轮相近范围的行动，存在使用旧清单的风险。',
                adviceZh: '不要再启动第二个全范围补缺；Bob 先处理稀有材料，结束后由 Andy 重新检查并只处理普通石材余项。',
                posthoc: {
                    status: 'possible_over_alert',
                    label: '有风险，但干预收益未知',
                    summary: 'Bob 的长任务随后把进度推进到约 98.8%。计划重叠得到语言证据支持，但暂停 Bob 是否更好无法由 shadow replay 证明。',
                },
            },
        },
        eventCriticNarrative: {
            trial_106_online_t000294772: {
                summaryZh: '任务已经完成，所有行动观察均已静默关闭；没有仍需上级处理的分工问题。',
                adviceZh: '',
                triggerDetailZh: '终局到达 100 分，事件策略执行一次正式复盘。',
                episode: '终局',
                episodeState: 'closed',
                posthoc: {
                    status: 'supported',
                    label: '负对照未被打断',
                    summary: '事件策略没有在顺利并行阶段插入战术检查；与完整轨迹中的持续推进一致。',
                },
            },
        },
    },
    trial_162: {
        id: 'trial_162',
        title: '资源耗尽后，团队停了约 247 秒',
        subtitle: '求助没有立即解除阻塞，后期策略升级集中补齐',
        duration: 507.022,
        outcome: '100 分 · 507.0 秒完成',
        condition: '2 Agents · 2a_d33 · 33% 资源缺口',
        synopsis: '前期两人共同推进，常用石材耗尽后长期停滞；Andy 最终改变执行方式并主导完成与修复。',
        media: {
            video: '../../../out/render_trial_162/trial_162_god_2x.mp4',
            poster: '../../../out/render_trial_162/frame_plateau.png',
            playbackRate: 2,
            frames: [
                { time: 100, src: '../../../out/render_trial_162/frame_early.png', label: '前期推进' },
                { time: 250, src: '../../../out/render_trial_162/frame_plateau.png', label: '长期平台' },
                { time: 478, src: '../../../out/render_trial_162/frame_completion.png', label: '集中补齐' },
                { time: 507.022, src: '../../../out/render_trial_162/frame_final.png', label: '最终完成' },
            ],
        },
        metrics: [
            { label: '最终分数', value: '100' },
            { label: '完成时间', value: '507.0s' },
            { label: '无进展平台', value: '≈247s' },
            { label: '归因放置', value: '110 / 18' },
        ],
        phases: [
            { start: 0, end: 129.765, title: '库存转化', summary: '两人把初始材料转化为 47.62% 进度。' },
            { start: 129.765, end: 377.115, title: '长期平台', summary: '持续行动、求助和检查都未恢复得分。' },
            { start: 377.115, end: 477.5, title: '策略升级', summary: 'Andy 启动精确坐标修改，进度集中跃升。' },
            { start: 477.5, end: 507.022, title: '识别并修复', summary: '最后两个状态损失得到恢复。' },
        ],
        storyConclusion: '真正的问题不是谁看起来更忙，而是 Andy 发出的资源求助虽然被接受，却始终没有形成可验证交接；直到 Andy 更换执行策略，世界进度才恢复。',
        fixedStoryConclusion: '固定策略最终看到了长期阻塞，却没有对准“行动结束”和“求助验证失败”这两个协作转折；事件策略提供了更早、也更容易解释的审计时机。',
        chapters: [
            {
                id: 'initial-progress', start: 0, end: 129.765,
                title: '两人都认领完整任务，但前期确实在推进',
                narrative: 'Andy 和 Bob 的计划范围重叠，初始库存却被持续转化成建筑得分。只看承诺会像冲突，只看世界变化则仍是一段有效并行。',
                andy: { headline: '消耗现有石材并寻找缺料', detail: '第一条长任务持续到约 131.8 秒。' },
                bob: { headline: '建造后转向采集与补缺', detail: '97.9 秒启动第二条宽泛任务。' },
                relation: { kind: 'overlap', symbol: '↔', label: '范围重叠，尚未造成损害', detail: '双方都认领完整任务，但得分仍连续增长。', certainty: 'I' },
                world: { headline: '初始库存转化为 47.62% 进度', detail: '129.765 秒前得分从 0 持续上升。', score: '0% → 47.62%' },
                managerMeaning: '不能用后来的停滞反推此时已经失衡；在 cutoff 当下，团队仍有可验证进展。',
                eventIndexes: [0, 1, 2, 3, 4],
                evidence: ['trace/andy.trace.jsonl:11', 'trace/bob.trace.jsonl:17', 'trace/scores.tsv'],
            },
            {
                id: 'resource-block', start: 129.765, end: 236.715,
                title: '常用材料耗尽，忙碌不再带来进度',
                narrative: 'Andy 继续尝试采集，Bob 的长任务也仍在执行；但得分停在 47.62%，Andy 的行动结束后库存和得分都没有可验证变化。',
                andy: { headline: '采集行动结束，结果未被验证', detail: '72 秒行动关闭后只剩工具，蓝图仍显示大量缺块。' },
                bob: { headline: '较早的宽泛任务仍在执行', detail: '此时不能仅凭没有结果就认定 Bob 闲置。' },
                relation: { kind: 'blocked', symbol: '×', label: '共同受资源阻塞', detail: '两条行动都没有继续改变任务进度。', certainty: 'I' },
                world: { headline: '得分停在 47.62%', detail: '平台已经开始，但执行者责任仍然未知。', score: '47.62% → 47.62%' },
                managerMeaning: 'Critic 可以要求缩小任务范围和重新检查，但不应把世界变化直接归责给某个人。',
                eventIndexes: [5, 6],
                evidence: ['trace/andy.trace.jsonl:24', 'trace/andy.trace.jsonl:28', 'trace/scores.tsv'],
            },
            {
                id: 'failed-handoff', start: 236.715, end: 292.0,
                title: '求助被接受，却没有形成可验证交接',
                narrative: 'Andy 请求 Bob 处理金块、石英、萤石和石材。Bob 回复正在处理，但 replay 中没有对应命令开始；Andy 再次检查后，缺口仍在。',
                andy: { headline: '发出定向求助并重新验证', detail: '请求后没有只依赖语言承诺，而是再次检查蓝图。' },
                bob: { headline: '接受请求并声明正在处理', detail: '有确认和行动声明，但没有可复核的命令开始。' },
                relation: { kind: 'handoff', symbol: '→', label: '请求 → 确认 → 声明 → 验证失败', detail: '资源交接链条在真实执行与结果验证之间断开。', certainty: 'I' },
                world: { headline: '缺块和 47.62% 平台都没有解除', detail: '这使 263.956 秒成为本轮证据最完整的介入点。', score: '47.62% → 47.62%' },
                managerMeaning: '管理者应要求 Bob 启动可记录行动；无法执行时，应明确交付材料并报告阻塞。',
                eventIndexes: [7, 8, 9],
                evidence: ['trace/andy.trace.jsonl:29', 'trace/bob.trace.jsonl:18', 'trace/andy.trace.jsonl:32'],
            },
            {
                id: 'repeated-episode', start: 292.0, end: 467.6,
                title: '同一交接问题持续，但再次通知未必有用',
                narrative: 'Andy 的第一次补救没有恢复得分，304 秒的提醒仍属于 E-02。377 秒他启动精确坐标策略；仅 3 秒后得分轻微回退，380 秒的再次提醒已经偏早。',
                andy: { headline: '从常规补救升级到精确坐标修改', detail: '377.115 秒启动新的长执行，结果尚未揭示。' },
                bob: { headline: '旧请求仍未形成可验证行动', detail: '持有任务相关材料，但活动不能直接等同于任务推进。' },
                relation: { kind: 'unresolved', symbol: '…', label: 'E-02 持续开放', detail: '304 秒和 380 秒是同一问题的证据更新，不是两个新失衡。', certainty: 'I' },
                world: { headline: '先停滞，随后短暂回退到 46.43%', detail: '两处正确状态消失，但执行者归因未知。', score: '47.62% → 46.43%' },
                managerMeaning: '同一 episode 应折叠更新；新策略刚启动时，Critic 更适合继续观察而不是再次通知。',
                eventIndexes: [10, 11, 12, 13],
                evidence: ['trace/andy.trace.jsonl:34', 'trace/andy.trace.jsonl:36', 'trace/world_events.jsonl:2612', 'trace/world_events.jsonl:2666'],
            },
            {
                id: 'recovery', start: 467.6, end: 507.022,
                title: '新策略恢复进度，最后两处损失被修复',
                narrative: '约 10 秒内得分从 50% 升到 97.62%。最终检查只剩先前丢失的两个位置；修复后，团队在 507.022 秒完成。',
                andy: { headline: '完成集中补齐、检查与最终修复', detail: '执行结果与得分跃升在时间上紧密对齐。' },
                bob: { headline: '仍有活动和库存变化', detail: '现有证据不能确定 Bob 放置了哪些蓝图方块。' },
                relation: { kind: 'recovery', symbol: '✓', label: '团队重新推进，E-02 关闭', detail: '终局完成后不再需要发送战术建议。', certainty: 'I' },
                world: { headline: '得分集中跃升并到达 100%', detail: '最后两个正确状态恢复后，runner 标记成功。', score: '50% → 100%' },
                managerMeaning: '最终完成不证明先前交接没有问题；它只说明该问题在新策略推进后已经不再需要干预。',
                eventIndexes: [14, 15, 16, 17],
                evidence: ['trace/scores.tsv', 'trace/andy.trace.jsonl:38', 'trace/world_events.jsonl:3093', 'trace/scores.tsv:3372'],
            },
        ],
        progress: [
            [0, 0], [81.3, 8.9], [82.7, 10], [94.2, 20], [105.8, 30],
            [116.4, 40], [126.755, 44.05], [129.765, 47.62], [253.511, 47.62],
            [377.115, 47.62], [380.267, 47.02], [389.8, 46.43], [467.6, 50],
            [469.8, 60], [471.8, 70], [473.8, 80], [475.8, 90], [477.5, 97.62],
            [480.6, 98.81], [507.022, 100],
        ],
        events: [
            event(1.0, 'world', 'goal', '共同目标下达', '两人收到同一张 168 方块蓝图，资源条件比 trial_106 更紧张。', ['trace/andy.trace.jsonl:2', 'trace/bob.trace.jsonl:2']),
            event(13.106, 'bob', 'action', 'Bob 首先认领全任务', '计划完整建造并在需要时采集缺料。', ['trace/bob.trace.jsonl:6', 'trace/bob.trace.jsonl:11'], { end: 81.313, command: '!newAction' }),
            event(31.627, 'andy', 'action', 'Andy 也认领完整建造', '先消耗现有石材，再寻找缺少的稀有材料。', ['trace/andy.trace.jsonl:11', 'trace/andy.trace.jsonl:22'], { end: 131.761, command: '!newAction' }),
            event(97.86, 'bob', 'action', 'Bob 启动采集与补缺', '意识到材料不足后尝试通过常规方式收集并继续建造。', ['trace/bob.trace.jsonl:15', 'trace/bob.trace.jsonl:17'], { end: 236.759, command: '!newAction' }),
            event(129.765, 'world', 'plateau', '进度停在 47.62%', '初始石材基本耗尽，此后约 247 秒没有正向得分。', ['trace/scores.tsv'], { score: 47.62 }),
            event(138.411, 'andy', 'action', 'Andy 尝试从蓝图外采集', '执行另一条覆盖多种材料的采集与补缺任务。', ['trace/andy.trace.jsonl:23', 'trace/andy.trace.jsonl:24'], { end: 210.432, command: '!newAction' }),
            event(220.69, 'andy', 'check', '检查仍显示大量缺块', 'Andy 的库存只剩工具，资源阻塞变得直接可见。', ['trace/andy.trace.jsonl:26', 'trace/andy.trace.jsonl:28']),
            event(236.735, 'andy', 'message', 'Andy 向 Bob 求助', '请求帮助收集并放置缺少的金块、石英、萤石和石材。', ['trace/andy.trace.jsonl:29']),
            event(244.297, 'bob', 'message', 'Bob 接受求助', '回复正在处理缺块，但语言承诺尚未带来世界进度。', ['trace/bob.trace.jsonl:18']),
            event(263.956, 'andy', 'check', '接棒后仍未解除阻塞', '再次检查蓝图，缺口和 47.62% 平台仍在。', ['trace/andy.trace.jsonl:32']),
            event(292.1, 'andy', 'strategy', '第一次策略升级', '提出在常规放置失败时改用直接 world/block placement；首次尝试只检查了接口。', ['trace/andy.trace.jsonl:33', 'trace/andy.trace.jsonl:34']),
            event(377.115, 'andy', 'action', '启动精确坐标修改', '使用 /setblock 处理剩余坐标，并保留最后检查。', ['trace/andy.trace.jsonl:35', 'trace/andy.trace.jsonl:36'], { end: 477.5, command: '!newAction' }),
            event(380.0, 'world', 'anomaly', '一个正确石砖位置丢失', '归因置信度不足，不能确定执行者。', ['trace/world_events.jsonl:2612'], { score: 47.02 }),
            event(389.8, 'world', 'anomaly', '一个正确石英位置丢失', '第二处正确状态消失，同样保持责任未知。', ['trace/world_events.jsonl:2666'], { score: 46.43 }),
            event(467.6, 'world', 'progress', '进度开始集中跃升', '约 10 秒内由 50% 上升到 97.62%。', ['trace/scores.tsv'], { score: 50 }),
            event(480.6, 'andy', 'check', '只剩两个异常位置', '最终蓝图检查把余项缩小到先前丢失的石砖和石英。', ['trace/andy.trace.jsonl:38']),
            event(506.1, 'andy', 'repair', '修复最后两个位置', '世界聊天中的精确坐标反馈与两次方块恢复紧密对齐。', ['trace/world_events.jsonl:3093', 'trace/world_events.jsonl:3094', 'trace/world_events.jsonl:3095', 'trace/world_events.jsonl:3096']),
            event(507.022, 'world', 'success', '任务完成', '两处状态损失恢复后，得分到达 100%。', ['trace/scores.tsv:3372']),
        ],
        criticNarrative: {
            trial_162_online_t000126755: {
                summaryZh: '两人都在执行，库存消耗互补，得分刚增长到 44.05%；此时没有足够证据介入。',
                adviceZh: '',
                posthoc: {
                    status: 'unknown',
                    label: '临界时刻，保持未知',
                    summary: '约 3 秒后进度到达 47.62% 并进入长平台；但 cutoff 当下仍在增长，不能用未来结果反推当时必然应该报警。',
                },
            },
            trial_162_online_t000253511: {
                summaryZh: 'Andy 已耗尽建筑材料，Bob 仍持有稀有材料；求助已被接受，但 123.7 秒没有得分增长。',
                adviceZh: 'Bob 只处理手中金块、石英、石英柱和萤石；Andy 采集普通石材，之后进行一次共享检查。',
                posthoc: {
                    status: 'supported',
                    label: '阻塞判断得到后续支持',
                    summary: '无干预基线中平台继续延伸到 377 秒，说明此处确实是值得管理者关注的阻塞点；建议本身是否有效仍未实验。',
                },
            },
            trial_162_online_t000380267: {
                summaryZh: '团队虽长期停滞，但 Andy 刚启动新的精确修改策略，仅执行 3.15 秒；此时并行改派可能造成冲突。',
                adviceZh: '',
                posthoc: {
                    status: 'supported',
                    label: '不打断新策略得到支持',
                    summary: '该执行窗随后把进度集中推进到 97.62%，说明等待新策略产生结果比立即重分配更稳妥。',
                },
            },
        },
        eventCriticNarrative: {
            trial_162_online_t000210448: {
                summaryZh: 'Andy 的采集行动结束后，得分和库存都没有可验证变化；Bob 仍在执行另一条宽泛任务。',
                adviceZh: 'Andy 先检查剩余缺口；随后按普通石材与金块、石英等稀有材料拆开职责，避免再次启动两条全范围行动。',
                triggerDetailZh: '一条 72.0 秒行动关闭，未观察到得分或执行者库存变化。',
                episode: 'E-01 范围重叠',
                episodeState: 'opened',
                posthoc: {
                    status: 'supported',
                    label: '比固定检查早 43 秒',
                    summary: '此后平台继续，固定策略要到 253.5 秒才第一次建议介入；但 210 秒时 Bob 仍在执行，责任保持未知。',
                },
            },
            trial_162_online_t000263956: {
                summaryZh: '求助已被接受，但只有行动声明，没有 Bob 的真实命令开始；Andy 复查后缺口仍在。',
                adviceZh: 'Bob 立即启动可记录的稀有材料放置；若无法执行，就把材料交给 Andy 并报告阻塞。',
                triggerDetailZh: '请求、确认、行动声明之后，蓝图验证仍显示缺块。',
                episode: 'E-02 资源交接',
                episodeState: 'opened',
                posthoc: {
                    status: 'supported',
                    label: '本轮最强触发点',
                    summary: '请求链条已有确认和后续验证，且 Bob 仍持有任务所需材料；这是证据最完整的未闭环交接。',
                },
            },
            trial_162_online_t000304221: {
                summaryZh: 'Andy 再次独自尝试全范围补救，但资源交接仍未落地，得分也没有恢复。',
                adviceZh: 'Bob 使用现有金块、石英、石英柱和萤石完成稀有材料部分；Andy 只处理普通石材并负责最终检查。',
                triggerDetailZh: 'Andy 的新行动关闭，仍没有得分或库存变化；E-02 尚未解除。',
                episode: 'E-02 资源交接',
                episodeState: 'repeated',
                posthoc: {
                    status: 'possible_over_alert',
                    label: '同一问题首次重复提醒',
                    summary: '建议有证据，但与 263.956 秒高度相似；仅靠 20 秒 cooldown 无法识别同一问题 episode。',
                },
            },
            trial_162_online_t000380108: {
                summaryZh: '得分出现回退，旧交接仍未关闭；但 Andy 的新策略才启动约 3 秒。',
                adviceZh: '暂时不要与 Andy 修改同一批坐标；Bob 等本轮结束后独立检查，并处理剩余稀有材料。',
                triggerDetailZh: '得分由 47.62% 回退到 47.02%，执行者归因未知。',
                episode: 'E-02 资源交接',
                episodeState: 'repeated',
                posthoc: {
                    status: 'possible_over_alert',
                    label: '重复提醒且时机偏早',
                    summary: '固定版在晚 0.159 秒的截点选择不介入；新策略随后集中推进，说明这里更适合更新证据而不是再次通知。',
                },
            },
            trial_162_online_t000507022: {
                summaryZh: '得分达到 100，资源交接 watch 已因团队重新推进而关闭；当前没有待处理失衡。',
                adviceZh: '',
                triggerDetailZh: '终局达到 100 分，所有开放观察均已关闭。',
                episode: 'E-02 已关闭',
                episodeState: 'closed',
                posthoc: {
                    status: 'supported',
                    label: '终局正确撤回报警',
                    summary: 'critic 没有把历史阻塞延续成终局责任判断，完成时不再发送建议。',
                },
            },
        },
    },
};

function loadCritics(trial, policy) {
    const isEvent = policy === 'event';
    const resultsRoot = isEvent ? EVENT_RESULTS_ROOT : FIXED_RESULTS_ROOT;
    const narratives = isEvent ? trial.eventCriticNarrative : trial.criticNarrative;
    const records = readJsonl(path.join(resultsRoot, `${trial.id}.jsonl`));
    return records.map(record => {
        if (record.status !== 'ok') throw new Error(`${record.critic_id}: ${record.status}`);
        if (record.packet.schema_version !== 'online_replay_critic.v2') {
            throw new Error(`${record.critic_id}: expected v2 packet`);
        }
        const narrative = narratives[record.critic_id];
        if (!narrative) throw new Error(`${record.critic_id}: missing Chinese narrative`);
        const candidates = record.packet.trigger_context?.candidate_signals || [];
        const triggerType = candidates[0]?.type || record.packet.window.trigger_reason;
        return {
            id: record.critic_id,
            policy,
            policyLabel: isEvent ? '事件租约' : '固定截点',
            time: record.packet.window.cutoff_s,
            fraction: record.packet.window.cutoff_s / trial.duration,
            terminal: Boolean(record.packet.window.is_terminal),
            triggerType,
            triggerLabel: TRIGGER_NAMES[triggerType] || triggerType,
            triggerCandidates: candidates,
            openWatches: record.packet.open_watches || {
                task_actions: [], coordination_requests: [],
            },
            verdict: record.result.verdict,
            labels: record.result.imbalance_types,
            confidence: record.result.confidence,
            advice: record.result.manager_advisory,
            observations: record.result.observations,
            assessments: record.result.agent_assessments,
            limitations: record.result.limitations,
            activeExecutions: record.packet.agents.map(agent => ({
                agent: agent.agent,
                ...agent.current_execution,
            })),
            score: record.packet.team_observations.score,
            resultEvidence: isEvent
                ? `derived/event_lease_v1/results/${trial.id}.jsonl`
                : `derived/timeline_106_162_v2/results/${trial.id}.jsonl`,
            ...narrative,
        };
    });
}

const trials = Object.values(CASES).map(trial => {
    const { criticNarrative, eventCriticNarrative, ...publicTrial } = trial;
    const criticsByPolicy = {
        event: loadCritics(trial, 'event'),
        fixed: loadCritics(trial, 'fixed'),
    };
    const policySummary = Object.fromEntries(
        Object.entries(criticsByPolicy).map(([policy, critics]) => [policy, {
            evaluations: critics.length,
            tacticalEvaluations: critics.filter(critic => !critic.terminal).length,
            advisories: critics.filter(critic => critic.advice.send).length,
        }]),
    );
    return { ...publicTrial, criticsByPolicy, policySummary };
});

const data = {
    schemaVersion: 'critic_timeline_viewer.v3',
    generatedAt: new Date().toISOString(),
    defaultPolicy: 'event',
    policies: {
        event: {
            label: '事件租约',
            shortLabel: '事件驱动',
            description: '行动、求助、验证、状态回退和终局决定检查时机。',
        },
        fixed: {
            label: '固定 25% / 50% / 75%',
            shortLabel: '固定对照',
            description: '每轮在三个固定 replay 百分比检查，作为实验对照。',
        },
    },
    sourceNote: 'Curated chronology plus fixed-cutoff v2 and event-lease v1 critic results.',
    evidenceBoundary: '两种 critic 都是只读 shadow replay，建议没有发送给执行 Agent；后验结果不能代表真实干预效果。',
    trials,
};

fs.writeFileSync(
    OUTPUT,
    `window.CRITIC_TIMELINE_DATA = ${JSON.stringify(data, null, 2)};\n`,
    'utf8',
);
process.stdout.write(`${JSON.stringify({
    output: OUTPUT,
    trials: trials.length,
    critics: trials.reduce(
        (sum, trial) => sum + Object.values(trial.criticsByPolicy).flat().length,
        0,
    ),
})}\n`);
