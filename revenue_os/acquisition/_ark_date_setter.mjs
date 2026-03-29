/**
 * _ark_date_setter.mjs
 * playwright headless：在千帆 ARK 页面设置自定义日期范围
 * 用法: node _ark_date_setter.mjs <url> <start:YYYY-MM-DD> <end:YYYY-MM-DD>
 * 输出: JSON { ok, statsTime, expected }
 *
 * 通过月份箭头导航 + 点击日期格子，支持跨月设置
 */
import { chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const [,, pageUrl, startDate, endDate] = process.argv;
const [sy, sm, sd] = startDate.split('-').map(Number);
const [ey, em, ed] = endDate.split('-').map(Number);

const cookiesFile = process.env.COOKIES_JSON;
const cookies = JSON.parse(fs.readFileSync(cookiesFile, 'utf-8'));

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

async function navigateToMonth(page, targetYear, targetMonth) {
    for(let a = 0; a < 36; a++) {
        const months = await getDisplayedMonths(page);
        if(!months.length) break;
        const left = months[0];
        const diff = (left.year - targetYear) * 12 + (left.month - targetMonth);
        if(diff === 0) return true;
        const svgs = await page.evaluate(function(){
            return Array.from(document.querySelectorAll('.css-7ll3nl')).map(function(svg){
                var r = svg.getBoundingClientRect();
                return { x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), cls: svg.className.baseVal };
            });
        });
        if(diff > 0) {
            const prev = svgs.find(function(s){ return s.cls.indexOf('css-cvpy5t') > -1; });
            if(prev) await page.mouse.click(prev.x, prev.y);
        } else {
            const next = svgs.find(function(s){ return s.cls.indexOf('css-fvvjfw') > -1; });
            if(next) await page.mouse.click(next.x, next.y);
        }
        await page.waitForTimeout(400);
    }
    return false;
}

async function clickDay(page, day, inLeft) {
    const cells = await page.evaluate(function(){
        return Array.from(document.querySelectorAll('.calendar-dayCell')).map(function(c){
            var r = c.getBoundingClientRect();
            return { text: c.innerText.trim(), x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2), left: Math.round(r.x) };
        });
    });
    var allXs = cells.map(function(c){ return c.left; }).sort(function(a,b){ return a-b; });
    var midX = allXs[Math.floor(allXs.length/2)];
    var target = cells.find(function(c){
        return c.text === String(day) && (inLeft ? c.left < midX : c.left >= midX);
    });
    if(target) { await page.mouse.click(target.x, target.y); return true; }
    return false;
}

const NODE_MODULES = path.join(path.dirname(new URL(import.meta.url).pathname),
    '../../../../runtime/revenue_os/.tooling/creator_capture/node/node_modules');

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
await ctx.addCookies(cookies);
const page = await ctx.newPage();

await page.goto(pageUrl, { waitUntil: 'networkidle', timeout: 45000 });
await page.waitForTimeout(3000);

// Click 自定义
await page.evaluate(function(){
    var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); var n;
    while(n = w.nextNode()){ if(n.textContent.trim() === '自定义' && n.parentElement.getBoundingClientRect().height > 0){ n.parentElement.click(); return; } }
});
await page.waitForTimeout(1200);
await page.locator("input[placeholder='开始时间']").first().click({ timeout: 5000 });
await page.waitForTimeout(1200);

const navOk = await navigateToMonth(page, sy, sm);
const r1 = await clickDay(page, sd, true);
await page.waitForTimeout(600);

const months = await getDisplayedMonths(page);
const endInLeft = months[0] && months[0].year === ey && months[0].month === em;
const endInRight = months[1] && months[1].year === ey && months[1].month === em;
if(!endInLeft && !endInRight) await navigateToMonth(page, ey, em > 1 ? em-1 : 12);
const months2 = await getDisplayedMonths(page);
const endLeft2 = months2[0] && months2[0].year === ey && months2[0].month === em;
const r2 = await clickDay(page, ed, endLeft2);
await page.waitForTimeout(2500);

const bodyText = await page.evaluate(function(){ return document.body.innerText; });
const m = bodyText.match(/(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})/);
const statsTime = m ? m[0] : '';
const expected = startDate + '~' + endDate;

process.stdout.write(JSON.stringify({ ok: statsTime === expected, statsTime, expected, navOk, r1, r2 }));
await browser.close();
