using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Effects;

namespace DeskFolders {
sealed class PreviewDrag : IDisposable {
    sealed class Tile {
        public Button Button;
        public string Name;
        public Point Home;
        public int MoveVersion;
        public readonly ScaleTransform Scale=new ScaleTransform(1,1);
        public readonly TranslateTransform Offset=new TranslateTransform();
    }

    readonly UniformGrid grid;
    readonly Border surface;
    readonly Func<string[],string,string,bool> commit;
    readonly List<Tile> tiles=new List<Tile>();
    Tile[] slots, savedSlots;
    Tile lifted;
    Point pointerStart;
    Vector grabOffset;
    int currentSlot;
    long lastFrame;
    bool settling,disposed;

    internal PreviewDrag(UniformGrid grid,Border surface,Func<string[],string,string,bool> commit){
        this.grid=grid;this.surface=surface;this.commit=commit;
        grid.PreviewMouseLeftButtonUp+=Release;
        grid.PreviewMouseMove+=TrackPointer;
        grid.LostMouseCapture+=CaptureLost;
    }

    internal void Add(Button button,string name){
        var tile=new Tile{Button=button,Name=name};
        var transform=new TransformGroup();
        transform.Children.Add(tile.Scale);transform.Children.Add(tile.Offset);
        button.RenderTransformOrigin=new Point(.5,.5);
        button.RenderTransform=transform;
        tiles.Add(tile);
        button.PreviewMouseLeftButtonDown+=(s,e)=>{
            e.Handled=true;
            if(settling||lifted!=null||!grid.CaptureMouse())return;
            Begin(tile,e.GetPosition(grid));
        };
    }

    void Begin(Tile tile,Point pointer){
        if(savedSlots==null)savedSlots=tiles.ToArray();
        slots=(Tile[])savedSlots.Clone();
        foreach(var item in tiles)item.Home=(Point)VisualTreeHelper.GetOffset(item.Button);
        tile.MoveVersion++;
        double x=tile.Offset.X,y=tile.Offset.Y;
        tile.Offset.X=x;tile.Offset.Y=y;
        tile.Offset.BeginAnimation(TranslateTransform.XProperty,null);
        tile.Offset.BeginAnimation(TranslateTransform.YProperty,null);
        lifted=tile;currentSlot=Array.IndexOf(slots,tile);pointerStart=pointer;
        grabOffset=pointer-tiles[currentSlot].Home;
        Panel.SetZIndex(tile.Button,100);
        tile.Button.IsHitTestVisible=false;
        tile.Button.Effect=new DropShadowEffect{Color=Colors.Black,Opacity=.28,BlurRadius=15,ShadowDepth=4};
        AnimateScale(tile,1.08,105);
        lastFrame=Stopwatch.GetTimestamp();
        CompositionTarget.Rendering+=Frame;
    }

    int CellAt(Point pointer){
        if(pointer.X<0||pointer.Y<0||pointer.X>=grid.ActualWidth||pointer.Y>=grid.ActualHeight||grid.Columns<1||grid.Rows<1)return -1;
        int col=(int)(pointer.X*grid.Columns/grid.ActualWidth);
        int row=(int)(pointer.Y*grid.Rows/grid.ActualHeight);
        int index=row*grid.Columns+col;
        return index<slots.Length?index:-1;
    }

    void SwapAt(Point pointer){
        int next=CellAt(pointer);
        if(next<0||next==currentSlot)return;
        var displaced=slots[next];
        slots[currentSlot]=displaced;slots[next]=lifted;
        Move(displaced,tiles[currentSlot].Home-displaced.Home,155);
        currentSlot=next;
    }

    void TrackPointer(object sender,MouseEventArgs e){
        if(lifted!=null&&!settling)SwapAt(e.GetPosition(grid));
    }

    void Frame(object sender,EventArgs args){
        if(lifted==null||settling)return;
        var pointer=Mouse.GetPosition(grid);
        SwapAt(pointer);
        long now=Stopwatch.GetTimestamp();
        double dt=Math.Min(.05,(now-lastFrame)/(double)Stopwatch.Frequency);
        lastFrame=now;
        double blend=1-Math.Exp(-dt*25);
        var destination=pointer-grabOffset-lifted.Home;
        lifted.Offset.X+=(destination.X-lifted.Offset.X)*blend;
        lifted.Offset.Y+=(destination.Y-lifted.Offset.Y)*blend;
    }

