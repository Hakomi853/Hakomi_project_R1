# 电池管理 · 满电 / 养护 一键切换

给联想笔记本用的两个桌面按钮:一个把充电上限放开到 100%(满电模式),一个立刻恢复 80% 养护模式。再配一个开机自启的守护脚本,防止充电模式被改回去。

## 功能

- **电量满满**:关闭 80% 充电上限,一直充到 100%,并弹出省电建议清单(按效果排序)。
- **电池护士**:恢复养护模式(约 80%),并提醒把之前为续航改过的设置改回来。
- **开机自启守护**:登录时检查一次充电模式,如果不是养护模式就改回去。
- **两种暂停状态区分**:满电模式下守护完全不干预;临时暂停则充满后自动恢复养护。

## 依赖

| 项目 | 要求 |
| --- | --- |
| 系统 | Windows 10 / 11 |
| 硬件 | 联想笔记本(充电模式由联想电脑管家接管) |
| 软件 | 联想电脑管家(提供 PCM MCP 服务 `pcm_mcp_server.exe`) |
| 运行环境 | Node.js 18 以上,装在 `%ProgramFiles%\nodejs` 或已在 PATH 中 |

> 换到非联想电脑上也能正常运行,只是会明确弹出「没有找到联想电脑管家的 PCM 服务」,不会改动任何系统设置。

## 使用

1. 双击 `电池护士.vbs` 或 `电量满满.vbs` 即可,结果用弹窗显示。
2. 开机自启(可选):双击 `安装开机自启.vbs`,它只往「启动」文件夹写一个入口,想取消就删掉那里生成的 `LenovoKeepConservationMode.vbs`。
3. 整个文件夹可以随意移动或改名,脚本按自身位置解析路径。

命令行调试(不弹窗,直接输出到控制台):

```bat
cscript //nologo "电池护士.vbs" silent
node battery-mode.mjs nurse
node keep-conservation-mode.mjs
```

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `电池护士.vbs` | 按钮:恢复养护模式(80%) |
| `电量满满.vbs` | 按钮:进入满电模式(100%) |
| `安装开机自启.vbs` | 把守护脚本注册为开机启动 |
| `启动守护.vbs` | 静默启动守护脚本,无控制台窗口 |
| `battery-mode.mjs` | 两个按钮共用的后端逻辑 |
| `keep-conservation-mode.mjs` | 守护:把充电模式锁回养护模式 |

两个按钮其实是**完全相同的代码**,靠文件名里是否含「满满」来决定模式 —— 改一处逻辑时记得同步另一份。

## 工作原理

```
双击 .vbs
   └─ 定位 node.exe → 运行 battery-mode.mjs full|nurse
         └─ 启动 联想 pcm_mcp_server.exe,用 JSON-RPC 调用
               set_charge_config / get_charge_status / get_device_status_info
         └─ 把结果写成 UTF-16LE 的 conservation-button-msg.txt
   └─ .vbs 读取该文件,用 MsgBox 显示
```

守护脚本另有一套暂停机制:存在 `conservation-paused.flag` 时不强制改模式。标记里 `{"mode":"keep"}` 表示用户主动选了满电模式,永不自动恢复;其它内容表示临时暂停,电量到 100% 后自动恢复养护。

## 运行时文件(不入库)

| 文件 | 说明 |
| --- | --- |
| `conservation-button-msg.txt` | 按钮与 VBS 之间的消息中转,每次运行重建 |
| `conservation-mode-log.txt` | 操作日志,超过 400 KB 自动截断保留最近 5000 行 |
| `conservation-paused.flag` | 暂停/满电标记 |

它们都已被 `.gitignore` 排除,首次运行自动生成。

## 为什么 `.vbs` 存成 UTF-16

Windows Script Host 只可靠支持 ANSI 与 UTF-16LE;含中文注释时用 UTF-16LE 才能在任何系统区域设置下都不乱码。代价是 git 把这些文件当二进制处理 —— 无法逐行 diff,但内容完全可用。

## 常见问题

- **双击没反应**:在 cmd 里跑 `node -v` 确认 Node 可用;或右键用 `cscript //nologo 电池护士.vbs` 看报错。
- **提示找不到 PCM 服务**:确认装了联想电脑管家;管家装在非默认位置时,设置环境变量 `PCM_EXE` 指向 `pcm_mcp_server.exe`。
- **点了没效果**:先看 `conservation-mode-log.txt` 最后几行,通常是管家没运行或服务超时。
