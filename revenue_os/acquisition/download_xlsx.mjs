/**
 * download_xlsx.mjs
 * 千帆各数据页 XLSX 下载脚本
 *
 * 机制：点击页面"下载数据"按钮 → 浏览器直接下载到 ~/Downloads
 * 验证：2026-03-28 确认 成交分析/流量/商品/搜索/笔记/账号/退款/订单/评价/店铺/买手笔记/商家类目 均有"下载数据"
 *
 * 无下载按钮的页面（实时商品/售后/物流/客服/群聊/市场行情）：这些只能 DOM 采集
 *
 * 用法:
 *   node download_xlsx.mjs                    # 下载所有有按钮的页面
 *   node download_xlsx.mjs --pages 成交分析,流量数据  # 只下载指定页面
 *   node download_xlsx.mjs --dry-run          # 只打印不下载
 */

import { sendCommand } from '/opt/homebrew/lib/node_modules/@jackwener/opencli/dist/browser/daemon-client.js';
import { readdirSync, statSync, mkdirSync, copyFileSync } from 'fs';
import { join, basename } from 'path';

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── 配置 ─────────────────────────────────────────────────────────────────────
const DOWNLOADS_DIR = `${process.env.HOME}/Downloads`;
const DEST_DIR = `${process.env.HOME}/Library/Mobile Documents/com~apple~CloudDocs/Thoth_Academy_Obsidian/08_Le_Fond_Bridge/Business Library/raw_data/source_auto`;
const BASE_URL = 'https://ark.xiaohongshu.com';

const DRY_RUN = process.argv.includes('--dry-run');
const PAGES_FILTER = process.argv.find(a => a.startsWith('--pages='))?.slice(8)?.split(',') || null;

// ── 页面配置 ─────────────────────────────────────────────────────────────────
// 格式: { path, label, btnText, destDir }
// 验证日期: 2026-03-28
const DOWNLOAD_PAGES = [
    // 交易数据
    { path: '/app-datacenter/business-overview', label: '成交分析',   btnText: '下载数据', destDir: '商家成交' },
    { path: '/app-datacenter/flow-overview',     label: '流量数据',   btnText: '下载数据', destDir: '商家流量' },
    { path: '/app-datacenter/good-data',         label: '商品总览',   btnText: '下载数据', destDir: '商品明细' },
    { path: '/app-datacenter/good-data/category-analysis', label: '商家类目', btnText: '下载数据', destDir: '商家类目' },
    { path: '/app-datacenter/search-overview',   label: '搜索总览',   btnText: '下载数据', destDir: '搜索' },
    { path: '/app-datacenter/search-overview/words', label: '引流搜索词', btnText: '下载数据', destDir: '搜索' },
    { path: '/app-datacenter/note-data/goods',   label: '笔记数据',   btnText: '下载数据', destDir: 'posts_metrics' },
    { path: '/app-datacenter/note-cooperate',    label: '买手笔记',   btnText: '下载数据', destDir: '买手笔记' },
    { path: '/app-datacenter/business-account',  label: '账号分析',   btnText: '下载数据', destDir: '账号总览' },
    { path: '/app-datacenter/business-refund',   label: '退款分析',   btnText: '下载数据', destDir: '退款分析' },
    { path: '/app-datacenter/business-order',    label: '订单明细',   btnText: '下载数据', destDir: '订单明细' },
    { path: '/app-datacenter/comment-overview',  label: '评价数据',   btnText: '下载数据', destDir: '评价' },
    { path: '/app-datacenter/homepage',          label: '店铺主页',   btnText: '下载数据', destDir: '店铺页' },
    // 管理类
    { path: '/app-item/list/shelf',              label: '商品管理',   btnText: '导出查询结果', destDir: '售卖中商品' },
];

// ── 工具函数 ──────────────────────────────────────────────────────────────────
let TAB = null;

async function getTab() {
    if (TAB) {
        try {
            const url = await sendCommand('exec', { code: 'location.href', tabId: TAB });
            if (url && url.includes('ark.xiaohongshu.com') && !url.includes('login')) return TAB;
        } catch(e) {}
    }
    const nav = await sendCommand('navigate', { url: `${BASE_URL}/app-datacenter/business-overview`, timeout: 500 });
    TAB = nav.tabId;
    await sleep(8000);
    const url = await sendCommand('exec', { code: 'location.href', tabId: TAB });
    if (url.includes('login')) throw new Error('未登录千帆，请先在 Chrome 中登录 ark.xiaohongshu.com');
    return TAB;
}

async function exec(code) {
    const tabId = await getTab();
    return sendCommand('exec', { code, tabId });
}

