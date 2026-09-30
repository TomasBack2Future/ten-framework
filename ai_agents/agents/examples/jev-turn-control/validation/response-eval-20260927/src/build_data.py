"""Build provenance-labelled family-grouped traces without provider outputs."""

import argparse, difflib, hashlib, json, re, zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def dump(v):
    return json.dumps(
        v, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sha(v):
    return hashlib.sha256(dump(v).encode()).hexdigest()


def norm(s):
    return " ".join(re.findall(r"\w+", s.lower()))


# Eight distinct authored dialog scaffolds per requested stratum. Timings below
# are synthetic and never relabelled as acoustic/ASR observations.
SYNTH = {
    "question": [
        ("", "Why does bread rise?", "Why does bread"),
        ("", "Can you explain what a watershed is?", "Can you explain"),
        (
            "",
            "Which way should a ceiling fan turn in winter?",
            "Which way should a",
        ),
        ("", "Who wrote The Time Machine?", "Who wrote"),
        (
            "",
            "What is the difference between a comet and an asteroid?",
            "What is the difference between",
        ),
        (
            "",
            "Would you describe how a bicycle brake works?",
            "Would you describe how",
        ),
        (
            "",
            "Is it possible to see Venus without a telescope?",
            "Is it possible to see",
        ),
        ("", "How do I convert inches into centimeters?", "How do I convert"),
    ],
    "context_short": [
        (
            "Would you prefer the aisle seat or the window seat?",
            "Aisle, please.",
            "Aisle",
        ),
        ("What size envelope do you need?", "A4.", "A"),
        (
            "Should I explain that using an example?",
            "Yes, use an example.",
            "Yes",
        ),
        (
            "Which of those two titles do you want to use?",
            "The second one.",
            "The second",
        ),
        ("How many guests are coming for dinner?", "Six.", "Six"),
        ("What color should the cover be?", "Dark green.", "Dark"),
        (
            "Do you want the route with stairs or the accessible route?",
            "The accessible one.",
            "The accessible",
        ),
        (
            "What subject are you studying for the exam?",
            "Organic chemistry.",
            "Organic",
        ),
    ],
    "numbers_finished": [
        (
            "Please read the six-digit shipment code.",
            "Two, five, zero, eight, one, nine.",
            "Two, five, zero",
        ),
        (
            "Give me the four numbers you want added.",
            "Seven, twelve, six, and five. That is all four.",
            "Seven, twelve",
        ),
        (
            "What is the three-digit locker number?",
            "Four, zero, seven.",
            "Four, zero",
        ),
        (
            "List the prices, and tell me when you are done.",
            "Eleven, fourteen, and twenty. Done.",
            "Eleven, fourteen",
        ),
        (
            "How many pages were in each of the two chapters?",
            "Nine and sixteen.",
            "Nine and",
        ),
        (
            "Read the five measurements, then I can find the median.",
            "Eight, eight, twelve, thirteen, twenty.",
            "Eight, eight",
        ),
        (
            "What are the two coordinates of that point?",
            "Minus three, plus seven. Those are the coordinates.",
            "Minus three",
        ),
        (
            "Tell me the sequence you want reversed.",
            "One, zero, one, zero. End of sequence.",
            "One, zero, one",
        ),
    ],
    "hesitation": [
        (
            "",
            "I was thinking, um, maybe we could talk about gardening instead.",
            "I was thinking, um, maybe",
        ),
        (
            "",
            "The part I do not understand is how the pulley changes the force.",
            "The part I do not understand is",
        ),
        (
            "Which explanation was unclear?",
            "It was the, uh, section about evaporation.",
            "It was the, uh",
        ),
        (
            "",
            "First I checked the lid, then I checked the switch. What should I check next?",
            "First I checked the lid, then",
        ),
        (
            "What should I include in the recipe?",
            "I want apples and, let me think, cinnamon.",
            "I want apples and, let me think",
        ),
        (
            "",
            "About the timetable, I mean the weekend one, when is the first departure?",
            "About the timetable, I mean",
        ),
        (
            "",
            "I started to compare the two methods, but I have not finished explaining the second method yet.",
            "I started to compare the two methods, but",
        ),
        (
            "Tell me the numbers, then say done.",
            "Three, seven, eleven, eighteen. Done.",
            "Three, seven, eleven",
        ),
    ],
    "explicit_wait": [
        ("", "Please stay quiet while I read this paragraph to myself.", ""),
        ("", "Hold on. I have more to say before you answer.", ""),
        ("", "Do not respond yet; I am checking my notes.", ""),
        ("", "Give me a moment to finish the question.", ""),
        ("", "Let me complete the whole list first, please.", ""),
        ("", "Wait until I tell you I am finished.", ""),
        ("", "I need silence for a little while. Please wait.", ""),
        ("", "Pause your answer for now; I will ask when I am ready.", ""),
    ],
    "acknowledgment": [
        ("Explain the water cycle.", "Mm-hmm.", ""),
        ("Describe the parts of a violin.", "Right, go on.", ""),
        ("Tell me how composting works.", "I see.", ""),
        ("Explain the rules of chess castling.", "Okay, keep going.", ""),
        ("Describe what a black hole is.", "Yeah, that makes sense.", ""),
        ("Walk me through folding a paper crane.", "Uh-huh.", ""),
        ("Tell me about cave formations.", "Got it, continue.", ""),
        ("Explain the stages of making pottery.", "Yes, I am following.", ""),
    ],
    "correction": [
        (
            "Compare the two maps.",
            "No, I meant the second map, not the first. Compare that one.",
            "No, I meant",
        ),
        (
            "How far is the hike?",
            "Actually, the distance is twelve kilometers, not twenty. How long will that take?",
            "Actually, the distance is",
        ),
        (
            "Explain the example with the red ball.",
            "I said blue ball. Please explain that example again.",
            "I said blue",
        ),
        (
            "Help me prepare the shopping list.",
            "Sorry, make that three people instead of five. What quantities do I need?",
            "Sorry, make that",
        ),
        (
            "Tell me about the planet.",
            "Not Saturn; I meant Neptune. What is its atmosphere like?",
            "Not Saturn",
        ),
        (
            "Please summarize the first paragraph.",
            "You are describing the wrong paragraph. Summarize the last paragraph instead.",
            "You are describing the wrong",
        ),
        (
            "How do I care for that plant?",
            "It is a fern, not a cactus. Does that change the advice?",
            "It is a fern",
        ),
        (
            "Explain the dates on this timeline.",
            "The year is eighteen sixty, not nineteen sixty. Please correct the explanation.",
            "The year is",
        ),
    ],
    "response_urge": [
        (
            "What causes tides?",
            "Could you answer my question about tides now?",
            "Could you answer",
        ),
        (
            "How do fractions work?",
            "Are you still there? I am waiting for your explanation.",
            "Are you still there",
        ),
        (
            "What is a haiku?",
            "Please respond. I finished asking.",
            "Please respond",
        ),
        (
            "How long is a lunar month?",
            "You have been silent. Can you give me the answer?",
            "You have been silent",
        ),
        (
            "What does the word fragile mean?",
            "Hello? Did you hear my question?",
            "Hello",
        ),
        (
            "How do you calculate an average?",
            "I am ready for you to explain it now.",
            "I am ready",
        ),
        (
            "What is the capital of Norway?",
            "Can you tell me now, please?",
            "Can you tell me",
        ),
        (
            "Why are leaves green?",
            "I have nothing more to add; please answer.",
            "I have nothing more to add",
        ),
    ],
    "interrupted_new_question": [
        (
            "Explain how a refrigerator works.",
            "Stop for a moment. Why does frost form inside it?",
            "Stop for a moment",
        ),
        (
            "Tell me about ancient bridges.",
            "Wait, a different question: how does an arch carry weight?",
            "Wait, a different question",
        ),
        (
            "Describe the solar system.",
            "Before you continue, which planet has the shortest year?",
            "Before you continue",
        ),
        (
            "Explain a computer keyboard.",
            "Let me interrupt. What is the escape key used for?",
            "Let me interrupt",
        ),
        (
            "Talk about ocean currents.",
            "I have another question. What causes a rip current?",
            "I have another question",
        ),
        (
            "Describe how birds migrate.",
            "Pause that explanation. How do they navigate at night?",
            "Pause that explanation",
        ),
        (
            "Explain the history of paper.",
            "Can I ask something else? Why does wet paper tear easily?",
            "Can I ask something else",
        ),
        (
            "Tell me about cloud types.",
            "Stop. What is the difference between fog and a cloud?",
            "Stop",
        ),
    ],
}


def synthetic():
    out = []
    for scenario, examples in SYNTH.items():
        for n, (context, final, prefix) in enumerate(examples):
            active = scenario in (
                "acknowledgment",
                "correction",
                "interrupted_new_question",
            )
            history = []
            if context:
                history = [
                    {
                        "role": (
                            "user"
                            if active or scenario == "response_urge"
                            else "assistant"
                        ),
                        "content": context,
                    }
                ]
            last = 3300 if scenario == "hesitation" else 900
            events = []
            if prefix:
                events.append(
                    {
                        "at_ms": 200,
                        "type": "asr",
                        "text": prefix,
                        "final": False,
                        "segment_id": "focal",
                    }
                )
            events.append(
                {
                    "at_ms": last,
                    "type": "asr",
                    "text": final,
                    "final": True,
                    "segment_id": "focal",
                }
            )
            negative = scenario in ("acknowledgment", "explicit_wait")
            # One deliberately unfinished terminal narrative: observed intent retains floor.
            if scenario == "hesitation" and n == 6:
                negative = True
            out.append(
                {
                    "id": f"synthetic-{scenario}-{n+1:02}",
                    "scenario": scenario,
                    "family": f"authored-{scenario}-{n+1:02}",
                    "source_type": "authored_synthetic",
                    "history": history,
                    "initial_assistant_speaking": active,
                    "assistant_end_ms": 2500 if active else None,
                    "events": events,
                    "horizon_ms": last + 8000,
                    "opportunity_ms": None if negative else last,
                    "stop_expected": active and scenario != "acknowledgment",
                    "source": {
                        "authoring": "single-author scaffold; not a transcript of any real call",
                        "timing": "synthetic ASR arrival assumptions; not measured acoustic silence",
                    },
                    "gold_basis": "Authored visible intention and completion. Same family covers all prefixes and silence checkpoints.",
                }
            )
    return out


def public_sources(work):
    seen = json.loads(
        (ROOT / "manifests/seen-source-ids.json").read_text(encoding="utf-8")
    )
    seen_ids = {x["id"] for x in seen}
    rows = []
    for subset, scenario in [
        ("pause", "hesitation"),
        ("interrupt", "interrupted_new_question"),
        ("backchannel", "acknowledgment"),
    ]:
        with zipfile.ZipFile(work / (subset + ".zip")) as z:
            folders = sorted(
                {
                    n.rsplit("/", 1)[0]
                    for n in z.namelist()
                    if n.endswith("/input.wav") and not n.startswith("__MACOSX")
                }
            )
            for folder in folders:
                files = {
                    n.split("/")[-1]: n
                    for n in z.namelist()
                    if n.startswith(folder + "/") and n.endswith(".json")
                }
                md = {k: json.loads(z.read(v)) for k, v in files.items()}
                source_id = subset + "-" + folder.split("/")[-1]
                if subset == "pause":
                    words = md["transcription.json"]
                    context = " ".join(
                        x["text"] for x in words if x["text"] != "[PAUSE]"
                    )
                    end = round(max(x["timestamp"][1] for x in words) * 1000)
                    chunks = [x for x in words if x["text"] != "[PAUSE]"]
                    events = []
                    text = []
                    last = 0
                    for i, w in enumerate(chunks):
                        text.append(w["text"])
                        at = round(w["timestamp"][1] * 1000)
                        # 400 ms batching is a declared reference-projection assumption, not Soniox.
                        if at - last >= 400 or i == len(chunks) - 1:
                            events.append(
                                {
                                    "at_ms": at,
                                    "type": "asr",
                                    "text": " ".join(text),
                                    "final": i == len(chunks) - 1,
                                    "segment_id": "focal",
                                }
                            )
                            last = at
                    history = []
                    source_window = md["pause.json"][0]["timestamp"]
                    origin = 0
                else:
                    m = (
                        md["interrupt.json"][0]
                        if subset == "interrupt"
                        else md["metadata.json"]
                    )
                    context = (
                        m["context"]
                        if subset == "interrupt"
                        else m["context_text"]
                    )
                    window = (
                        m["timestamp"]
                        if subset == "interrupt"
                        else m["timestamps"]
                    )
                    origin = round(window[0] * 1000)
                    end = round(window[1] * 1000) - origin
                    final = (
                        m["interrupt"]
                        if subset == "interrupt"
                        else m["backchannel_text"]
                    )
                    events = [
                        {
                            "at_ms": end,
                            "type": "asr",
                            "text": final,
                            "final": True,
                            "segment_id": "focal",
                        }
                    ]
                    history = [{"role": "user", "content": context}]
                    source_window = window
                rows.append(
                    {
                        "id": "fdb-" + source_id,
                        "source_id": source_id,
                        "context_key": norm(context),
                        "scenario": scenario,
                        "family": "fdb-" + sha(norm(context))[:16],
                        "source_type": "public_reference_projection",
                        "history": history,
                        "initial_assistant_speaking": subset != "pause",
                        "assistant_end_ms": (
                            end + 1800 if subset != "pause" else None
                        ),
                        "events": events,
                        "horizon_ms": end + 8000,
                        "opportunity_ms": (
                            end if subset != "backchannel" else None
                        ),
                        "stop_expected": subset == "interrupt",
                        "source": {
                            "repository": "DanielLin94144/Full-Duplex-Bench",
                            "revision": "3e799c45a045256f47d5f1c9cda90157e2d2ec9e",
                            "folder": folder,
                            "audio_sha256": hashlib.sha256(
                                z.read(folder + "/input.wav")
                            ).hexdigest(),
                            "metadata_sha256": sha(md),
                            "original_time_origin_ms": origin,
                            "source_window_seconds": source_window,
                            "timing": "Original annotation timestamps; reference transcript projected into ASR-shaped events. No new ASR/audio listening claim. Assistant-end time is a replay assumption.",
                        },
                        "gold_basis": "Source synthetic task category and focal completion annotation; reference-label proxy, reported separately from authored examples.",
                        "seen": source_id in seen_ids,
                        "subset": subset,
                    }
                )
    # Conservative connected components, including all known old source conversations.
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(rows):
        ta = set(a["context_key"].split())
        for j in range(i):
            b = rows[j]
            tb = set(b["context_key"].split())
            overlap = len(ta & tb) / max(1, len(ta | tb))
            if (
                a["context_key"] == b["context_key"]
                or overlap >= 0.58
                or difflib.SequenceMatcher(
                    None, a["context_key"], b["context_key"]
                ).ratio()
                >= 0.72
            ):
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        groups[find(i)].append(row)
    candidates = []
    excluded = []
    for members in groups.values():
        family = (
            "fdb-component-" + sha(sorted(x["source_id"] for x in members))[:16]
        )
        seen = any(x["seen"] for x in members)
        for row in members:
            row["family"] = family
            if seen:
                excluded.append(
                    {
                        "id": row["id"],
                        "family": family,
                        "reason": "component touches prior seen corpus",
                    }
                )
            else:
                candidates.append(row)
    selected = []
    for subset in ("pause", "interrupt", "backchannel"):
        eligible = sorted(
            [x for x in candidates if x["subset"] == subset],
            key=lambda x: sha("response-eval-v2:" + x["id"]),
        )
        chosen_families = set()
        for row in eligible:
            if row["family"] in chosen_families:
                continue
            chosen_families.add(row["family"])
            selected.append(row)
            if len(chosen_families) >= 12:
                break
    for row in selected:
        for key in ("seen", "context_key", "subset"):
            row.pop(key)
    return selected, excluded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=Path("work"))
    args = parser.parse_args()
    public, excluded = public_sources(args.work)
    rows = synthetic() + public
    # Source groups remain indivisible even when they span strata.
    groups = defaultdict(list)
    for row in rows:
        groups[row["family"]].append(row)
    buckets = defaultdict(list)
    for family, members in groups.items():
        buckets[(members[0]["source_type"], members[0]["scenario"])].append(
            family
        )
    for families in buckets.values():
        families.sort(key=lambda x: sha("family-split-v2:" + x))
        n = len(families)
        for i, family in enumerate(families):
            split = (
                "development"
                if i < n // 2
                else "validation" if i < (3 * n) // 4 else "holdout"
            )
            for row in groups[family]:
                row["split"] = split
    for row in rows:
        row["record_sha256"] = sha(row)
    target = ROOT / "data/new-sequences.jsonl"
    if target.exists():
        raise SystemExit("Refuse to overwrite frozen dataset")
    target.write_text("".join(dump(r) + "\n" for r in rows))
    manifest = {
        "seed": "family-split-v2",
        "source_selection_seed": "response-eval-v2",
        "dataset_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "n_sequences": len(rows),
        "n_families": len(groups),
        "counts": dict(
            Counter(
                f"{r['source_type']}:{r['scenario']}:{r['split']}" for r in rows
            )
        ),
        "annotation_status": "single author; synthetic gold and source-task proxy labels; no independent blind/audio annotation",
        "excluded_source_components": excluded,
        "old_corpus_role": "all previously seen data and call49c0d169 are regression-only",
        "family_grouping": "same original context, token Jaccard >= .58 or sequence similarity >= .72, transitive components; heuristic, not an independent semantic audit",
        "files": {
            "new-sequences.jsonl": hashlib.sha256(
                target.read_bytes()
            ).hexdigest()
        },
    }
    (ROOT / "manifests/data-freeze.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "sequences": len(rows),
                "families": len(groups),
                "source_types": dict(Counter(r["source_type"] for r in rows)),
                "splits": dict(Counter(r["split"] for r in rows)),
                "excluded_seen_component_records": len(excluded),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
