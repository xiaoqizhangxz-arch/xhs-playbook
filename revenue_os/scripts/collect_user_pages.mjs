/**
 * collect_user_pages.mjs
 * 每日采集千帆两个用户分析页面的完整快照
 *
 * 页面A: /app-circle/user-data (人群分层)
 *   6主tab(认知/意向/新客/老客/流失/粉丝) × 3子tab(人群流转/用户画像/用户数据) = 18视图
 *
 * 页面B: /app-promotion/user-assets (AINRL漏斗)
 *   5主tab(了解A/兴趣I/新客N/老客R/亲密L)
 *     了解/新客/老客/亲密: 用户数据 + 用户画像
 *     兴趣(I): 用户数据 + 用户画像 + 兴趣行为明细(含各笔记更多信息)
 *
 * 用法: node collect_user_pages.mjs [--date 2026-03-28]
 */

import { sendCommand } from '/opt/homebrew/lib/node_modules/@jackwener/opencli/dist/browser/daemon-client.js';
import { writeFileSync, mkdirSync } from 'fs';
import { join } from 'path';

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── 配置 ────────────────────────────────────────────────────────────────────
const BASE_URL = 'https://ark.xiaohongshu.com';
const SAVE_DIR = process.env.REVENUE_OS_DATA_DIR
  ? `${process.env.REVENUE_OS_DATA_DIR}/creator_auto/historical`
  : `${process.env.HOME}/revenue-os-data/creator_auto/historical`;
const TODAY = process.argv.find(a => a.startsWith('--date='))?.slice(7) || new Date().toISOString().slice(0, 10);

mkdirSync(SAVE_DIR, { recursive: true });

// ── 工具函数 ─────────────────────────────────────────────────────────────────
let TAB = null;

async function getTab() {
    if (TAB) {
        try {
            const url = await sendCommand('exec', { code: 'location.href', tabId: TAB });
            if (url && url.includes('ark.xiaohongshu.com')) return TAB;
        } catch(e) {}
    }
    const nav = await sendCommand('navigate', { url: `${BASE_URL}/app-circle/user-data`, timeout: 500 });
    TAB = nav.tabId;
    await sleep(8000);
    return TAB;
}

async function exec(code) {
    const tabId = await getTab();
    return sendCommand('exec', { code, tabId });
}

async function navTo(path) {
    const tabId = await getTab();
    const url = `${BASE_URL}${path}`;
    const cur = await sendCommand('exec', { code: 'location.href', tabId });
    if (cur === url) return;
    // SPA 内导航用 pushState，外部页面用 navigate
    if (path.startsWith('/app-circle') || path.startsWith('/app-promotion')) {
        await sendCommand('exec', { code: `history.pushState(null,'','${url}'); window.dispatchEvent(new PopStateEvent('popstate',{state:null}))`, tabId });
    } else {
        await sendCommand('navigate', { url, tabId, timeout: 500 });
    }
    await sleep(4000);
}

async function getText() {
    const body = await exec('document.body.innerText');
    return typeof body === 'string' ? body : JSON.stringify(body);
}

async function clickByText(text, options = {}) {
    const { minY = 0, maxY = 9999, childrenMax = 3 } = options;
    return exec(`(function(){
        var all = Array.from(document.querySelectorAll('*'));
        var el = all.find(function(e){
            var t = e.innerText && e.innerText.trim();
            var r = e.getBoundingClientRect();
            return t === '${text.replace(/'/g,"\\'")}' && e.children.length <= ${childrenMax}
                && r.height > 0 && r.top >= ${minY} && r.top <= ${maxY};
        });
        if(!el) return 'not found: ${text.replace(/'/g,"\\'")}';
        el.click();
        return 'ok';
    })()`);
}

function save(filename, content) {
    const path = join(SAVE_DIR, filename);
    writeFileSync(path, content, 'utf8');
    console.log(`    ✅ ${filename} (${content.length} chars)`);
    return path;
}

// ── 页面A: 人群分层 /app-circle/user-data ───────────────────────────────────
const LAYER_TABS = ['认知', '意向', '新客', '老客', '流失', '粉丝'];
const LAYER_SUB_TABS = ['人群流转', '用户画像', '用户数据'];

async function collectLayerPage() {
    console.log('\n📊 [A] 人群分层 /app-circle/user-data');
    await navTo('/app-circle/user-data');

    for (const layer of LAYER_TABS) {
        console.log(`  ▶ ${layer}`);

        // 点主 Tab（找 SPAN 文本完全匹配，y 在 150~200 区域）
        const r = await clickByText(layer, { minY: 150, maxY: 220, childrenMax: 1 });
        if (r === `not found: ${layer}`) {
            console.log(`    ⚠️ tab "${layer}" not found, skip`);
            continue;
        }
        await sleep(1500);

        for (const sub of LAYER_SUB_TABS) {
            // 子 tab 在 y=290~340 区域的 H6
            const rSub = await exec(`(function(){
                var els = Array.from(document.querySelectorAll('h6')).filter(function(el){
                    var t = el.innerText && el.innerText.trim();
                    var r = el.getBoundingClientRect();
                    return t === '${sub}' && r.top > 280 && r.top < 360;
                });
                if(!els.length) return 'not found: ${sub}';
                els[0].click();
                return 'ok';
            })()`);
            await sleep(1500);

            const text = await getText();
            const filename = `${TODAY}_人群分层_${layer}_${sub}.txt`;
            save(filename, text);
        }
    }
}

