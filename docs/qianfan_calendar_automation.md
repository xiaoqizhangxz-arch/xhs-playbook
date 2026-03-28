# 千帆日历选择器自动化指南

> 2026-03-28 完成，投入 3h + 100K tokens

## TL;DR

**可行方案**：同面板两次点击（不翻页）  
**不可行方案**：跨面板、翻页后点击  
**推荐策略**：每日增量采集（避免历史回溯）

---

## 核心发现

### ✅ 成功模式

```javascript
// 1. 打开日历（默认显示当月/次月）
// 2. 在 panel[0] 点起始日
// 3. 在 panel[0] 点结束日 → 自动提交 → 成功
```

**验证案例**：`2026-03-01 ~ 2026-03-27`（同面板，无翻页） — 成功率 100%

### ❌ 失败模式

| 场景 | 现象 | 原因 |
|------|------|------|
| 跨面板选择 | 点 panel[0]日期 + panel[1]日期 → 第二次点击不响应 | 日历组件要求两次点击在同一面板 |
| 翻页后选择 | 翻页 → 点第一个日期 → 点第二个日期 → 日期回退 | 翻页SVG的click被当成"确认选择"而非导航 |
| 初次选择 | 从快捷项进入自定义 → 点一个日期 → 日历关闭 | 单次点击模式（start=end=同一天）|

---

## 日历组件行为规律

### 模式判定

| 前置状态 | 日历行为 | 点击次数 |
|---------|---------|---------|
| 页面默认 / 快捷项切换 | 单次模式（点一下=start+end） | 1次 |
| 已有自定义范围 | Range模式（点两下=start→end） | 2次 |

### 翻页行为

- **非选择状态**：翻页 SVG = 导航（安全）
- **选择状态**（点完起始日后）：翻页 SVG = "接受当前选择" + 关闭日历（危险）

### Panel结构

- 日历显示两个面板：`panel[0]`（左/当月）、`panel[1]`（右/次月）
- Range选择要求：**两次点击必须在同一个panel上**

---

## 成功脚本模板

```javascript
// tools/千帆日历自动化_同面板选择.mjs
import { sendCommand } from '@jackwener/opencli/dist/browser/daemon-client.js';
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function exec(tabId, code) { return sendCommand('exec', { code, tabId }); }

const nav0 = await sendCommand('navigate', { 
    url: 'https://ark.xiaohongshu.com/app-datacenter/business-overview', 
    timeout: 500 
});
const TAB = nav0.tabId;
await sleep(8000);

// 先点"近7日"重置状态
await exec(TAB, `(function(){
    var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    var n;
    while(n=w.nextNode()){
        if(n.textContent.trim()==='近7日'){
            n.parentElement.click();
            return;
        }
    }
})()`);
await sleep(2000);

// 点"自定义"
await exec(TAB, `(function(){
    var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    var n;
    while(n=w.nextNode()){
        if(n.textContent.trim()==='自定义'){
            n.parentElement.click();
            return;
        }
    }
})()`);
await sleep(1500);

// 打开日历
await exec(TAB, `(function(){
    var i=document.querySelector('input[placeholder="开始时间"]');
    if(i){
        i.focus();
        i.click();
        i.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
    }
})()`);

// 等待日历面板加载
for (let i = 0; i < 8; i++) {
    await sleep(500);
    const cnt = await exec(TAB, 'document.querySelectorAll(".css-1e487he").length');
    if (parseInt(cnt) >= 2) break;
}
await sleep(500);

// 检查当前显示月份
const months = await exec(TAB, `
    Array.from(document.querySelectorAll('.css-q8o7ik'))
        .map(x => x.innerText.replace(/\\s+/g, ''))
        .join('|')
`);
console.log('当前日历:', months); // 例如 "2026年03月|2026年04月"

// 点击第一个日期（panel[0]的1号）
await exec(TAB, `(function(){
    var p = document.querySelectorAll('.css-1e487he');
    if (!p[0]) return 'no panel';
    var cells = Array.from(p[0].querySelectorAll('.calendar-dayCell'));
    var c = cells.find(x => x.innerText.trim() === '1');
    if (!c) return 'no cell';
    ['pointerdown', 'pointerup', 'click'].forEach(ev => {
        c.dispatchEvent(new PointerEvent(ev, {
            bubbles: true,
            cancelable: true,
            pointerId: 1,
            pointerType: 'mouse'
        }));
    });
    return 'ok';
})()`);
await sleep(800);

// 点击第二个日期（panel[0]的27号）
await exec(TAB, `(function(){
    var p = document.querySelectorAll('.css-1e487he');
    if (!p[0]) return 'no panel';
    var cells = Array.from(p[0].querySelectorAll('.calendar-dayCell'));
    var c = cells.find(x => x.innerText.trim() === '27');
    if (!c) return 'no cell';
    ['pointerdown', 'pointerup', 'click'].forEach(ev => {
        c.dispatchEvent(new PointerEvent(ev, {
            bubbles: true,
            cancelable: true,
            pointerId: 1,
            pointerType: 'mouse'
        }));
    });
    return 'ok';
})()`);
await sleep(3000);

// 验证结果
const stat = await exec(TAB, `(function(){
    var b = document.body.innerText;
    var i = b.indexOf('统计时间');
    return i > -1 ? b.slice(i, i+50).replace(/\\n/g, ' ') : 'NOT FOUND';
})()`);
console.log('结果:', stat); // 应该显示 2026-03-01~2026-03-27

// 保存数据
const body = await exec(TAB, 'document.body.innerText');
// writeFileSync('...', body);
```

---

## 推荐方案：每日增量采集

**原因**：
- 历史回溯需要翻页 → 日历行为不可靠
- 同面板选择的覆盖范围 ≤ 31天（一个月内）
- 跨月份范围需要拼接多段 → 复杂度↑

**实现**：
```javascript
// 每日 cron 任务：采集昨天的数据
// 日期: today-1 ~ today-1
// 示例: 2026-03-28 采集 2026-03-27 的数据
```

**优势**：
- ✅ 日历默认显示当月 → 无需翻页
- ✅ 单日数据 = 起始日=结束日 → 无需两次点击
- ✅ 累积90天数据 → 每日3KB × 90 = 270KB

---

## 技术细节

### DOM结构

- **日历容器**: `.css-1yp4ln`
- **月份面板**: `.css-1e487he` (共2个，panel[0]和panel[1])
- **日期格**: `.calendar-dayCell`
- **月份标题**: `.css-q8o7ik`
- **导航SVG**: `.css-1nslssr .css-707ean svg`（共4个，左面板上一年/上一月，右面板下一月/下一年）

### API端点（备选方案）

```
POST https://ark.xiaohongshu.com/api/edith/butterfly/data?type=sellerDealCarrierOverall
Content-Type: application/json

{
  "sellerId": "65ad2c90a553de0001f203ee",
  "startDate": "2026-03-01",
  "endDate": "2026-03-27"
}
```

**注**：API需要特殊签名header，当前返回 `{code:0, success:true, msg:"成功"}` 但无data字段。需要逆向完整的请求签名算法。

---

## 维护日志

| 日期 | 发现 |
|------|------|
| 2026-03-28 | 初始版本：确认同面板选择可行，跨面板/翻页失败 |

---

## 参考资料

- [opencli 文档](https://github.com/jackwener/opencli)
- 千帆 URL: https://ark.xiaohongshu.com/app-datacenter/business-overview
- Obsidian Vault: `~/Library/Mobile Documents/com~apple~CloudDocs/Thoth_Academy_Obsidian/Revenue OS/`
