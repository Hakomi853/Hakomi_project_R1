using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using System.Runtime.InteropServices;
using System.Xml.Linq;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Media.Animation;
using System.Windows.Media.Effects;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Threading;
using System.Windows.Automation;
using Forms=System.Windows.Forms;
using D=System.Drawing;
using P=System.Windows.Point;

namespace DeskFolders {
class Folder {
    public string Name, Path, Icon="", TitleImage="", Link="", Id=Guid.NewGuid().ToString("N");
    public string[] Order=new string[0];
    public bool Snap=true;
    public double X, Y;
    public Folder Copy(){return (Folder)MemberwiseClone();}
}
class Program {
    internal static readonly string Home=System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"HoverFolders");
    internal static readonly string Desktop=Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
    internal static readonly List<Widget> Widgets=new List<Widget>();
    internal static Manager Manager;
    static EventWaitHandle signal;
    static DispatcherTimer monitor;
    internal static void Manage(Widget widget){
        if(Manager==null){Manager=new Manager();Manager.Closed+=(s,e)=>Manager=null;}
        Manager.Select(widget);Manager.Show();Manager.WindowState=WindowState.Normal;Manager.Activate();
    }
    internal static Widget Add(Folder f){var w=new Widget(f);Widgets.Add(w);return w;}
    internal static void Save(){
        var doc=new XDocument(new XElement("folders",new XAttribute("dark",Palette.Dark),Widgets.Select(w=>new XElement("folder",
          new XAttribute("id",w.F.Id),new XAttribute("link",w.F.Link),new XAttribute("name",w.F.Name),new XAttribute("path",w.F.Path),new XAttribute("icon",w.F.Icon),
          new XAttribute("x",w.F.X),new XAttribute("y",w.F.Y),new XAttribute("snap",w.F.Snap),new XAttribute("titleImage",w.F.TitleImage),w.F.Order.Select(name=>new XElement("itemOrder",name))))));
        string file=Path.Combine(Home,"folders.xml");doc.Save(file+".tmp");
        if(File.Exists(file))File.Replace(file+".tmp",file,null);else File.Move(file+".tmp",file);
    }
    static void OpenClickedFolder(D.Point point){
        Rect anchor;
        string name=ShellDesktop.Hit(point,out anchor);
        var widget=Widgets.FirstOrDefault(item=>item.MatchesDesktopName(name));
        if(widget!=null)widget.OpenFromClick(anchor);
    }
    [STAThread] static void Main(string[] args){
        bool first;
        using(var mutex=new Mutex(true,"Local\\DeskFoldersV2",out first))
        using(signal=new EventWaitHandle(false,EventResetMode.AutoReset,"Local\\DeskFoldersManage")){
            if(!first){signal.Set();return;}
            try{
                var app=new Application{ShutdownMode=ShutdownMode.OnExplicitShutdown};SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext(Dispatcher.CurrentDispatcher));Directory.CreateDirectory(Home);
                var file=Path.Combine(Home,"folders.xml");
                if(File.Exists(file)){
                    var root=XDocument.Load(file).Root;Palette.Dark=(bool?)root.Attribute("dark")??false;foreach(var el in root.Elements("folder")){
                        var folder=new Folder{Id=(string)el.Attribute("id")??Guid.NewGuid().ToString("N"),Link=(string)el.Attribute("link")??"",Name=(string)el.Attribute("name"),Path=(string)el.Attribute("path"),Icon=(string)el.Attribute("icon")??"",TitleImage=(string)el.Attribute("titleImage")??"",
                          X=(double)el.Attribute("x"),Y=(double)el.Attribute("y"),Snap=(bool)el.Attribute("snap")};
                        folder.Order=el.Elements("itemOrder").Select(item=>item.Value).ToArray();
                        Add(folder);
                    }
                }else{
                    var area=SystemParameters.WorkArea;
                    var f=new Folder{Name="悬浮文件夹",Path=Path.Combine(Desktop,"悬浮文件夹"),X=area.Right-125,Y=area.Top+80};
                    double x,y;var legacy=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"位置.txt");
                    if(File.Exists(legacy)){var p=File.ReadAllLines(legacy);if(p.Length>=2&&double.TryParse(p[0],out x)&&double.TryParse(p[1],out y)){f.X=x/Native.Scale;f.Y=y/Native.Scale;}}
                    if(!Directory.Exists(f.Path)){Directory.CreateDirectory(f.Path);ShellDesktop.CreateManagerShortcut(f.Path);}Add(f);Save();
                }
                Save();app.Exit+=(s,e)=>{foreach(var w in Widgets)w.Close();};if(Widgets.Count==0||args.Contains("/manage"))Manage(Widgets.FirstOrDefault());
                monitor=new DispatcherTimer{Interval=TimeSpan.FromMilliseconds(350)};
                monitor.Tick+=(s,e)=>{if(signal.WaitOne(0))Manage(Widgets.FirstOrDefault());};monitor.Start();
                using(new DesktopClickListener(app.Dispatcher,OpenClickedFolder))app.Run();
            }catch(Exception ex){MessageBox.Show(ex.Message,"悬浮文件夹");}
        }
    }
}
static class UI {
    internal static Brush Fill(string hex){return Palette.Brush(hex);}
    internal static readonly FontFamily Font=new FontFamily("Segoe UI, Microsoft YaHei UI");
    internal static TextBlock Text(string value,double size){return new TextBlock{Text=value,FontFamily=Font,FontSize=size,Foreground=Fill("#22252A"),VerticalAlignment=VerticalAlignment.Center};}
    internal static Button Button(string label,Action action,bool accent=false){
        var b=new Button{Content=label,FontFamily=Font,FontSize=13,Padding=new Thickness(12,5,12,5),MinHeight=30,
            Foreground=Fill("#22252A"),Background=Fill("#FAFAFA"),BorderBrush=Palette.ButtonStroke(),BorderThickness=new Thickness(1),Cursor=Cursors.Hand};
        if(accent){
            b.Background=Fill(Palette.Dark?"#51C9EF":"#0067C0");
            b.Foreground=Palette.Dark?Fill("#10252C"):Brushes.White;
            b.BorderThickness=new Thickness(0);
        }
        var border=new FrameworkElementFactory(typeof(Border));border.Name="surface";border.SetValue(Border.CornerRadiusProperty,new CornerRadius(5));
        foreach(var p in new[]{Border.BackgroundProperty,Border.BorderBrushProperty,Border.BorderThicknessProperty,Border.PaddingProperty})
            border.SetBinding(p,new System.Windows.Data.Binding(p.Name){RelativeSource=new System.Windows.Data.RelativeSource(System.Windows.Data.RelativeSourceMode.TemplatedParent)});
        var presenter=new FrameworkElementFactory(typeof(ContentPresenter));presenter.SetValue(FrameworkElement.HorizontalAlignmentProperty,HorizontalAlignment.Center);
        presenter.SetValue(FrameworkElement.VerticalAlignmentProperty,VerticalAlignment.Center);border.AppendChild(presenter);
        var template=new ControlTemplate(typeof(Button)){VisualTree=border};
        var hover=new Trigger{Property=UIElement.IsMouseOverProperty,Value=true};hover.Setters.Add(new Setter(Border.BackgroundProperty,Fill(accent?(Palette.Dark?"#47B9DE":"#005AA8"):"#E5ECF5"),"surface"));template.Triggers.Add(hover);
        var disabled=new Trigger{Property=UIElement.IsEnabledProperty,Value=false};disabled.Setters.Add(new Setter(UIElement.OpacityProperty,.45));template.Triggers.Add(disabled);
        b.Template=template;b.Click+=(s,e)=>action();return b;
    }
    internal static Window Layer(string title){return new Window{Title=title,WindowStyle=WindowStyle.None,AllowsTransparency=true,Background=Brushes.Transparent,
        ResizeMode=ResizeMode.NoResize,ShowInTaskbar=false,ShowActivated=false,SizeToContent=SizeToContent.Manual,FontFamily=Font,UseLayoutRounding=true};}
    internal static void Open(string path){try{Process.Start(new ProcessStartInfo(path){UseShellExecute=true});}catch(Exception e){MessageBox.Show(e.Message,"打开失败");}}
    internal static BitmapSource LoadImage(string file,int pixels=0){
        using(var stream=File.OpenRead(file)){
            var decoder=BitmapDecoder.Create(stream,BitmapCreateOptions.PreservePixelFormat,BitmapCacheOption.OnLoad);
            var img=pixels<=0?decoder.Frames.OrderByDescending(f=>f.PixelWidth).First():decoder.Frames.OrderBy(f=>f.PixelWidth<pixels).ThenBy(f=>Math.Abs(f.PixelWidth-pixels)).First();img.Freeze();return img;
        }
    }
}
static class Native {
    [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr h);
    [DllImport("comctl32.dll")] static extern IntPtr ImageList_GetIcon(IntPtr list,int index,uint flags);
    [DllImport("shell32.dll",EntryPoint="#727")] static extern int SHGetImageList(int size,ref Guid iid,out IntPtr list);
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct Info{public IntPtr h;public int index;public uint attr;
        [MarshalAs(UnmanagedType.ByValTStr,SizeConst=260)]public string name;[MarshalAs(UnmanagedType.ByValTStr,SizeConst=80)]public string type;}
    [DllImport("shell32.dll",CharSet=CharSet.Unicode)] static extern IntPtr SHGetFileInfo(string p,uint attr,out Info info,uint cb,uint flags);

