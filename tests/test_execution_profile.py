from __future__ import annotations

import unittest

from arnaldo.capabilities.semantics import build_capability_need, summarize_capability_ids
from arnaldo.kernel.execution_profile import select_execution_profile


class CapabilitySemanticsTest(unittest.TestCase):
    def test_abstract_remote_families_get_inline_lookup_fallback(self) -> None:
        summary = summarize_capability_ids(["connector.*", "tool.*"])
        self.assertTrue(summary.supports_inline_lookup)
        self.assertFalse(summary.requires_full_pipeline)
        self.assertEqual(summary.inline_lookup_executor_ids, ("search.public_web",))

    def test_concrete_connector_requires_full_pipeline(self) -> None:
        summary = summarize_capability_ids(["connector.http.generic"])
        self.assertTrue(summary.requires_full_pipeline)
        self.assertFalse(summary.supports_inline_lookup)

    def test_build_capability_need_enriches_metadata(self) -> None:
        need = build_capability_need(
            "search.public_web",
            required=False,
            reason="lookup_publico",
        )
        self.assertEqual(need["family"], "search")
        self.assertEqual(need["locality"], "remote")
        self.assertEqual(need["access_mode"], "lookup")
        self.assertEqual(need["inline_lookup_executor_id"], "search.public_web")
        self.assertFalse(need["required"])
        self.assertEqual(need["reason"], "lookup_publico")

    def test_local_read_only_capabilities_support_inline_execution(self) -> None:
        summary = summarize_capability_ids(["filesystem.local.search", "shell.local.readonly"])
        self.assertTrue(summary.supports_inline_lookup)
        self.assertFalse(summary.requires_full_pipeline)
        self.assertEqual(
            summary.inline_lookup_executor_ids,
            ("filesystem.local.search", "shell.local.readonly"),
        )


class ExecutionProfileSelectionTest(unittest.TestCase):
    def test_intermediate_external_lookup_routes_inline(self) -> None:
        profile = select_execution_profile(
            level="intermediate",
            needs_external_data=True,
            capability_ids=["connector.*", "tool.*"],
        )
        self.assertEqual(profile.name, "inline_capability")
        self.assertTrue(profile.skip_full_pipeline)
        self.assertEqual(profile.inline_capability_ids, ("search.public_web",))

    def test_external_gap_without_capability_goes_full_pipeline(self) -> None:
        profile = select_execution_profile(
            level="intermediate",
            needs_external_data=True,
            capability_ids=[],
        )
        self.assertEqual(profile.name, "full_pipeline")
        self.assertFalse(profile.skip_full_pipeline)

    def test_conversational_request_routes_fast(self) -> None:
        profile = select_execution_profile(
            level="conversational",
            needs_external_data=False,
            capability_ids=[],
        )
        self.assertEqual(profile.name, "fast_response")
        self.assertTrue(profile.skip_full_pipeline)

    def test_intermediate_local_shell_routes_inline(self) -> None:
        profile = select_execution_profile(
            level="intermediate",
            needs_external_data=False,
            capability_ids=["shell.local.readonly"],
        )
        self.assertEqual(profile.name, "inline_capability")
        self.assertTrue(profile.skip_full_pipeline)
        self.assertEqual(profile.inline_capability_ids, ("shell.local.readonly",))


if __name__ == "__main__":
    unittest.main()
