# 不回应问题：冻结配对评测（2026-09-27）

**结论：本轮不替换默认 prompt、阈值或等待时间，继续默认纯 Jev。** 新 prompt 没有证明改善漏响应；高阈值把大量响应推到 5 秒澄清兜底；四档单次静音复判在新留出上没有改善主要结果。独立提交评测与候选 prompt，生产 engine/Web/config 不变。

## 测量范围与冻结顺序

- 原版 `78d44c91d2a7151da18a9d5e82b69b86dbbc1536`；bugfix 对照 `bf4c21e1f70940b28e4e794e7b1db08624afaedb`。逐文件哈希见 `manifests/engine-lock.json`。
- 108 个原对话 family：72 个作者合成、36 个此前未用的 Full-Duplex-Bench 合成源参考转录投影。开发 54、验证 27、新留出 27。九个语义层各有 8 个作者合成 family；另外三个公开源层各 12 个 family。
- 原对话所有前缀、静音探针、模式派生同属一个 split。公开源通过相似度连通分量分组；碰到旧 72 个源的整个分量排除。旧 351 快照 pilot/63 test、24 次音频回归和已查看通话均只作已见回归。
- A/B prompt 和 gold 先冻结，开发/验证实测后锁定阈值，再调用新留出。未按留出结果修改 prompt、gold 或阈值。作者写过这些合成内容，因此这不是独立盲标注；family 相似度规则也不是独立语义审计。
- **没有新的真实 ASR 或真实端到端音频证据。** 公开参考文字不是 Soniox 识别输出；输入保留源标注时间，但 400ms 文本批次是投影假设。合成对话使用已声明的合成时序。
- 原 49c 通话缺失完整供应商请求和部分正文，不能回填为原始证据；24 次已见真实音频回归没有被冒充新留出或重新盲测。

## khipaa 配对供应商实测

专用非服务 Pod，4 个工作线程、HTTPS 连接复用、每个完全相同的 state/questions 均调用 Jev 与 ScaleDown；顺序轮换。无服务部署或新通话。Pod 已删除并验证不存在。

| 供应商 | 实际 HTTP 次数 | 错误 | 超过 800ms | P50 / P95（ms） | 返回 model |
|---|---:|---:|---:|---:|---|
| jev | 2688 | 0 | 0 | 92.7 / 140.9 | jev-1.13.0 |
| scaledown | 2688 | 0 | 0 | 302.3 / 402.0 | classify-1 |

总计 5,376 次：固定快照 3,040、序列中新状态 2,168、关键分歧追加重复 168。记录实际请求 body、原始响应、概率、model、耗时、错误和哈希；凭证仅通过 stdin 传入内存。模型返回名不保证 ScaleDown 后端修订不可变。这是供应商 API 耗时，**不是音频轮次延迟，也不是负载测试**。

28 组关键 state/prompt 每家各追加 3 次（连同初次每组 4 次）。Jev 有 2/28 组选择标签变化、1/28 组 `.47` 准入变化；ScaleDown 为 4/28、3/28。重复仅报告不稳定性，不用于重新选择阈值或扩大独立样本数。

## 固定分数 A/B/C/D

A=已上线 prompt+.47；B=候选 prompt+.47；C=已上线 prompt+开发选择阈值；D=候选 prompt+开发选择阈值。选择网格、损失与验证拒绝规则见 protocol/selection lock。Jev C=.95、D=.90；ScaleDown C/D=.95。

为了隔离供应商差异，两家均使用 **Jev 的 chosen-label 分数规则和同一套问题**。这是受控比较，不是已部署 SD（answer+clarify 合分、不同 stop 阈值）策略的验收。chosen label 原样保留，不用概率 argmax 替换；stop 问题未迭代，阈值固定 .65。

阈值搜索使用同一批冻结分数，没有重新请求模型。选择目标对误抢话罚 10、漏响应罚 2，包含所有稳定前缀；长对话贡献更多前缀，因此可能偏向保守阈值。没有在留出后改成另一个更好看的目标。

