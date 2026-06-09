from io import StringIO

from video_meeting_minutes.codex_app import CodexAppServerClient


def test_codex_client_extracts_agent_delta() -> None:
    client = object.__new__(CodexAppServerClient)
    client._process = type(
        "FakeProcess",
        (),
        {
            "stdout": StringIO(
                '{"method":"item/agentMessage/delta","params":{"turnId":"t1","delta":"こん"}}\n'
                '{"method":"item/agentMessage/delta","params":{"turnId":"t1","delta":"にちは"}}\n'
                '{"method":"turn/completed","params":{"turn":{"error":null},"turnId":"t1"}}\n'
            )
        },
    )()
    client.timeout_seconds = 1

    assert client._read_until_turn_completed("t1") == "こんにちは"
