/*
 * TaskbarClock — NTP-synced UTC+8 clock embedded in the Windows taskbar.
 *
 * Build : build.bat
 * Register (admin): register.bat
 * After registration, right-click the taskbar → Toolbars → "NTP Clock"
 */

using System;
using System.ComponentModel;
using System.Drawing;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

// ---------------------------------------------------------------------------
// COM interface definitions (from Windows SDK)
// ---------------------------------------------------------------------------

[ComImport]
[Guid("00000114-0000-0000-C000-000000000046")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IOleWindow
{
    void GetWindow(out IntPtr hwnd);
    void ContextSensitiveHelp([MarshalAs(UnmanagedType.Bool)] bool fEnterMode);
}

[ComImport]
[Guid("012DD920-7B26-11D0-8CA9-00A0C92DBFE8")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IDockingWindow : IOleWindow
{
    new void GetWindow(out IntPtr hwnd);
    new void ContextSensitiveHelp([MarshalAs(UnmanagedType.Bool)] bool fEnterMode);
    void ShowDW([MarshalAs(UnmanagedType.Bool)] bool fShow);
    void CloseDW(uint dwReserved);
    void ResizeBorderDW(RECT prcBorder, [MarshalAs(UnmanagedType.IUnknown)] object punkToolbarSite,
        [MarshalAs(UnmanagedType.Bool)] bool fReserved);
}

[ComImport]
[Guid("EB0FE172-1A3A-11D0-89B3-00A0C90A90AC")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IDeskBand : IDockingWindow
{
    new void GetWindow(out IntPtr hwnd);
    new void ContextSensitiveHelp([MarshalAs(UnmanagedType.Bool)] bool fEnterMode);
    new void ShowDW([MarshalAs(UnmanagedType.Bool)] bool fShow);
    new void CloseDW(uint dwReserved);
    new void ResizeBorderDW(RECT prcBorder, [MarshalAs(UnmanagedType.IUnknown)] object punkToolbarSite,
        [MarshalAs(UnmanagedType.Bool)] bool fReserved);
    void GetBandInfo(uint dwBandID, uint dwViewMode, ref DESKBANDINFO pdbi);
}

[ComImport]
[Guid("79D16DE4-ABEE-4021-8D9D-916B261D6574")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IDeskBand2 : IDeskBand
{
    new void GetWindow(out IntPtr hwnd);
    new void ContextSensitiveHelp([MarshalAs(UnmanagedType.Bool)] bool fEnterMode);
    new void ShowDW([MarshalAs(UnmanagedType.Bool)] bool fShow);
    new void CloseDW(uint dwReserved);
    new void ResizeBorderDW(RECT prcBorder, [MarshalAs(UnmanagedType.IUnknown)] object punkToolbarSite,
        [MarshalAs(UnmanagedType.Bool)] bool fReserved);
    new void GetBandInfo(uint dwBandID, uint dwViewMode, ref DESKBANDINFO pdbi);
    void CanRenderComposited(out bool pfCanRenderComposited);
    void SetCompositionState([MarshalAs(UnmanagedType.Bool)] bool fCompositionEnabled);
    void GetCompositionState(out bool pfCompositionEnabled);
}

[ComImport]
[Guid("FC4801A3-2BA9-11CF-A229-00AA003D7352")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IObjectWithSite
{
    void SetSite([MarshalAs(UnmanagedType.IUnknown)] object pUnkSite);
    void GetSite(ref Guid riid, out IntPtr ppvSite);
}

[ComImport]
[Guid("68284FAA-6A48-11D0-8C78-00C04FD918B4")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IInputObject
{
    void UIActivateIO([MarshalAs(UnmanagedType.Bool)] bool fActivate, ref MSG pMsg);
    void HasFocusIO();
    void TranslateAcceleratorIO(ref MSG pMsg);
}

// ---------------------------------------------------------------------------
// Structures
// ---------------------------------------------------------------------------

[StructLayout(LayoutKind.Sequential)]
public struct RECT
{
    public int left, top, right, bottom;
}

[StructLayout(LayoutKind.Sequential)]
public struct POINT
{
    public int x, y;
}

[StructLayout(LayoutKind.Sequential)]
public struct DESKBANDINFO
{
    public uint dwMask;
    public POINT ptMinSize;
    public POINT ptMaxSize;
    public POINT ptIntegral;
    public POINT ptActual;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
    public string wszTitle;
    public uint dwModeFlags;
    public int crBkgnd;
}

[StructLayout(LayoutKind.Sequential)]
public struct MSG
{
    public IntPtr hwnd;
    public uint message;
    public IntPtr wParam;
    public IntPtr lParam;
    public uint time;
    public POINT pt;
}

// DESKBANDINFO dwMask flags
internal static class DBIM
{
    public const uint MINSIZE   = 0x0001;
    public const uint MAXSIZE   = 0x0002;
    public const uint INTEGRAL  = 0x0004;
    public const uint ACTUAL    = 0x0008;
    public const uint TITLE     = 0x0010;
    public const uint MODEFLAGS = 0x0020;
    public const uint BKCOLOR   = 0x0040;
}

// DESKBANDINFO dwModeFlags
internal static class DBIMF
{
    public const uint NORMAL          = 0x0000;
    public const uint FIXED           = 0x0001;
    public const uint FIXEDBMP        = 0x0004;
    public const uint VARIABLEHEIGHT  = 0x0008;
    public const uint UNDELETEABLE    = 0x0010;
    public const uint DEBOSSED        = 0x0020;
    public const uint BKCOLOR         = 0x0040;
    public const uint USECHEVRON      = 0x0080;
    public const uint BREAK           = 0x0100;
    public const uint ADDTOFRONT      = 0x0200;
    public const uint TOPALIGN        = 0x0400;
    public const uint NOGRIPPER       = 0x0800;
    public const uint ALWAYSGRIPPER   = 0x1000;
    public const uint NOMARGINS       = 0x2000;
}

internal static class DBGF
{
    public const uint NORMAL = 0x0000;
    public const uint FIXED  = 0x0001;
}

// ---------------------------------------------------------------------------
// BandObject — base class for DeskBand COM objects
// ---------------------------------------------------------------------------

[ComVisible(true)]
public abstract class BandObject : IDeskBand2, IObjectWithSite, IInputObject, IDisposable
{
    protected Control _control;
    protected IntPtr _sitePtr;
    protected IntPtr _hwndParent;
    protected bool _bandVisible;
    protected uint _bandId;
    protected bool _disposed;

    public abstract string Title { get; }
    public abstract Size MinSize { get; }
    public abstract Size MaxSize { get; }

    // ---- IDeskBand2 ----

    public virtual void GetWindow(out IntPtr hwnd)
    {
        hwnd = _control != null ? _control.Handle : IntPtr.Zero;
    }

    public virtual void ContextSensitiveHelp(bool fEnterMode) { }

    public virtual void ShowDW(bool fShow)
    {
        _bandVisible = fShow;
        if (_control != null)
        {
            if (fShow)
            {
                _control.Show();
                Native.SetWindowPos(_control.Handle, IntPtr.Zero,
                    0, 0, _control.Width, _control.Height,
                    Native.SWP_NOZORDER | Native.SWP_NOACTIVATE | Native.SWP_SHOWWINDOW);
            }
            else
            {
                _control.Hide();
            }
        }
    }

    public virtual void CloseDW(uint dwReserved)
    {
        _bandVisible = false;
    }

    public virtual void ResizeBorderDW(RECT prcBorder, object punkToolbarSite, bool fReserved) { }

    public virtual void GetBandInfo(uint dwBandID, uint dwViewMode, ref DESKBANDINFO pdbi)
    {
        _bandId = dwBandID;
        var min = MinSize;
        var max = MaxSize;

        if ((pdbi.dwMask & DBIM.MINSIZE) != 0)
        {
            pdbi.ptMinSize.x = min.Width;
            pdbi.ptMinSize.y = min.Height;
        }
        if ((pdbi.dwMask & DBIM.MAXSIZE) != 0)
        {
            pdbi.ptMaxSize.x = max.Width;
            pdbi.ptMaxSize.y = max.Height;
        }
        if ((pdbi.dwMask & DBIM.INTEGRAL) != 0)
        {
            pdbi.ptIntegral.x = 1;
            pdbi.ptIntegral.y = 1;
        }
        if ((pdbi.dwMask & DBIM.ACTUAL) != 0)
        {
            pdbi.ptActual.x = _control != null ? _control.Width  : min.Width;
            pdbi.ptActual.y = _control != null ? _control.Height : min.Height;
        }
        if ((pdbi.dwMask & DBIM.TITLE) != 0)
        {
            pdbi.wszTitle = Title;
        }
        if ((pdbi.dwMask & DBIM.MODEFLAGS) != 0)
        {
            pdbi.dwModeFlags = DBIMF.VARIABLEHEIGHT | DBIMF.NORMAL;
        }
        if ((pdbi.dwMask & DBIM.BKCOLOR) != 0)
        {
            pdbi.crBkgnd = ColorTranslator.ToWin32(Color.Black);
        }
    }

    public virtual void CanRenderComposited(out bool pfCanRenderComposited)
    {
        pfCanRenderComposited = true;
    }

    public virtual void SetCompositionState(bool fCompositionEnabled) { }
    public virtual void GetCompositionState(out bool pfCompositionEnabled)
    {
        pfCompositionEnabled = true;
    }

    // ---- IObjectWithSite ----

    public virtual void SetSite(object pUnkSite)
    {
        if (pUnkSite != null)
        {
            _sitePtr = Marshal.GetIUnknownForObject(pUnkSite);

            // Get parent HWND through IOleWindow
            var oleWindow = pUnkSite as IOleWindow;
            if (oleWindow != null)
            {
                oleWindow.GetWindow(out _hwndParent);
            }

            if (_control == null)
            {
                _control = CreateControl();
                _control.CreateControl();
            }

            if (_hwndParent != IntPtr.Zero)
            {
                Native.SetParent(_control.Handle, _hwndParent);
                Native.SetWindowLong(_control.Handle, Native.GWL_STYLE,
                    Native.WS_CHILD | Native.WS_VISIBLE | Native.WS_CLIPSIBLINGS);
            }
        }
        else
        {
            // Site being cleared — cleanup
            if (_sitePtr != IntPtr.Zero)
            {
                Marshal.Release(_sitePtr);
                _sitePtr = IntPtr.Zero;
            }
        }
    }

    public virtual void GetSite(ref Guid riid, out IntPtr ppvSite)
    {
        ppvSite = IntPtr.Zero;
        if (_sitePtr != IntPtr.Zero)
        {
            Marshal.QueryInterface(_sitePtr, ref riid, out ppvSite);
        }
    }

    // ---- IInputObject ----

    public virtual void UIActivateIO(bool fActivate, ref MSG pMsg)
    {
        if (fActivate && _control != null)
            _control.Focus();
    }

    public virtual void HasFocusIO()
    {
        if (_control != null && _control.ContainsFocus)
        {
            // notify site we have focus
        }
    }

    public virtual void TranslateAcceleratorIO(ref MSG pMsg) { }

    // ---- Overrides ----

    protected abstract Control CreateControl();

    public virtual void Dispose()
    {
        if (!_disposed)
        {
            _disposed = true;
            if (_control != null)
            {
                _control.Dispose();
                _control = null;
            }
            if (_sitePtr != IntPtr.Zero)
            {
                Marshal.Release(_sitePtr);
                _sitePtr = IntPtr.Zero;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// P/Invoke helpers
// ---------------------------------------------------------------------------

internal static class Native
{
    public const int GWL_STYLE      = -16;
    public const int WS_CHILD        = 0x40000000;
    public const int WS_VISIBLE      = 0x10000000;
    public const int WS_CLIPSIBLINGS = 0x04000000;
    public const int SWP_NOZORDER    = 0x0004;
    public const int SWP_NOACTIVATE  = 0x0010;
    public const int SWP_SHOWWINDOW  = 0x0040;

    [DllImport("user32.dll")]
    public static extern IntPtr SetParent(IntPtr hWndChild, IntPtr hWndNewParent);

    [DllImport("user32.dll")]
    public static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter,
        int X, int Y, int cx, int cy, uint uFlags);
}

// ---------------------------------------------------------------------------
// NTP client
// ---------------------------------------------------------------------------

internal static class NtpClient
{
    private const int NTP_PORT = 123;
    private static readonly DateTime Epoch = new DateTime(1900, 1, 1, 0, 0, 0, DateTimeKind.Utc);

    private static readonly string[] Servers =
    {
        "ntp.aliyun.com",
        "pool.ntp.org",
        "time.windows.com",
    };

    /// <summary>Try to sync with an NTP server.  Returns null on failure.</summary>
    public static NtpResult Sync(int timeoutMs = 3000)
    {
        foreach (var server in Servers)
        {
            try
            {
                var packet = new byte[48];
                packet[0] = 0x23; // LI=0, VN=4, Mode=3 (client)

                var t1 = DateTime.UtcNow;

                using (var sock = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp))
                {
                    sock.ReceiveTimeout = timeoutMs;
                    sock.SendTimeout = timeoutMs;
                    sock.Connect(server, NTP_PORT);
                    sock.Send(packet);
                    sock.Receive(packet);
                }

                var t4 = DateTime.UtcNow;

                // Extract server timestamps
                var t2 = NtpToUtc(packet, 32);
                var t3 = NtpToUtc(packet, 40);

                var offset = ((t2 - t1).TotalSeconds + (t3 - t4).TotalSeconds) / 2.0;
                return new NtpResult { Ok = true, Offset = offset };
            }
            catch
            {
                // try next server
            }
        }
        return new NtpResult { Ok = false, Offset = 0.0 };
    }

    public class NtpResult
    {
        public bool Ok { get; set; }
        public double Offset { get; set; }
    }

    private static DateTime NtpToUtc(byte[] data, int offset)
    {
        ulong intPart = ((ulong)data[offset] << 24) | ((ulong)data[offset + 1] << 16)
                      | ((ulong)data[offset + 2] << 8) | data[offset + 3];
        ulong fracPart = ((ulong)data[offset + 4] << 24) | ((ulong)data[offset + 5] << 16)
                       | ((ulong)data[offset + 6] << 8) | data[offset + 7];

        double seconds = intPart + fracPart / 4294967296.0; // 2^32
        return Epoch.AddSeconds(seconds);
    }
}

// ---------------------------------------------------------------------------
// Clock Control  (the UI hosted inside the taskbar)
// ---------------------------------------------------------------------------

internal class ClockControl : UserControl
{
    private readonly Label _lblTime;
    private readonly Label _lblDate;
    private readonly System.Windows.Forms.Timer _timer;
    private double _ntpOffset;
    private bool _ntpOk;
    private int _ntpRetryCount;

    // UTC+8 timezone
    private static readonly TimeSpan TZ_OFFSET = TimeSpan.FromHours(8);

    private static readonly string[] WEEKDAYS = { "周日", "周一", "周二", "周三", "周四", "周五", "周六" };

    public ClockControl()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint |
                 ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);

        BackColor = Color.Black;

        _lblTime = new Label
        {
            AutoSize = false,
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.White,
            BackColor = Color.Transparent,
        };

        _lblDate = new Label
        {
            AutoSize = false,
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(180, 180, 180),
            BackColor = Color.Transparent,
        };

        Controls.Add(_lblTime);
        Controls.Add(_lblDate);

        // Layout
        LayoutControls();

        // Update timer — 200ms for smooth seconds
        _timer = new System.Windows.Forms.Timer { Interval = 200 };
        _timer.Tick += (s, e) => RefreshClock();
        _timer.Start();

        // Initial NTP sync
        Task.Run(new Action(() =>
        {
            var result = NtpClient.Sync();
            _ntpOffset = result.Offset;
            _ntpOk = result.Ok;
        }));

        // Periodic NTP re-sync
        var ntpTimer = new System.Windows.Forms.Timer { Interval = 3600000 }; // 1 hour
        ntpTimer.Tick += (s, e) =>
        {
            Task.Run(new Action(() =>
            {
                var result = NtpClient.Sync();
                if (result.Ok)
                {
                    _ntpOffset = result.Offset;
                    _ntpOk = true;
                    _ntpRetryCount = 0;
                }
                else
                {
                    _ntpRetryCount++;
                }
            }));
        };
        ntpTimer.Start();
    }

    private void LayoutControls()
    {
        int h = Height;
        int w = Width;
        int timeH = (int)(h * 0.55);
        int dateH = h - timeH;
        int pad = 4;

        _lblTime.SetBounds(pad, 0, w - pad * 2, timeH);
        _lblDate.SetBounds(pad, timeH, w - pad * 2, dateH);

        using (var g = CreateGraphics())
        {
            _lblTime.Font = GetAdjustedFont(g, "00:00:00", _lblTime.Size, 6, 16);
            _lblDate.Font = GetAdjustedFont(g, "2026-12-31 周日", _lblDate.Size, 6, 11);
        }
    }

    /// <summary>Find the largest font size that fits the given text in the given bounds.</summary>
    private static Font GetAdjustedFont(Graphics g, string text, Size bounds, int minSize, int maxSize)
    {
        for (int sz = maxSize; sz >= minSize; sz--)
        {
            using (var f = new Font("Microsoft YaHei", sz, FontStyle.Regular))
            {
                var m = g.MeasureString(text, f);
                if (m.Width <= bounds.Width && m.Height <= bounds.Height)
                    return new Font("Microsoft YaHei", sz, FontStyle.Regular);
            }
        }
        return new Font("Microsoft YaHei", minSize, FontStyle.Regular);
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        LayoutControls();
    }

    private void RefreshClock()
    {
        // NTP-corrected time in UTC+8
        var localTime = DateTime.UtcNow.AddSeconds(_ntpOffset).Add(TZ_OFFSET);
        var now = _ntpOk ? localTime : DateTime.Now; // fallback to system time

        var timeStr = now.ToString("HH:mm:ss");
        var dateStr = string.Format("{0:yyyy-MM-dd} {1}", now, WEEKDAYS[(int)now.DayOfWeek]);

        // Only update if changed (avoids flicker)
        if (_lblTime.Text != timeStr)
            _lblTime.Text = timeStr;
        if (_lblDate.Text != dateStr)
            _lblDate.Text = dateStr;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            if (_timer != null)
            {
                _timer.Stop();
                _timer.Dispose();
            }
        }
        base.Dispose(disposing);
    }
}

// ---------------------------------------------------------------------------
// Clock DeskBand  (COM-visible DeskBand that wraps ClockControl)
// ---------------------------------------------------------------------------

[ComVisible(true)]
[Guid("B7C8F3A1-5D2E-4F6B-9A1C-2E4D8F0B6C9A")]
[ProgId("TaskbarClock.NtpClock")]
[ClassInterface(ClassInterfaceType.None)]
[Description("NTP Clock — UTC+8 taskbar clock with seconds")]
public sealed class ClockDeskBand : BandObject
{
    private ClockControl _clockCtrl;

    public override string Title { get { return "NTP Clock"; } }

    public override Size MinSize { get { return new Size(130, 32); } }
    public override Size MaxSize { get { return new Size(300, 60); } }

    protected override Control CreateControl()
    {
        _clockCtrl = new ClockControl
        {
            MinimumSize = MinSize,
            MaximumSize = MaxSize,
            Size = new Size(145, 34),
            BackColor = Color.Black,
            ForeColor = Color.White,
        };
        return _clockCtrl;
    }

    #region COM Registration

    private const string CLSID = "{B7C8F3A1-5D2E-4F6B-9A1C-2E4D8F0B6C9A}";
    private const string CATID_DESKBAND = "{00021492-0000-0000-C000-000000000046}";

    [ComRegisterFunction]
    public static void Register(Type t)
    {
        try
        {
            var keyPath = @"CLSID\" + CLSID;
            using (var key = Registry.ClassesRoot.CreateSubKey(keyPath))
            {
                key.SetValue(null, "NTP Clock DeskBand");
            }

            // Implemented Categories
            var catPath = @"CLSID\" + CLSID + @"\Implemented Categories\" + CATID_DESKBAND;
            using (var catKey = Registry.ClassesRoot.CreateSubKey(catPath))
            {
            }

            // Register as a toolbar
            var toolbarPath = @"SOFTWARE\Microsoft\Internet Explorer\Toolbar\" + CLSID;
            using (var toolKey = Registry.LocalMachine.CreateSubKey(toolbarPath))
            {
            }
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine("ComRegisterFunction error: " + ex.Message);
        }
    }

    [ComUnregisterFunction]
    public static void Unregister(Type t)
    {
        try
        {
            Registry.ClassesRoot.DeleteSubKeyTree(@"CLSID\" + CLSID, false);

            using (var toolKey = Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\Microsoft\Internet Explorer\Toolbar", true))
            {
                if (toolKey != null)
                    toolKey.DeleteSubKey(CLSID, false);
            }
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine("ComUnregisterFunction error: " + ex.Message);
        }
    }

    #endregion
}
