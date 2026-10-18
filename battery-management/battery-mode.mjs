// 「电量满满」和「电池护士」两个按钮的后端逻辑
//   node battery-mode.mjs full   -> 满电模式：关掉 80% 上限、保持满电、不自动恢复，并列出省电建议
//   node battery-mode.mjs nurse  -> 养护模式：恢复 80% 上限，并提醒把为续航改过的设置改回来
// 结果写成 UTF-16LE 消息文件，供 VBS 按钮用 MsgBox 显示
//
// 本文件不依赖任何绝对路径：状态文件统一放在脚本所在目录，便于整个文件夹拷到别的电脑上使用。
import { spawn } from 'node:child_process';
import readline from 'node:readline';
import { existsSync, unlinkSync, writeFileSync, appendFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = path.dirname(fileURLToPath(import.meta.url));

// 联想电脑管家自带的 MCP 服务；装了管家一般在固定位置，可用环境变量 PCM_EXE 覆盖
const EXE =
  process.env.PCM_EXE ??
  'C:\\ProgramData\\Lenovo\\LeMcpManager\\servers\\tai-pcm-mcp-server\\pcm_mcp_server.exe';

const FLAG = path.join(BASE, 'conservation-paused.flag');
const MSG = path.join(BASE, 'conservation-button-msg.txt');
const LOG = path.join(BASE, 'conservation-mode-log.txt');

const MODE_FULL = '1'; // 常规模式：0→100%
const MODE_NURSE = '2'; // 养护模式：75~80%

const arg = String(process.argv[2] ?? '').toLowerCase();
const isFull = arg === 'full';

function stamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function log(line) {
  try {
    const bom = existsSync(LOG) ? '' : '\uFEFF';
    appendFileSync(LOG, bom + line + '\r\n', 'utf8');
  } catch {
    /* 忽略 */
  }
}
function writeMsg(text) {
  // VBS 端按 Unicode 读取，所以写成 UTF-16LE + BOM
  writeFileSync(MSG, Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(text, 'utf16le')]));
}

// ---- 环境检查：缺什么就明确告诉用户，而不是抛一堆栈 ----
if (!existsSync(EXE)) {
  const hint =
    '没有找到联想电脑管家的 PCM 服务 ❌\n\n' +
    `期望路径：\n${EXE}\n\n` +
    '本工具只适用于「联想笔记本 + 已安装联想电脑管家」。\n' +
    '如果管家装在别处，可设置环境变量 PCM_EXE 指向 pcm_mcp_server.exe 再试。';
  writeMsg(hint);
  log(`${stamp()} | 错误 | 未找到 PCM 服务：${EXE}`);
  process.exit(1);
}

const child = spawn(EXE, [], { stdio: ['pipe', 'pipe', 'pipe'] });
const rl = readline.createInterface({ input: child.stdout });
const pending = new Map();
let nextId = 1;
child.stderr.on('data', () => {});
child.on('error', (e) => {
  const line = `${stamp()} | 错误 | 无法启动 PCM 服务: ${e.message}`;
  log(line);
  writeMsg(`操作失败 ❌\n\n无法启动联想电脑管家服务：\n${e.message}\n\n请确认管家正在运行。`);
  process.exit(1);
});
rl.on('line', (line) => {
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }
  if (msg.id !== undefined && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});

function rpc(method, params) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, resolve);
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        reject(new Error(method + ' 超时'));
      }
    }, 20000);
  });
}
async function call(name, args = {}) {
  const res = await rpc('tools/call', { name, arguments: args });
  const text = (res?.result?.content ?? []).map((c) => c.text ?? '').join(' ').trim();
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}
async function batteryLevel() {
  const bt = await call('get_device_status_info', { type: '2' });
  const n = Number.parseInt(String(bt['battery percentage'] ?? '').replace(/[^0-9]/g, ''), 10);
  return Number.isFinite(n) ? n : null;
}

const TIPS = [
  ' 1. 关掉独显 —— Legion Zone → 显卡模式 → 混合 / 核显',
  '    （省 10~20W，效果最大的一条）',
  ' 2. 性能模式切「安静」—— 按 Fn+Q 循环切换',
  ' 3. 屏幕刷新率降到 60Hz',
  ' 4. 屏幕亮度调低（屏幕是耗电大户）',
  ' 5. 关掉键盘 RGB 背光',
  ' 6. Windows 电源模式设为「最佳能效」',
];

const REVERT = [
  ' 1. 显卡模式 → 恢复「独显直连」或「混合」（Legion Zone）',
  ' 2. 性能模式 → 恢复「野兽 / 智能」（Fn+Q 或 Legion Zone）',
  ' 3. 屏幕刷新率 → 恢复高刷新率',
  ' 4. 屏幕亮度 → 恢复常用亮度',
  ' 5. 键盘 RGB 背光 → 恢复',
  ' 6. Windows 电源模式 → 恢复「平衡」或「高性能」',
];

try {
  await rpc('initialize', {
    protocolVersion: '2024-11-05',
    capabilities: {},
    clientInfo: { name: 'battery-management', version: '1.0' },
  });
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} }) + '\n');

  const lv = await batteryLevel();
  const lvText = lv === null ? '?' : lv;

  if (isFull) {
    // ---------- 电量满满：满电模式 ----------
    writeFileSync(
      FLAG,
      JSON.stringify({
        mode: 'keep',
        since: stamp(),
        lastLevel: lv,
        lastLog: Date.now(),
      }),
      'utf8',
    );
    await call('set_charge_config', { type: MODE_FULL });
    const st = await call('get_charge_status');

    writeMsg(
      `电量满满 ⚡ 已进入「满电模式」\n\n` +
        `已关闭 80% 充电上限，会一直充到 100% 并保持满电。\n` +
        `当前电量：${lvText}%\n` +
        `当前模式：${st.desc ?? ''}\n\n` +
        `想榨出更多续航，建议做这几件事（按效果排序）：\n\n` +
        TIPS.join('\n') +
        `\n\n` +
        `————————————————\n` +
        `用完回来记得点「电池护士」恢复养护模式。\n` +
        `（长期停在 100% 会加速电池老化）`,
    );
    log(`${stamp()} | 按钮 | 电量满满：进入满电模式 (电量 ${lvText}%)`);
  } else {
    // ---------- 电池护士：恢复养护模式 ----------
    try {
      unlinkSync(FLAG);
    } catch {
      /* 忽略 */
    }
    await call('set_charge_config', { type: MODE_NURSE });
    const st = await call('get_charge_status');

    writeMsg(
      `电池护士 💚 已恢复「养护模式」\n\n` +
        `充电上限回到约 80%，守护脚本已恢复每分钟巡检。\n` +
        `当前电量：${lvText}%\n` +
        `当前模式：${st.desc ?? ''}\n\n` +
        `别忘了把之前为续航改过的设置改回来：\n\n` +
        REVERT.join('\n') +
        `\n\n` +
        `（没改过的话忽略即可）`,
    );
    log(`${stamp()} | 按钮 | 电池护士：恢复养护模式 (电量 ${lvText}%)`);
  }
} catch (e) {
  writeMsg(
    `操作失败 ❌\n\n${e.message}\n\n` + `请确认联想电脑管家正常运行，或查看日志：\n${LOG}`,
  );
  log(`${stamp()} | 按钮 | 错误 ${e.message}`);
  process.exitCode = 1;
} finally {
  child.kill();
}
process.exit(process.exitCode ?? 0);
