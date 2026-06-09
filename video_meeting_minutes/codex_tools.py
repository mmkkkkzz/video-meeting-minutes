from __future__ import annotations

import json
from pathlib import Path

from .codex_app import CodexAppServerClient
from .models import FrameAnalysis, FrameEvent, TranscriptSegment
from .timefmt import format_time


def analyze_frame(
    client: CodexAppServerClient,
    frame: FrameEvent,
    *,
    model: str | None = None,
    effort: str | None = None,
) -> FrameAnalysis:
    prompt = f"""
この画像は会議動画から画面差分で抽出されたフレームです。
時刻: {format_time(frame.timestamp)}

画面の内容を日本語で詳述してください。議事録生成の根拠として使うため、単なる短い要約ではなく、画面を見ていない人にも状況が伝わる粒度で書いてください。

必ず以下の観点を含めてください。

1. 画面全体の種類
- Zoomの参加者画面、資料共有、ブラウザ、Notion、業務アプリ、設定画面など、何の画面かを説明する。

2. レイアウトと配置
- 画面の上部・左側・中央・右側・下部に何があるかを説明する。
- 表、サイドバー、メニュー、カード、モーダル、ボタン、一覧、入力欄などの配置を具体的に書く。

3. 読み取れる文字・項目
- 読める見出し、ボタン名、メニュー名、表の列名、名前、日付、数値、エラー文、通知文をできるだけ列挙する。
- 小さくて読めない部分は「小さくて判読困難」と明記する。

4. 画面上で起きていること
- 何を確認・操作・説明している場面に見えるかを、画像から分かる範囲で説明する。
- 画面遷移、選択状態、エラー、警告、空欄、強調表示があれば書く。

5. 会議上の意味
- この画面が会議の論点、決定事項、TODO、確認事項にどう関係しそうかを書く。
- 推測が必要な場合は「推測」と明示し、断定しない。

出力はMarkdownで、300〜800字程度を目安にしてください。情報量が多い画面では長くなって構いません。
""".strip()
    return FrameAnalysis(
        index=frame.index,
        timestamp=frame.timestamp,
        image_path=frame.path,
        analysis=client.ask(prompt, local_images=[frame.path], model=model, effort=effort),
    )


def analyze_frames(
    frames: list[FrameEvent],
    *,
    client: CodexAppServerClient,
    output_path: Path,
    model: str | None = None,
    effort: str | None = None,
) -> list[FrameAnalysis]:
    analyses: list[FrameAnalysis] = []
    for frame in frames:
        print(f"Analyzing frame {frame.index}/{len(frames)} at {format_time(frame.timestamp)}", flush=True)
        analyses.append(analyze_frame(client, frame, model=model, effort=effort))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([analysis.to_dict() for analysis in analyses], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return analyses


def transcript_for_prompt(segments: list[TranscriptSegment]) -> str:
    lines = []
    for segment in segments:
        speaker = f" {segment.speaker}" if segment.speaker else ""
        lines.append(
            f"[{format_time(segment.start)} - {format_time(segment.end)}{speaker}] {segment.text}"
        )
    return "\n".join(lines)


def visual_context_for_prompt(analyses: list[FrameAnalysis]) -> str:
    lines = []
    for analysis in analyses:
        lines.append(
            f"[{format_time(analysis.timestamp)}] frame {analysis.index}: {analysis.analysis}"
        )
    return "\n\n".join(lines)


def generate_minutes(
    *,
    client: CodexAppServerClient,
    video_name: str,
    transcript_segments: list[TranscriptSegment],
    frame_analyses: list[FrameAnalysis],
    model: str | None = None,
    effort: str | None = None,
) -> str:
    prompt = f"""
あなたは会議録作成担当です。
音声文字起こしと、動画画面の変化点ごとの画像解析を突き合わせて、日本語の議事録を作成してください。

制約:
- 音声で明示された内容と、画面に表示されていた内容を混同しない
- 画像解析は補助情報として扱い、断定しすぎない
- 話者ラベルがある場合は発言要旨に活用する。ただし名前との対応は明示情報がある場合だけ行う
- 不明点は不明として残す
- Markdownで出力
- 大見出しは下記テンプレートだけを使う。TODOと発言要旨の中では、必要に応じて小見出しや表で構造化してよい
- 決定事項とTODOは5W1Hを意識し、「誰が」「いつ」「どの画面・機能で」「何を」「なぜ」「どうする」を可能な限り含める
- 「修正する」「連携する」「確認する」だけで終わらせず、対象画面・対象機能・具体的な状態や問題を必ず書く
- 画面解析に対象画面や配置が含まれる場合は、それを使って「どの画面の話か」を補う
- 分からない要素は省略せず、「担当者不明」「期限不明」「対象画面不明」のように明記する

テンプレート:
# 議事録: {video_name}

## 参加者
- 確認できた参加者を列挙する。話者ラベルしか分からない場合は speaker_0 のように記載する。

## 決定事項
- 決定した内容を箇条書きにする。なければ「不明」。
- 各項目は「対象」「内容」「理由・背景」「決定者/関係者」「時期」が分かる粒度にする。

## TODO
- Markdown表で構造化する。
- 列は「トピック」「担当者」「対象画面/機能」「作業内容」「理由・背景」「期限」にする。
- 作業内容は具体的に書く。例: 「『会議』『議事録』が別列で同じ値として重複表示されている状態を1列に統合する」。

## 発言要旨
- 欠席者に共有する価値がある情報、後日参照する可能性が高い論点だけを書く。
- 時系列順に並べる必要はない。時間は書かない。
- トピック別に `### サービスの利益分配` のような小見出しで構造化する。
- トピック例: サービスの利益分配、改修状況報告、バグ報告、UI/導線改善、権限管理、現場運用、次回会議。
- 各トピック内は「背景」「論点」「主な意見・判断」「未決事項/リスク」の観点で整理する。不要な観点は省略してよい。
- 挨拶、謝意、雑談、聞き返し、画面操作の段取り、単なる相づち、結論やTODOに影響しない確認会話は書かない。
- 「原因」「背景」「判断理由」「懸念」「代替案」「合意に至らなかった論点」「次回判断に必要な情報」を優先する。
- 決定事項やTODOに載せた内容でも、背景や判断理由を補う価値がある場合は発言要旨に残す。
- 1項目は、後から読んだ人が「なぜこの話が重要だったか」まで分かる粒度にする。
- 目安は4〜8トピック。重要でない冒頭・終盤のやり取りを無理に残さない。

動画ファイル:
{video_name}

音声タイムライン:
{transcript_for_prompt(transcript_segments)}

画面タイムライン:
{visual_context_for_prompt(frame_analyses)}
""".strip()
    return client.ask(prompt, model=model, effort=effort)