新留出主快照：27 family，20 个正例、7 个负例；最后文本后 120ms，start 按假设已释放话权评估。完整 source/scenario/prefix/silence 分层及 Wilson 区间在 snapshot-metrics 中。

| Provider | 方案 | 正例准入 / 20 | 负例误触发 / 7 |
|---|---|---:|---:|
| jev | A | 19 | 1 |
| jev | B | 19 | 1 |
| jev | C | 5 | 0 |
| jev | D | 15 | 1 |
| scaledown | A | 20 | 2 |
| scaledown | B | 20 | 3 |
| scaledown | C | 16 | 1 |
| scaledown | D | 18 | 1 |

Jev A/B 的准入率同为 19/20，Wilson95% 为 76.4%–99.1%；负例误触发 1/7，区间 2.6%–51.3%。数量不足以把小幅差异当作可靠提升。保持不变的 stop 在留出 12 个样例上两家各错 1 个；没有据此优化 stop。

## 原时间序列回放

共 2,592 次：108 序列 × 两家驱动输出 ×（原版/修复版各 A/B/C/D + 修复版四档计时反事实）。对 immutable engine 真实调用 input/begin_decision/complete_decision/tick/playback；持续到最后输入后 8 秒，包含没有后续 ASR 的等待。新状态必须按完整 body 哈希重新配对测量；不把错配的旧分数复用于新状态。

供应商耗时取实际记录，按模拟时钟完成；800ms 截止。20ms tick、回复 1200ms 空文本模拟音频、下一 tick 的零光标 stop ACK 均是显式假设。**未运行 LLM/TTS、未听音频；延迟是机会点到 response.start，而非声音开始时间。** 早启动指机会标注前启动或负例上任何启动，不能直接等同人耳判断的真实抢话。

修复版新留出（各行 27 family、20 正例、7 负例）：

| Provider | 方案 | 漏响应 / 20 | 有早启动 / 27 | 负例回复 / 7 | 延迟 P50 / P95 ms | >2s / 已响应 |
|---|---|---:|---:|---:|---:|---:|
| jev | A | 0 | 8 | 2 | 520 / 1380 | 1 / 20 |
| jev | B | 1 | 7 | 1 | 500 / 1340 | 0 / 19 |
| jev | C | 0 | 3 | 2 | 5000 / 5000 | 14 / 20 |
| jev | D | 1 | 5 | 1 | 580 / 5000 | 3 / 19 |
| scaledown | A | 0 | 5 | 2 | 760 / 1680 | 0 / 20 |
| scaledown | B | 0 | 6 | 2 | 720 / 1080 | 0 / 20 |
| scaledown | C | 0 | 3 | 2 | 780 / 5000 | 4 / 20 |
| scaledown | D | 0 | 4 | 2 | 740 / 5000 | 2 / 20 |

Jev C 的最终响应率看似 20/20，但 14/20 要等超过 2 秒，P50=5 秒，并增加到 16 次 clarify 启动；不能称为解决“不愿回答”。Jev B 减少 1 个负例回复，但增加 1 个删失的漏响应。配对 family bootstrap：B−A 早启动比例差 −3.7pp，95% [−14.8,+7.4]pp；C−A 已响应对的平均延迟 +2796ms，95% [1852,3681]ms。

Jev A/B 分语义层（作者合成与公开源合计，完整分源结果保留在指标文件）：

| 层 | family | A 漏响应 | B 漏响应 | A/B 早启动 family | A/B 负例回复 |
|---|---:|---:|---:|---:|---:|
| question | 2 | 0 | 0 | 0/0 | 0/0 |
| context_short | 2 | 0 | 0 | 2/2 | 0/0 |
| numbers_finished | 2 | 0 | 0 | 0/0 | 0/0 |
| hesitation | 5 | 0 | 1 | 2/2 | 0/0 |
| explicit_wait | 2 | 0 | 0 | 0/0 | 0/0 |
| acknowledgment | 5 | 0 | 0 | 2/1 | 2/1 |
| correction | 2 | 0 | 0 | 0/0 | 0/0 |
| response_urge | 2 | 0 | 0 | 2/2 | 0/0 |
| interrupted_new_question | 5 | 0 | 0 | 0/0 | 0/0 |

