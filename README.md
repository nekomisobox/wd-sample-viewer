# WD Tag Sample Viewer
<img width="498" height="628" alt="image" src="https://github.com/user-attachments/assets/4d92e91c-3f74-48c7-82fc-fe9361f65e88" />

<img width="1919" height="840" alt="image" src="https://github.com/user-attachments/assets/109fd211-46e2-417f-8434-5d02cbde85a0" />

画像や動画（HTML5 `<video>` の表示中フレーム）から WD14 タグを抽出し、そのタグを元にサンプル画像を自動生成し、**WD Tag Sample Viewer**（bridge / ビューア）に蓄積・表示するツールです。

## 概要

Chrome の右クリックメニューから、対象の画像または動画の現在のフレームを取得し、ローカル **bridge**（`config.txt` の `bridge_host` / `bridge_port`）経由で Forge / ComfyUI へ送信します。
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
http://127.0.0.1:7860  # 生成APIのURL（1行目に記述しても可）

# bridge（WD Tag Sample Viewer）の待受（既定: 127.0.0.1:8777）
bridge_host=127.0.0.1
bridge_port=8777
# bridge_url=http://127.0.0.1:8777  # まとめて指定する場合（host/port より優先）

# --- ComfyUI 用の設定例 ---
# workflow=workflows/txt2img_sample.json
# node_positive=CLIP Text Encode Positive
# node_negative=CLIP Text Encode Negative
# node_ksampler=KSampler
```

### ComfyUI を使用する場合の注意点

> **ComfyUI 利用者へ（必読）**  
> 同梱の `workflows/txt2img_sample.json` は**サンプル**です。**このままでは動きません。**  
> 必ず次の **2 点** を自分の環境用に直してください。
>
> 1. **【必須】モデル（Checkpoint）指定** — `CheckpointLoaderSimple` の `ckpt_name` を、ComfyUI の `models/checkpoints/` にある**実ファイル名**に変更（例: `your_model.safetensors`）。初期値 `model.safetensors` のままは**失敗します**。  
> 2. **【必須】API 形式のワークフロー** — 自作 workflow は ComfyUI で **Save (API Format)** で保存した JSON のみ使用可。通常のワークフロー保存形式は**そのままでは動きません**。
>
> 上記を直さないと、接続できていてもプロンプト投入時にエラーになります。

- `config.txt` で `backend=comfyui` と ComfyUI の URL（例: `http://127.0.0.1:8188`）を指定してください。
- **【必須】モデル指定 — 編集しないと動きません。** `workflows/txt2img_sample.json` の `CheckpointLoaderSimple` → `ckpt_name` を**必ず**自分の `.safetensors` 名に変更してください。
- **【必須】API 形式 — これ以外は動きません。** 自作 workflow は **Save (API Format)** の JSON のみ。同梱 `txt2img_sample.json` は API 形式済みですが、**モデル名の変更は必須**です。
- **seed（シード）:** 実行のたびに bridge が `KSampler` の seed を **ランダム値で上書き**します（ワークフロー JSON の seed 値は使われません）。解像度・steps・sampler 等は workflow JSON のままです。
- `config.txt` の `workflow` / `node_*` の行は、同梱ワークフローをそのまま使う限りコメントのままで構いません（コード側のデフォルトと一致しています）。別 JSON を使う場合やノードの `_meta.title` が違う場合だけ、コメントを外して上書きしてください。
- ワークフローは **txt2img のみ**（Load Image / WD14 ノードは不要）で構成してください。WD14 や Florence の処理は bridge 内で実行されます。
- 終端ノードは必ず **Preview Image** にしてください（ComfyUI の `output/` フォルダを圧迫しないため）。
- bridge が `/view?type=temp` で取得し、`jobs/` フォルダ内に保存します。

### サンプル生成時に bridge が渡すもの

bridge はタグから組み立てた **ポジティブ** と `config.txt` の **ネガティブ** だけを各 backend に渡します。解像度・steps・sampler・モデル等は **backend 側の普段の設定** に任せます。

| 項目 | Forge / ReForge | ComfyUI |
| --- | --- | --- |
| ポジティブ | txt2img API の `prompt` | workflow の正 CLIP ノード |
| ネガティブ | API の `negative_prompt` | workflow の負 CLIP ノード |
| seed | Forge UI の設定 | bridge が **毎回ランダム** で `KSampler` に注入 |
| 解像度・steps・sampler・batch・モデル | **Forge の txt2img タブ** | **workflow JSON** |

`prompt_prefix` / `prompt_suffix` はポジ組み立て用（タグの前後に付与。Quality タグは通常 `prompt_suffix`）。ビューアのタグ一覧には表示されません。

旧 `config.txt` の `width` / `height` / `steps` 等は読み込まれません（残していても無視されます）。

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

`config.txt` の bridge アドレス（既定 `http://127.0.0.1:8777/`、`start.bat` 起動中）

`bridge_host` / `bridge_port` を変更したら **start.bat を再起動**し、`chrome://extensions/` で拡張を **再読み込み**してください（`chrome_extension/src/bridge_config.js` が自動更新されます）。

- 画像のドラッグ＆ドロップ、クリップボード貼り付け、画像 URL
- ジョブ一覧・プロンプトコピー
- **サンプル生成** ON/OFF（タグ抽出のみ / 生成あり）— 変更は `preferences.json` に保存
- **Florence自然文** ON/OFF（VRAM 節約のため OFF 可。初回 ON 時はモデル読込で遅くなります）— 同上
- Florence は **transformers 4.41.2 以上 4.50 未満**、および **timm / einops** が必要です（`requirements-florence.txt` で自動インストール）。エラー時は `.venv\.florence-installed-v3` を削除して `start.bat` を再実行するか、`.venv\Scripts\python.exe -m pip install -r requirements-florence.txt` を実行してください。
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

**対処法:** 取得に失敗した場合は、該当フレームをスクリーンショットするか、画像をコピーして **WD Tag Sample Viewer**（bridge の URL）へ直接ドラッグ＆ドロップ（または貼り付け）してタグ抽出を行ってください。

## トラブルシュート（初回 WD14 モデル `model.onnx` のダウンロード）

初回のタグ抽出時、bridge が `models/wd14/model.onnx` を自動ダウンロードします。Windows で次のエラーが出ることがあります。

`[WinError 32] プロセスはファイルにアクセスできません。別のプロセスが使用中です。`

| 確認項目 | 対処 |
| :--- | :--- |
| `start.bat` を複数起動していないか | 開いている bridge コンソールをすべて閉じ、**1 つだけ**再起動 |
| 別フォルダのコピーでも bridge が動いていないか | 検証用コピーだけ使う場合は、元フォルダ側の bridge を停止 |
| `models/wd14/model.onnx` が既にあるか | サイズが十分（数十 MB）なら DL 不要。`model.onnx.tmp` だけ残っていれば削除してよい |
| ダウンロードが途中で止まった | bridge を終了 → `model.onnx.tmp` を削除 → bridge を 1 つ起動 → 画像を 1 件送って再試行 |

ウイルス対策ソフトがダウンロード直後にファイルをスキャンしている場合も、一時的に同様のエラーになることがあります。bridge はリトライしますが、解消しないときは上記を確認してください。

## License

MIT License — 詳細は [LICENSE](LICENSE) を参照してください。
