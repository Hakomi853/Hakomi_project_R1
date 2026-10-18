// 把联想笔记本的充电模式锁在「养护模式」(2)
// 通过联想电脑管家自带的 MCP 服务读写充电模式；发现被改成其它模式就立刻改回来。
//
// 用法: node keep-conservation-mode.mjs
//   建议开机自启（见同目录 启动守护.vbs）：每次启动跑一遍即可。
// 状态文件（日志、暂停标记）都放在脚本所在目录，整个文件夹可直接拷走使用。
import { spawn } from 'node:child_process';
import readline from 'node:readline';
import { appendFileSync, existsSync, readFileSync, writeFileSync, statSync, unlinkSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import os from 'node:os';

const BASE = path.dirname(fileURLToPath(import.meta.url));

// 以「低于正常」优先级运行：即使每分钟启动一次，也不会跟游戏/渲染抢 CPU
try {
  os.setPriority(0, os.constants.priority.PRIORITY_BELOW_NORMAL);
} catch {
  /* 忽略 */
}

// 联想电脑管家的 MCP 服务，可用环境变量 PCM_EXE 覆盖
const EXE =
  process.env.PCM_EXE ??
  'C:\\ProgramData\\Lenovo\\LeMcpManager\\servers\\tai-pcm-mcp-server\\pcm_mcp_server.exe';
const LOG = path.join(BASE, 'conservation-mode-log.txt');
const TARGET_MODE = '2'; // 1=常规 2=养护(80%) 3=智能快充 4=夜晚优化
const TARGET_NAME = '养护模式';
// 暂停标记：存在时守护进入「暂停」状态（不再强制养护模式），只等电池充满后自动恢复
const PAUSE_FLAG = path.join(BASE, 'conservation-paused.flag');
// 认为「已充满」的电量阈值(%)，可用环境变量 KEEP_FULL_THRESHOLD 覆盖（便于测试）
const FULL_THRESHOLD = Number(process.env.KEEP_FULL_THRESHOLD ?? 100);

function stamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function log(line) {
  try {
    // 首次创建时写入 BOM，保证记事本 / PowerShell 都能正确识别中文
    const bom = existsSync(LOG) ? '' : '\uFEFF';
    appendFileSync(LOG, bom + line + '\r\n', 'utf8');
    // 高频运行时防止日志无限增长：超过 400 KB 就只保留最近 5000 行
    if (statSync(LOG).size > 400 * 1024) {
      const kept = readFileSync(LOG, 'utf8')
        .split(/\r?\n/)
        .filter((l) => l !== '')
        .slice(-5000);
      writeFileSync(LOG, '\uFEFF' + kept.join('\r\n') + '\r\n', 'utf8');
    }
  } catch {
    /* 忽略日志写入失败 */
  }
}

if (!existsSync(EXE)) {
  log(`${stamp()} | 错误 | 未找到 PCM 服务：${EXE}`);
  console.error('未找到联想电脑管家的 PCM 服务，本工具仅适用于安装了联想电脑管家的联想笔记本。');
  process.exit(1);
}

const child = spawn(EXE, [], { stdio: ['pipe', 'pipe', 'pipe'] });
const rl = readline.createInterface({ input: child.stdout });
const pending = new Map();
let nextId = 1;
child.stderr.on('data', () => {});
child.on('error', (e) => {
  log(`${stamp()} | 错误 | 无法启动 MCP 服务: ${e.message}`);
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

try {
  await rpc('initialize', {
    protocolVersion: '2024-11-05',
    capabilities: {},
    clientInfo: { name: 'keep-conservation-mode', version: '1.0' },
  });
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} }) + '\n');

  if (existsSync(PAUSE_FLAG)) {
    // ---- 暂停/满电状态 ----
    // 标记内容 {"mode":"keep"} = 满电模式（点「电量满满」进入，不自动恢复）
    // 其它（旧格式/空文件）    = 临时暂停，充满后自动恢复
    let flag = { mode: 'temp' };
    try {
      flag = JSON.parse(readFileSync(PAUSE_FLAG, 'utf8'));
    } catch {
      flag = { mode: 'temp' };
    }

    const batt = await call('get_device_status_info', { type: '2' });
    const level = Number.parseInt(String(batt['battery percentage'] ?? '').replace(/[^0-9]/g, ''), 10);
    const levelText = Number.isFinite(level) ? level : '?';

    if (flag.mode === 'keep') {
      // 满电模式：完全不干预，只在电量变化或每 30 分钟记一次日志
      const stale = !flag.lastLog || Date.now() - Number(flag.lastLog) > 30 * 60 * 1000;
      if (level !== flag.lastLevel || stale) {
        const line = `${stamp()} | 满电模式中 | 电量 ${levelText}% | 不自动恢复（等按「电池护士」）`;
        console.log(line);
        log(line);
        flag.lastLevel = level;
        flag.lastLog = Date.now();
        try {
          writeFileSync(PAUSE_FLAG, JSON.stringify(flag), 'utf8');
        } catch {
          /* 忽略 */
        }
      }
    } else if (Number.isFinite(level) && level >= FULL_THRESHOLD) {
      try {
        unlinkSync(PAUSE_FLAG);
      } catch {
        /* 忽略 */
      }
      const set = await call('set_charge_config', { type: TARGET_MODE });
      const after = await call('get_charge_status');
      const line = `${stamp()} | 已充满 ${level}% -> 自动恢复${TARGET_NAME} (${set.desc ?? 'ok'}) | 当前模式 ${after.charging_mode}`;
      console.log(line);
      log(line);
    } else {
      const line = `${stamp()} | 暂停中 | 电量 ${levelText}% | 等待充满后自动恢复`;
      console.log(line);
      log(line);
    }
    child.kill();
    process.exit(0);
  }

  const before = await call('get_charge_status');
  const modeBefore = String(before.charging_mode ?? '?');
  let action = '无需处理';

  if (modeBefore !== TARGET_MODE) {
    const set = await call('set_charge_config', { type: TARGET_MODE });
    action = `已改回${TARGET_NAME} (${set.desc ?? set.raw ?? 'ok'})`;
  }

  const after = await call('get_charge_status');
  const modeAfter = String(after.charging_mode ?? '?');

  const line = `${stamp()} | 模式 ${modeBefore} -> ${modeAfter} | ${action}`;
  console.log(line);
  log(line);

  if (modeAfter !== TARGET_MODE) {
    const fail = `${stamp()} | 警告 | 设置后仍为模式 ${modeAfter}，未能锁在${TARGET_NAME}`;
    console.log(fail);
    log(fail);
    process.exitCode = 1;
  }
} catch (e) {
  const line = `${stamp()} | 错误 | ${e.message}`;
  console.log(line);
  log(line);
  process.exitCode = 1;
} finally {
  child.kill();
}
process.exit(process.exitCode ?? 0);
