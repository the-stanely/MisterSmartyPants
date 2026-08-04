from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

import websearchMCP


class OpenRouterChatTests(unittest.TestCase):
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
