# 悬浮文件夹

Windows 桌面文件夹工具。鼠标悬停在桌面快捷方式上时显示内容，双击快捷方式可在资源管理器中打开目录。

## 构建与运行

需要 64 位 Windows 和 .NET Framework 4.8。打开 PowerShell，进入本目录后运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
.\dist\悬浮文件夹.exe /manage
```

在管理器里点击「新建文件夹」，填写显示名称并选择已有目录，或留空让程序创建目录。选中已有项目后，可以更换桌面图标、设置展开栏标题图片，或点击「预览」拖动排序。同页排序后会保留当前网格，展开栏的「管理」按钮会直接打开对应的属性。

配置保存在当前用户的 `%LOCALAPPDATA%\HoverFolders` 下。该目录包含本机设置和内容文件夹，构建产物写入 `dist/`。
