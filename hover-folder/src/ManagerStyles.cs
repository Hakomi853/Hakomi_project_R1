using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Animation;
using System.Windows.Input;
using System.Windows.Markup;

namespace DeskFolders {
sealed class SmoothScrollViewer : ScrollViewer {
    double target,position;
    TimeSpan? lastFrame;
    bool scrolling;

    public SmoothScrollViewer(){Unloaded+=(s,e)=>StopScrolling();}

    protected override void OnPreviewMouseWheel(MouseWheelEventArgs e){
        int lines=SystemParameters.WheelScrollLines;
        if(e.Handled||ScrollableHeight<=0||Keyboard.Modifiers!=ModifierKeys.None||lines==0){
            base.OnPreviewMouseWheel(e);return;
        }
        double distance=lines<0?ViewportHeight:lines*43.0;
        double delta=-e.Delta*distance/120.0;
        if(!scrolling||Math.Sign(delta)!=Math.Sign(target-position))target=position=VerticalOffset;
        target=Math.Max(0,Math.Min(ScrollableHeight,target+delta));
        e.Handled=true;
        if(!SystemParameters.ClientAreaAnimation){StopScrolling();ScrollToVerticalOffset(target);return;}
        if(scrolling)return;
        scrolling=true;lastFrame=null;
        System.Windows.Media.CompositionTarget.Rendering+=ScrollFrame;
    }

    void ScrollFrame(object sender,EventArgs e){
        var time=((System.Windows.Media.RenderingEventArgs)e).RenderingTime;
        double elapsed=lastFrame.HasValue?(time-lastFrame.Value).TotalSeconds:1.0/60;
        lastFrame=time;target=Math.Min(target,ScrollableHeight);
        double remaining=target-position;
        if(Math.Abs(remaining)<=1){ScrollToVerticalOffset(target);StopScrolling();return;}
        position+=remaining*(1-Math.Exp(-22*elapsed));
        double dpi=System.Windows.Media.VisualTreeHelper.GetDpi(this).DpiScaleY;
        ScrollToVerticalOffset(Math.Round(position*dpi)/dpi);
    }
    protected override void OnPreviewMouseDown(MouseButtonEventArgs e){
        StopScrolling();base.OnPreviewMouseDown(e);
    }
    protected override void OnPreviewKeyDown(KeyEventArgs e){
        StopScrolling();base.OnPreviewKeyDown(e);
    }
    void StopScrolling(){
        if(!scrolling)return;
        scrolling=false;System.Windows.Media.CompositionTarget.Rendering-=ScrollFrame;
    }

}

static class ManagerStyles {
    internal static ResourceDictionary Create(){
        string thumb=Palette.Dark?"#A2A2A2":"#858585";
        string track=Palette.Dark?"#3C3C3C":"#E7E7E7";
        string hover=Palette.Dark?"#353535":"#EBEBEB";
        string selected=Palette.Dark?"#3A3A3A":"#E5E5E5";
        string xaml=@"
<ResourceDictionary xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml'>
  <Style x:Key='TrackButton' TargetType='RepeatButton'>
    <Setter Property='Focusable' Value='False'/>
    <Setter Property='Template'>
      <Setter.Value><ControlTemplate TargetType='RepeatButton'><Border Background='Transparent'/></ControlTemplate></Setter.Value>
    </Setter>
  </Style>
  <Style TargetType='ScrollBar'>
    <Setter Property='Width' Value='12'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='ScrollBar'>
          <Grid Background='Transparent'>
            <Border x:Name='Rail' Background='Transparent' Width='6' CornerRadius='3' Margin='0,2'/>
            <Track x:Name='PART_Track' Orientation='Vertical' IsDirectionReversed='True'>
              <Track.DecreaseRepeatButton><RepeatButton Style='{StaticResource TrackButton}' Command='ScrollBar.PageUpCommand'/></Track.DecreaseRepeatButton>
              <Track.Thumb>
                <Thumb>
                  <Thumb.Template>
                    <ControlTemplate TargetType='Thumb'>
                      <Grid Background='Transparent'>
                        <Border x:Name='Grip' Width='3' MinHeight='12' Background='THUMB_COLOR' CornerRadius='3' Margin='0,2'/>
                      </Grid>
                      <ControlTemplate.Triggers>
                        <Trigger Property='IsMouseOver' Value='True'><Setter TargetName='Grip' Property='Width' Value='6'/></Trigger>
                        <Trigger Property='IsDragging' Value='True'><Setter TargetName='Grip' Property='Width' Value='6'/></Trigger>
                      </ControlTemplate.Triggers>
                    </ControlTemplate>
                  </Thumb.Template>
                </Thumb>
              </Track.Thumb>
              <Track.IncreaseRepeatButton><RepeatButton Style='{StaticResource TrackButton}' Command='ScrollBar.PageDownCommand'/></Track.IncreaseRepeatButton>
            </Track>
          </Grid>
          <ControlTemplate.Triggers>
            <Trigger Property='IsMouseOver' Value='True'><Setter TargetName='Rail' Property='Background' Value='TRACK_COLOR'/></Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
  <Style x:Key='FolderRow' TargetType='ListBoxItem'>
    <Setter Property='HorizontalContentAlignment' Value='Stretch'/>
    <Setter Property='Padding' Value='12,8'/>
    <Setter Property='MinHeight' Value='36'/>
    <Setter Property='Margin' Value='0,1'/>
    <Setter Property='Template'>
      <Setter.Value>
        <ControlTemplate TargetType='ListBoxItem'>
          <Border x:Name='Surface' Background='Transparent' CornerRadius='5' Padding='{TemplateBinding Padding}'>
            <DockPanel>
              <Image DockPanel.Dock='Left' Source='{Binding Icon}' Width='20' Height='20' RenderOptions.BitmapScalingMode='HighQuality' Margin='0,0,10,0'/>
              <TextBlock Text='{Binding Name}' VerticalAlignment='Center' TextTrimming='CharacterEllipsis' ToolTip='{Binding Name}'/>
            </DockPanel>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property='IsMouseOver' Value='True'><Setter TargetName='Surface' Property='Background' Value='HOVER_COLOR'/></Trigger>
            <Trigger Property='IsSelected' Value='True'><Setter TargetName='Surface' Property='Background' Value='SELECTED_COLOR'/></Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
</ResourceDictionary>";
        return (ResourceDictionary)XamlReader.Parse(xaml.Replace("THUMB_COLOR",thumb).Replace("TRACK_COLOR",track)
            .Replace("HOVER_COLOR",hover).Replace("SELECTED_COLOR",selected));
    }
}
}
