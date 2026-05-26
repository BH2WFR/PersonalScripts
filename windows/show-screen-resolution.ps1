$TypeName = "ScreenInfo20260502.Native"

if (-not ($TypeName -as [type])) {
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace ScreenInfo20260502
{
    public class MonitorData
    {
        public IntPtr HMonitor;
        public string DeviceName;
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
        public bool Primary;
    }

    public static class Native
    {
        public const int ENUM_CURRENT_SETTINGS = -1;
        public const int MDT_EFFECTIVE_DPI = 0;

        [StructLayout(LayoutKind.Sequential)]
        public struct RECT
        {
            public int left;
            public int top;
            public int right;
            public int bottom;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
        public struct MONITORINFOEX
        {
            public int cbSize;
            public RECT rcMonitor;
            public RECT rcWork;
            public int dwFlags;

            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
            public string szDevice;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
        public struct DEVMODE
        {
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
            public string dmDeviceName;

            public ushort dmSpecVersion;
            public ushort dmDriverVersion;
            public ushort dmSize;
            public ushort dmDriverExtra;
            public uint dmFields;

            public int dmPositionX;
            public int dmPositionY;
            public uint dmDisplayOrientation;
            public uint dmDisplayFixedOutput;

            public short dmColor;
            public short dmDuplex;
            public short dmYResolution;
            public short dmTTOption;
            public short dmCollate;

            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
            public string dmFormName;

            public ushort dmLogPixels;
            public uint dmBitsPerPel;
            public uint dmPelsWidth;
            public uint dmPelsHeight;
            public uint dmDisplayFlags;
            public uint dmDisplayFrequency;

            public uint dmICMMethod;
            public uint dmICMIntent;
            public uint dmMediaType;
            public uint dmDitherType;
            public uint dmReserved1;
            public uint dmReserved2;
            public uint dmPanningWidth;
            public uint dmPanningHeight;
        }

        public delegate bool MonitorEnumProc(
            IntPtr hMonitor,
            IntPtr hdcMonitor,
            ref RECT lprcMonitor,
            IntPtr dwData
        );

        [DllImport("user32.dll")]
        public static extern bool EnumDisplayMonitors(
            IntPtr hdc,
            IntPtr lprcClip,
            MonitorEnumProc lpfnEnum,
            IntPtr dwData
        );

        [DllImport("user32.dll", CharSet = CharSet.Auto)]
        public static extern bool GetMonitorInfo(
            IntPtr hMonitor,
            ref MONITORINFOEX lpmi
        );

        [DllImport("user32.dll", CharSet = CharSet.Ansi)]
        public static extern bool EnumDisplaySettings(
            string lpszDeviceName,
            int iModeNum,
            ref DEVMODE lpDevMode
        );

        [DllImport("Shcore.dll")]
        public static extern int GetDpiForMonitor(
            IntPtr hmonitor,
            int dpiType,
            out uint dpiX,
            out uint dpiY
        );

        [DllImport("Shcore.dll")]
        public static extern int GetScaleFactorForMonitor(
            IntPtr hMon,
            out int pScale
        );

        [DllImport("user32.dll")]
        public static extern bool SetProcessDpiAwarenessContext(
            IntPtr dpiContext
        );

        [DllImport("Shcore.dll")]
        public static extern int SetProcessDpiAwareness(
            int value
        );

        public static MonitorData[] GetMonitors()
        {
            List<MonitorData> result = new List<MonitorData>();

            MonitorEnumProc proc = delegate(
                IntPtr hMonitor,
                IntPtr hdcMonitor,
                ref RECT lprcMonitor,
                IntPtr dwData
            )
            {
                MONITORINFOEX info = new MONITORINFOEX();
                info.cbSize = Marshal.SizeOf(typeof(MONITORINFOEX));

                if (GetMonitorInfo(hMonitor, ref info))
                {
                    MonitorData m = new MonitorData();
                    m.HMonitor = hMonitor;
                    m.DeviceName = info.szDevice;
                    m.Left = info.rcMonitor.left;
                    m.Top = info.rcMonitor.top;
                    m.Right = info.rcMonitor.right;
                    m.Bottom = info.rcMonitor.bottom;
                    m.Primary = (info.dwFlags & 1) != 0;
                    result.Add(m);
                }

                return true;
            };

            EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, proc, IntPtr.Zero);

            return result.ToArray();
        }
    }
}
"@
}

# 尽量把当前 PowerShell 进程设为 Per-Monitor DPI Aware。
# 如果当前进程之前已经被锁定 DPI Awareness，这一步可能失败，不影响后续 EnumDisplaySettings 获取实际分辨率。
try {
    [void][ScreenInfo20260502.Native]::SetProcessDpiAwarenessContext([IntPtr]::new(-4))
} catch {
    try {
        [void][ScreenInfo20260502.Native]::SetProcessDpiAwarenessContext([IntPtr]::new(-3))
    } catch {
        try {
            [void][ScreenInfo20260502.Native]::SetProcessDpiAwareness(2)
        } catch {}
    }
}

$monitors = [ScreenInfo20260502.Native]::GetMonitors()

$result = for ($i = 0; $i -lt $monitors.Count; $i++) {
    $m = $monitors[$i]

    # 取 Windows 显示器编号：\\.\DISPLAY1 -> 1
    $displayIndex = $i + 1
    if ($m.DeviceName -match "DISPLAY(\d+)") {
        $displayIndex = [int]$Matches[1]
    }

    # 用 EnumDisplaySettings 获取实际物理像素分辨率
    $dm = New-Object ScreenInfo20260502.Native+DEVMODE
    $dm.dmSize = [System.Runtime.InteropServices.Marshal]::SizeOf([type][ScreenInfo20260502.Native+DEVMODE])

    $actualWidth = $null
    $actualHeight = $null

    $ok = [ScreenInfo20260502.Native]::EnumDisplaySettings(
        $m.DeviceName,
        [ScreenInfo20260502.Native]::ENUM_CURRENT_SETTINGS,
        [ref]$dm
    )

    if ($ok) {
        $actualWidth = [int]$dm.dmPelsWidth
        $actualHeight = [int]$dm.dmPelsHeight
    } else {
        # 兜底：如果 EnumDisplaySettings 失败，则使用监视器矩形
        $actualWidth = [int]($m.Right - $m.Left)
        $actualHeight = [int]($m.Bottom - $m.Top)
    }

    # 获取缩放率
    $dpiX = 0
    $dpiY = 0
    $dpiScale = $null

    try {
        $hrDpi = [ScreenInfo20260502.Native]::GetDpiForMonitor(
            $m.HMonitor,
            [ScreenInfo20260502.Native]::MDT_EFFECTIVE_DPI,
            [ref]$dpiX,
            [ref]$dpiY
        )

        if ($hrDpi -eq 0 -and $dpiX -gt 0) {
            $dpiScale = $dpiX / 96.0
        }
    } catch {}

    $factor = 0
    $factorScale = $null

    try {
        $hrFactor = [ScreenInfo20260502.Native]::GetScaleFactorForMonitor(
            $m.HMonitor,
            [ref]$factor
        )

        if ($hrFactor -eq 0 -and $factor -gt 0) {
            $factorScale = $factor / 100.0
        }
    } catch {}

    # 优先使用非 100% 的 DPI 结果；如果 DPI 被虚拟化成 96，则使用 GetScaleFactorForMonitor 的结果
    if ($dpiScale -and [math]::Abs($dpiScale - 1.0) -gt 0.001) {
        $scale = $dpiScale
    } elseif ($factorScale) {
        $scale = $factorScale
    } elseif ($dpiScale) {
        $scale = $dpiScale
    } else {
        $scale = 1.0
    }

    $scalePercent = [math]::Round($scale * 100)

    $effectiveWidth = [math]::Round($actualWidth / $scale)
    $effectiveHeight = [math]::Round($actualHeight / $scale)

    [PSCustomObject]@{
        MonitorIndex        = $displayIndex
        ActualResolution    = "${actualWidth}x${actualHeight}"
        ScaleRatio          = [math]::Round($scale, 4)
        ScalePercent        = "${scalePercent}%"
        EffectiveResolution = "${effectiveWidth}x${effectiveHeight}"
        DeviceName          = $m.DeviceName
        Primary             = $m.Primary
    }
}

$result | Sort-Object MonitorIndex | Format-Table -AutoSize