    [DllImport("user32.dll",CharSet=CharSet.Unicode)]
    static extern uint PrivateExtractIcons(string path,int index,int width,int height,out IntPtr icon,out uint id,uint count,uint flags);
    public static readonly double Scale=GetScale();
    static double GetScale(){using(var g=D.Graphics.FromHwnd(IntPtr.Zero))return g.DpiX/96.0;}
    public static P Cursor(){var p=Forms.Cursor.Position;return new P(p.X/Scale,p.Y/Scale);}
    public static Rect Area(P p){var a=Forms.Screen.FromPoint(new D.Point((int)(p.X*Scale),(int)(p.Y*Scale))).WorkingArea;return new Rect(a.X/Scale,a.Y/Scale,a.Width/Scale,a.Height/Scale);}
    public static double Clamp(double x,double lo,double hi){return Math.Max(lo,Math.Min(x,hi));}
    static BitmapSource FromIcon(IntPtr h){
        if(h==IntPtr.Zero)return null;
        try{var image=Imaging.CreateBitmapSourceFromHIcon(h,Int32Rect.Empty,BitmapSizeOptions.FromEmptyOptions());image.Freeze();return image;}
        finally{DestroyIcon(h);}
    }
    static BitmapSource ShellIcon(string path,int pixels){
        Info info;if(SHGetFileInfo(path,0,out info,(uint)Marshal.SizeOf(typeof(Info)),0x4000)==IntPtr.Zero)return null;
        var iid=new Guid("46EB5926-582E-4017-9FDF-E8998DAA0950");IntPtr list;
        if(SHGetImageList(pixels<=48?2:4,ref iid,out list)!=0)return null;
        try{return FromIcon(ImageList_GetIcon(list,info.index,1));}finally{Marshal.Release(list);}
    }
    static BitmapSource LocalIcon(string location,string shortcut,int index,int pixels){
        if(string.IsNullOrWhiteSpace(location))return null;
        string file=Environment.ExpandEnvironmentVariables(location.Trim().Trim('"'));
        Uri uri;
        if(Uri.TryCreate(file,UriKind.Absolute,out uri)&&!uri.IsFile)return null;
        if(!Path.IsPathRooted(file))file=Path.Combine(Path.GetDirectoryName(shortcut),file);
        if(file.StartsWith(@"\")||!File.Exists(file))return null;
        string ext=Path.GetExtension(file).ToLowerInvariant();
        if(ext==".ico"||ext==".png"||ext==".jpg"||ext==".jpeg"||ext==".bmp"){
            try{return UI.LoadImage(file,pixels);}catch(NotSupportedException){return null;}
        }
        IntPtr icon;uint id;PrivateExtractIcons(file,index,pixels,pixels,out icon,out id,1,0);
        return FromIcon(icon);
    }
    static BitmapSource InternetIcon(string path,int pixels){
        string location=null;int index=0;bool section=false;
        foreach(var raw in File.ReadLines(path,System.Text.Encoding.Default).Take(256)){
            string line=raw.Trim();
            if(line.StartsWith("[")){section=line.Equals("[InternetShortcut]",StringComparison.OrdinalIgnoreCase);continue;}
            if(!section)continue;
            if(line.StartsWith("IconFile=",StringComparison.OrdinalIgnoreCase))location=line.Substring(9);
            if(line.StartsWith("IconIndex=",StringComparison.OrdinalIgnoreCase))int.TryParse(line.Substring(10),out index);
        }
        try{return LocalIcon(location,path,index,pixels);}catch(IOException){return null;}catch(ArgumentException){return null;}
    }
    internal static BitmapSource DefaultFolderIcon(int pixels){
        IntPtr icon;uint id;
        PrivateExtractIcons(Path.Combine(Environment.SystemDirectory,"shell32.dll"),3,pixels,pixels,out icon,out id,1,0);
        return FromIcon(icon)??Icon(Program.Home,pixels);
    }
    internal static BitmapSource Icon(string path,int pixels=48){
        bool web=Path.GetExtension(path).Equals(".url",StringComparison.OrdinalIgnoreCase);
        try{
            if(web){
                BitmapSource custom=null;
                try{custom=InternetIcon(path,pixels);}catch(IOException){}catch(UnauthorizedAccessException){}
                if(custom!=null)return custom;
            }
            if(string.Equals(Path.GetExtension(path),".lnk",StringComparison.OrdinalIgnoreCase)){
                object shell=null,link=null;
                try{
                    dynamic sh=shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));dynamic shortcut=link=sh.CreateShortcut(path);
                    string loc=Environment.ExpandEnvironmentVariables((string)shortcut.IconLocation);int comma=loc.LastIndexOf(',');int index;
                    if(comma>0 && int.TryParse(loc.Substring(comma+1),out index)){
                        IntPtr h;uint id;PrivateExtractIcons(loc.Substring(0,comma).Trim().Trim('"'),index,pixels,pixels,out h,out id,1,0);
                        var custom=FromIcon(h);if(custom!=null)return custom;
                    }
                    string target=shortcut.TargetPath;if(File.Exists(target)||Directory.Exists(target))path=target;
                }finally{if(link!=null)Marshal.ReleaseComObject(link);if(shell!=null)Marshal.ReleaseComObject(shell);}
            }
            var shellImage=ShellIcon(path,pixels);
            if(shellImage!=null)return shellImage;
        }catch{}
        var fallback=Imaging.CreateBitmapSourceFromHIcon(D.SystemIcons.Application.Handle,Int32Rect.Empty,BitmapSizeOptions.FromEmptyOptions());
        fallback.Freeze();return fallback;
    }
}
class GridPlan {
    public Rect Bounds;public int Cols,Rows;public P Pivot;
    public const int CW=100,RH=90,Head=48,Foot=38,Inset=8;
    public static GridPlan Make(Rect a,Rect t,int n){
        var spaces=new[]{new Size(Math.Max(0,a.Right-t.Right),a.Height),new Size(Math.Max(0,t.Left-a.Left),a.Height),
            new Size(a.Width,Math.Max(0,a.Bottom-t.Bottom)),new Size(a.Width,Math.Max(0,t.Top-a.Top))};
        GridPlan best=null;int score=-1;
        for(int side=0;side<4;side++){
            var s=spaces[side];int cols=Math.Min(Math.Min(5,(int)Math.Ceiling(Math.Sqrt(Math.Max(1,n)))),(int)(s.Width-2*Inset)/CW);
            if(cols<1||s.Width<192)continue;
            int rows=Math.Min(Math.Min(4,(int)Math.Ceiling(Math.Max(1,n)/(double)cols)),(int)(s.Height-Head-Inset)/RH);
            if(rows*cols<n)rows=Math.Min(rows,(int)(s.Height-Head-Inset-Foot)/RH);if(rows<1)continue;
            int value=Math.Min(Math.Max(1,n),rows*cols)*100+cols;if(value<=score)continue;
            double w=Math.Max(192,cols*CW+2*Inset),h=Head+rows*RH+Inset+(n>cols*rows?Foot:0);
            double x=side==0?t.Right:side==1?t.Left-w:Native.Clamp(t.Left+(t.Width-w)/2,a.Left,a.Right-w);
            double y=side==2?t.Bottom:side==3?t.Top-h:Native.Clamp(t.Top+(t.Height-h)/2,a.Top,a.Bottom-h);
            best=new GridPlan{Bounds=new Rect(x,y,w,h),Cols=cols,Rows=rows,Pivot=new P(Native.Clamp((t.Left+t.Width/2-x)/w,0,1),Native.Clamp((t.Top+t.Height/2-y)/h,0,1))};
            score=value;
        }return best;
    }
}
class Widget {
    internal Folder F;
    Window popup; Border surface;
    readonly DispatcherTimer tick=new DispatcherTimer{Interval=TimeSpan.FromMilliseconds(60)};
    FileSystemWatcher watcher;

