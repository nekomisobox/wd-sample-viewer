WD Tag Sample Viewer
====================

画像・動画（HTML5 video の表示中フレーム）から WD14 タグを抽出し、そのタグでサンプル画像を生成して Chrome 上に表示するツールです。

- backend=forge … Forge/ReForge txt2img
- backend=comfyui … ComfyUI txt2img ワークフロー
- WD14 / Florence は bridge 内で実行（ComfyUI に WD14 は入れない）
- プロンプトの日本語訳あり（辞書 + 非公式翻訳、有料 API 非対応）

元画像を img2img の入力にするツールではありません。
右クリックした画像はタグ抽出のためだけに使います。


使い方
------

1. config.txt を開いて backend と api_url を設定してください。

   例（Forge）:
   backend=forge
   http://127.0.0.1:7860

   例（ComfyUI）:
   backend=comfyui
   http://127.0.0.1:8188

   bridge（ビューア）の待受アドレス（既定 127.0.0.1:8777）:
   bridge_host=127.0.0.1
   bridge_port=8777
   変更したら start.bat 再起動と chrome://extensions/ の再読み込みが必要です。

   【重要】同梱 workflow はサンプルです。必ず以下を編集してください。
   ・ckpt_name … 自分の checkpoint ファイル名（必須。これ無しでは動きません）
   ・自作 workflow … Save (API Format) の JSON のみ使用可（通常保存は動きません）
   ComfyUI 利用時は workflows/txt2img_sample.json の ckpt_name を
   自分の checkpoints フォルダのモデル名に必ず変更してください。
   自作 workflow は ComfyUI の Save (API Format) で保存した JSON を使うこと。
   seed は JSON の値ではなく、実行ごとに bridge がランダムで上書きします。
   config.txt の workflow / node_* は同梱 JSON のままならコメントのままで可。

2. 生成バックエンドを起動してください。

   Forge の場合: --api 付きで起動
   ComfyUI の場合: 通常起動で OK

3. start.bat をダブルクリックしてください。

   初回はPython環境、必要ライブラリ、WD14モデルの準備で時間がかかります。
   Bridge ready と表示されたら、ウィンドウを閉じずにそのまま置いてください。

   Pythonが見つからないと言われた場合:
   Python 3.10以降を https://www.python.org/downloads/ からインストールしてください。
   インストール時は Add python.exe to PATH にチェックを入れてください。

   Microsoft Storeを開けと言われる場合:
   Windowsの設定から Python の実行エイリアスをOFFにしてください。
   Settings > Apps > Advanced app settings > App execution aliases

4. Chromeで chrome://extensions/ を開いてください。

   デベロッパーモードをONにします。
   「パッケージ化されていない拡張機能を読み込む」を押します。
   chrome_extension フォルダを選択してください。

5. Webページ上の画像または動画を右クリックしてください。

   画像: 「WDタグ+サンプル生成」
   動画（HTML5 video）: 「WDタグ+サンプル生成（動画フレーム）」
   いずれもタグ抽出と（設定ON時）サンプル生成が始まります。
   送信後、WD Tag Sample Viewer が新しいタブで開きます。
   待機中、処理中、完了した結果はそのページに蓄積されます。

   動画は右クリックした瞬間の1フレームのみ使います。
   別ドメイン動画・DRM・iframe内プレイヤーなどはサイト側の制限で
   フレームを取得できないことがあります。その場合は画像として
   ビューアに貼り付けるか、スクリーンショットを使ってください。


WD Tag Sample Viewer（ビューア）
--------------------------------

start.bat の起動中は、config.txt の bridge_host:bridge_port で開く
ビューア（既定 http://127.0.0.1:8777/）が使えます。

このページでは以下ができます。

画像ファイルのドラッグ&ドロップ
クリップボード画像の貼り付け
画像URLの貼り付け
処理待ち、処理中、完了の確認
プロンプトのコピー


生成に使われるモデル
--------------------

サンプル生成に使われるモデルは、Forge/ReForge側で現在選択されているCheckpointです。
モデルを変えたい場合は、Forge/ReForge側でCheckpointを変更してください。

このツール側ではCheckpointを切り替えません。


Florence自然文キャプション
--------------------------

WD Tag Sample Viewer（bridge の URL）の **「Florence自然文」スイッチ** で ON/OFF します。
変更は preferences.json に保存されます（config.txt ではありません）。

- OFF: VRAM に Florence モデルを載せません
- ON 後の初回ジョブ: モデル読込で遅くなります（2回目以降は速い）
- OFF に戻すと VRAM から解放します

Florenceの詳細設定（モデル名など）は config.txt の固定プリセットです。
通常は変更しないでください。


ReForgeについて
---------------

ReForgeでも、A1111/Forge互換APIが有効なら動く想定です。

以下のURLがブラウザで返る状態にしてください。

http://127.0.0.1:7860/sdapi/v1/options

ポートが違う場合は config.txt のURLも変更してください。


config.txt の主な設定
---------------------

bridge_host:
bridge の待受ホスト（既定 127.0.0.1）

bridge_port:
bridge の待受ポート（既定 8777）

bridge_url:
bridge を URL でまとめて指定（指定時は bridge_host/port より優先）

general_threshold:
WD14の一般タグの採用しきい値

character_threshold:
WD14のキャラタグの採用しきい値

max_tags:
最大タグ数

florence_model:
Florenceモデル名。通常は変更しない

florence_task:
Florenceのタスク。通常は変更しない

florence_max_new_tokens:
Florenceの最大生成トークン数。通常は変更しない

prompt_prefix:
サンプル生成時のみ先頭に付与。タグ一覧には表示されない

prompt_suffix:
サンプル生成時のみ末尾に付与（masterpiece, best quality 等）。タグ一覧には表示されない

negative_prompt:
ネガティブプロンプト（Forge は API 送信、ComfyUI は workflow の負 CLIP に注入）

サンプル生成の解像度・steps・sampler・モデル等:
Forge/ReForge は txt2img タブの普段の設定。ComfyUI は workflow JSON。
bridge はポジ・ネガ（と ComfyUI の seed のみ）を渡します。旧 width/steps 等の config 行は無視されます。


注意
----

Forge/ReForgeは --api 付きで起動してください。
Python 3.10以降が必要です。
生成結果はForge/ReForge側の現在設定の影響を受けます。
初回起動時にWD14モデルをダウンロードします。
Florenceを有効にすると初回セットアップがかなり重くなります。
Florenceで forced_bos_token_id エラーは transformers が新しすぎます。
timm / einops が無いエラーは requirements-florence.txt の未インストールです。
.venv\.florence-installed-v3 を削除して start.bat を再実行するか、
.venv\Scripts\python.exe -m pip install -r requirements-florence.txt を実行してください。
動画フレームは HTML5 video のみ対応。CORS/DRM/iframe 等により
取得できない場合があります（README.md の「動画フレームの取得」を参照）。
jobs フォルダにジョブ履歴と生成画像が保存されます。

.venv について
--------------

リポジトリには .venv を含めていません。
各 PC で start.bat 実行時に自動作成されます。
