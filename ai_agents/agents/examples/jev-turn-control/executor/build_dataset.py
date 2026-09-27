"""Build independently authored fixtures plus pinned, non-vendored BFCL inputs."""

# pylint: disable=line-too-long  # Preserve explicit benchmark/prompt text.

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

REVISION = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
BASE = "berkeley-function-call-leaderboard/bfcl_eval/data"
CAPABILITIES = [
    {
        "name": "artifact",
        "description": "Create or modify local HTML, CSV, TXT or JSON files. No network, email, purchases or deployment.",
    }
]
ACTIVE = [
    {
        "task_id": "task-demo",
        "status": "running",
        "summary": "Editing index.html",
    }
]

# Each row is a semantic family; both variants must share a split.
PAIRS = [
    (
        "speech_vs_task",
        "别念了",
        "conversation",
        "别改了",
        "task_control",
        True,
    ),
    (
        "conditional",
        "如果要修改网页会怎样？",
        "conversation",
        "现在修改网页标题为欢迎",
        "execute",
        False,
    ),
    (
        "negation",
        "不要创建网页",
        "conversation",
        "请创建标题为欢迎的网页",
        "execute",
        False,
    ),
    (
        "quotation",
        "解释一下‘创建网页’这句话",
        "conversation",
        "创建一个标题为你好的网站文件",
        "execute",
        False,
    ),
    (
        "status_context",
        "完成了吗？",
        "clarify",
        "完成了吗？",
        "task_control",
        "second",
    ),
    ("cancel_context", "取消它", "clarify", "取消它", "task_control", "second"),
    (
        "adjust",
        "把正在做的标题改成再见",
        "task_control",
        "正在改的页面用蓝色背景",
        "task_control",
        True,
    ),
    (
        "chitchat",
        "今天天气让我心情很好",
        "conversation",
        "谢谢，继续做你的任务",
        "conversation",
        True,
    ),
    (
        "progress",
        "网页任务进展怎么样？",
        "task_control",
        "报告一下后台任务的状态",
        "task_control",
        True,
    ),
    (
        "stop_reading",
        "Stop reading aloud",
        "conversation",
        "Cancel the page editing task",
        "task_control",
        True,
    ),
    (
        "hypothetical_en",
        "What would happen if we changed the title?",
        "conversation",
        "Create index.html with title Welcome",
        "execute",
        False,
    ),
    (
        "negation_en",
        "Do not create a file",
        "conversation",
        "Create notes.txt containing Hello",
        "execute",
        False,
    ),
    (
        "quoted_en",
        "Translate 'create a page' into Chinese",
        "conversation",
        "Make a local HTML page saying Hello",
        "execute",
        False,
    ),
    (
        "missing_filename",
        "把它改一下",
        "clarify",
        "Change that thing",
        "clarify",
        False,
    ),
    (
        "missing_data",
        "汇总销售CSV但我还没给你数据",
        "clarify",
        "Summarize my CSV; I have not supplied the data",
        "clarify",
        False,
    ),
    (
        "unsupported_email",
        "给客户发邮件",
        "execute",
        "Email this to my manager",
        "execute",
        False,
    ),
    (
        "unsupported_buy",
        "帮我买一台电脑",
        "execute",
        "Purchase a laptop for me",
        "execute",
        False,
    ),
    (
        "unsupported_weather",
        "查一下纽约现在的天气",
        "execute",
        "Look up the live weather in Tokyo",
        "execute",
        False,
    ),
    (
        "unsupported_deploy",
        "把网页部署到生产环境",
        "execute",
        "Deploy the website to production",
        "execute",
        False,
    ),
    (
        "concept_csv",
        "CSV是什么？",
        "conversation",
        "Explain HTML to me",
        "conversation",
        False,
    ),
    (
        "greeting",
        "你好，很高兴认识你",
        "conversation",
        "Hello, how are you?",
        "conversation",
        False,
    ),
    (
        "thanks",
        "谢谢你的帮助",
        "conversation",
        "That looks nice, thanks",
        "conversation",
        True,
    ),
    (
        "csv_sum",
        "生成sum.csv，数字2和3的和是结果",
        "execute",
        "Create sum.csv with the sum of 4 and 5",
        "execute",
        False,
    ),
    (
        "html_blue",
        "创建蓝色背景标题为Demo的index.html",
        "execute",
        "Create a blue HTML page with heading Demo",
        "execute",
        False,
    ),
    (
        "json",
        "创建data.json，name字段是Jev",
        "execute",
        "Write data.json with name equal to Jev",
        "execute",
        False,
    ),
    (
        "task_pause",
        "停止后台修改任务",
        "task_control",
        "Stop working on the current page",
        "task_control",
        True,
    ),
    (
        "speech_keep",
        "别读出来，后台继续做",
        "conversation",
        "Be quiet, keep editing in the background",
        "conversation",
        True,
    ),
    (
        "task_status_en",
        "How is the current task progressing?",
        "task_control",
        "Is my background page edit finished?",
        "task_control",
        True,
    ),
    (
        "partial_rewrite",
        "创建一个网页",
        "execute",
        "不要创建网页，只解释步骤",
        "conversation",
        False,
    ),
    (
        "partial_object",
        "创建标题为",
        "clarify",
        "创建标题为你好的网页",
        "execute",
        False,
    ),
    (
        "task_cancel_negated",
        "不要取消任务",
        "conversation",
        "Do not cancel the running task",
        "conversation",
        True,
    ),
    (
        "task_quote",
        "用户说‘取消任务’是什么意思？",
        "conversation",
        "What does 'cancel the task' mean?",
        "conversation",
        True,
    ),
]


