某放送局のラジオの聞き逃し番組を、TimeManagerに登録して再生するプログラムです。

実行すると、一番直近に公開された番組の情報を取得し、  
番組の長さに合わせたスケジュールを、TimeManagerの空き時間に登録します。  
取得する番組は、オプションを指定することで絞り込むことができます。

再生が終了すると、指定された間隔を空けて、繰り返し実行します。  
標準では無限に繰り返しますが、繰り返す回数、間隔はオプションで設定できます。

rオプションを指定すると、番組をランダムに取得します。

## SYNOPSIS
```
$ nhk_radio_ondemand_for_timemanager.py [-h] [-c CORNERID] [-f FILEID] [-r] [-i INTERVAL] [-R REPEAT] [-s SITEID] [-v]
```
                                             
## EXAMPLE
```
# 空き時間に収まる聞き逃し番組をランダムに選んで、TimeManagerに登録して、再生する。
$ nhk_radio_ondemand_for_timemanager.py -r
```

## NOTE
内部で以下のプログラムを呼び出しています。  
- [ffmpeg](https://www.ffmpeg.org)
- [mplayer](http://www.mplayerhq.hu/)
- [nhk_radio_ondemand.py](https://github.com/ll0s0ll/nhk_radio_ondemand)
- [TimeManager](https://github.com/ll0s0ll/TimeManager)
- [xargs](https://ja.wikipedia.org/wiki/Xargs)

以下の moduleを使用しています。
 - [m3u8](https://pypi.python.org/pypi/m3u8)

## SEE ALSO
[TimeManagerを使って、聴きたいラジオ番組が流れてくる、自分だけのラジオを作る](https://ll0s0ll.wordpress.com/raspberrypi/automated_radio_station/)
 