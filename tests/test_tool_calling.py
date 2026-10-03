import unittest

from knightagent.agent.parsing import parse_envelope, FormatError
from knightagent.tools.files import DEFINITIONS


class ParsingTests(unittest.TestCase):
    def test_duplicate_json_key(self):
        with self.assertRaises(FormatError):
            parse_envelope('{"content":"a","content":"b","tool_calls":[]}', DEFINITIONS)

    def test_valid_and_final(self):
        result = parse_envelope('{"content":"ler", "tool_calls":[{"name":"read_file", "arguments":{"path":"x"}}]}', DEFINITIONS)
        self.assertEqual(result.calls[0].name, "read_file")
        self.assertEqual(parse_envelope('{"content":"feito","tool_calls":[]}', DEFINITIONS).content, "feito")

    def test_invalid(self):
        for value in ('{}', '```json\n{}\n```', '[]', '{"content":1,"tool_calls":[]}', '{"content":"","tool_calls":[{"name":"shell","arguments":{}}]}', '{"content":"","tool_calls":[{"name":"read_file","arguments":{"path":"x","offset":true}}]}', '{"content":"","tool_calls":[{"name":"read_file","arguments":{"path":"x","offset":-1}}]}', '{"content":"","tool_calls":[{"name":"create_file","arguments":{"path":"x"}}]}'):
            with self.subTest(value=value), self.assertRaises(FormatError):
                parse_envelope(value, DEFINITIONS)