    Rect anchor=Rect.Empty;
    bool over,armed=true,dirty,busy,closing,disposed,resolving,previewing;
    PreviewDrag previewDrag;
    DateTime entered,departed,nextTrack,nextResolve;
    FileSystemInfo[] files=new FileSystemInfo[0];string issue;int page,version,transition;
    DirectoryIdentity identity,linkIdentity;
    string originalPhysical;
    readonly Dictionary<string,BitmapSource> cache=new Dictionary<string,BitmapSource>(StringComparer.OrdinalIgnoreCase);
    public Widget(Folder f){
        Apply(f);tick.Interval=TimeSpan.FromMilliseconds(82);tick.Tick+=(s,e)=>Hover();tick.Start();
    }
    static bool Same(string a,string b){return string.Equals(a,b,StringComparison.OrdinalIgnoreCase);}
    static bool OnDesktop(string link){return !string.IsNullOrEmpty(link)&&Same(Path.GetDirectoryName(link),Program.Desktop)&&Same(Path.GetExtension(link),".lnk");}
    internal void Apply(Folder f){
        bool initial=F==null;string old=OnDesktop(f.Link)?f.Link:null;
        bool legacy=old!=null&&ShellDesktop.HasLegacySuffix(Path.GetFileNameWithoutExtension(old));
        if(legacy)f.Name=ShellDesktop.CleanLegacyName(f.Name);
        string dest=initial&&old!=null&&!legacy?old:ShellDesktop.FreeLink(f.Name,old);
        if(!initial && !legacy && Same(F.Name,f.Name)&&old!=null)dest=old;
        if(!initial||legacy||old==null||!File.Exists(dest)){
            if(old!=null&&!Same(old,dest)&&File.Exists(old))File.Move(old,dest);
            ShellDesktop.Link(f,dest);
        }
        f.Link=dest;F=f;HidePanel(false);cache.Clear();
        if(linkIdentity!=null)linkIdentity.Dispose();linkIdentity=new DirectoryIdentity(dest);
        Watch();nextTrack=DateTime.MinValue;
    }
    void Watch(){
        if(identity!=null)identity.Dispose();identity=new DirectoryIdentity(F.Path);originalPhysical=identity.Current();
        if(watcher!=null){watcher.Dispose();watcher=null;}
        if(!Directory.Exists(F.Path))return;
        try{
            watcher=new FileSystemWatcher(F.Path){NotifyFilter=NotifyFilters.FileName|NotifyFilters.DirectoryName|NotifyFilters.Attributes|NotifyFilters.LastWrite};
            watcher.Created+=Change;watcher.Deleted+=Change;watcher.Changed+=Change;watcher.Renamed+=Change;
            watcher.Error+=(s,e)=>Dispatch(()=>dirty=true);watcher.EnableRaisingEvents=true;
        }catch(IOException){}catch(ArgumentException){}catch(UnauthorizedAccessException){}
    }
    void Dispatch(Action a){if(!disposed)Application.Current.Dispatcher.BeginInvoke(a);}
    void Change(object s,FileSystemEventArgs e){Dispatch(()=>{dirty=true;cache.Clear();});}
    internal void Close(){ReleasePreviewDrag();disposed=true;tick.Stop();version++;transition++;if(identity!=null)identity.Dispose();if(linkIdentity!=null)linkIdentity.Dispose();
        if(watcher!=null)watcher.Dispose();if(popup!=null)popup.Close();}
    internal void RemoveLink(){if(OnDesktop(F.Link)&&File.Exists(F.Link))File.Delete(F.Link);}
    async void Track(){
        var f=F;
        string liveLink=linkIdentity.Current();
        if(OnDesktop(liveLink)&&!Same(liveLink,F.Link)&&File.Exists(liveLink)){
            F.Link=liveLink;F.Name=Path.GetFileNameWithoutExtension(liveLink);
            if(Program.Manager!=null)Program.Manager.Moved(this,F.Path);Program.Save();
        }
        string actual=identity.Current();
        if(actual!=null&&Same(actual,originalPhysical))actual=null;
        if(actual==null&&!Directory.Exists(f.Path)&&File.Exists(f.Link)&&!resolving&&DateTime.UtcNow>=nextResolve){
            nextResolve=DateTime.UtcNow.AddSeconds(15);resolving=true;
            try{actual=await Task.Run(()=>ShellDesktop.Resolved(f.Link));}finally{resolving=false;}
        }
        if(disposed||F!=f)return;
        if(actual!=null&&!Same(actual,F.Path)&&Directory.Exists(actual)&&actual.IndexOf(@"\$Recycle.Bin",StringComparison.OrdinalIgnoreCase)<0){
            string old=F.Path;F.Path=actual;Watch();dirty=true;cache.Clear();
            if(File.Exists(F.Link))ShellDesktop.Link(F,F.Link);
            if(Program.Manager!=null)Program.Manager.Moved(this,old);Program.Save();
        }else if(originalPhysical==null&&Directory.Exists(F.Path))Watch();
    }
    static int lastHit;static string lastName;static Rect lastBounds;
    static string Hit(out Rect bounds){
        int now=Environment.TickCount;if(unchecked(now-lastHit)>35||lastHit==0){lastHit=now;lastName=ShellDesktop.Hit(out lastBounds);}bounds=lastBounds;return lastName;
    }
    internal bool MatchesDesktopName(string name){
        string leaf=Path.GetFileNameWithoutExtension(F.Link);
        return name!=null&&(Same(name,leaf)||Same(name,leaf+".lnk"));
    }
    internal void OpenFromClick(Rect bounds){
        if(previewing||disposed)return;
        anchor=bounds;armed=false;over=true;departed=DateTime.UtcNow;
        if(popup!=null&&popup.IsVisible){
            if(closing)Animate(true,false);
            return;
        }
        if(!busy){page=0;Read(true,true);}
    }
    void Hover(){
        if(DateTime.UtcNow>=nextTrack){nextTrack=DateTime.UtcNow.AddSeconds(2);Track();}
        if(previewing){if(dirty&&!busy&&(previewDrag==null||!previewDrag.Active))Read(false);return;}
        Rect r;bool here=MatchesDesktopName(Hit(out r));
        if(here){anchor=r;if(!over)entered=DateTime.UtcNow;}
        else armed=true;over=here;
        if(popup!=null&&popup.IsVisible){
            if(here||popup.IsMouseOver){departed=DateTime.UtcNow;if(closing)Animate(true,false);}
            else if((DateTime.UtcNow-departed).TotalMilliseconds>310){HidePanel(true);return;}
            if(dirty&&!busy&&!closing)Read(false);
        }else if(here&&armed&&!busy&&(DateTime.UtcNow-entered).TotalMilliseconds>=220){armed=false;page=0;Read(true);}
    }
    void HidePanel(bool animate=true){
        if(popup==null||!popup.IsVisible){version++;busy=false;return;}
        if(closing&&animate)return;
        version++;busy=false;
        if(animate){Animate(false,false);return;}
        transition++;closing=false;popup.Hide();
    }
    void Animate(bool show,bool fresh){
        int stamp=++transition;closing=!show;
        if(!SystemParameters.ClientAreaAnimation){
            if(!show)popup.Hide();closing=false;return;
        }
        var scale=surface.RenderTransform as ScaleTransform;
        if(scale==null){scale=new ScaleTransform(fresh?.64:1,fresh?.64:1);surface.RenderTransform=scale;}
        var duration=TimeSpan.FromMilliseconds(show?180:150);
        var resize=new DoubleAnimation(scale.ScaleX,show?1:.64,duration){
            EasingFunction=new CubicEase{EasingMode=show?EasingMode.EaseOut:EasingMode.EaseIn}};
        var fade=new DoubleAnimation(fresh?.4:surface.Opacity,show?1:0,duration);
        fade.Completed+=(s,e)=>{
            if(stamp!=transition)return;
            if(!show)popup.Hide();
            surface.RenderTransform=Transform.Identity;
            surface.Opacity=1;surface.BeginAnimation(UIElement.OpacityProperty,null);
            closing=false;
        };
        scale.BeginAnimation(ScaleTransform.ScaleXProperty,resize);
        scale.BeginAnimation(ScaleTransform.ScaleYProperty,resize);
        surface.BeginAnimation(UIElement.OpacityProperty,fade);
    }
    internal void StartPreview(Window owner){
        StopPreview();HidePanel(false);previewing=true;page=0;
        var area=Native.Area(new P(owner.Left+owner.ActualWidth/2,owner.Top+owner.ActualHeight/2));
        double x=owner.Left+owner.ActualWidth;
        if(area.Right-x<210)x=owner.Left;
        anchor=new Rect(Native.Clamp(x,area.Left+2,area.Right-16),
            Native.Clamp(owner.Top+owner.ActualHeight/2,area.Top,area.Bottom-14),12,12);
        Read(false);
    }
    internal void StopPreview(){
        if(!previewing)return;
        previewing=false;ReleasePreviewDrag();HidePanel(false);
        if(popup!=null){popup.Topmost=false;popup.ShowActivated=false;}
    }
    static void DropTarget(FrameworkElement element,string target){element.Tag=target;}

