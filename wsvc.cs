using System;
using System.IO;
using System.Net;
using System.Text;
using System.Diagnostics;
using System.Threading;

class Wsvc {
  static readonly string OUTFILE = @"D:\WSDI\ws_out.txt";
  static void Main() {
    HttpListener l = new HttpListener();
    l.Prefixes.Add("http://127.0.0.1:8765/");
    bool up = false;
    for (int i = 0; i < 40 && !up; i++) {   // retry bind: survives stale-socket release + double-start
      try { l.Start(); up = true; } catch { Thread.Sleep(500); }
    }
    if (!up) return;                         // another healthy instance already owns the port -> exit cleanly
    while (true) {
      HttpListenerContext c;
      try { c = l.GetContext(); } catch { continue; }
      try { Handle(c); } catch { }            // sequential: one request at a time, every response closed
    }
  }
  static string ReadBody(HttpListenerRequest r) {
    long len = r.ContentLength64;
    if (len <= 0) return "";
    byte[] body = new byte[len];
    int off = 0;
    while (off < len) {
      int n = r.InputStream.Read(body, off, (int)(len - off));
      if (n <= 0) break;
      off += n;
    }
    return Encoding.UTF8.GetString(body, 0, off).Trim();
  }
  static void Handle(HttpListenerContext c) {
    byte[] rb;
    string path = c.Request.Url.AbsolutePath;
    if (path == "/ok") {
      rb = Encoding.UTF8.GetBytes("alive");
    } else if (path == "/rm") {
      try { File.Delete(OUTFILE); } catch { }
      rb = Encoding.UTF8.GetBytes("rm");
    } else if (path == "/c") {
      string hx = ReadBody(c.Request);
      string cmd = HexTo(hx);
      ProcessStartInfo psi = new ProcessStartInfo("cmd.exe", "/Q /C " + cmd);
      psi.RedirectStandardOutput = true;
      psi.RedirectStandardError = true;
      psi.UseShellExecute = false;
      psi.CreateNoWindow = true;
      string o = "", e = ""; int rc = -1;
      using (Process p = Process.Start(psi)) {
        o = p.StandardOutput.ReadToEnd();
        e = p.StandardError.ReadToEnd();
        try { if (p.WaitForExit(60000)) rc = p.ExitCode; else p.Kill(); } catch { }
      }
      string j = "{\"rc\":" + rc + ",\"out\":\"" + B64(o) + "\",\"err\":\"" + B64(e) + "\"}";
      rb = Encoding.UTF8.GetBytes(j);
      WriteAtomic(OUTFILE, j);                    // decoupled result channel: read back via D:/ junction
    } else {
      rb = Encoding.UTF8.GetBytes("nf");
    }
    c.Response.KeepAlive = false;
    c.Response.ContentType = "text/plain";
    c.Response.OutputStream.Write(rb, 0, rb.Length);
    try { c.Response.Close(); } catch { }
  }
  static void WriteAtomic(string path, string text) {   // temp+rename: reader never sees a partial file
    string tmp = path + ".tmp";
    try {
      File.WriteAllText(tmp, text);
      try { File.Delete(path); } catch { }
      File.Move(tmp, path);
    } catch { }
  }
  static string B64(string s) {
    if (s == null) s = "";
    return Convert.ToBase64String(Encoding.UTF8.GetBytes(s));
  }
  static string HexTo(string h) {
    if (h.Length % 2 != 0) h = h + "0";
    byte[] b = new byte[h.Length / 2];
    for (int i = 0; i < b.Length; i++) {
      int a = Nib(h[i * 2]);
      int c = Nib(h[i * 2 + 1]);
      b[i] = (byte)(a * 16 + c);
    }
    return Encoding.UTF8.GetString(b);
  }
  static int Nib(char ch) {
    int v = (int)ch;
    if (v >= 97) return v - 87;
    if (v >= 65) return v - 55;
    return v - 48;
  }
}
