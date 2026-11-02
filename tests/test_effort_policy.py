import unittest

from ai_orchestrator.effort_policy import (
    EffortMode,
    EffortPolicyError,
    ProfileSource,
    resolve_reasoning_profile,
    resolve_review_decision,
)


class EffortPolicyTest(unittest.TestCase):
    def test_supported_modes_adjust_only_reasoning_and_keep_model(self) -> None:
        for mode, current, expected, source in (
            (EffortMode.ECONOMY, "medium", "low", ProfileSource.MODE),
            (EffortMode.BALANCED, "medium", "medium", ProfileSource.ROUTING),
            (EffortMode.FOCUSED, "medium", "high", ProfileSource.MODE),
            (EffortMode.FOCUSED, "xhigh", "xhigh", ProfileSource.ROUTING),
        ):
            with self.subTest(mode=mode, current=current):
                result = resolve_reasoning_profile(
                    mode=mode,
                    provider_id="codex",
                    model="gpt-6-sol",
                    reasoning_effort=current,
                    profile_source=ProfileSource.ROUTING,
                )
                self.assertEqual(result.model, "gpt-6-sol")
                self.assertEqual(result.reasoning_effort, expected)
                self.assertEqual(result.profile_source, source)
                self.assertEqual(result.unsupported_effects, ())

    def test_manual_and_legacy_profiles_are_preserved(self) -> None:
        for source, effort in ((ProfileSource.MANUAL, "medium"), (ProfileSource.LEGACY, "unknown-old-value")):
            with self.subTest(source=source):
                result = resolve_reasoning_profile(
                    mode=EffortMode.ECONOMY,
                    provider_id="codex",
                    model="gpt-6-sol",
                    reasoning_effort=effort,
                    profile_source=source,
                )
                self.assertEqual(result.reasoning_effort, effort)
                self.assertEqual(result.profile_source, source)

    def test_mode_profile_uses_original_routing_reasoning_as_baseline(self) -> None:
        focused = resolve_reasoning_profile(
            mode="focused", provider_id="codex", model="gpt-6-sol", reasoning_effort="low",
            profile_source=ProfileSource.MODE, baseline_reasoning_effort="xhigh",
        )
        self.assertEqual(focused.reasoning_effort, "xhigh")
        self.assertEqual(focused.profile_source, ProfileSource.ROUTING)
        balanced = resolve_reasoning_profile(
            mode="balanced", provider_id="codex", model="gpt-6-sol", reasoning_effort="low",
            profile_source=ProfileSource.MODE, baseline_reasoning_effort="medium",
        )
        self.assertEqual(balanced.reasoning_effort, "medium")
        self.assertEqual(balanced.profile_source, ProfileSource.ROUTING)
        missing = resolve_reasoning_profile(
            mode="balanced", provider_id="codex", model="gpt-6-sol", reasoning_effort="low",
            profile_source=ProfileSource.MODE,
        )
        self.assertEqual(missing.unsupported_effects, ("mode_profile_baseline_missing",))

    def test_unsupported_automatic_adjustment_is_reported(self) -> None:
        result = resolve_reasoning_profile(
            mode=EffortMode.FOCUSED,
            provider_id="custom",
            model="local-model",
            reasoning_effort="",
            profile_source=ProfileSource.ROUTING,
        )
        self.assertEqual(result.reasoning_effort, "")
        self.assertEqual(result.unsupported_effects, ("reasoning_auto_adjustment_unsupported",))

    def test_invalid_mode_source_and_explicit_reasoning_fail(self) -> None:
        base = {"provider_id": "codex", "model": "gpt-6-sol", "reasoning_effort": "medium", "profile_source": "routing"}
        with self.assertRaisesRegex(EffortPolicyError, "unsupported effort mode"):
            resolve_reasoning_profile(mode="turbo", **base)
        with self.assertRaisesRegex(EffortPolicyError, "unsupported profile source"):
            resolve_reasoning_profile(mode=EffortMode.BALANCED, **{**base, "profile_source": "unknown"})
        with self.assertRaisesRegex(EffortPolicyError, "unsupported reasoning effort"):
            resolve_reasoning_profile(mode=EffortMode.ECONOMY, **{**base, "reasoning_effort": "extreme", "profile_source": "manual"})

    def test_required_or_explicit_review_is_never_removed(self) -> None:
        for mode in EffortMode:
            with self.subTest(mode=mode):
                required = resolve_review_decision(
                    mode=mode,
                    required=True,
                    explicitly_requested=False,
                    reviewer_agent_id="reviewer",
                    is_code_change=True,
                    is_automatic=True,
                    reviewer_available=True,
                )
                explicit = resolve_review_decision(
                    mode=mode,
                    required=False,
                    explicitly_requested=True,
                    reviewer_agent_id="reviewer",
                    is_code_change=True,
                    is_automatic=True,
                    reviewer_available=True,
                )
                self.assertTrue(required.required)
                self.assertFalse(required.policy_added)
                self.assertTrue(explicit.optional)
                self.assertFalse(explicit.policy_added)

    def test_focused_review_is_only_added_for_automatic_code_changes(self) -> None:
        for is_code_change, is_automatic, existing_reviewer, expected in (
            (True, True, "", True),
            (False, True, "", False),
            (True, False, "", False),
            (True, True, "reviewer", False),
        ):
            with self.subTest(code=is_code_change, automatic=is_automatic, existing=existing_reviewer):
                result = resolve_review_decision(
                    mode=EffortMode.FOCUSED,
                    required=False,
                    explicitly_requested=False,
                    reviewer_agent_id=existing_reviewer,
                    is_code_change=is_code_change,
                    is_automatic=is_automatic,
                    reviewer_available=True,
                )
                self.assertEqual(result.policy_added, expected)
                self.assertEqual(result.requires_reviewer, expected)

    def test_missing_reviewer_is_visible_instead_of_skipped(self) -> None:
        result = resolve_review_decision(
            mode=EffortMode.FOCUSED,
            required=False,
            explicitly_requested=False,
            reviewer_agent_id="",
            is_code_change=True,
            is_automatic=True,
            reviewer_available=False,
        )
        self.assertTrue(result.optional)
        self.assertTrue(result.requires_reviewer)
        self.assertEqual(result.unsupported_effects, ("reviewer_unavailable",))


if __name__ == "__main__":
    unittest.main()
