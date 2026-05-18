# YouTube Loop Trainer

英語シャドーイング・発表練習用の簡易Webアプリです。  
YouTube URLと開始時間・終了時間を入力すると、その区間だけを埋め込み再生します。

## ローカル実行

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Renderでの設定

- Build Command

```bash
pip install -r requirements.txt
```

- Start Command

```bash
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

## 注意

このアプリは動画を保存・加工・再配布しません。  
YouTubeの埋め込み再生を利用するだけです。
