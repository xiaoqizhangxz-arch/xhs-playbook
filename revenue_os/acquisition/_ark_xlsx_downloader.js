/**
 * _ark_xlsx_downloader.js
 * playwright headless: 千帆 ARK 设置日期范围 → 点击下载 → 保存 XLSX
 *
 * 用法:
 *   node _ark_xlsx_downloader.js <pageUrl> <btnText> <downloadDir> <window>
 *
 *   window: '30d' | '7d' | '1d' | 'custom:YYYY-MM-DD:YYYY-MM-DD'
 *
 * 输出: JSON { ok, file, statsTime, error }
 *
 * 日期设置机制（跨月支持，2026-03-28 验证）：
 *   - CSS selectors: .css-vmmof7 (月份文字), .css-7ll3nl (箭头 SVG)
 *   - .css-cvpy5t = 前月箭头, .css-fvvjfw = 后月箭头
 *   - .calendar-dayCell = 日期格子
 *   - 用 page.mouse.click() 真实点击（isTrusted=true），不用 dispatchEvent
 */

const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const fs = require('fs');
const path = require('path');

const [,, pageUrl, btnText, downloadDir, windowArg] = process.argv;

const cookies = JSON.parse(fs.readFileSync(process.env.COOKIES_JSON, 'utf-8'));

// ── Month navigation helpers ──────────────────────────────────────────────────
async function getDisplayedMonths(page) {
    const texts = await page.evaluate(function(){
        return Array.from(document.querySelectorAll('.css-vmmof7'))
            .filter(function(el){ return el.getBoundingClientRect().height > 0; })
            .map(function(el){ return el.innerText.trim(); });
    });
    const months = [];
    for(let i = 0; i < texts.length - 1; i++) {
        const yM = texts[i].match(/(\d{4})/);
        const mM = texts[i+1].match(/(\d{1,2})/);
        if(yM && mM) months.push({ year: parseInt(yM[1]), month: parseInt(mM[1]) });
    }
    return months;
}

async function clickSvgArrow(page, svgClass) {
    const pos = await page.evaluate(function(cls){
        var svg = Array.from(document.querySelectorAll('.css-7ll3nl'))
            .find(function(s){ return s.className.baseVal.indexOf(cls) > -1; });
        if(!svg) return null;
        var r = svg.getBoundingClientRect();
        return { x: r.left + r.width/2, y: r.top + r.height/2 };
    }, svgClass);  // single string arg - ok
    if(pos) {
        await page.mouse.click(pos.x, pos.y);
        await page.waitForTimeout(450);
    }
    return !!pos;
}

async function navigateToMonth(page, targetYear, targetMonth) {
    for(let a = 0; a < 36; a++) {
        const months = await getDisplayedMonths(page);
        if(!months.length) break;
        const left = months[0];
        const diff = (left.year - targetYear) * 12 + (left.month - targetMonth);
        if(diff === 0) return true;
        if(diff > 0) await clickSvgArrow(page, 'css-cvpy5t'); // prev
        else await clickSvgArrow(page, 'css-fvvjfw');          // next
    }
    return false;
}

async function clickDayCell(page, day, inLeft) {
    const pos = await page.evaluate(function({d, isLeft}){
        var cells = Array.from(document.querySelectorAll('.calendar-dayCell'));
        if(!cells.length) return null;
        var xs = cells.map(function(c){ return c.getBoundingClientRect().x; })
            .filter(function(x,i,a){ return a.indexOf(x) === i; })
            .sort(function(a,b){ return a-b; });
        var maxGap = 0, midX = xs[Math.floor(xs.length/2)];
        for(var i=0; i<xs.length-1; i++) {
            var g = xs[i+1]-xs[i];
            if(g > maxGap) { maxGap = g; midX = (xs[i]+xs[i+1])/2; }
        }
        var target = cells.find(function(c){
            var r = c.getBoundingClientRect();
            return c.innerText.trim() === String(d) && (isLeft ? r.x < midX : r.x >= midX);
        });
        if(!target) return null;
        var r = target.getBoundingClientRect();
        return { x: r.left + r.width/2, y: r.top + r.height/2 };
    }, {d: day, isLeft: inLeft});
    if(pos) {
        await page.mouse.click(pos.x, pos.y);
        return true;
    }
    return false;
}

async function clickTabText(page, text) {
    return await page.evaluate(function(t){
        var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); var n;
        while(n = w.nextNode()) {
            if(n.textContent.trim() === t && n.parentElement.getBoundingClientRect().height > 0) {
                n.parentElement.click();
                return true;
            }
        }
        return false;
    }, text);
}

