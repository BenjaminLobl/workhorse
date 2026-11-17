using System;
using System.Diagnostics;
using System.IO;
class Workhorse {
    static int Main() {
        try {
            string folder = AppDomain.CurrentDomain.BaseDirectory;
            string script = Path.Combine(folder, "Start-Desktop.ps1");
            if (!File.Exists(script)) throw new Exception("Start-Desktop.ps1 is missing. Reinstall the desktop launcher.");
            var start = new ProcessStartInfo();
            start.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), @"WindowsPowerShell\v1.0\powershell.exe");
            start.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\"";
            start.WorkingDirectory = folder;
            start.UseShellExecute = false;
            using (var process = Process.Start(start)) { process.WaitForExit(); return process.ExitCode; }
        } catch(Exception ex) { Console.WriteLine(ex.Message); Console.WriteLine("Press Enter to close."); Console.ReadLine(); return 1; }
    }
}
