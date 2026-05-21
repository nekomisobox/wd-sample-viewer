WD Tag Sample Viewer
====================

画像から WD14 タグを抽出し、そのタグでサンプル画像を生成して Chrome 上に表示するツールです。

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

5. Webページ上の画像を右クリックしてください。

   「WDタグ+サンプル生成」を押すと、タグ抽出とサンプル生成が始まります。
   送信後、Chrome取込ページが新しいタブで開きます。
   待機中、処理中、完了した結果はそのページに蓄積されます。


Chrome取込ページ
----------------

start.bat の起動中は、以下のページが使えます。

http://127.0.0.1:8777/

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

Chrome取込ページ（http://127.0.0.1:8777/）の **「Florence自然文」スイッチ** で ON/OFF します。
config.txt ではありません。

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

width:
サンプル画像の横幅

height:
サンプル画像の高さ

steps:
生成ステップ

cfg_scale:
CFG Scale

sampler_name:
サンプラー名

batch_size:
生成枚数

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
タグの前に足すプロンプト

prompt_suffix:
タグの後に足すプロンプト

negative_prompt:
ネガティブプロンプト


注意
----

Forge/ReForgeは --api 付きで起動してください。
Python 3.10以降が必要です。
生成結果はForge/ReForge側の現在設定の影響を受けます。
初回起動時にWD14モデルをダウンロードします。
Florenceを有効にすると初回セットアップがかなり重くなります。
動画フレームはサイト側の制限により取得できない場合があります。
jobs フォルダに取込履歴と生成画像が保存されます。

.venv について
--------------

リポジトリには .venv を含めていません。
各 PC で start.bat 実行時に自動作成されます。
