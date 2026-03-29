/**
 * ark_date_utils.mjs — 千帆 ARK 日期范围设置工具函数
 *
 * 支持跨月日期设置（通过月份箭头导航 + 日期格子点击）
 *
 * 适用场景：
 *   - download_xlsx.mjs（XLSX 下载前设置时间窗口）
 *   - xhs_historical_collector.py（DOM 采集前设置时间）
 *
 * 验证：2026-03-28 playwright headless 测试通过
 *   - 从 2026-03 → 2026-01（导航2个月 + 点日期格子）
 *   - 统计时间确认：2026-01-15~2026-02-20 ✅
 *
 * DOM 选择器（千帆数据页通用）：
 *   - 时间 tab: 文字匹配（近1日/近7日/近30日/自定义）
 *   - 月份文字: .css-vmmof7 → "2026 年" "03 月"
 *   - 月份前箭头(←): .css-7ll3nl.css-cvpy5t
 *   - 月份后箭头(→): .css-7ll3nl.css-fvvjfw
 *   - 日期格子: .calendar-dayCell
 *   - 开始时间 input: input[placeholder='开始时间']
 *   - 截止时间 input: input[placeholder='截止时间']
 */

// ── 获取当前日历显示的月份 ─────────────────────────────────────────────────
export async function getDisplayedMonths(page) {
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

// ── 导航左侧日历到目标月份 ─────────────────────────────────────────────────
export async function navigateToMonth(page, targetYear, targetMonth) {
    for(let a = 0; a < 36; a++) {
        const months = await getDisplayedMonths(page);
        if(!months.length) break;
        const left = months[0];
        const diff = (left.year - targetYear) * 12 + (left.month - targetMonth);
        if(diff === 0) return true;

        const svgs = await page.evaluate(function(){
            return Array.from(document.querySelectorAll('.css-7ll3nl')).map(function(svg){
                var r = svg.getBoundingClientRect();
                return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), cls: svg.className.baseVal };
            });
        });
        if(diff > 0) {
            // Go backward: click prev month arrow (single left chevron)
            const prev = svgs.find(function(s){ return s.cls.indexOf('css-cvpy5t') > -1; });
            if(prev) await page.mouse.click(prev.x, prev.y);
        } else {
            // Go forward: click next month arrow (single right chevron)
            const next = svgs.find(function(s){ return s.cls.indexOf('css-fvvjfw') > -1; });
            if(next) await page.mouse.click(next.x, next.y);
        }
        await page.waitForTimeout(400);
    }
    return false;
}

// ── 点击日历中的指定日期 ───────────────────────────────────────────────────
export async function clickDay(page, day, inLeftCalendar) {
    const cells = await page.evaluate(function(){
        return Array.from(document.querySelectorAll('.calendar-dayCell')).map(function(c){
            var r = c.getBoundingClientRect();
            return { text: c.innerText.trim(), x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), left: Math.round(r.x) };
        });
    });
    if(!cells.length) return false;
    
    var allXs = cells.map(function(c){ return c.left; });
    allXs.sort(function(a,b){ return a-b; });
    var midX = allXs[Math.floor(allXs.length/2)];
    
    var target = cells.find(function(c){
        var isLeft = c.left < midX;
        return c.text === String(day) && (inLeftCalendar ? isLeft : !isLeft);
    });
    if(target) {
        await page.mouse.click(target.x, target.y);
        return true;
    }
    return false;
}

// ── 点击时间 tab（近7日/近30日/自定义等）──────────────────────────────────
export async function clickTimeTab(page, tabText) {
    return await page.evaluate(function(text){
        var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); var n;
        while(n = w.nextNode()){
            if(n.textContent.trim() === text && n.parentElement.getBoundingClientRect().height > 0){
                n.parentElement.click();
                return true;
            }
        }
        return false;
    }, tabText);
}

// ── 完整日期范围设置 ───────────────────────────────────────────────────────
/**
 * 在千帆 ARK 数据页设置自定义日期范围
 *
 * @param {Page} page - playwright Page 对象
 * @param {string} startDate - 开始日期 'YYYY-MM-DD'
 * @param {string} endDate - 结束日期 'YYYY-MM-DD'
 * @returns {{ ok: boolean, statsTime: string }}
 *
 * 流程：
 *   1. 点击"自定义" tab
 *   2. 点击开始时间 input 打开日历
 *   3. 导航到起始月份（点击 ← 箭头）
 *   4. 点击起始日期格子
 *   5. 点击结束日期格子（如果右侧月份不是目标月份，需要导航）
 *   6. 验证页面统计时间显示
 */
export async function setDateRange(page, startDate, endDate) {
    const [sy, sm, sd] = startDate.split('-').map(Number);
    const [ey, em, ed] = endDate.split('-').map(Number);

    // 1. Click 自定义
    await clickTimeTab(page, '自定义');
    await page.waitForTimeout(1200);

    // 2. Open calendar
    const startInput = page.locator("input[placeholder='开始时间']").first();
    if(await startInput.count() === 0) return { ok: false, error: 'no start input' };
    await startInput.click({ timeout: 5000 });
    await page.waitForTimeout(1200);

    // 3. Navigate to start month
    const navOk = await navigateToMonth(page, sy, sm);
    if(!navOk) return { ok: false, error: 'month navigation failed' };

    // 4. Click start day
    const startOk = await clickDay(page, sd, true);
    if(!startOk) return { ok: false, error: 'start day click failed' };
    await page.waitForTimeout(600);

    // 5. Click end day
    const months = await getDisplayedMonths(page);
    // Check if end month is visible
    const endInLeft = months[0] && months[0].year === ey && months[0].month === em;
    const endInRight = months[1] && months[1].year === ey && months[1].month === em;
    
    if(!endInLeft && !endInRight) {
        // End month not visible, navigate
        // Navigate so endMonth is in right calendar (endMonth - 1 in left)
        await navigateToMonth(page, ey, em - 1 || 12);
        const endOk = await clickDay(page, ed, false);
        if(!endOk) return { ok: false, error: 'end day click failed after nav' };
    } else {
        const endOk = await clickDay(page, ed, endInLeft);
        if(!endOk) return { ok: false, error: 'end day click failed' };
    }
    await page.waitForTimeout(2500);

    // 6. Verify
    const statsTime = await page.evaluate(function(){
        var body = document.body.innerText;
        var m = body.match(/(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})/);
        return m ? m[0] : '';
    });
    const expected = `${startDate}~${endDate}`;
    return { ok: statsTime === expected, statsTime, expected };
}

// ── 简化：设置时间 tab（近7日/近30日/近90日）──────────────────────────────
export async function setTimeWindow(page, mode) {
    const tabMap = { '1d': '近1日', '7d': '近7日', '30d': '近30日' };
    const tabText = tabMap[mode] || mode;
    const clicked = await clickTimeTab(page, tabText);
    if(!clicked) return { ok: false, error: 'tab not found: ' + tabText };
    await page.waitForTimeout(2500);
    return { ok: true, mode };
}
