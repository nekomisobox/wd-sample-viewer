# WD Tag Sample Viewer

画像・動画（HTML5 `<video>` の表示中フレーム）から WD14 タグを抽出し、そのタグでサンプル画像を生成して Chrome 上に表示するツールです。

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

## WD Tag Sample Viewer（ビューア）

`http://127.0.0.1:8777/` — 画像のドロップ／貼り付け、ジョブ一覧、設定スイッチ。

- **サンプル生成**: ON/OFF（タグのみ / 生成あり）
- **Florence自然文**: ON/OFF（UI スイッチ。OFF で VRAM 解放、初回 ON は読込で遅い）

## Chrome 拡張

右クリックメニュー（2種類）:

| 対象 | メニュー |
|---|---|
| 画像 | **WDタグ+サンプル生成** |
| 動画（`<video>` 要素） | **WDタグ+サンプル生成（動画フレーム）** |

どちらも bridge に送り、WD14 でタグ抽出 →（設定が ON なら）サンプル生成 → ビューアに結果を蓄積します。

拡張を更新したら `chrome://extensions/` で再読み込みしてください。

## 動画フレームの取得（注意事項）

動画対応は **ページ内の HTML5 `<video>` 要素** に限ります。右クリックした瞬間の **1フレーム** を PNG 化してタグ抽出に使います（動画ファイル全体のダウンロードや連続フレーム抽出ではありません）。

### 取得できる場合

- ページに `<video>` があり、右クリックした要素（またはその上）からその video が特定できる
- 動画のメタデータが読み込まれ、`videoWidth` / `videoHeight` が取れる（真っ黒・0px のときは失敗）
- 同一オリジン、または `drawImage` で canvas に描画しても **tainted にならない** ソース（サイトの CORS 設定次第）

### 取得できない・失敗しやすい場合

| 状況 | 挙動 |
|---|---|
| 別ドメイン・CORS 制限の動画 | `SecurityError` 相当 →「サイト側の制限によりフレームを取得できません」 |
| DRM（Widevine 等）・暗号化ストリーム | フレームを canvas に描画できないことが多い |
| iframe 内のプレイヤー、Flash 系、独自 canvas 再生 | 親ページから `<video>` を参照できずメニューが出ない／取得失敗 |
| まだ読み込み前・解像度不明 | 「動画の解像度を取得できませんでした」 |
| 右クリック位置に video がない | 「動画要素が見つかりませんでした」 |

**対処の例:** 該当フレームをスクリーンショットする、または WD Tag Sample Viewer（`http://127.0.0.1:8777/`）へ画像をドラッグ＆ドロップ／貼り付けしてタグ抽出する。
