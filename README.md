# video-meeting-minutes

動画会議ファイルから、音声文字起こしと画面変化の画像解析を組み合わせて議事録を作るCLIです。

## Features

- `ffmpeg` で動画から音声を抽出
- ElevenLabs Scribe v2 でタイムスタンプ付き文字起こし
- OpenCV でフレーム差分を検知し、画面が変わったタイミングだけ画像保存
- Codex app-server で抽出画像を解析
- 音声タイムラインと画面タイムラインを合わせて `minutes.md` を生成

## Requirements

- Python 3.11+
- uv
- ffmpeg / ffprobe
- ElevenLabs API key
- Codex CLI login

```bash
brew install ffmpeg
uv sync
cp .env.example .env
```

`.env`:

```bash
ELEVENLABS_API_KEY=...
ELEVENLABS_LANGUAGE_CODE=ja
ELEVENLABS_SCRIBE_MODEL=scribe_v2

# Codex app-server model defaults
CODEX_MODEL=
CODEX_VISION_MODEL=
CODEX_MINUTES_MODEL=
```

Codex側は `codex login` 済みである必要があります。

モデル指定:

- 画像解析: `CODEX_VISION_MODEL`
- 議事録生成: `CODEX_MINUTES_MODEL`
- 文字起こし: `ELEVENLABS_SCRIBE_MODEL`
- Codex共通のfallback: `CODEX_MODEL`

## Usage

```bash
uv run video-meeting-minutes path/to/meeting.mp4
```

用語補正を効かせる場合:

```bash
uv run video-meeting-minutes path/to/meeting.mp4 \
  --keyterms 勤怠管理 受給者証 事業所 ヘルパー 監査ログ ログインID
```

Codex解析をスキップして、音声抽出・フレーム抽出・文字起こしだけ行う場合:

```bash
uv run video-meeting-minutes path/to/meeting.mp4 --skip-vision --skip-minutes
```

## Output

```text
output/<video-name>_<timestamp>/
  audio/
    <video-name>.m4a
  frames/
    frame_0001_00-00-00.000.jpg
  transcript/
    elevenlabs_scribe_v2.txt
    elevenlabs_scribe_v2.json
  vision/
    frames.json
    frame_analysis.json
  manifest.json
  minutes.md
```

## Notes

- フレーム差分は `--frame-threshold`, `--min-frame-gap`, `--sample-fps` で調整できます。
- 画面共有の小さい文字や低解像度動画では、画像解析の精度が落ちます。
- 議事録生成では、音声で明示された内容と画面に映っていた内容を分けて扱うようCodex app-serverへ依頼します。
