import unittest
from unittest.mock import MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath("."))
from core.engine import call_llm_with_retry
import openai

class MockCompletionChoice:
    def __init__(self, content):
        self.message = MagicMock(content=content)

class MockCompletionResponse:
    def __init__(self, content="test output"):
        self.choices = [MockCompletionChoice(content)]
        self.usage = MagicMock(prompt_tokens=10, completion_tokens=10, total_tokens=20)

class TestLLMResilience(unittest.TestCase):
    def test_call_llm_with_retry_succeeds_first_time(self):
        client = MagicMock()
        client.chat.completions.create.return_value = MockCompletionResponse("all good")
        
        resp = call_llm_with_retry(client, {"model": "deepseek-chat", "messages": []})
        self.assertEqual(resp.choices[0].message.content, "all good")
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_call_llm_with_retry_recovers_from_unexpected_eof(self):
        client = MagicMock()
        # 第一次模拟抛出典型校园内网 SSL unexpected EOF 错误，第二次正常返回
        eof_err = openai.APIConnectionError(
            message="Connection error: [SSL: UNEXPECTED_EOF_WHILE_READING] unexpected eof while reading (_ssl.c:1007)",
            request=MagicMock()
        )
        success_resp = MockCompletionResponse("recovered on second attempt")
        client.chat.completions.create.side_effect = [eof_err, success_resp]

        resp = call_llm_with_retry(client, {"model": "deepseek-chat", "messages": []}, max_retries=3, initial_delay=0.01)
        self.assertEqual(resp.choices[0].message.content, "recovered on second attempt")
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_call_llm_with_retry_recovers_from_timeout(self):
        client = MagicMock()
        timeout_err = openai.APITimeoutError(request=MagicMock())
        success_resp = MockCompletionResponse("recovered from timeout")
        client.chat.completions.create.side_effect = [timeout_err, success_resp]

        resp = call_llm_with_retry(client, {"model": "deepseek-chat", "messages": []}, max_retries=3, initial_delay=0.01)
        self.assertEqual(resp.choices[0].message.content, "recovered from timeout")
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_call_llm_with_retry_raises_after_max_retries(self):
        client = MagicMock()
        eof_err = openai.APIConnectionError(
            message="Persistent unexpected eof while reading",
            request=MagicMock()
        )
        client.chat.completions.create.side_effect = eof_err

        with self.assertRaises(openai.APIConnectionError):
            call_llm_with_retry(client, {"model": "deepseek-chat", "messages": []}, max_retries=2, initial_delay=0.01)
        self.assertEqual(client.chat.completions.create.call_count, 2)

if __name__ == "__main__":
    unittest.main()
