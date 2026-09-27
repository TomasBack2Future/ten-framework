"""Regression protection for family grouping, selection locks and ablation."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from executor.ablation import score_turn
from executor.build_dataset import authored
from executor.evaluate import resolve_config
from executor.routing import REFINED


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
                        "variant": "refined",
                        "execute_threshold": 0.75,
                        "dataset_sha256": hashlib.sha256(
                            data.read_bytes()
                        ).hexdigest(),
                        "prompt_sha256": hashlib.sha256(
                            REFINED.encode()
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
            selection["prompt_sha256"] = "wrong"
            lock.write_text(json.dumps(selection))
            with self.assertRaises(ValueError):
                resolve_config(args)
            selection["prompt_sha256"] = hashlib.sha256(
                REFINED.encode()
            ).hexdigest()
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
