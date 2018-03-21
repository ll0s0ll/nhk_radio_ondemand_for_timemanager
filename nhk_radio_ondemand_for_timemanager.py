#! /usr/bin/env python
# -*- coding: utf-8 -*-
u"""
某放送局のラジオの聞き逃し番組を、TimeManagerに登録して再生するプログラムです。

実行すると、一番直近に公開された番組の情報を取得し、
番組の長さに合わせたスケジュールを、TimeManagerの空き時間に登録します。
取得する番組は、オプションを指定することで絞り込むことができます。

再生が終了すると、指定された間隔を空けて、繰り返し実行します。
標準では無限に繰り返しますが、繰り返す回数、間隔はオプションで設定できます。

rオプションを指定すると、番組をランダムに取得します。

内部で以下のプログラムを呼び出しています。
[ffmpeg]
https://www.ffmpeg.org

[mplayer]
http://www.mplayerhq.hu/

[nhk_radio_ondemand.py]
https://github.com/ll0s0ll/nhk_radio_ondemand

[TimeManager]
https://github.com/ll0s0ll/TimeManager

[xargs]
https://ja.wikipedia.org/wiki/Xargs

以下のmoduleを使用しています。
[m3u8]
https://pypi.python.org/pypi/m3u8
"""
from __future__ import print_function

import argparse
import errno
import logging
import m3u8
import math
import os
import random
import signal
import subprocess
import sys
import time

DEFAULT_INTERVAL = 30


