from video_meeting_minutes.scribe import transcript_segments
from video_meeting_minutes.timefmt import format_time


def test_format_time() -> None:
    assert format_time(65.4321) == "00:01:05.432"


def test_transcript_segments_groups_words() -> None:
    transcript = {
        "words": [
            {"type": "word", "text": "今日は", "start": 0.0, "end": 0.5},
            {"type": "spacing", "text": " "},
            {"type": "word", "text": "よろしくお願いします。", "start": 0.6, "end": 1.2},
            {"type": "word", "text": "次の", "start": 3.0, "end": 3.4},
            {"type": "spacing", "text": " "},
            {"type": "word", "text": "議題です。", "start": 3.5, "end": 4.0},
        ]
    }

    segments = transcript_segments(transcript)

    assert len(segments) == 2
    assert segments[0].text == "今日は よろしくお願いします。"
    assert segments[0].start == 0.0
    assert segments[0].end == 1.2
    assert segments[1].text == "次の 議題です。"
