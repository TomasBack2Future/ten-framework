# Full demo session evidence

When JEV_EVENT_LOG_DIR is configured, each session receives a private directory. Business text is preserved in full. API keys, authorization/cookie fields and known credential environment values are excluded. This is server-side evidence, independent of the UI and reducer event ring. No session rotation, 2 MB cutoff, field truncation or automatic deletion is performed. Existing flat JSONL logs remain untouched.

Files:
- graph.jsonl: complete reducer events before UI redaction; raw incoming interim/final ASR and TTS alignment/end payloads; actual decision request/HTTP payload and returned probability distributions; decision completion/failure and discarded results; voice command/stream; TTS text input.
- web.jsonl: received event and browser control/playback ACK, input/output audio byte offsets and metadata.
- user.pcm: inbound user PCM at the web boundary (including silence).
- tts.pcm: TTS PCM at the graph boundary, including late/rejected frames with accepted=false.
- delivered.pcm: audio observed at Web upstream, not proof of acoustic playback. Actual browser playing/stopped status is recorded separately.
- llm_evidence graph input: the final Groq/OpenAI request after system-message/parameter assembly, and original SDK stream chunks before text parsing. The provider capability is disabled by default and enabled only for the configured demo evidence graph. Headers are never included.

Every record contains session/revision correlation, wall and monotonic receipt time. Preserve producer relative_time_ms, seq, provider timestamps and browser ACK values as distinct clocks; do not treat them as synchronized. PCM offsets are bytes in the named file; metadata specifies rate/channels/sample width. response_id links TTS and playback; decision request_id links overlapping classifiers. Evidence disk I/O is asynchronous; storage failure or queue overload emits a JEV_EVIDENCE failure and close fails; it must be treated as incomplete evidence. It does not trigger a new model request or retry audio. An absent graph.closed or session.ended record means the recording may be partial. A process kill/power loss can lose the in-memory write tail; do not label such recordings complete.

## Export

End the session and allow worker shutdown first, then run inside the runtime or against a copied evidence root:

    python scripts/export_evidence.py --root /var/lib/jev-evidence --session SESSION_ID --output /tmp/SESSION_ID.tgz

The archive includes original files plus SHA-256 inventory. Export does not delete or rewrite source files and refuses an existing output. Copy the archive to the investigation directory. There is no new public archive endpoint or UI transcript cap involved. Exporting an active session is not a consistent snapshot.

## Persistent deployment and existing evidence

The demo manifest now declares a 20 GiB ReadWriteOnce PVC and mounts /var/lib/jev-evidence, with a single-replica Recreate strategy to avoid cross-node concurrent mounts. StorageClass uses the cluster default and must be checked at deployment. No manifest is applied by this PR. Keep the claim across rollbacks; do not remove it or install automated expiry. Monitor capacity and expand/archive deliberately before exhaustion.

Before any rollout of the current ephemeral deployment, separately preserve ALL existing /tmp/jev-observations files and investigation material outside the old Pod, verify hashes and retain originals. Copying into a new claim requires a separate deployment/migration step; do not assume changing the environment variable migrates old data. This PR does not modify live data.

Historical limitations: previously unrecorded input/TTS audio, exact provider request messages and classifier prompts/HTTP responses cannot be recreated exactly from a transcript. Redacted/truncated text, events beyond the 2 MB cap and rotated session files are unrecoverable unless another preserved trace contains them. Keep independently captured wire/browser/audio artifacts; never use a fresh call as replacement evidence for an old session.