// ── 页面B: AINRL漏斗 /app-promotion/user-assets ─────────────────────────────
// 注：兴趣(I)的"兴趣行为明细"是"用户数据"tab 下半部分内容，不是独立第三个 tab
// 采集"用户数据"时已包含兴趣行为明细+笔记列表，无需单独处理
const AINRL_TABS = [
    { label: '了解(A)', text: '了解 (A)', subTabs: ['用户数据', '用户画像'] },
    { label: '兴趣(I)', text: '兴趣 (I)', subTabs: ['用户数据', '用户画像'] },
    { label: '新客(N)', text: '新客 (N)', subTabs: ['用户数据', '用户画像'] },
    { label: '老客(R)', text: '老客 (R)', subTabs: ['用户数据', '用户画像'] },
    { label: '亲密(L)', text: '亲密 (L)', subTabs: ['用户数据', '用户画像'] },
];

async function clickAINRLTab(tabText) {
    return exec(`(function(){
        var el = Array.from(document.querySelectorAll('.title-text')).find(function(e){
            return e.innerText && e.innerText.trim() === '${tabText}';
        });
        if(!el) return 'not found';
        el.click();
        return 'ok';
    })()`);
}

async function clickAINRLSubTab(subText) {
    return exec(`(function(){
        // 子 tab 在 y=220~280 区域的 .tab-item-container
        var els = Array.from(document.querySelectorAll('[class*=tab-item-container]')).filter(function(el){
            var t = el.innerText && el.innerText.trim();
            var r = el.getBoundingClientRect();
            return t === '${subText}' && r.height > 0 && r.top > 220 && r.top < 280;
        });
        if(!els.length) {
            // fallback: 找 y=1100~1200 的"兴趣行为明细"
            els = Array.from(document.querySelectorAll('*')).filter(function(el){
                var t = el.innerText && el.innerText.trim();
                var r = el.getBoundingClientRect();
                return t === '${subText}' && r.height > 0 && r.top > 1000;
            });
        }
        if(!els.length) return 'not found: ${subText}';
        els[0].click();
        return 'ok';
    })()`);
}

async function collectNoteDetails() {
    // 采集兴趣(I)→兴趣行为明细里所有笔记的"更多信息"
    // 先一次性收集所有链接（去重），再逐条采集
    const links = await exec(`(function(){
        var seen = {};
        return Array.from(document.querySelectorAll('a')).filter(function(a){
            if (!a.innerText || a.innerText.trim() !== '更多信息') return false;
            if (!a.href || !a.href.includes('note-detail')) return false;
            var id = (a.href.match(/id=([^&]+)/) || [])[1] || a.href;
            if (seen[id]) return false;
            seen[id] = true;
            return true;
        }).map(function(a){ return a.href; });
    })()`);
    const hrefs = Array.isArray(links) ? links : JSON.parse(links || '[]');
    console.log(`    📎 找到 ${hrefs.length} 条笔记（去重）`);

    const details = [];
    for (let i = 0; i < hrefs.length; i++) {
        const href = hrefs[i];
        const noteId = href.match(/id=([^&]+)/)?.[1] || `note_${i}`;
        const filename = `${TODAY}_笔记详情_${noteId}.txt`;

        await sendCommand('navigate', { url: href, tabId: TAB, timeout: 500 });
        await sleep(5000);
        const text = await getText();
        save(filename, text);
        details.push({ noteId, href, file: filename });

        // 返回用户资产页并恢复到兴趣行为明细（为下一条做准备）
        await sendCommand('navigate', { url: `${BASE_URL}/app-promotion/user-assets`, tabId: TAB, timeout: 500 });
        await sleep(5000);
        await clickAINRLTab('兴趣 (I)');
        await sleep(1000);
        await clickAINRLSubTab('兴趣行为明细');
        await sleep(1500);
    }
    return details;
}

async function collectAINRLPage() {
    console.log('\n📊 [B] AINRL漏斗 /app-promotion/user-assets');
    await navTo('/app-promotion/user-assets');

    for (const tab of AINRL_TABS) {
        console.log(`  ▶ ${tab.label}`);

        const r = await clickAINRLTab(tab.text);
        if (r === 'not found') {
            console.log(`    ⚠️ tab "${tab.text}" not found`);
            continue;
        }
        await sleep(1500);

        for (const sub of tab.subTabs) {
            const rSub = await clickAINRLSubTab(sub);
            await sleep(1500);
            const text = await getText();
            save(`${TODAY}_AINRL_${tab.label}_${sub}.txt`, text);

            // 兴趣(I)→用户数据 里包含兴趣行为明细+笔记列表，顺便采集各笔记详情
            if (tab.label === '兴趣(I)' && sub === '用户数据' && text.includes('感兴趣人数')) {
                await collectNoteDetails();
            }
        }
    }
}

// ── 主流程 ───────────────────────────────────────────────────────────────────
console.log(`\n${'='.repeat(60)}`);
console.log(`用户分析页采集  日期: ${TODAY}`);
console.log(`${'='.repeat(60)}`);

try {
    await getTab();
    await collectLayerPage();
    await collectAINRLPage();
    console.log('\n✅ 全部完成');
} catch(e) {
    console.error('❌ Error:', e.message);
    process.exit(1);
}
