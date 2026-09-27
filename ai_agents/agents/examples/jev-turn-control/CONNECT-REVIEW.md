# Connect 恢复与契约核对

本次基于 bdd3c2f 修复，尚未合并或部署。

- Connect 使用 finally 恢复重试；覆盖音频 unlock 失败、409、创建会话后的初始化异常。创建成功后的失败会清理对应 session_id；清理请求失败保留 ID，下一次 Connect 先重试清理，再创建图。服务器忽略已过期 ID 的清理请求，保留 owner 校验。
- OpenAI adapter 将完整请求日志改为 message_count；真实 adapter 单测断言 system、user、assistant 内容及 API key 不进入日志。
- Node 16 项通过；原生 TEN Python 36 项通过；Black、Pylint 10/10、tman schema 检查通过。

## 跨 PR 接口

- `test_asr_timed_duplicate_final_and_late_partial_are_not_new_turns`覆盖相同时间范围 final 重复与晚到 partial 不推进 revision，以及更晚时间同文本可继续输入。
- `test_shutdown_sends_tts_flush_before_llm_abort` 调用真实 on_stop 和 abort，拦截边界 send_data/send_cmd，验证按顺序发送 `tts_flush {flush_id: rid}` 到 tts 与 `abort {request_id: rid}`。旧测试仅 mock abort 的不足已补齐。
- `test_final_cursor_can_correct_an_earlier_overestimate` 覆盖最终 stopped cursor 从 900ms 下调至 200ms，历史只保留已听到前缀；迟到旧 ACK 不恢复新 response。
- 这些结论针对当前 PR1；PR2/PR3 合并后仍需父任务在最终整合 SHA 跑检查。

## 供应商时间戳证据

Soniox 官方 SDK Token 文档将 start_ms/end_ms 定义为相对音频开头的毫秒数，非逐句归零：https://soniox.com/docs/sdk/python-SDK/Full-SDK-reference/types 。仓库 `soniox_asr_python/extension.py:1076-1113` 将 token 时间映射到输入音频时间线；`_adjust_timestamp` 加 `sent_user_audio_duration_ms_before_last_reset`。`_handle_open:621-624` 在重连时先累加旧 user audio 总时长再 reset timeline。因此当前适配器使用连续 user-audio 时间轴，而非把单句起点当零。该实现证据不等于承诺供应商绝不会乱序；本地仍忽略已消费范围内的重复/迟到数据。

Cartesia 仓库 `cartesia_tts/cartesia_tts.py:535-575` 为同 context 的首音频/时间戳建立 `time.time()*1000` 基准，音频时间为 base + samples/sample_rate；`_handle_timestamps:641-663` 明确将原始 `start_s/end_s` 乘1000，再加同一 base，duration 也是毫秒。`cartesia_tts/extension.py:445` 把音频 timestamp 交给 send_tts_audio_data，`ten_ai_base/tts2.py` 保留到 AudioFrame.timestamp。故 Jev 以首 AudioFrame.timestamp 归一化词时间；不会直接将 epoch-ms 与播放器相对毫秒比较。这里的单位结论来自当前仓库适配器源码。

播放 cursor 仍为浏览器调度估算，不是声学测量；本次未做新的真人通话验证。