    void ReleasePreviewDrag(){
        if(previewDrag==null)return;
        previewDrag.Dispose();previewDrag=null;
    }

    bool SavePreviewOrder(int pageStart,string[] names,string source,string pageTarget){
        var list=files.ToList();
        var byName=list.ToDictionary(file=>file.Name,StringComparer.OrdinalIgnoreCase);
        for(int i=0;i<names.Length;i++)list[pageStart+i]=byName[names[i]];
        if(pageTarget!=null){
            int from=list.FindIndex(file=>Same(file.Name,source)),to=list.FindIndex(file=>Same(file.Name,pageTarget));
            if(from>=0&&to>=0){var item=list[from];list.RemoveAt(from);list.Insert(to,item);}
        }
        var order=list.Select(file=>file.Name).ToArray();
        if(!order.SequenceEqual(files.Select(file=>file.Name),StringComparer.OrdinalIgnoreCase)){
            var previous=F.Order;F.Order=order;
            try{Program.Save();files=list.ToArray();}
            catch(Exception ex){F.Order=previous;MessageBox.Show(ex.Message,"无法保存排列");return false;}
        }
        if(pageTarget!=null)Render(false);
        return true;
    }
    async void Read(bool opening,bool clicked=false){
        busy=true;dirty=false;int stamp=++version;string path=F.Path;string message=null;
        var ranks=new Dictionary<string,int>(StringComparer.OrdinalIgnoreCase);
        foreach(string name in F.Order)ranks[name]=ranks.Count;
        var result=await Task.Run(()=>{try{return new DirectoryInfo(path).EnumerateFileSystemInfos().Where(f=>(f.Attributes&(FileAttributes.Hidden|FileAttributes.System))==0&&!ShellDesktop.IsManagerShortcut(f))
            .OrderBy(f=>ranks.ContainsKey(f.Name)?ranks[f.Name]:int.MaxValue).ThenBy(f=>(f.Attributes&FileAttributes.Directory)==0).ThenBy(f=>f.Name,StringComparer.CurrentCultureIgnoreCase).ToArray();}
            catch(Exception ex){message=ex.Message;return new FileSystemInfo[0];}});
        if(stamp!=version)return;busy=false;files=result;issue=message;
        if(opening&&!over&&!clicked)return;Render(opening);
    }
    async void LoadIcon(Image image,string path){
        double scale=VisualTreeHelper.GetDpi(image).DpiScaleX;
        int pixels=(int)Math.Round(image.Width*scale);
        string key=pixels+"|"+path;
        BitmapSource source;if(!cache.TryGetValue(key,out source)){
            int stamp=version;source=await Task.Run(()=>Native.Icon(path,pixels));
            if(source==null||stamp!=version)return;
            if(cache.Count>=300)cache.Clear();cache[key]=source;
        }image.Source=source;
    }
    internal static string DisplayName(string name,bool directory){
        if(directory)return name;string ext=Path.GetExtension(name);string label=name.Length>ext.Length?name.Substring(0,name.Length-ext.Length):name;
        if(ext.Equals(".lnk",StringComparison.OrdinalIgnoreCase)||ext.Equals(".url",StringComparison.OrdinalIgnoreCase))
            foreach(var suffix in new[]{" - 快捷方式"," - Shortcut"})if(label.Length>suffix.Length&&label.EndsWith(suffix,StringComparison.OrdinalIgnoreCase))return label.Substring(0,label.Length-suffix.Length);
        return label;
    }
    void Render(bool opening){
        ReleasePreviewDrag();
        if(anchor.IsEmpty)return;var plan=GridPlan.Make(Native.Area(new P(anchor.Left+anchor.Width/2,anchor.Top+anchor.Height/2)),anchor,files.Length);if(plan==null)return;
        if(popup==null){popup=UI.Layer(F.Name);popup.KeyDown+=(s,e)=>{if(e.Key==Key.Escape){armed=false;if(previewing)StopPreview();else HidePanel();}};}
        if(previewing){popup.Topmost=true;popup.ShowActivated=true;}
        TextOptions.SetTextFormattingMode(popup,TextFormattingMode.Display);
        popup.Left=plan.Bounds.Left;popup.Top=plan.Bounds.Top;popup.Width=plan.Bounds.Width;popup.Height=plan.Bounds.Height;
        if(previewing){var area=Native.Area(anchor.TopLeft);popup.Height=Math.Min(area.Height,plan.Bounds.Height+25);popup.Top=Native.Clamp(popup.Top,area.Top,area.Bottom-popup.Height);}
        var layout=new DockPanel();surface=new Border{Background=UI.Fill("#F7F8FA"),BorderBrush=UI.Fill("#BBBFC5"),BorderThickness=new Thickness(1),CornerRadius=new CornerRadius(10),
            Padding=new Thickness(7,0,7,6),Child=layout,RenderTransformOrigin=plan.Pivot};popup.Content=surface;
        var head=new DockPanel{Height=47};DockPanel.SetDock(head,Dock.Top);layout.Children.Add(head);
        var open=UI.Button(previewing?"关闭预览":"管理",()=>{if(previewing)StopPreview();else{armed=false;HidePanel(false);Program.Manage(this);}});open.Margin=new Thickness(8,0,1,0);open.VerticalAlignment=VerticalAlignment.Center;DockPanel.SetDock(open,Dock.Right);head.Children.Add(open);
        var heading=UI.Text(F.Name,14);heading.Margin=new Thickness(6,0,0,0);heading.FontWeight=FontWeights.SemiBold;heading.TextTrimming=TextTrimming.CharacterEllipsis;heading.ToolTip=F.Name;
        BitmapSource titleArt=null;
        if(File.Exists(F.TitleImage)){
            try{titleArt=UI.LoadImage(F.TitleImage);}catch(IOException){}catch(NotSupportedException){}
        }
        if(titleArt==null)head.Children.Add(heading);
        else{
            var titleImage=new Image{Source=titleArt,Height=28,MaxWidth=160,Margin=new Thickness(6,0,0,0),
                HorizontalAlignment=HorizontalAlignment.Left,VerticalAlignment=VerticalAlignment.Center,Stretch=Stretch.Uniform,ToolTip=F.Name};
            AutomationProperties.SetName(titleImage,F.Name);RenderOptions.SetBitmapScalingMode(titleImage,BitmapScalingMode.HighQuality);
            head.Children.Add(titleImage);
        }
        if(previewing){
            var hint=UI.Text("拖动以排序",11.5);hint.Margin=new Thickness(6,0,0,7);hint.Foreground=UI.Fill("#616670");
            DockPanel.SetDock(hint,Dock.Top);layout.Children.Add(hint);
        }
        int capacity=plan.Cols*plan.Rows,pages=Math.Max(1,(files.Length+capacity-1)/capacity);page=Math.Max(0,Math.Min(page,pages-1));
        if(pages>1){var nav=new StackPanel{Orientation=Orientation.Horizontal,HorizontalAlignment=HorizontalAlignment.Center,Height=37};
            DockPanel.SetDock(nav,Dock.Bottom);layout.Children.Add(nav);
            var prev=UI.Button("‹",()=>{page--;Render(false);});prev.IsEnabled=page>0;nav.Children.Add(prev);
            var number=UI.Text((page+1)+" / "+pages,12);number.Margin=new Thickness(12,0,12,0);nav.Children.Add(number);
            var next=UI.Button("›",()=>{page++;Render(false);});next.IsEnabled=page+1<pages;nav.Children.Add(next);
            if(previewing){
                if(page>0){prev.ToolTip="拖到这里移到上一页";DropTarget(prev,files[page*capacity-1].Name);}
                if(page+1<pages){next.ToolTip="拖到这里移到下一页";DropTarget(next,files[(page+1)*capacity].Name);}
            }
        }
        if(files.Length==0){if(issue!=null){var reconnect=UI.Button("选择内容文件夹…",()=>{HidePanel(false);Program.Manage(this);Program.Manager.ChoosePath();});reconnect.HorizontalAlignment=HorizontalAlignment.Center;reconnect.VerticalAlignment=VerticalAlignment.Center;reconnect.ToolTip=issue;layout.Children.Add(reconnect);}else{var empty=UI.Text("文件夹为空",13);empty.HorizontalAlignment=HorizontalAlignment.Center;layout.Children.Add(empty);}}
        else{
            var grid=new UniformGrid{Rows=plan.Rows,Columns=plan.Cols};layout.Children.Add(grid);
            int pageStart=page*capacity;
            if(previewing)previewDrag=new PreviewDrag(grid,surface,(order,source,target)=>SavePreviewOrder(pageStart,order,source,target));
            foreach(var f in files.Skip(page*capacity).Take(capacity)){
                string path=f.FullName;string name=DisplayName(f.Name,f is DirectoryInfo);
                var tile=UI.Button("",()=>{if(!previewing){HidePanel();UI.Open(path);}});tile.Background=Brushes.Transparent;tile.BorderThickness=new Thickness(0);tile.Padding=new Thickness(3,1,3,1);tile.ToolTip=name;
                var stack=new StackPanel{Width=90};var image=new Image{Width=48,Height=48};RenderOptions.SetBitmapScalingMode(image,BitmapScalingMode.HighQuality);stack.Children.Add(image);
                var label=UI.Text(name,11.5);label.Margin=new Thickness(0,3,0,0);label.TextWrapping=TextWrapping.Wrap;label.TextAlignment=TextAlignment.Center;
                label.LineHeight=15;label.LineStackingStrategy=LineStackingStrategy.BlockLineHeight;label.MaxHeight=30;label.TextTrimming=TextTrimming.CharacterEllipsis;
                stack.Children.Add(label);
                AutomationProperties.SetName(tile,name);
                if(previewing){
                    tile.Cursor=Cursors.SizeAll;
                    tile.ToolTip=name+" · 拖动排序";
                    previewDrag.Add(tile,f.Name);
                }
                tile.Content=stack;grid.Children.Add(tile);
                image.Loaded+=(s,e)=>LoadIcon(image,path);
            }
        }
        if(opening&&SystemParameters.ClientAreaAnimation)surface.Opacity=0;
        if(!popup.IsVisible){departed=DateTime.UtcNow;popup.Show();}
        if(opening)Animate(true,true);
    }
    internal void RefreshTheme(){if(popup!=null&&popup.IsVisible&&!closing)Render(false);}
}
class Manager : Window {
    internal sealed class FolderRow {
        public string Name{get;set;}
        public ImageSource Icon{get;set;}
    }
    readonly ListBox list=new ListBox{BorderThickness=new Thickness(0),Background=Brushes.Transparent,FontSize=14,MinHeight=100};
    readonly TextBox name=Field(),path=Field(),icon=Field(),titleImage=Field();

