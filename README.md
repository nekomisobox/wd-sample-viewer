# WD Tag Sample Viewer

画像や動画（HTML5 `<video>` の表示中フレーム）から WD14 タグを抽出し、そのタグを元にサンプル画像を自動生成し、**WD Tag Sample Viewer**（`http://127.0.0.1:8777/`）に蓄積・表示するツールです。

## 概要

Chrome の右クリックメニューから、対象の画像または動画の現在のフレームを取得し、ローカル **bridge**（`http://127.0.0.1:8777/`）経由で Forge / ComfyUI へ送信します。
WD14 によるタグ抽出、Danbooru 辞書等を用いた日本語翻訳、およびサンプル画像の自動生成を行い、ビューア画面に蓄積・表示します。

- **対応バックエンド**:
  - `forge`: Forge / ReForge の txt2img API
  - `comfyui`: ComfyUI の txt2img ワークフロー
- **タグ・キャプション処理**: WD14 および任意の Florence モデルによる説明文生成は **bridge 内**で実行（ComfyUI ワークフローに WD14 ノードは不要）
- **自然文処理**: Florence による説明文生成に対応（ON/OFF 切替可能）
- **日本語翻訳**: Danbooru 辞書（`data/danbooru_translations_jp.csv`）＋非公式翻訳 API によるタグの日本語訳（**有料 API は使用しません**）

※本ツールは「元画像を img2img の入力にするツール」ではありません。右クリックした画像・動画は**タグ抽出のためだけ**に使用されます。

## セットアップ手順

初めてお使いになる方は、同梱の [README.txt](README.txt) に記載されているセットアップ手順をご参照ください。

## 設定

`config.txt` を編集することで、バックエンドや接続先 URL を変更できます。

```ini
backend=forge          # forge または comfyui を指定
http://127.0.0.1:7860  # APIのURL（1行目に記述しても可）

# --- ComfyUI 用の設定例 ---
# workflow=workflows/txt2img_sample.json
# node_positive=CLIP Text Encode Positive
# node_negative=CLIP Text Encode Negative
# node_ksampler=KSampler
# node_empty_latent=Empty Latent Image
```

### ComfyUI を使用する場合の注意点

- `workflows/txt2img_sample.json` を同梱しています。使用する環境に合わせて Checkpoint 名などを編集してください。
- ワークフローは **txt2img のみ**（Load Image / WD14 ノードは不要）で構成してください。WD14 や Florence の処理は bridge 内で実行されます。
- 終端ノードは必ず **Preview Image** にしてください（ComfyUI の `output/` フォルダを圧迫しないため）。
- bridge が `/view?type=temp` で取得し、`jobs/` フォルダ内に保存します。

## 翻訳

- 辞書: `data/danbooru_translations_jp.csv`
- 未知タグ / Florence 説明文: 非公式翻訳（Google 経由）
- API 失敗時: 辞書訳のみ＋「説明文の翻訳を取得できませんでした」（課金案内なし）

## 保存仕様

処理されたデータは以下の場所に保存されます。

- **元画像**: `jobs/{id}/input.png`
- **生成サンプル**: `jobs/{id}/output_001.png`

**生成画像側の保存抑制について:**

- **Forge**: `save_images=false` でローカル保存の抑制を試行します（Forge 側の設定に依存）。
- **ComfyUI**: `temp/` ディレクトリへの一時保存のみとなります（Preview Image ノード使用時）。

## WD Tag Sample Viewer（ビューア）

`http://127.0.0.1:8777/`（`start.bat` 起動中）

- 画像のドラッグ＆ドロップ、クリップボード貼り付け、画像 URL
- ジョブ一覧・プロンプトコピー
- **サンプル生成** ON/OFF（タグ抽出のみ / 生成あり）
- **Florence自然文** ON/OFF（VRAM 節約のため OFF 可。初回 ON 時はモデル読込で遅くなります）
- **Backend 接続状態**（接続済み / 未接続 / 更新ボタン）

## Chrome 拡張機能の使い方

拡張機能をインストールすると、右クリックメニューに以下の 2 つが追加されます。

1. **対象メニュー: 画像**
   - 「WDタグ+サンプル生成」
2. **対象メニュー: 動画（`<video>` 要素）**
   - 「WDタグ+サンプル生成（動画フレーム）」

どちらも bridge に送り、WD14 でタグ抽出 →（サンプル生成 ON なら）画像生成 → ビューアに結果を蓄積します。ページ上には拡張の簡易通知パネル（送信中・完了など）が表示されます。

※拡張機能をアップデートした際は、`chrome://extensions/` から必ず「再読み込み」を行ってください。

## 動画フレーム取得に関する注意事項

動画への対応は、ページ内の **HTML5 `<video>` 要素** に限ります。
右クリックした瞬間の「1 フレーム」を PNG 化してタグ抽出に使用します（動画全体のダウンロードや連続抽出ではありません）。

### 取得できる条件

- ページ内に `<video>` 要素が存在し、右クリック位置から特定できる
- 動画メタデータが読み込み済みで、`videoWidth` / `videoHeight` が取得可能
- 同一オリジン、または `drawImage` で Canvas に描画しても CORS による `tainted` エラーにならないソース

### 取得に失敗する主なケースとエラー

| 状況・原因 | 挙動・エラーメッセージ |
| :--- | :--- |
| 別ドメイン・CORS 制限 | `SecurityError` 相当（「サイト側の制限によりフレームを取得できません」） |
| DRM（Widevine 等）・暗号化 | フレームを Canvas に描画できず取得失敗 |
| iframe 内プレイヤー、Flash、独自 Canvas 再生 | 親ページから動画要素を参照できずメニューが出ない／取得失敗 |
| 読み込み前・解像度不明 | 「動画の解像度を取得できませんでした」 |
| 右クリック位置に video 要素がない | 「動画要素が見つかりませんでした」 |

**対処法:** 取得に失敗した場合は、該当フレームをスクリーンショットするか、画像をコピーして **WD Tag Sample Viewer**（`http://127.0.0.1:8777/`）へ直接ドラッグ＆ドロップ（または貼り付け）してタグ抽出を行ってください。

## License

MIT License — 詳細は [LICENSE](LICENSE) を参照してください。
