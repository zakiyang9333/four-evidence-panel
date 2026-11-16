"""把面板套进一个独立窗口（pywebview，系统自带的 WebKit），不用开浏览器。
窗口只是个壳：页面还是 http://localhost:端口 上的那个面板，前后端不变。
面板没在跑时先尝试拉起自动启动的面板，再不行就给出提示。用法：./open_window.sh"""
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


def port():
    if os.environ.get('FE_PORT'):
        return int(os.environ['FE_PORT'])
    try:
        with open(os.path.join(ROOT, 'config.json'), encoding='utf-8') as f:
            return int(json.load(f).get('port', 8777))
    except (OSError, ValueError):
        return 8777


def up(url):
    try:
        with urllib.request.urlopen(url + 'api/meta', timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def main():
    url = f'http://localhost:{port()}/'
    if not up(url):
        label = os.environ.get('FE_AGENT_PREFIX', 'com.zaki.four-evidence') + '.panel'
        subprocess.run(['launchctl', 'kickstart', f'gui/{os.getuid()}/{label}'], capture_output=True)
        for _ in range(60):
            if up(url):
                break
            time.sleep(0.5)
    import webview
    if up(url):
        webview.create_window('四要素观察面板', url, width=1500, height=950, min_size=(980, 620))
    else:
        webview.create_window('四要素观察面板', html=(
            '<body style="font:15px -apple-system,sans-serif;background:#12151c;color:#e6e8ee;padding:40px">'
            '<h2>面板没有在运行</h2><p>在终端运行 <code>~/Applications/VIXWatch/four_evidence/start_with_key.sh</code>'
            '（先复制密钥），或 <code>./start.sh</code>，然后再打开这个窗口。</p></body>'), width=700, height=300)
    webview.start()


if __name__ == '__main__':
    sys.exit(main())
