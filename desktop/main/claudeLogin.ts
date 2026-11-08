import { spawn } from "node:child_process";

/** Only the official interactive login action can be opened by the renderer. */
export function claudeLoginCommand(platform: string, selectedExecutable = ""): { executable: string; args: string[] } {
  if (platform === "win32") {
    const command = selectedExecutable ? `& '${selectedExecutable.replaceAll("'", "''")}' auth login` : "claude auth login";
    return { executable: "powershell.exe", args: ["-NoLogo", "-NoProfile", "-NoExit", "-Command", command] };
  }
  if (platform === "darwin") {
    if (selectedExecutable) return { executable: "osascript", args: [
      "-e", "on run argv",
      "-e", 'tell application "Terminal" to do script ((quoted form of item 1 of argv) & " auth login")',
      "-e", "end run", selectedExecutable,
    ] };
    return { executable: "osascript", args: ["-e", 'tell application "Terminal" to do script "claude auth login"'] };
  }
  return { executable: "x-terminal-emulator", args: ["-e", selectedExecutable || "claude", "auth", "login"] };
}

export function openClaudeLogin(cwd: string, selectedExecutable = ""): Promise<boolean> {
  const command = claudeLoginCommand(process.platform, selectedExecutable);
  return new Promise((resolve, reject) => {
    const child = spawn(command.executable, command.args, { cwd, stdio: "ignore", detached: true, windowsHide: false, shell: false });
    child.once("error", () => reject(new Error("Claude 로그인 터미널을 열지 못했습니다. 터미널에서 claude auth login을 실행해 주세요.")));
    child.once("spawn", () => { child.unref(); resolve(true); });
  });
}
