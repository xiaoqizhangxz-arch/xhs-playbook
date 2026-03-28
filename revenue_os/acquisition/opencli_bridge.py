"""
opencli_bridge.py — opencli daemon 通信封装
依赖：opencli v1.4.1+（npm install -g @jackwener/opencli）
"""
from __future__ import annotations
import json, subprocess, shutil
from pathlib import Path

_MJS = Path(__file__).parent / '_daemon_exec.mjs'

def ensure_opencli():
    if not shutil.which('opencli'):
        raise RuntimeError('opencli not installed: npm install -g @jackwener/opencli')

def _ensure_mjs():
    if _MJS.exists():
        return
    _MJS.write_text(r'''
import { sendCommand } from '/opt/homebrew/lib/node_modules/@jackwener/opencli/dist/browser/daemon-client.js';
import { writeFileSync } from 'fs';
const [,, action, ...args] = process.argv;
async function exec(tabId, code) { return sendCommand('exec', { code, tabId }); }
async function main() {
    if (action === 'navigate') {
        const nav = await sendCommand('navigate', { url: args[0], timeout: parseInt(args[1]||'500') });
        process.stdout.write(JSON.stringify(nav));
    } else if (action === 'exec') {
        const r = await exec(parseInt(args[0]), args.slice(1).join(' '));
        process.stdout.write(JSON.stringify({result: r}));
    } else if (action === 'screenshot') {
        const r = await sendCommand('screenshot', { tabId: parseInt(args[0]), format: 'png' });
        process.stdout.write(typeof r === 'string' ? r : (r?.data||''));
    } else if (action === 'canvas') {
        const code = `(function(){var cs=document.querySelectorAll('canvas');var o={};cs.forEach(function(c,i){if(c.width>100&&c.height>100){try{o['c'+i]={w:c.width,h:c.height,data:c.toDataURL('image/png')};}catch(e){}}});return JSON.stringify(o);})()`;
        const r = await exec(parseInt(args[0]), code);
        process.stdout.write(typeof r === 'string' ? r : JSON.stringify(r));
    }
}
main().catch(e => { process.stderr.write(e.message); process.exit(1); });
''', encoding='utf-8')

def node_exec(action: str, *args: str, timeout: int = 30) -> str:
    _ensure_mjs()
    r = subprocess.run(['node', str(_MJS), action, *args],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()

def navigate(url: str, timeout_ms: int = 500) -> dict:
    raw = node_exec('navigate', url, str(timeout_ms), timeout=20)
    try: return json.loads(raw)
    except: return {}

def exec_js(tab_id: int, code: str) -> str:
    raw = node_exec('exec', str(tab_id), code, timeout=20)
    try: return json.loads(raw).get('result', raw)
    except: return raw

def screenshot(tab_id: int) -> bytes | None:
    raw = node_exec('screenshot', str(tab_id), timeout=20)
    if raw and len(raw) > 100:
        import base64
        try: return base64.b64decode(raw)
        except: return None
    return None

def get_canvas_images(tab_id: int) -> dict[str, bytes]:
    raw = node_exec('canvas', str(tab_id), timeout=20)
    try:
        import base64
        data = json.loads(raw)
        result = {}
        for key, val in data.items():
            if isinstance(val, dict) and val.get('data', '').startswith('data:image'):
                b64 = val['data'].replace('data:image/png;base64,', '')
                result[key] = base64.b64decode(b64)
        return result
    except:
        return {}