    readonly TextBlock heading=UI.Text("",22);
    readonly Image preview=new Image{Width=52,Height=52,Margin=new Thickness(0,0,14,0)};
    readonly Button remove,openPreview;Widget selected;bool loading;
    static TextBox Field(){return new TextBox{Padding=new Thickness(9,6,9,6),FontSize=13,VerticalContentAlignment=VerticalAlignment.Center,
        BorderBrush=UI.Fill("#C5C8CC"),BorderThickness=new Thickness(1),Background=UI.Fill("#FFFFFF")};}
    public Manager(){SourceInitialized+=(s,e)=>Palette.Caption(this);
        Title="悬浮文件夹管理";Width=760;Height=540;MinWidth=650;MinHeight=520;WindowStartupLocation=WindowStartupLocation.CenterScreen;
        FontFamily=UI.Font;Foreground=UI.Fill("#22252A");list.Foreground=Foreground;name.Foreground=path.Foreground=icon.Foreground=titleImage.Foreground=Foreground;Background=UI.Fill("#F5F6F8");UseLayoutRounding=true;
        Resources.MergedDictionaries.Add(ManagerStyles.Create());
        list.ItemContainerStyle=(Style)Resources["FolderRow"];
        var baseGrid=new Grid();Content=baseGrid;baseGrid.ColumnDefinitions.Add(new ColumnDefinition{Width=new GridLength(190)});baseGrid.ColumnDefinitions.Add(new ColumnDefinition());
        var sidebar=new DockPanel{Margin=new Thickness(14,22,12,16)};baseGrid.Children.Add(sidebar);
        var title=UI.Text("我的文件夹",17);title.FontWeight=FontWeights.SemiBold;title.Margin=new Thickness(5,0,0,16);DockPanel.SetDock(title,Dock.Top);sidebar.Children.Add(title);
        var create=UI.Button("＋  新建文件夹",()=>Select(null));DockPanel.SetDock(create,Dock.Bottom);sidebar.Children.Add(create);
        var theme=UI.Button(Palette.Dark?"外观  ·  深色":"外观  ·  浅色",SwitchTheme);theme.ToolTip="切换浅色或深色模式";theme.Margin=new Thickness(0,0,0,9);DockPanel.SetDock(theme,Dock.Bottom);sidebar.Children.Add(theme);
        var quit=UI.Button("退出程序",()=>{
            if(selected!=null)selected.StopPreview();
            if(MessageBox.Show(this,"确认退出悬浮文件夹管理？退出后仍可正常打开文件夹。要恢复悬停展开，请从内容文件夹或桌面打开「悬浮文件夹管理」。",
                "退出程序",MessageBoxButton.YesNo,MessageBoxImage.Question,MessageBoxResult.No)==MessageBoxResult.Yes)
                Application.Current.Shutdown();
        });quit.Margin=new Thickness(0,0,0,9);DockPanel.SetDock(quit,Dock.Bottom);sidebar.Children.Add(quit);sidebar.Children.Add(list);
        list.SelectionChanged+=(s,e)=>{if(!loading&&list.SelectedIndex>=0)Select(Program.Widgets[list.SelectedIndex]);};
        var editor=new Border{CornerRadius=new CornerRadius(9),BorderBrush=UI.Fill("#D8DADF"),BorderThickness=new Thickness(1),Background=UI.Fill("#FFFFFF"),
            Margin=new Thickness(0,12,12,12),Padding=new Thickness(22,18,22,16)};Grid.SetColumn(editor,1);baseGrid.Children.Add(editor);
        var dock=new DockPanel();editor.Child=dock;var footer=new DockPanel{Margin=new Thickness(0,12,0,0)};DockPanel.SetDock(footer,Dock.Bottom);dock.Children.Add(footer);
        var save=UI.Button("保存",Commit,true);save.MinWidth=110;save.MinHeight=34;DockPanel.SetDock(save,Dock.Right);footer.Children.Add(save);
        openPreview=UI.Button("预览",()=>selected.StartPreview(this));openPreview.Margin=new Thickness(8,0,8,0);
        DockPanel.SetDock(openPreview,Dock.Right);footer.Children.Add(openPreview);
        Closed+=(s,e)=>{if(selected!=null)selected.StopPreview();};
        remove=UI.Button("移除悬浮图标",Remove);remove.HorizontalAlignment=HorizontalAlignment.Left;footer.Children.Add(remove);
        var scroll=new SmoothScrollViewer{VerticalScrollBarVisibility=ScrollBarVisibility.Auto};dock.Children.Add(scroll);var body=new StackPanel();scroll.Content=body;
        var header=new StackPanel{Orientation=Orientation.Horizontal};header.Children.Add(preview);header.Children.Add(heading);body.Children.Add(header);
        Row(body,"显示名称",name,null);Row(body,"内容文件夹",path,UI.Button("浏览…",BrowseFolder));
        var hint=UI.Text("留空时，会在程序数据目录创建同名文件夹。",11.5);hint.Foreground=UI.Fill("#616670");hint.Margin=new Thickness(0,4,0,0);body.Children.Add(hint);Row(body,"自定义图标",icon,UI.Button("选择…",BrowseIcon));var reset=UI.Button("使用默认图标",()=>icon.Clear());reset.HorizontalAlignment=HorizontalAlignment.Left;
        reset.Margin=new Thickness(0,6,0,4);body.Children.Add(reset);
        Row(body,"展开栏标题图片",titleImage,UI.Button("选择…",()=>BrowseImage(titleImage,"选择展开栏标题图片")));
        var clearTitle=UI.Button("使用文字标题",()=>titleImage.Clear());clearTitle.HorizontalAlignment=HorizontalAlignment.Left;
        clearTitle.Margin=new Thickness(0,6,0,4);body.Children.Add(clearTitle);
        RenderOptions.SetBitmapScalingMode(preview,BitmapScalingMode.HighQuality);
        preview.SnapsToDevicePixels=true;
        TextOptions.SetTextFormattingMode(this,TextFormattingMode.Display);
        icon.TextChanged+=(s,e)=>{try{preview.Source=File.Exists(icon.Text)?UI.LoadImage(icon.Text,PreviewPixels()):Native.Icon(selected!=null && Directory.Exists(selected.F.Path)?selected.F.Path:Program.Home,PreviewPixels());}catch{preview.Source=null;}};
    }
    int PreviewPixels(){return (int)Math.Ceiling(preview.Width*VisualTreeHelper.GetDpi(this).DpiScaleX);}
    static void Row(StackPanel body,string caption,TextBox field,Button action){
        var label=UI.Text(caption,13);label.Margin=new Thickness(0,12,0,5);body.Children.Add(label);
        var row=new DockPanel();body.Children.Add(row);if(action!=null){action.Margin=new Thickness(8,0,0,0);DockPanel.SetDock(action,Dock.Right);row.Children.Add(action);}row.Children.Add(field);
    }
    public void Select(Widget w){
        if(selected!=null)selected.StopPreview();
        selected=w;openPreview.IsEnabled=w!=null;loading=true;var folderIcon=Native.DefaultFolderIcon(32);list.ItemsSource=Program.Widgets.Select(x=>new FolderRow{Name=x.F.Name,Icon=folderIcon}).ToArray();list.SelectedIndex=Program.Widgets.IndexOf(w);loading=false;
        name.Text=w==null?"":w.F.Name;path.Text=w==null?"":w.F.Path;path.ToolTip="留空时，在程序数据目录创建与显示名称同名的文件夹";
        titleImage.Text=w==null?"":w.F.TitleImage;icon.Text=w==null?"":w.F.Icon;if(string.IsNullOrEmpty(icon.Text))preview.Source=Native.Icon(w!=null && Directory.Exists(w.F.Path)?w.F.Path:Program.Home,PreviewPixels());
        heading.Text=w==null?"新建悬浮文件夹":Directory.Exists(w.F.Path)?"文件夹属性":"请选择内容文件夹的新位置";
        remove.Visibility=w==null?Visibility.Collapsed:Visibility.Visible;if(w==null)name.Focus();
    }
    internal void Moved(Widget w,string previous){if(selected==w&&string.Equals(path.Text,previous,StringComparison.OrdinalIgnoreCase))path.Text=w.F.Path;}
    void SwitchTheme(){
        var n=name.Text;var p=path.Text;var i=icon.Text;var t=titleImage.Text;var w=selected;double x=Left,y=Top;
        Palette.Dark=!Palette.Dark;Program.Save();foreach(var item in Program.Widgets)item.RefreshTheme();
        Close();Program.Manage(w);var next=Program.Manager;next.Left=x;next.Top=y;next.name.Text=n;next.path.Text=p;next.icon.Text=i;next.titleImage.Text=t;
    }
    internal void ChoosePath(){BrowseFolder();}
    void BrowseFolder(){using(var dlg=new Forms.FolderBrowserDialog{Description="选择要展开的内容文件夹",SelectedPath=Directory.Exists(path.Text)?path.Text:Program.Desktop}){
        if(dlg.ShowDialog()==Forms.DialogResult.OK){path.Text=dlg.SelectedPath;if(name.Text.Trim()=="")name.Text=new DirectoryInfo(path.Text).Name;}}}
    void BrowseIcon(){BrowseImage(icon,"选择悬浮文件夹图标");}
    void BrowseImage(TextBox field,string title){var dlg=new Microsoft.Win32.OpenFileDialog{Filter="图标和图片|*.ico;*.png;*.jpg;*.jpeg;*.bmp",Title=title};if(dlg.ShowDialog(this)==true)field.Text=dlg.FileName;}
    void Commit(){
        try{
            string n=name.Text.Trim(),p=path.Text.Trim(),i=icon.Text.Trim();
            if(n==""){name.Focus();throw new ArgumentException("请输入显示名称。");}
            if(p==""){if(n.IndexOfAny(Path.GetInvalidFileNameChars())>=0||n=="."||n==".."||n.EndsWith("."))throw new ArgumentException("请填写有效的文件夹名称，或选择已有文件夹。");p=Path.Combine(Program.Home,"内容",n);}
            if(!Path.IsPathRooted(p))throw new ArgumentException("请选择完整的文件夹路径。");p=Path.GetFullPath(p);
            if(i!=""){
                UI.LoadImage(i);
                string assets=Path.Combine(Program.Home,"图标");Directory.CreateDirectory(assets);
                if(!string.Equals(Path.GetDirectoryName(Path.GetFullPath(i)),assets,StringComparison.OrdinalIgnoreCase)){
                    string copy=Path.Combine(assets,Guid.NewGuid().ToString("N")+Path.GetExtension(i));File.Copy(i,copy);i=copy;}
            }
            if(selected!=null && string.Equals(selected.F.Path,p,StringComparison.OrdinalIgnoreCase) && !Directory.Exists(p))throw new IOException("原内容目录已移动或暂时不可用。请点击“浏览”选择它的当前位置。");bool created=!Directory.Exists(p);Directory.CreateDirectory(p);if(created)ShellDesktop.CreateManagerShortcut(p);var a=SystemParameters.WorkArea;
            var f=selected==null?new Folder{X=a.Right-120,Y=a.Top+80}:selected.F.Copy();
            string titleFile=titleImage.Text.Trim();
            if(titleFile!=""){
                UI.LoadImage(titleFile);
                string assets=Path.Combine(Program.Home,"标题图片");Directory.CreateDirectory(assets);
                if(!string.Equals(Path.GetDirectoryName(Path.GetFullPath(titleFile)),assets,StringComparison.OrdinalIgnoreCase)){
                    string copy=Path.Combine(assets,Guid.NewGuid().ToString("N")+Path.GetExtension(titleFile));File.Copy(titleFile,copy);titleFile=copy;
                }
            }
            if(!string.Equals(f.Path,p,StringComparison.OrdinalIgnoreCase))f.Order=new string[0];
            f.Name=n;f.Path=p;f.Icon=i;f.TitleImage=titleFile;
            if(selected==null)selected=Program.Add(f);else selected.Apply(f);
            Program.Save();Select(selected);heading.Text="属性已保存";
        }catch(Exception ex){MessageBox.Show(this,ex.Message,"无法保存",MessageBoxButton.OK,MessageBoxImage.Information);}
    }
    void Remove(){if(selected==null||MessageBox.Show(this,"移除这个悬浮图标？文件夹和里面的文件会保留。","移除悬浮图标",MessageBoxButton.YesNo)!=MessageBoxResult.Yes)return;
        var w=selected;w.RemoveLink();Program.Widgets.Remove(w);w.Close();Program.Save();Select(Program.Widgets.FirstOrDefault());}
}
}
