"""通用后台启动器:双 fork + os.setsid 让目标命令完全脱离当前会话/进程组,
不会被父 shell(或工具超时)的进程组信号杀掉。macOS 无 setsid 命令时替代。

用法:
    python3 scripts/bg_launch.py <logfile> <cmd> [args...]
打印子进程 PID 后立即退出。
"""

import os
import sys


def main() -> None:
    if len(sys.argv) < 3:
        sys.stderr.write("usage: bg_launch.py <logfile> <cmd> [args...]\n")
        sys.exit(2)

    logfile = sys.argv[1]
    cmd = sys.argv[2:]

    pid = os.fork()
    if pid > 0:
        os.waitpid(pid, 0)
        return

    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        sys.stdout.write(f"PID={pid2}\n")
        sys.stdout.flush()
        os._exit(0)

    fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