    string PageTarget(Point pointer){
        var hit=surface.InputHitTest(pointer) as DependencyObject;
        while(hit!=null&&hit!=surface){
            var element=hit as FrameworkElement;
            if(element!=null&&element.Tag is string)return (string)element.Tag;
            var content=hit as FrameworkContentElement;
            hit=content!=null?content.Parent:VisualTreeHelper.GetParent(hit);
        }
        return null;
    }

    void Release(object sender,MouseButtonEventArgs e){
        if(lifted==null||settling)return;
        e.Handled=true;
        Point pointer=e.GetPosition(grid);
        SwapAt(pointer);
        string pageTarget=null;
        if((pointer-pointerStart).Length>=4&&CellAt(pointer)<0)pageTarget=PageTarget(e.GetPosition(surface));
        Finish(pageTarget);
    }

    void Finish(string pageTarget){
        settling=true;
        CompositionTarget.Rendering-=Frame;
        if(grid.IsMouseCaptured)grid.ReleaseMouseCapture();
        AnimateScale(lifted,1,135);
        Move(lifted,tiles[currentSlot].Home-lifted.Home,145,()=>{
            if(disposed)return;
            bool saved=commit(slots.Select(tile=>tile.Name).ToArray(),lifted.Name,pageTarget);
            if(disposed)return;
            if(saved)savedSlots=slots;
            else RestoreSlots();
            EndLift();

        });
    }

    static DoubleAnimation Tween(double from,double to,int ms){
        return new DoubleAnimation(from,to,TimeSpan.FromMilliseconds(SystemParameters.ClientAreaAnimation?ms:0)){
            EasingFunction=new CubicEase{EasingMode=EasingMode.EaseOut}};
    }
    static void AnimateScale(Tile tile,double scale,int ms){
        var animation=Tween(tile.Scale.ScaleX,scale,ms);
        tile.Scale.BeginAnimation(ScaleTransform.ScaleXProperty,animation);
        tile.Scale.BeginAnimation(ScaleTransform.ScaleYProperty,animation);
    }
    static void Move(Tile tile,Vector offset,int ms,Action completed=null){
        var x=Tween(tile.Offset.X,offset.X,ms);
        var y=Tween(tile.Offset.Y,offset.Y,ms);
        int version=++tile.MoveVersion;
        x.Completed+=(s,e)=>{
            if(version!=tile.MoveVersion)return;
            tile.Offset.X=offset.X;tile.Offset.Y=offset.Y;
            tile.Offset.BeginAnimation(TranslateTransform.XProperty,null);
            tile.Offset.BeginAnimation(TranslateTransform.YProperty,null);
            if(completed!=null)completed();
        };
        tile.Offset.BeginAnimation(TranslateTransform.XProperty,x);
        tile.Offset.BeginAnimation(TranslateTransform.YProperty,y);
    }

    void CaptureLost(object sender,MouseEventArgs e){
        if(lifted==null||settling||disposed)return;
        CompositionTarget.Rendering-=Frame;
        RestoreSlots();
        AnimateScale(lifted,1,125);
        EndLift();
    }

    void RestoreSlots(){
        for(int i=0;i<savedSlots.Length;i++)
            Move(savedSlots[i],tiles[i].Home-savedSlots[i].Home,125);
    }

    void EndLift(){
        Panel.SetZIndex(lifted.Button,0);
        lifted.Button.Effect=null;
        lifted.Button.IsHitTestVisible=true;
        lifted=null;settling=false;
    }

    internal bool Active{get{return lifted!=null;}}

    public void Dispose(){
        if(disposed)return;
        disposed=true;
        CompositionTarget.Rendering-=Frame;
        grid.PreviewMouseLeftButtonUp-=Release;grid.PreviewMouseMove-=TrackPointer;grid.LostMouseCapture-=CaptureLost;
        if(grid.IsMouseCaptured)grid.ReleaseMouseCapture();
    }
}
}
