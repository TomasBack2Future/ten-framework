# Stop lifecycle regression

`stop-lifecycle.json` is a sanitized lifecycle projection from the actual Web event stream that reproduced Stop PASS persisting after a terminal playback ACK. It retains original sequence numbers, input revisions, event types and lifecycle flags, and normalizes response IDs. Transcript, provider payloads and audio are omitted.

Source decompressed stream SHA-256: `6a88a1c21674d9431d38e517ce97b0386288334661744b639e067aa36ff82e9c`.

The first stop is applied at sequence 1477, cancellation at 1479, and terminal ACK at 1485 (61.778 seconds). At sequence 2111 (101.353 seconds) the baseline still showed Stop PASS and an active interrupt path. Both must be cleared. Later response starts and terminal ACKs cover subsequent cycles.
