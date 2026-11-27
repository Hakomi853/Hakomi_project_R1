using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Interop;
using System.Windows.Controls;
using System.Windows.Threading;
using System.Collections.Generic;
using D=System.Drawing;

namespace DeskFolders {
static class Art {
    public static byte[] Ico(ImageSource source){
        var sizes=new[]{16,20,24,32,40,48,64,128,256};var blobs=new List<byte[]>();
        foreach(int size in sizes){var v=new DrawingVisual();using(var g=v.RenderOpen()){
            double ratio=Math.Min(size/source.Width,size/source.Height);double w=source.Width*ratio,h=source.Height*ratio;
            g.DrawImage(source,new Rect((size-w)/2,(size-h)/2,w,h));}
            var bmp=new RenderTargetBitmap(size,size,96,96,PixelFormats.Pbgra32);bmp.Render(v);
            var enc=new PngBitmapEncoder();enc.Frames.Add(BitmapFrame.Create(bmp));using(var m=new MemoryStream()){enc.Save(m);blobs.Add(m.ToArray());}}
        using(var m=new MemoryStream())using(var b=new BinaryWriter(m)){
            b.Write((ushort)0);b.Write((ushort)1);b.Write((ushort)sizes.Length);int offset=6+16*sizes.Length;
            for(int i=0;i<sizes.Length;i++){b.Write((byte)sizes[i]);b.Write((byte)sizes[i]);b.Write((ushort)0);b.Write((ushort)1);b.Write((ushort)32);
                b.Write(blobs[i].Length);b.Write(offset);offset+=blobs[i].Length;}
            foreach(var bytes in blobs)b.Write(bytes);return m.ToArray();}
    }
}
class DirectoryIdentity : IDisposable {
    [DllImport("kernel32",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern SafeFileHandle CreateFile(string p,uint access,uint share,IntPtr security,uint mode,uint flags,IntPtr template);
    [DllImport("kernel32",CharSet=CharSet.Unicode)]
    static extern uint GetFinalPathNameByHandle(SafeFileHandle h,StringBuilder s,uint len,uint flags);
    SafeFileHandle handle;
    public DirectoryIdentity(string p){handle=CreateFile(p,0,7,IntPtr.Zero,3,0x02000000,IntPtr.Zero);}
    public string Current(){
        if(handle.IsInvalid)return null;var b=new StringBuilder(512);uint len=GetFinalPathNameByHandle(handle,b,(uint)b.Capacity,0);
        if(len>=b.Capacity){b.EnsureCapacity((int)len+1);len=GetFinalPathNameByHandle(handle,b,(uint)b.Capacity,0);}
        if(len==0)return null;string p=b.ToString();if(p.StartsWith(@"\\?\UNC\"))return @"\\"+p.Substring(8);return p.StartsWith(@"\\?\")?p.Substring(4):p;
    }
    public void Dispose(){handle.Dispose();}
}
static class ShellDesktop {
    [DllImport("user32")]static extern IntPtr WindowFromPoint(D.Point p);
    [DllImport("user32")]static extern IntPtr GetParent(IntPtr h);
    [DllImport("user32",CharSet=CharSet.Unicode)]static extern int GetClassName(IntPtr h,StringBuilder s,int n);
    [DllImport("oleacc")]static extern int AccessibleObjectFromPoint(D.Point p,[MarshalAs(UnmanagedType.Interface)]out Accessibility.IAccessible obj,[MarshalAs(UnmanagedType.Struct)]out object child);
    static string Class(IntPtr h){var s=new StringBuilder(80);GetClassName(h,s,80);return s.ToString();}
    internal static IntPtr DesktopAt(D.Point point){
        var handle=WindowFromPoint(point);
        if(Class(handle)!="SysListView32"||Class(GetParent(handle))!="SHELLDLL_DefView")return IntPtr.Zero;
        string host=Class(GetParent(GetParent(handle)));
        return host=="Progman"||host=="WorkerW"?handle:IntPtr.Zero;
    }
    internal static string Hit(out Rect bounds){
        bounds=Rect.Empty;
        if(System.Windows.Forms.Control.MouseButtons!=System.Windows.Forms.MouseButtons.None)return null;
        return Hit(System.Windows.Forms.Cursor.Position,out bounds);
    }
    internal static string Hit(D.Point point,out Rect bounds){
        bounds=Rect.Empty;
        if(DesktopAt(point)==IntPtr.Zero)return null;
        Accessibility.IAccessible a=null;
        try{object child;if(AccessibleObjectFromPoint(point,out a,out child)!=0||a==null)return null;
            if(Convert.ToInt32(a.get_accRole(child))!=34)return null;
            int x,y,w,height;a.accLocation(out x,out y,out w,out height,child);if(w<=0||height<=0)return null;
            bounds=new Rect(x/Native.Scale,y/Native.Scale,w/Native.Scale,height/Native.Scale);return a.get_accName(child);
        }catch(COMException){return null;}finally{if(a!=null&&Marshal.IsComObject(a))Marshal.ReleaseComObject(a);}
    }
    internal static bool HasLegacySuffix(string name){return System.Text.RegularExpressions.Regex.IsMatch(name,@"（悬浮(?: \d+)?）$");}
    internal static string CleanLegacyName(string name){return System.Text.RegularExpressions.Regex.Replace(name,@"（悬浮(?: \d+)?）$","");}
    internal static string FreeLink(string name,string existing){
        var safe=string.Concat(name.Select(c=>Path.GetInvalidFileNameChars().Contains(c)?'＿':c)).TrimEnd(' ','.');
        if(safe.Length==0)safe="悬浮文件夹";
        for(int i=0;;i++){
            string leaf=safe+(i==0?"":" ("+(i+1)+")");string p=Path.Combine(Program.Desktop,leaf+".lnk");
            if(string.Equals(p,existing,StringComparison.OrdinalIgnoreCase))return p;
            if(!Directory.Exists(Path.Combine(Program.Desktop,leaf))&&!File.Exists(p)&&!File.Exists(Path.Combine(Program.Desktop,leaf)))return p;
        }
    }
    internal static string Resolved(string link){
        object shell=null,dir=null,item=null,shortcut=null;
        try{dynamic sh=shell=Activator.CreateInstance(Type.GetTypeFromProgID("Shell.Application"));
            dynamic folder=dir=sh.NameSpace(Path.GetDirectoryName(link));dynamic file=item=folder.ParseName(Path.GetFileName(link));
            dynamic sc=shortcut=file.GetLink;sc.Resolve(1|16|(800<<16));return (string)sc.Path;
        }catch{return null;}finally{foreach(var o in new[]{shortcut,item,dir,shell})if(o!=null&&Marshal.IsComObject(o))Marshal.ReleaseComObject(o);}
    }
    const string ManagerLink="悬浮文件夹管理.lnk";
    static readonly string ManagerExe=System.Reflection.Assembly.GetEntryAssembly().Location;

    internal static void CreateManagerShortcut(string folder){
        string file=Path.Combine(folder,ManagerLink);
        if(File.Exists(file))return;
        object shell=null,shortcut=null;
        try{
            dynamic sh=shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            dynamic link=shortcut=sh.CreateShortcut(file);
            link.TargetPath=ManagerExe;link.Arguments="/manage";link.WorkingDirectory=Path.GetDirectoryName(ManagerExe);
            link.Description="打开悬浮文件夹管理";link.IconLocation=ManagerExe+",0";link.Save();
        }finally{if(shortcut!=null)Marshal.ReleaseComObject(shortcut);if(shell!=null)Marshal.ReleaseComObject(shell);}
    }
    internal static bool IsManagerShortcut(FileSystemInfo file){
        if(!file.Name.Equals(ManagerLink,StringComparison.OrdinalIgnoreCase))return false;
        object shell=null,shortcut=null;
        try{
            dynamic sh=shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            dynamic link=shortcut=sh.CreateShortcut(file.FullName);
            return string.Equals((string)link.TargetPath,ManagerExe,StringComparison.OrdinalIgnoreCase)&&(string)link.Arguments=="/manage";
        }catch{return false;}
        finally{if(shortcut!=null)Marshal.ReleaseComObject(shortcut);if(shell!=null)Marshal.ReleaseComObject(shell);}
    }
    internal static void Link(Folder f,string file){
        object sh=null,sc=null;
        try{dynamic shell=sh=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));dynamic link=sc=shell.CreateShortcut(file);
            link.TargetPath=f.Path;link.Description="位置："+f.Path;
            if(File.Exists(f.Icon)){
                string ico=f.Icon;if(!Path.GetExtension(ico).Equals(".ico",StringComparison.OrdinalIgnoreCase)){
                    var assets=Path.Combine(Program.Home,"图标");Directory.CreateDirectory(assets);
                    ico=Path.Combine(assets,f.Id+".ico");File.WriteAllBytes(ico,Art.Ico(UI.LoadImage(f.Icon)));}
                link.IconLocation=ico+",0";
            }else link.IconLocation=Path.Combine(Environment.SystemDirectory,"shell32.dll")+",3";
            link.Save();
        }finally{if(sc!=null)Marshal.ReleaseComObject(sc);if(sh!=null)Marshal.ReleaseComObject(sh);}
    }
}
sealed class DesktopClickListener : IDisposable {
    const int LowLevelMouse=14, MouseMove=0x200, LeftDown=0x201, LeftUp=0x202;
    delegate IntPtr MouseCallback(int code,IntPtr message,IntPtr data);
    [DllImport("user32",SetLastError=true)] static extern IntPtr SetWindowsHookEx(int type,MouseCallback callback,IntPtr module,uint thread);
    [DllImport("user32")] static extern IntPtr CallNextHookEx(IntPtr hook,int code,IntPtr message,IntPtr data);
    [DllImport("user32")] static extern bool UnhookWindowsHookEx(IntPtr hook);
    [DllImport("kernel32",CharSet=CharSet.Unicode)] static extern IntPtr GetModuleHandle(string module);
    readonly System.Windows.Threading.Dispatcher dispatcher;
    readonly MouseCallback callback;
    readonly Action<D.Point> clicked;
    readonly D.Size dragSize=System.Windows.Forms.SystemInformation.DragSize;
    IntPtr hook, pressedDesktop;
    D.Point pressed;

    internal DesktopClickListener(System.Windows.Threading.Dispatcher dispatcher,Action<D.Point> clicked){
        this.dispatcher=dispatcher;this.clicked=clicked;
        callback=Observe;
        hook=SetWindowsHookEx(LowLevelMouse,callback,GetModuleHandle(null),0);
    }
    IntPtr Observe(int code,IntPtr message,IntPtr data){
        if(code>=0){
            int kind=message.ToInt32();
            if(kind==LeftDown){
                pressed=new D.Point(Marshal.ReadInt32(data),Marshal.ReadInt32(data,4));
                pressedDesktop=ShellDesktop.DesktopAt(pressed);
            }else if(pressedDesktop!=IntPtr.Zero&&(kind==MouseMove||kind==LeftUp)){
                var point=new D.Point(Marshal.ReadInt32(data),Marshal.ReadInt32(data,4));
                if(Math.Abs(point.X-pressed.X)*2>=dragSize.Width||Math.Abs(point.Y-pressed.Y)*2>=dragSize.Height)
                    pressedDesktop=IntPtr.Zero;
                if(kind==LeftUp){
                    var desktop=pressedDesktop;pressedDesktop=IntPtr.Zero;
                    if(desktop!=IntPtr.Zero&&ShellDesktop.DesktopAt(point)==desktop&&!dispatcher.HasShutdownStarted)
                        dispatcher.BeginInvoke(new Action(()=>clicked(point)));
                }
            }
        }
        return CallNextHookEx(hook,code,message,data);
    }
    public void Dispose(){
        if(hook==IntPtr.Zero)return;
        UnhookWindowsHookEx(hook);hook=IntPtr.Zero;
    }
}
static class Palette {
    public static bool Dark;
    static readonly Dictionary<string,string> colors=new Dictionary<string,string>{
        {"#22252A","#F4F4F5"},{"#FAFAFA","#3A3A3A"},{"#D2D3D5","#454545"},{"#E5ECF5","#444444"},{"#F7F8FA","#303030"},
        {"#BBBFC5","#3B3B3B"},{"#C5C8CC","#484848"},{"#FFFFFF","#343434"},{"#F5F6F8","#2B2B2B"},{"#D8DADF","#3B3B3B"},
        {"#DAEAFB","#304C68"},{"#616670","#B7BBC2"}};
    public static Brush Brush(string key){return (Brush)new BrushConverter().ConvertFromString(Dark&&colors.ContainsKey(key)?colors[key]:key);}
    public static Brush ButtonStroke(){
        var top=(Color)ColorConverter.ConvertFromString(Dark?"#595959":"#DBDBDB");
        var lower=(Color)ColorConverter.ConvertFromString(Dark?"#444444":"#E8E8E8");
        var brush=new LinearGradientBrush{StartPoint=new Point(0,0),EndPoint=new Point(0,1)};
        brush.GradientStops.Add(new GradientStop(top,0));brush.GradientStops.Add(new GradientStop(lower,.09));
        return brush;
    }
    [DllImport("dwmapi")]static extern int DwmSetWindowAttribute(IntPtr h,int attr,ref int value,int size);
    public static void Caption(Window w){int v=Dark?1:0;DwmSetWindowAttribute(new WindowInteropHelper(w).Handle,20,ref v,4);}
}
}