def calculate_duration(url):
    """
    継続時間を計算する。

    Args:
    [Unicode] url ファイルのURL。

    Return:
    [int] 継続時間(sec)

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        m3u8_obj = m3u8.load(url)
        m3u8_obj2 = m3u8.load(m3u8_obj.playlists[0].uri)

        duration = 0.0
        for s in m3u8_obj2.segments:
            duration += s.duration

        return math.ceil(duration) + 3

    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def compose_caption(record):
    """
    キャプション文字列を作成する。

    Args:
    [Tuple] record parse_record_string()によって作成されたタプル。

    Return:
    [int] 継続時間(sec)

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        c = u''
        for i in (6,7,8,9,10,11):
            if record[i]:
                c += u' %s' % record[i]

        return c.lstrip(' ')

    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def compose_schedule_str(args):
    """
    TimeManager形式のスケジュール文字列を作成する。

    Args:
    [argparse.Namespace] args 解析済みの引数

    Return:
    [Unicode] スケジュール文字列

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:        
        site_id = args.opt_s
        corner_id = args.opt_c

        if site_id == None or corner_id == None:
            
            rs = fetch_records()
            rs = select_records_by_siteid(rs, site_id, args.opt_r)
            r = select_record_by_cornerid(rs, corner_id, args.opt_r)
            if r == None:
                logger.info('No record found.')
                return None
            site_id = r[0]
            corner_id = r[1]
            time.sleep(0.1)

        records = fetch_records(opt_d=u'%s_%s' % (site_id, corner_id))
        
        record = select_record_by_fileid(records, args.opt_f, args.opt_r)
        if record == None:
            logger.info('No record found.')
            return None

        duration = calculate_duration(record[12])
        caption = compose_caption(record)
        
        schedule = u'0:%d:%s\n%s' % (duration, caption, record[12])
        logger.debug(schedule)

        return schedule

    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]
        

def execute():
    """
    子プロセスを作成してコマンドを実行する。

    子プロセスは自プロセスをプロセスリーダーとした、
    新しいプロセスグループを作成する。

    Return:
    [Int] 実行したコマンドの終了ステータス。

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        global logger

        child_pid = os.fork()
        if child_pid == 0:
            # child process

            try:
                # 親プロセスから受け継いだ設定をデフォルトに戻す。
                for sig in (signal.SIGINT, signal.SIGQUIT, signal.SIGTERM):
                    signal.signal(sig, signal.SIG_DFL)

                # 新しいプロセスグループを作成する。
                # このプロセスグループでTimeManagerに登録される。
                os.setpgid(0, 0)

                # 空き時間がない場合は、コマンドを実行しない。
                if not is_unoccupied_avail():
                    logger.info('No unoccupied sched found, skip.')
                    os._exit(0)

                global args
                schedule = compose_schedule_str(args)
                if schedule == None:
                    logger.info('No story found, skip.')
                    os._exit(0)

                cmd = u'tm unoccupied | tm set - | xargs -i%% ffmpeg -loglevel quiet -i %% -vn -acodec copy pipe:1.ts | mplayer -vo null -msglevel all=0 -cache 256 -af volume=5 -; tm terminate'

                # logger.debug('[CMD] %s' % cmd)
                
                # 実行する。
                DEVNULL = open(os.devnull, 'wb')
                process = subprocess.Popen([cmd.encode('utf-8')],
                                           stdin=subprocess.PIPE,
                                           stderr=DEVNULL,
                                           shell=True)
                process.stdin.write((schedule+u'\n').encode('utf-8'))
                process.stdin.flush()
                process.stdin.close()
                process.wait()

                os._exit(process.returncode)

            except Exception, e:
                logger.exception(e)
                os._exit(1)
        else:
            # parent process
            logger.info('[SPAWN] pgid:%d' % child_pid)
            
            global child_pgid
            child_pgid = child_pid

            rc = wait_process(child_pid)
            logger.info('[DIED] rc:%d' % rc)

            return rc

    except Exception, e:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def fetch_records(opt_d=None):
    """
    nhk_radio_ondemandプログラムからレコードを取得する。

    Arg:
    [Unicode] dオプション値。

    Return:
    [List] レコードをフィールド値に分解したタプルのリスト。

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        cmd = ['nhk_radio_ondemand.py']

        if opt_d:
            cmd += [u'-d', opt_d]

        process = subprocess.Popen(cmd,
                                   stderr=subprocess.PIPE,
                                   stdout=subprocess.PIPE)

        records = []
        for line in process.stdout:
            record = parse_record_string(line.decode('utf-8').rstrip('\n'))
            records.append(record)

        process.wait()
        if process.returncode != 0:
            msg = 'Error: Popen returned %d.' % returncode
            if stderr:
                msg += '(%s)' % stderr
            raise RuntimeError(msg)

        return records

    except ValueError, ve:
        print(ve, file=sys.stderr)
    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def is_unoccupied_avail():
    """
    空き時間があるか確認する。

    Return:
    [Bool] 空き時間がある場合はTrue、ない場合はFalseを返す。

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        cmd = u'echo "0:0:C" | tm unoccupied'
        process = subprocess.Popen(cmd.encode('utf-8'),
                                   stderr=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   shell=True)
        (stdout, stderr) = process.communicate()

        if process.returncode == 0:
            return True
        else:
            return False

    except Exception, e:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def parse_argument():
    """
    引数を解析する。

    Return:
    [class 'argparse.Namespace'] 解析したコマンドライン

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        parser = argparse.ArgumentParser(description=__doc__.encode('utf-8'),
                                 formatter_class=argparse.RawTextHelpFormatter)
        parser.add_argument('-c', dest='opt_c', metavar='CORNERID',
                            help='corner_id。')
        #parser.add_argument('-d', dest='opt_d', metavar='SITEID_CORNERID',
        #        help='詳細表示。site_idとcorner_idをハイフンでつないだもの。')
        parser.add_argument('-f', dest='opt_f', metavar='FILEID',
                 help='file_id。')
        parser.add_argument('-r', dest='opt_r', action='store_true',
                            help='ランダム')
        parser.add_argument('-i', dest='interval', type=int,
                            default=DEFAULT_INTERVAL,
                            help='実行を繰り返す間隔 (sec)')
        parser.add_argument('-R', dest='repeat', type=int, default=None,
                            help='繰り返す回数 (デフォルトは無制限)')
        parser.add_argument('-s', dest='opt_s', metavar='SITEID',
                            help='site_id。')
        parser.add_argument('-v', dest='verbose', action='store_true',
                            help='verboseモード')
        return parser.parse_args()
    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def parse_record_string(string):
    """
    nhk_radio_ondemandプログラムからレコードを取得する。

    Arg:
    [Unicode] レコード文字列。

    Return:
    [Tuple] レコードをフィールド値に分解したタプル。

    Exception:
    [ValueError]   文字列が不正なフォーマットだった場合。
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        record = string.split('\t')

        if len(record) != 13:
            raise ValueError('Unknown record format.')

        return tuple(record)

    except ValueError:
        raise ValueError(sys.exc_info()[1]), None, sys.exc_info()[2]
    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def select_record_by_cornerid(records, corner_id, is_random):
    """
    corner_idで与えられた条件に合致するレコードを返します。

    corner_idがNoneかつis_randomがNoneの場合は、recordsの一番始めの値を
    返します。corner_idがNoneかつis_randomがTrueの場合は、recordsの中から
    ランダムの選んだ値を返します。
    
    Arg:
    [list]    records   レコードのリスト。
    [unicode] corner_id corner_idの文字列。
    [bool]    is_random ランダム指定かどうか。

    Return:
    [tuple] 合致するレコード。

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        matched_record = None

        if len(records) == 0:
            pass
        elif corner_id:
            for r in records:
                if r[1] == corner_id:
                    matched_record = r
        elif is_random:
            # ランダム
            random.seed()
            matched_record = random.choice(records)
        else:
            # 一番始めのレーコードを返す。
            matched_record = records[0]
            
        return matched_record

    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def select_record_by_fileid(records, file_id, is_random):
    """
    file_idで与えられた条件に合致するレコードを返します。

    file_idがNoneかつis_randomがNoneの場合は、recordsの一番始めの値を
    返します。file_idがNoneかつis_randomがTrueの場合は、recordsの中から
    ランダムの選んだ値を返します。
    
    Arg:
    [list]    records   レコードのリスト。
    [unicode] file_id   site_idの文字列。
    [bool]    is_random ランダム指定かどうか。

    Return:
    [tuple] 合致するレコード。

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        matched_record = None

        if len(records) == 0:
            pass
        elif file_id:
            for r in records:
                if r[3] == file_id:
                    matched_record = r
        elif is_random:
            # ランダム
            random.seed()
            matched_record = random.choice(records)
        else:
            # 一番始めのレーコードを返す。
            matched_record = records[0]
            
        return matched_record

    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def select_records_by_siteid(records, site_id, is_random):
    """
    site_idで与えられた条件に合致するレコードを返します。

    site_idがNoneかつis_randomがNoneの場合は、recordsの一番始めの値を
    返します。site_idがNoneかつis_randomがTrueの場合は、recordsの中から
    ランダムの選んだ値を返します。
    
    Arg:
    [list]    records   レコードのリスト。
    [unicode] site_id   site_idの文字列。
    [bool]    is_random ランダム指定かどうか。

    Return:
    [list] 合致するレコードのリスト。

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        matched_records = []

        if len(records) == 0:
            pass
        elif site_id:
            for r in records:
                if r[0] == site_id:
                    matched_records.append(r)
        elif is_random:
            # ランダム
            random.seed()
            matched_records.append(random.choice(records))
        else:
            # 一番始めのレーコードを返す。
            matched_records.append(records[0])
            
        return matched_records

    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def setup_logger():
    """
    loggingをセットアップする。

    Return:
    [class 'logging.Logger'] loggerインスタンス。
    
    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    try:
        global args

        log_fmt = '%(filename)s: %(asctime)s %(levelname)s: %(message)s'
        #log_fmt = '%(filename)s:%(lineno)d: %(asctime)s %(levelname)s: %(message)s'
        
        if args.verbose:
            logging.basicConfig(level=logging.DEBUG, format=log_fmt)
        else:
            logging.basicConfig(format=log_fmt)

        return logging.getLogger(__name__)

    except Exception:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def sig_handler(sig, Handler):
    """
    シグナルハンドラ。
    グローバル変数child_pgidに保存されたプロセスグループに、SIGTERMを送信する。
    送信先のプロセスグループが存在しなくても、エラーは出さない。
    
    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    global child_pgid
    global is_force_termination
    global signo

    is_force_termination = True
    signo = sig

    try:
        os.killpg(child_pgid, sig)
        #logger.debug('send sig %d to pg %d' % (sig, child_pgid))
        
    except OSError, e:
        if e.errno == errno.ESRCH:
            # シグナル送信先プロセスグループが存在しなければ、それでよし。
            #print('Not found, pgid:', child_pgid, file=sys.stderr)
            return
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]

    except Exception, e:
        raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


def wait_process(pid):
    """
    プロセス番号がpidのプロセスをwaitして、終了ステータスを返す。

    シグナル割り込みにより終了した場合は、
    シグナル番号+128を終了ステータスとする。

    Arg:
    [Int] waitするプロセスのプロセス番号

    Return:
    [Int] waitしたプロセスの終了ステータス。

    Exception:
    [RuntimeError] 実行時に何らかのエラーが発生した場合。
    """
    while True:
        try:
            (pid, status) = os.waitpid(pid, 0)
                
            # プロセスの終了ステータスを計算する。
            if os.WIFEXITED(status):
                rc = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                rc = os.WTERMSIG(status)+128 # signum+128
            else:
                continue

            return rc
        except OSError, e:
            # 割り込まれた場合は、再度waitする。
            if e.errno == errno.EINTR:
                #logger.debug(u'waitpid() EINTR')
                continue
            raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]
        except Exception, e:
            raise RuntimeError(sys.exc_info()[1]), None, sys.exc_info()[2]


if __name__ == '__main__':

    global args
    global is_force_termination
    global logger

    try:
        args = parse_argument()
        logger = setup_logger()

        is_force_termination = False

        for sig in (signal.SIGINT, signal.SIGQUIT, signal.SIGTERM):
            signal.signal(sig,  sig_handler)

        logger.info('[START]')

        while not is_force_termination:

            if execute() == 1:
                sys.exit(1)

            if is_force_termination:
                break

            if args.repeat != None:
                args.repeat -= 1
                if args.repeat < 0:
                    break

            logger.info('[INTERVAL] %dsec' % args.interval)
            time.sleep(args.interval)

        if is_force_termination:
            global signo
            logger.info('[EXIT] signal %d.' % signo)
            sys.exit(128 + signo)
        else:
            logger.info('[EXIT] OK')
            sys.exit(0)

    except Exception, e:
        logger.exception(e)
        sys.exit(1)
