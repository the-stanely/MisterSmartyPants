from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

import websearchMCP


class OpenRouterChatTests(unittest.TestCase):
    def test_routing_context_keeps_recent_dialogue_and_excludes_search_evidence(self) -> None:
        history = [
            {"role": "user", "content": "Let's discuss business casual."},
            {"role": "assistant", "content": "Long-sleeve oxfords are a versatile option."},
            {"role": "system", "content": "Prior web search context:\nvery large search payload"},
        ]

        self.assertEqual(
            websearchMCP.routing_context_messages(history),
            history[:2],
        )

    def test_decider_receives_conversation_before_latest_request(self) -> None:
        history = [
            {"role": "user", "content": "Help me choose business casual clothes."},
            {"role": "assistant", "content": "A long-sleeve oxford is a classic choice."},
        ]
        with patch("websearchMCP.chat_once", return_value="YES") as chat:
            should_search, _ = websearchMCP.decide_search_needed(
                "Would that work with chinos?", history
            )

        self.assertFalse(should_search)
        messages = chat.call_args.args[0]
        self.assertEqual(messages[1:3], history)
        self.assertIn("Would that work with chinos?", messages[-1]["content"])

    def test_planner_returns_a_contextual_search_query(self) -> None:
        history = [{"role": "assistant", "content": "We are discussing a Framework Laptop 16."}]
        with patch(
            "websearchMCP.chat_once",
            return_value='{"action":"SEARCH","query":"Framework Laptop 16 current price"}',
        ) as chat:
            should_search, reason, query = websearchMCP.plan_search_action(
                "How much does it cost now?", history
            )

        self.assertTrue(should_search)
        self.assertEqual(reason, "planner selected SEARCH")
        self.assertEqual(query, "Framework Laptop 16 current price")
        messages = chat.call_args.args[0]
        self.assertEqual(messages[1], history[0])
        self.assertEqual(messages[-1], {"role": "user", "content": "How much does it cost now?"})

    def test_planner_failure_answers_directly(self) -> None:
        with patch("websearchMCP.chat_once", side_effect=RuntimeError("provider unavailable")):
            should_search, reason, query = websearchMCP.plan_search_action("Explain chinos.", [])

        self.assertFalse(should_search)
        self.assertIn("planner failed; answering directly", reason)
        self.assertIsNone(query)

    def test_query_builder_receives_conversation_before_latest_request(self) -> None:
        history = [{"role": "assistant", "content": "We are discussing oxford shirts."}]
        with patch("websearchMCP.chat_once", return_value="oxford shirt chinos") as chat:
            query = websearchMCP.derive_search_query("What colors are most versatile?", history)

        self.assertEqual(query, "oxford shirt chinos")
        messages = chat.call_args.args[0]
        self.assertEqual(messages[1], history[0])
        self.assertEqual(messages[-1], {"role": "user", "content": "What colors are most versatile?"})
        self.assertNotIn("openrouter_model_chain", chat.call_args.kwargs)

    def test_only_referential_follow_ups_use_query_rewriting(self) -> None:
        history = [{"role": "assistant", "content": "We are discussing a Framework Laptop 16."}]

        self.assertTrue(websearchMCP.needs_contextual_query_rewrite("How much does it cost now?", history))
        self.assertFalse(
            websearchMCP.needs_contextual_query_rewrite(
                "What is the current price of a Framework Laptop 16?", history
            )
        )

    def test_standalone_search_skips_query_builder(self) -> None:
        session = websearchMCP.ChatSession(rich_output=False)
        session.locked = False
        session.llm_enabled = False
        session.history.append({"role": "assistant", "content": "We are discussing business casual clothing."})
        captured = StringIO()
        with patch.object(websearchMCP, "SEARCH_DECIDER", "python"), patch(
            "websearchMCP.decide_search_action", return_value=(True, "test", None)
        ), patch(
            "websearchMCP.derive_search_query"
        ) as query_builder, patch("websearchMCP.run_search", return_value="[]") as run_search, redirect_stdout(captured):
            session.run_query("What is the current price of a Framework Laptop 16?")

        query_builder.assert_not_called()
        self.assertEqual(run_search.call_args.kwargs["query"], "What is the current price of a Framework Laptop 16?")
        self.assertIn("Query builder skipped; standalone request", captured.getvalue())

    def test_search_uses_user_request_when_query_builder_fails(self) -> None:
        session = websearchMCP.ChatSession(rich_output=False)
        session.locked = False
        session.llm_enabled = False
        session.history.append({"role": "assistant", "content": "We are discussing business casual clothing."})
        captured = StringIO()
        with patch.object(websearchMCP, "SEARCH_DECIDER", "python"), patch(
            "websearchMCP.decide_search_action", return_value=(True, "test", None)
        ), patch(
            "websearchMCP.derive_search_query", side_effect=RuntimeError("provider unavailable")
        ), patch("websearchMCP.run_search", return_value="[]") as run_search, redirect_stdout(captured):
            session.run_query("Would that work with chinos?")

        self.assertEqual(run_search.call_args.kwargs["query"], "Would that work with chinos?")
        self.assertIn("failed; using user request", captured.getvalue())

    def test_uses_openrouter_chain_and_retries_after_failure(self) -> None:
        failed_response = Mock()
        failed_response.raise_for_status.side_effect = websearchMCP.requests.HTTPError("unavailable")
        successful_response = Mock()
        successful_response.raise_for_status.return_value = None
        successful_response.json.return_value = {
            "choices": [{"message": {"content": "OpenRouter answer"}}]
        }

        with patch.multiple(
            websearchMCP,
            USE_OPENROUTER=True,
            OPENROUTER_API_KEY="test-key",
            OPENROUTER_MODEL_CHAIN=("provider/first", "provider/second"),
            OPENROUTER_HTTP_REFERER="",
        ), patch("websearchMCP.requests.post", side_effect=[failed_response, successful_response]) as post:
            answer = websearchMCP.chat_once([{"role": "user", "content": "Hello"}], num_predict=123)

        self.assertEqual(answer, "OpenRouter answer")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["model"], "provider/first")
        self.assertEqual(post.call_args_list[1].kwargs["json"]["model"], "provider/second")
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 123)
        self.assertIn("Authorization", post.call_args.kwargs["headers"])
        self.assertEqual(websearchMCP.llm_model_label(), "provider/second")

    def test_uses_ollama_when_openrouter_is_disabled(self) -> None:
        ollama_response = Mock()
        ollama_response.raise_for_status.return_value = None
        ollama_response.json.return_value = {"message": {"content": "Ollama answer"}}

        with patch.object(websearchMCP, "USE_OPENROUTER", False), patch(
            "websearchMCP.requests.post", return_value=ollama_response
        ) as post:
            answer = websearchMCP.chat_once([{"role": "user", "content": "Hello"}])

        self.assertEqual(answer, "Ollama answer")
        self.assertEqual(post.call_args.args[0], websearchMCP.OLLAMA_API)

    def test_uses_a_dedicated_openrouter_chain_when_provided(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "Decider answer"}}]}

        with patch.multiple(
            websearchMCP,
            USE_OPENROUTER=True,
            OPENROUTER_API_KEY="test-key",
            OPENROUTER_MODEL_CHAIN=("answer/model",),
            OPENROUTER_HTTP_REFERER="",
        ), patch("websearchMCP.requests.post", return_value=response) as post:
            answer = websearchMCP.chat_once(
                [{"role": "user", "content": "Decide"}],
                openrouter_model_chain=("decider/first", "decider/second"),
            )

        self.assertEqual(answer, "Decider answer")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "decider/first")

    def test_memory_answers_do_not_append_links_from_prior_searches(self) -> None:
        session = websearchMCP.ChatSession(rich_output=False)
        session.locked = False
        session.search_enabled = False
        session.history.append(
            {
                "role": "system",
                "content": "Prior web search context:\nURL: https://example.com/unrelated",
            }
        )
        captured = StringIO()
        with patch("websearchMCP.answer_from_memory", return_value="Poland has a white-and-red flag."), redirect_stdout(captured):
            session.run_query("what's the flag of poland?")

        self.assertNotIn("Sources:", captured.getvalue())
        self.assertNotIn("https://example.com/unrelated", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
