"""Regression protection for family grouping, selection locks and ablation."""

import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from executor.ablation import score_turn
from executor.build_dataset import authored
from executor.evaluate import resolve_config, run
from executor.config import RoutingConfig
from executor import routing
from executor.routing import Router, decision_spec, spec_sha256


class EvaluationTests(unittest.TestCase):
    def test_semantic_families_share_one_split(self):
        rows = authored()
        source = {r["source_family"]: r for r in rows}
        groups = [
            (
                "speech_vs_task",
                "stop_reading",
                "speech_keep",
                "task_pause",
                "cancel_context",
                "task_cancel_negated",
            ),
            ("conditional", "hypothetical_en"),
            ("negation", "negation_en", "partial_rewrite"),
            ("quotation", "quoted_en", "task_quote"),
            ("status_context", "progress", "task_status_en"),
            ("missing_filename", "partial_object"),
            ("chitchat", "thanks", "greeting"),
        ]
        for group in groups:
            self.assertEqual(len({source[name]["family"] for name in group}), 1)
            self.assertEqual(len({source[name]["split"] for name in group}), 1)
        self.assertTrue(
            all(r["evaluation_boundary"] == "exposed-regression" for r in rows)
        )
        self.assertNotIn("locked-test", {r["split"] for r in rows})
        self.assertEqual(len(rows), 64)

    def test_wrong_dispatch_fails_even_if_fake_leaves_no_files(self):
        for turn in (0, 1):
            wrong = score_turn(turn, True, True)
            self.assertTrue(wrong["terminal_state_success"])
            self.assertTrue(wrong["unexpected_dispatch"])
            self.assertFalse(wrong["success"])
            self.assertTrue(score_turn(turn, False, True)["success"])
        self.assertFalse(score_turn(2, False, False)["success"])
        self.assertFalse(score_turn(2, True, False)["success"])
        self.assertTrue(score_turn(2, True, True)["success"])

    def test_nondev_loads_frozen_threshold_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            data, lock = Path(directory) / "data", Path(directory) / "lock"
            data.write_text("fixture")
            lock.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "decision_spec": decision_spec(RoutingConfig()),
                        "decision_spec_sha256": spec_sha256(
                            decision_spec(RoutingConfig())
                        ),
                        "variant": "refined",
                        "execute_threshold": 0.75,
                        "dataset_sha256": hashlib.sha256(
                            data.read_bytes()
                        ).hexdigest(),
                        "evaluation_boundary": "unseen-holdout",
                    }
                )
            )
            args = SimpleNamespace(
                split="locked-test",
                dataset=data,
                selection_lock=lock,
                variant=None,
                threshold=None,
            )
            self.assertEqual(resolve_config(args).execute_threshold, 0.75)
            self.assertEqual(resolve_config(args).variant, "refined")
            args.threshold = 0.65
            with self.assertRaises(ValueError):
                resolve_config(args)
            args.threshold, args.variant = None, "baseline"
            with self.assertRaises(ValueError):
                resolve_config(args)
            args.variant = None
            selection = json.loads(lock.read_text())
            selection["decision_spec_sha256"] = "wrong"
            lock.write_text(json.dumps(selection))
            with self.assertRaises(ValueError):
                resolve_config(args)
            selection["decision_spec_sha256"] = spec_sha256(
                decision_spec(RoutingConfig())
            )
            selection["evaluation_boundary"] = "exposed-regression"
            lock.write_text(json.dumps(selection))
            with self.assertRaises(ValueError):
                resolve_config(args)
            selection["evaluation_boundary"] = "unseen-holdout"
            lock.write_text(json.dumps(selection))
            data.write_text("changed")
            with self.assertRaises(ValueError):
                resolve_config(args)
            args.selection_lock = None
            with self.assertRaises(ValueError):
                resolve_config(args)

    def test_changed_spec_rejected_before_provider_or_key_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, lock = root / "data", root / "lock"
            data.write_text(
                json.dumps(
                    {
                        "split": "regression-test",
                        "evaluation_boundary": "exposed-regression",
                    }
                )
                + "\n"
            )
            spec = decision_spec(RoutingConfig())
            selection = {
                "schema_version": 2,
                "variant": "refined",
                "execute_threshold": 0.75,
                "dataset_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
                "evaluation_boundary": "exposed-regression",
                "decision_spec": spec,
                "decision_spec_sha256": spec_sha256(spec),
            }
            lock.write_text(json.dumps(selection))
            args = SimpleNamespace(
                split="regression",
                dataset=data,
                selection_lock=lock,
                variant=None,
                threshold=None,
                model=None,
                jev_key=root / "absent",
                scaledown_key=root / "absent",
                output=root / "output",
            )
            mutations = [
                patch.dict(routing.ROUTES, execute="changed route rubric"),
                patch.dict(routing.SUPPORT, supported="changed support rubric"),
                patch.object(routing, "REFINED", "changed instructions"),
                patch.object(routing, "SCALEDOWN_MULTI_LABEL", True),
                patch.object(
                    routing, "JEV_ENDPOINT", "https://example.invalid"
                ),
                patch.object(
                    routing, "INPUT_PROJECTION", [("text", "changed default")]
                ),
                patch.object(args, "model", "different-model"),
            ]
            for mutation in mutations:
                with mutation, patch(
                    "executor.evaluate.Router"
                ) as constructor, patch("executor.routing._post") as post:
                    with self.assertRaisesRegex(ValueError, "decision spec"):
                        asyncio.run(run(args))
                    constructor.assert_not_called()
                    post.assert_not_called()
            selection.pop("schema_version")
            lock.write_text(json.dumps(selection))
            with self.assertRaisesRegex(ValueError, "legacy"):
                resolve_config(args)
            selection["schema_version"] = 2
            selection["decision_spec"]["transport"]["timeout_seconds"] = 999
            lock.write_text(json.dumps(selection))
            with self.assertRaisesRegex(ValueError, "decision spec"):
                resolve_config(args)
            with self.assertRaisesRegex(ValueError, "decision spec"):
                Router("jev", root / "absent", expected_spec_sha256="incorrect")

    def test_effective_settings_are_fingerprinted(self):
        original = spec_sha256(decision_spec(RoutingConfig()))
        for override in (
            {"model": "other"},
            {"prompt_override": "other"},
            {"execute_threshold": 0.8},
            {"timeout": 7},
            {"variant": "baseline"},
        ):
            self.assertNotEqual(
                original, spec_sha256(decision_spec(RoutingConfig(**override)))
            )
        spec = decision_spec(RoutingConfig())
        scaledown = spec["providers"]["scaledown"]
        self.assertEqual(
            scaledown["model_selection"],
            {"mode": "omitted_provider_default", "resolved_id": None},
        )
        self.assertEqual(scaledown["compression"]["server"], "unknown")
        self.assertEqual(
            scaledown["compression"]["request_selector"], "omitted"
        )

    def test_requests_use_locked_snapshot_and_preserve_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_text("fake-test-key")
            config = RoutingConfig()
            spec = decision_spec(config)
            routers = [
                Router(provider, key, config, spec_sha256(spec))
                for provider in ("jev", "scaledown")
            ]
            sample = {
                "input": {"text": "你好", "gold": "must not leak"},
                "gold": "must not leak",
            }
            state = routing.model_input(sample)
            calls = []

            def post(url, body, headers, timeout):
                calls.append((url, body, timeout))
                if "questions" in body:
                    return {
                        "answers": {
                            name: {
                                "probabilities": {
                                    k: float(i == 0)
                                    for i, k in enumerate(labels)
                                }
                            }
                            for name, labels in (
                                ("route", routing.ROUTES),
                                ("support", routing.SUPPORT),
                            )
                        }
                    }
                return {
                    "scores": {
                        label["name"]: float(i == 0)
                        for i, label in enumerate(body["labels"])
                    }
                }

            with patch.dict(
                routing.ROUTES, execute="mutated after snapshot"
            ), patch.object(routing, "REFINED", "mutated"), patch(
                "executor.routing._post", side_effect=post
            ):
                results = [
                    asyncio.run(router.classify(sample)) for router in routers
                ]
            self.assertEqual(
                calls[0][1],
                {
                    "model": config.model,
                    "state": state,
                    "questions": spec["providers"]["jev"]["request"][
                        "questions"
                    ],
                },
            )
            actual = sorted(
                (json.dumps(body, sort_keys=True) for _, body, _ in calls[1:])
            )
            expected = sorted(
                json.dumps(
                    {
                        "text": json.dumps(state, ensure_ascii=False),
                        **request["body"],
                    },
                    sort_keys=True,
                )
                for request in spec["providers"]["scaledown"]["requests"]
            )
            self.assertEqual(actual, expected)
            self.assertTrue(
                all(timeout == config.timeout for _, _, timeout in calls)
            )
            self.assertTrue(
                all(
                    result["decision_spec_sha256"] == spec_sha256(spec)
                    for result in results
                )
            )
            self.assertTrue(
                all(result["route"] == "conversation" for result in results)
            )