def split(family):
    """Deterministic family-level allocation; no downstream label-based split."""
    bucket = (
        int(hashlib.sha256(("20260927:" + family).encode()).hexdigest()[:8], 16)
        % 10
    )
    return "train" if bucket < 3 else "dev" if bucket < 7 else "locked-test"


def authored():
    """Build authored contrast rows."""
    rows = []
    for family, first, first_route, second, second_route, active in PAIRS:
        for index, (text, route) in enumerate(
            ((first, first_route), (second, second_route))
        ):
            support = (
                "unsupported"
                if family.startswith("unsupported_")
                else "missing_parameters" if route == "clarify" else "supported"
            )
            rows.append(
                {
                    "id": f"self:{family}:{index}",
                    "family": family,
                    "split": split(family),
                    "kind": "self_authored",
                    "source_id": f"jev-pilot:{family}",
                    "input": {
                        "text": text,
                        "history": [],
                        "active_tasks": (
                            ACTIVE
                            if active is True
                            or (active == "second" and index == 1)
                            else []
                        ),
                        "capabilities": CAPABILITIES,
                        "stable": not (
                            family.startswith("partial_") and index == 0
                        ),
                    },
                    "gold": {"route": route, "support": support},
                    "rationale": "Independent contrast case; explicit action/context and capability policy applied.",
                }
            )
    return rows


def fetch(cache, category):
    """Download a pinned upstream file using GitHub CLI."""
    path = cache / (category + ".json")
    if not path.exists():
        endpoint = f"repos/ShishirPatil/gorilla/contents/{BASE}/BFCL_v4_{category}.json?ref={REVISION}"
        # JSON content response avoids silently accepting a truncated raw stream.
        import base64  # pylint: disable=import-outside-toplevel

        response = subprocess.run(
            ["gh", "api", endpoint], check=True, capture_output=True, timeout=90
        )
        data = json.loads(response.stdout)
        path.write_bytes(base64.b64decode(data["content"]))
    return [json.loads(line) for line in path.read_text().splitlines()]


def public_rows(cache):
    """Project reviewed source turns without hidden state or future turns."""
    specs = [
        ("live_relevance", i, 0, "execute", "supported") for i in (0, 1, 2)
    ]
    specs += [
        ("irrelevance", i, 0, "conversation", "supported") for i in (0, 28, 52)
    ]
    specs += [("irrelevance", i, 0, "execute", "unsupported") for i in (40, 46)]
    specs += [
        ("multi_turn_base", i, 0, "execute", "supported") for i in range(4)
    ]
    # Four explicitly derived capability/parameter contrasts; do not pretend upstream gold.
    specs += [
        ("multi_turn_miss_param", 2, 0, "clarify", "missing_parameters"),
        ("multi_turn_miss_param", 1, 3, "clarify", "missing_parameters"),
        ("multi_turn_miss_func", 0, 0, "execute", "unsupported"),
        ("multi_turn_miss_func", 1, 0, "execute", "unsupported"),
    ]
    rows, manifest, sources = [], [], {}
    for category, index, turn, route, support in specs:
        if category not in sources:
            sources[category] = fetch(cache, category)
        source = sources[category][index]
        derived = category.startswith("multi_turn")
        text = source["question"][turn][0]["content"]
        history = [
            message
            for messages in source["question"][:turn]
            for message in messages
        ]
        capabilities = source.get("function", [])
        if category == "multi_turn_miss_func":
            capabilities = [
                {
                    "name": "read_file",
                    "description": "Read one explicitly named file only; cannot move, create, list or search files.",
                }
            ]
        elif category.startswith("multi_turn"):
            capabilities = [
                {
                    "name": "filesystem",
                    "description": "List/search/read/move/create local files and directories. Creating requires an explicit filename; tail requires an explicit number of lines. Existing paths may be discovered by listing.",
                }
            ]
        family = (
            "bfcl-multi-" + str(index)
            if derived
            else (
                "bfcl-image"
                if category == "live_relevance" and index < 2
                else "bfcl-" + source["id"]
            )
        )
        ident = f"bfcl:{source['id']}:t{turn}"
        rationale = (
            "Derived tool inventory explicitly supplied; required filename/line count absent."
            if support == "missing_parameters"
            else (
                "Derived read-only inventory cannot fulfill requested move/list."
                if category == "multi_turn_miss_func"
                else "Current request and supplied tools manually checked; upstream tool-call label is not four-way routing gold."
            )
        )
        rows.append(
            {
                "id": ident,
                "source_id": source["id"],
                "family": family,
                "kind": "public_derived" if derived else "public_original",
                "split": "locked-test",
                "input": {
                    "text": text,
                    "history": history,
                    "active_tasks": [],
                    "capabilities": capabilities,
                    "stable": True,
                },
                "gold": {"route": route, "support": support},
                "rationale": rationale,
            }
        )
        manifest.append(
            {
                "id": ident,
                "source_id": source["id"],
                "turn": turn,
                "category": category,
                "family": family,
                "split": "locked-test",
                "kind": rows[-1]["kind"],
                "gold": rows[-1]["gold"],
                "rationale": rationale,
                "revision": REVISION,
                "path": f"{BASE}/BFCL_v4_{category}.json",
                "source_sha256": hashlib.sha256(
                    (cache / (category + ".json")).read_bytes()
                ).hexdigest(),
            }
        )
    return rows, manifest


def main():
    """Materialize local-only public text and a redistributable manifest."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    rows, manifest = public_rows(args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in authored() + rows
        )
    )
    if args.manifest:
        args.manifest.write_text(
            json.dumps(
                {
                    "seed": 20260927,
                    "source_revision": REVISION,
                    "license_status": "Repository Apache-2.0; separate dataset terms unconfirmed; download-only, no source wording vendored",
                    "samples": manifest,
                },
                indent=2,
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
