# Prompt provenance

The candidate instructions and criteria in
`../../ten_packages/extension/jev_turn_control_python/decision_profiles.json`
were authored for the September 27, 2026 six-decision pilot. Few-shot examples
come only from training families; boundary and baseline variants contain no
few-shot examples. ASR text is a transcription of synthetic audio; examples
were projected to visible state, and some task examples were modified to create
negation, missing-argument and no-capability controls.

- **Full-Duplex-Bench**, Guan-Ting Lin and collaborators, v1.0 synthetic pause /
  interruption and v1.5 user-backchannel data, revision
  `3e799c45a045256f47d5f1c9cda90157e2d2ec9e`.
  [Dataset license declaration](https://github.com/DanielLin94144/Full-Duplex-Bench/blob/3e799c45a045256f47d5f1c9cda90157e2d2ec9e/v1_v1.5/dataset/README.md#license)
  explicitly releases these synthetic subsets under MIT. Candor and ICC were
  not used. References: *Full-Duplex-Bench: A Benchmark to Evaluate Full-Duplex
  Spoken Dialogue Models on Turn-Taking Capabilities* (2025),
  [arXiv:2503.04721](https://arxiv.org/abs/2503.04721), and *Full-Duplex-Bench v1.5:
  Evaluating Overlap Handling for Full-Duplex Speech Models* (2025),
  [arXiv:2507.23159](https://arxiv.org/abs/2507.23159).
- **Berkeley Function Calling Leaderboard**, Gorilla project contributors,
  v4 simple_python, revision `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`.
  [Official dataset card](https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard)
  declares Apache-2.0. The triangle-area example and authored derivatives retain
  this attribution. [License text](licenses/BFCL-Apache-2.0.txt).

The retained Full-Duplex-Bench synthetic extracts are used under the MIT grant:

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