// 记录下载前的 Downloads 目录状态
function snapshotDownloads() {
    try {
        return new Set(readdirSync(DOWNLOADS_DIR).map(f => join(DOWNLOADS_DIR, f)));
    } catch(e) { return new Set(); }
}

// 等待新的 xlsx/csv 文件出现
async function waitForNewFile(before, timeoutMs = 15000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        await sleep(500);
        const after = readdirSync(DOWNLOADS_DIR);
        for (const f of after) {
            const fullPath = join(DOWNLOADS_DIR, f);
            if (!before.has(fullPath) && (f.endsWith('.xlsx') || f.endsWith('.csv') || f.endsWith('.xls'))) {
                // 等待文件写完（大小稳定）
                await sleep(1000);
                return fullPath;
            }
        }
    }
    return null;
}

// 移动文件到 source_auto 对应目录
function moveToSourceAuto(srcPath, destDirName) {
    const destDir = join(DEST_DIR, destDirName);
    mkdirSync(destDir, { recursive: true });
    const destPath = join(destDir, basename(srcPath));
    if (!DRY_RUN) {
        copyFileSync(srcPath, destPath);
    }
    return destPath;
}

// ── 主流程 ────────────────────────────────────────────────────────────────────
console.log(`\n${'='.repeat(60)}`);
console.log(`千帆 XLSX 下载  ${DRY_RUN ? '[DRY RUN]' : ''}`);
console.log(`目标: ${DEST_DIR}`);
console.log(`${'='.repeat(60)}\n`);

await getTab();

const pages = PAGES_FILTER
    ? DOWNLOAD_PAGES.filter(p => PAGES_FILTER.includes(p.label))
    : DOWNLOAD_PAGES;

const results = [];

for (const page of pages) {
    console.log(`▶ ${page.label} (${page.path})`);

    // 导航到页面
    await sendCommand('navigate', { url: `${BASE_URL}${page.path}`, tabId: TAB, timeout: 500 });
    await sleep(5000);

    const currentUrl = await sendCommand('exec', { code: 'location.href', tabId: TAB });
    if (currentUrl.includes('login')) {
        console.log('  ❌ 登录失效，跳过');
        results.push({ label: page.label, status: 'skip_login' });
        continue;
    }

    // 检查下载按钮
    const btnExists = await sendCommand('exec', { code: [
        '(function(){',
        '  var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);',
        '  var n;',
        '  while(n=w.nextNode()){',
        `    if(n.textContent.trim()==="${page.btnText}"&&n.parentElement.getBoundingClientRect().height>0) return true;`,
        '  }',
        '  return false;',
        '})()'
    ].join(''), tabId: TAB });

    if (!btnExists) {
        console.log(`  ⚠️ 未找到"${page.btnText}"按钮，跳过`);
        results.push({ label: page.label, status: 'no_btn' });
        continue;
    }

    if (DRY_RUN) {
        console.log(`  ✅ [DRY RUN] 找到按钮"${page.btnText}"`);
        results.push({ label: page.label, status: 'dry_run' });
        continue;
    }

    // 记录下载前状态
    const before = snapshotDownloads();

    // 点击下载按钮
    await sendCommand('exec', { code: [
        '(function(){',
        '  var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);',
        '  var n;',
        '  while(n=w.nextNode()){',
        `    if(n.textContent.trim()==="${page.btnText}"&&n.parentElement.getBoundingClientRect().height>0){`,
        '      n.parentElement.click();return "clicked";',
        '    }',
        '  }',
        '  return "not found";',
        '})()'
    ].join(''), tabId: TAB });

    console.log(`  🔄 等待下载...`);
    const newFile = await waitForNewFile(before, 20000);

    if (!newFile) {
        console.log('  ❌ 下载超时（20s）');
        results.push({ label: page.label, status: 'timeout' });
        continue;
    }

    console.log(`  ⬇️  下载完成: ${basename(newFile)}`);

    // 移动到 source_auto
    const destPath = moveToSourceAuto(newFile, page.destDir);
    console.log(`  ✅ 保存至: source_auto/${page.destDir}/${basename(newFile)}`);
    results.push({ label: page.label, status: 'ok', file: basename(newFile), dest: destPath });

    await sleep(2000); // 每次下载间隔
}

// ── 汇总 ─────────────────────────────────────────────────────────────────────
console.log(`\n${'='.repeat(60)}`);
console.log('下载汇总:');
const ok = results.filter(r => r.status === 'ok');
const skip = results.filter(r => r.status !== 'ok');
console.log(`  ✅ 成功: ${ok.length}/${results.length}`);
ok.forEach(r => console.log(`     ${r.label}: ${r.file}`));
if (skip.length > 0) {
    console.log(`  ⚠️ 跳过/失败:`);
    skip.forEach(r => console.log(`     ${r.label}: ${r.status}`));
}
