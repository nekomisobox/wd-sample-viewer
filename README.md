# WD Tag Sample Viewer

画像から WD14 タグを抽出し、そのタグでサンプル画像を生成して Chrome 上に表示するツールです。

初めて使う方は [README.txt](README.txt) にセットアップ手順があります。

- **backend=forge**: Forge/ReForge の txt2img API
- **backend=comfyui**: ComfyUI の txt2img ワークフロー（Preview Image 終端）
- WD14 / 任意 Florence は **bridge 内**で実行（ComfyUI ワークフローに WD14 は入れない）
- プロンプトの **日本語訳**（Danbooru 辞書 + 非公式翻訳 API、有料 API 非対応）

元画像を img2img の入力にするツールではありません。右クリックした画像はタグ抽出のためだけに使います。

## config.txt

```ini
backend=forge          # forge または comfyui
http://127.0.0.1:7860  # api_url（1行目でも可）

# ComfyUI 用
# workflow=workflows/txt2img_sample.json
# node_positive=CLIP Text Encode Positive
# node_negative=CLIP Text Encode Negative
# node_ksampler=KSampler
# node_empty_latent=Empty Latent Image
```

## ComfyUI ワークフロー

`workflows/txt2img_sample.json` を同梱。Checkpoint 名などは利用環境に合わせて編集してください。

- txt2img のみ（Load Image / WD14 なし）
- 終端は **Preview Image**（ComfyUI `output/` に永久保存しない）
- bridge が `/view?type=temp` で取得し `jobs/` に保存

## 翻訳

- 辞書: `data/danbooru_translations_jp.csv`
- 未知タグ / Florence 説明文: 非公式 Google 翻訳
- API 失敗時: 辞書訳のみ + 「説明文の翻訳を取得できませんでした」（課金案内なし）

## 保存

| ファイル | 場所 |
|---|---|
| 元画像 | `jobs/{id}/input.png` |
| 生成サンプル | `jobs/{id}/output_001.png` |
| Forge 側 | `save_images=false` で抑制を試行（設定次第） |
| ComfyUI 側 | `temp/` のみ（Preview Image） |

## Chrome 取込ページ

- **サンプル生成**: ON/OFF（タグのみ / 生成あり）
- **Florence自然文**: ON/OFF（UI スイッチ。OFF で VRAM 解放、初回 ON は読込で遅い）

## Chrome 拡張

右クリックメニュー: **WDタグ+サンプル生成**

拡張を更新したら `chrome://extensions/` で再読み込みしてください。
