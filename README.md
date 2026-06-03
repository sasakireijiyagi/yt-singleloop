# YouTube Loop Trainer

語学学習・シャドーイング・耳コピ練習用のWebアプリです。  
YouTube URLと開始・終了時間を指定すると、その区間だけをループ再生できます。

## 機能

- YouTube動画の任意区間をループ再生
- 開始・終了時間を秒単位で指定
- ループ区間の保存・管理
- 90言語以上対応（Whisperによる文字起こし連携）

## こんな使い方に

- 語学学習・シャドーイング（英語など90言語以上）
- 耳コピ（ギター・ピアノなど、繰り返し聴きたい小節に）
- 発表・スピーチの練習

## 使い方

1. YouTube URLを入力
2. ループしたい開始・終了時間を設定
3. 再生して練習

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

## 作者

**佐々木玲仁研究室**（九州大学臨床心理学講座）  
🐐 [ヤギ製作所](https://sasakireijiyagi.com/home)

## License

MIT License © 2025 Reiji Sasaki
