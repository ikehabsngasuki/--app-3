# 英単語テストPDFジェネレーター

市販の単語帳や授業教材をもとに作成した単語リストから、英単語テスト用の問題PDFと解答PDFを生成するWebアプリです。
単語帳を選択し、問題数や出題形式を指定して、印刷しやすい形式のテストを作成できます。

## Features

- Excel（`.xlsx`）形式の単語リストをアップロード
- 登録済みの単語帳・教材データを選択
- 出題範囲、問題数、出題形式を指定
- 問題PDFと解答PDFを生成
- 作成済みPDFのダウンロード
- ローカル保存とS3互換ストレージの切り替え

## Tech Stack

- Python
- Flask
- pandas
- ReportLab
- HTML / CSS
- S3-compatible storage

## Data Policy

このリポジトリには、市販教材から作成した単語データ、スキャン画像、生成PDF、アップロード済みファイルは含めていません。
アプリケーション本体のみを公開し、利用時の教材データは各利用者の環境で管理する前提です。

## Excel Format

最低限、以下の列を持つExcelファイルを使用します。

| column | required | description |
| --- | --- | --- |
| `word` | yes | 出題する英単語・熟語 |
| `meaning` | yes | 解答となる日本語訳 |
| `book` | no | 教材名 |
| `section` | no | セクションや章 |
| `number` | no | 単語番号 |

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

必要に応じて、以下の環境変数を設定します。

```bash
export FLASK_SECRET_KEY="change-me"
export STORAGE_PROVIDER="local"
```