explicit_wait 仅 2 个留出 family，0/2 不能证明不会打断等待；acknowledgment 5 个 family，A/B 误回复 2/5 与 1/5；correction 仅 2 个 family，两方案都恢复响应。短答前缀的机会时间由最后标注确定，可能比真实听者判断更保守。

分源主快照（Jev，正例准入/正例，负例误触发/负例）：

| 来源 | 方案 | family | 正例准入 | 负例误触发 |
|---|---|---:|---:|---:|
| authored_synthetic | A | 18 | 14/14 | 1/4 |
| authored_synthetic | B | 18 | 14/14 | 1/4 |
| authored_synthetic | C | 18 | 5/14 | 0/4 |
| authored_synthetic | D | 18 | 12/14 | 1/4 |
| public_reference_projection | A | 9 | 5/6 | 0/3 |
| public_reference_projection | B | 9 | 5/6 | 0/3 |
| public_reference_projection | C | 9 | 0/6 | 0/3 |
| public_reference_projection | D | 9 | 3/6 | 0/3 |

## bugfix 与调参分开

这批新序列中原版/修复版的 A/B/C/D 主要结果相同，不能由此断言修复无价值：新样本主要是单个焦点输入，没有充分覆盖之前已发过 guidance 的多个输入周期。

独立已见回归保留已观察到的 selected label=answer、score=.42（continuation 概率 .43，不擅自改标签）和相关时间。原版 `.47` 在 184000ms 前没有响应；修复版相同分数在 183254ms 恢复 clarify（问句后 5000ms）。把两版阈值都降到 `.42` 会在 178754ms 启动 answer（500ms），但这会掩盖 guidance 生命周期缺陷，不能证明泛化语义改善。完整历史请求未知，所以没有把新 prompt 的重建请求输出声称为原通话的实测修复。

## 独立静音复判反事实

不改变生产接口；测试驱动只在 idle/pending、没有在途请求和 answer/clarify timer 时，每个输入 revision 最多追加一次复判。固定 engine、prompt A 和 `.47`，分别尝试 300/500/1000/2000ms。

| Jev 新留出 | 请求数 | 漏响应 / 20 | 有早启动 / 27 | 延迟 P50 / P95 ms |
|---|---:|---:|---:|---:|
| A | 90 | 0 | 8 | 520 / 1380 |
| timing-300 | 124 | 0 | 8 | 520 / 1380 |
| timing-500 | 120 | 0 | 8 | 520 / 1380 |
| timing-1000 | 97 | 0 | 8 | 520 / 1380 |
| timing-2000 | 99 | 0 | 8 | 520 / 1380 |

300ms 增加约 38% 请求，未改善这批留出主要结果。它不是已验证的最优值，也不是通用静音定时策略的否定；这里仅检验明确的一次复判规则。该结果不计为 prompt 收益。

## 交付与验证

- 保留默认值；候选 B 仅作为冻结评测 artifact，不接入生产 profile。
- 数据、protocol/prompt/selection/engine 锁、原始 HTTP/序列证据、每层指标和重放脚本都可离线复算；参考来源沿用项目 PROMPT_PROVENANCE 的 MIT 合成子集许可。
- 2,592 条序列已通过离线精确重放：18,790 次完整 body cache lookup、0 次网络调用，所有 engine 事件和结果逐项一致。
- 原故障固定分数回归、selected-label gate、跨 split family、无未来 gold 泄漏、精确 ASR 时间与 stale fencing、Wilson 区间均有测试。
- 推广到真实通话需要包含完整请求和音频/播放时序的新证据；当前不足以推荐替换默认，评测 PR 不合并 engine/Web 修复，也不部署。
