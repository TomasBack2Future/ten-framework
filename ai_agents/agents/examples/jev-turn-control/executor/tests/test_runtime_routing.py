"""Runtime routing delegates to the session provider without executing work."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from executor.routing import RuntimeRouter


class RuntimeRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_provider_receives_only_visible_fields(self):
        decision = {"route": "wait", "support": "wait", "provider": "sd_jev"}
        provider = SimpleNamespace(route=AsyncMock(return_value=decision))
        router = RuntimeRouter(provider)
        actual = await router.classify(
            {
                "input": {
                    "text": "Create a report",
                    "stable": False,
                    "private_goal": "hidden",
                },
                "gold": "execute",
            }
        )
        self.assertEqual(actual, decision)
        provider.route.assert_awaited_once_with(
            {
                "text": "Create a report",
                "history": [],
                "active_tasks": [],
                "capabilities": [],
                "stable": False,
            }
        )

    async def test_provider_failure_propagates_without_actionable_fallback(
        self,
    ):
        provider = SimpleNamespace(route=AsyncMock(side_effect=TimeoutError))
        with self.assertRaises(TimeoutError):
            await RuntimeRouter(provider).classify({"input": {}})