// ── Set date range ────────────────────────────────────────────────────────────
async function setDateRange(page, startDate, endDate) {
    const [sy, sm, sd] = startDate.split('-').map(Number);
    const [ey, em, ed] = endDate.split('-').map(Number);

    // Open 自定义 tab
    await page.evaluate(function(){
        var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);var n;
        while(n=w.nextNode()){if(n.textContent.trim()==='自定义'&&n.parentElement.getBoundingClientRect().height>0){n.parentElement.click();return;}}
    });
    await page.waitForTimeout(1200);

    // Open start input (JS click avoids overlay intercept)
    const hasInput = await page.evaluate(function(){
        var inp=document.querySelector("input[placeholder='\u5f00\u59cb\u65f6\u95f4']");
        if(!inp) return false; inp.focus(); inp.click(); return true;
    });
    if(!hasInput) return { ok: false, error: 'no start input' };
    await page.waitForFunction(function(){ return document.querySelectorAll('.calendar-dayCell').length > 0; }, { timeout: 8000 }).catch(function(){});
    await page.waitForTimeout(500);

    // Navigate left calendar to start month
    const navOk = await navigateToMonth(page, sy, sm);
    if(!navOk) return { ok: false, error: 'nav to start month failed' };

    // Click start day in left calendar
    if(!await clickDayCell(page, sd, true))
        return { ok: false, error: 'start day not found' };
    await page.waitForTimeout(600);

    // Constraint: end month must be visible (left or right) without navigating
    // Caller must ensure end is within same 2-month window as start
    // After clicking start, calendar stays open in end-select mode
    // Current display: start month (left) + start month+1 (right)
    const months = await getDisplayedMonths(page);
    const endInLeft  = months[0] && months[0].year === ey && months[0].month === em;
    const endInRight = months[1] && months[1].year === ey && months[1].month === em;
    if(!endInLeft && !endInRight)
        return { ok: false, error: 'end month not visible - split into smaller range' };

    if(!await clickDayCell(page, ed, endInLeft))
        return { ok: false, error: 'end day not found' };
    await page.waitForTimeout(2500);

    const statsTime = await page.evaluate(function(){
        var b=document.body.innerText;
        var m=b.match(/(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})/);
        return m?m[0]:'';
    });
    const expected = startDate + '~' + endDate;
    return { ok: statsTime === expected, statsTime, expected };
}

// ── Main ──────────────────────────────────────────────────────────────────────
(async () => {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({
        viewport: { width: 1920, height: 1080 },
        acceptDownloads: true,
    });
    await ctx.addCookies(cookies);
    const page = await ctx.newPage();

    await page.goto(pageUrl, { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(3000);

    // Set time window
    let windowResult = { ok: true };
    const tabMap = { '1d': '近1日', '7d': '近7日', '30d': '近30日' };
    if(tabMap[windowArg]) {
        await clickTabText(page, tabMap[windowArg]);
        await page.waitForTimeout(2500);
        windowResult = { ok: true, note: 'clicked ' + tabMap[windowArg] };
    } else if(windowArg && windowArg.startsWith('custom:')) {
        const parts = windowArg.split(':');
        if(parts.length === 3) {
            windowResult = await setDateRange(page, parts[1], parts[2]);
        }
    }

    if(!windowResult.ok) {
        process.stderr.write('windowResult: ' + JSON.stringify(windowResult) + '\n');
        process.stdout.write(JSON.stringify({ ok: false, error: 'window: ' + (windowResult.error || windowArg) }));
        await browser.close();
        return;
    }

    // Set up download handler right before clicking (avoid 30s timeout from early setup)
    const downloadPromise = page.waitForEvent('download', { timeout: 30000 });

    // Click download button
    const clicked = await page.evaluate(function(btnTxt){
        var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); var n;
        while(n = w.nextNode()) {
            if(n.textContent.trim() === btnTxt && n.parentElement.getBoundingClientRect().height > 0) {
                n.parentElement.click();
                return true;
            }
        }
        return false;
    }, btnText);

    if(!clicked) {
        process.stdout.write(JSON.stringify({ ok: false, error: 'btn not found: ' + btnText }));
        await browser.close();
        return;
    }

    // Wait for download
    let download = null;
    try { download = await downloadPromise; }
    catch(e) {
        process.stdout.write(JSON.stringify({ ok: false, error: 'download failed: ' + e.message }));
        await browser.close();
        return;
    }

    // Save file
    const filename = download.suggestedFilename();
    const destPath = path.join(downloadDir, filename);
    await download.saveAs(destPath);

    const statsTime = await page.evaluate(function(){
        var b = document.body.innerText;
        var m = b.match(/(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})/);
        return m ? m[0] : '';
    });

    process.stdout.write(JSON.stringify({ ok: true, file: filename, destPath, statsTime, windowNote: windowResult.note || windowResult.statsTime }));
    await browser.close();
})();
