# Automation

Headless test harnesses drive DOSBox-X through the debugger's `mcp_server` channel
(needs a debugger build, e.g. `--enable-debug=heavy`). Start DOSBox-X with
`-set "dosbox mcp_server=PORT"` and it connects to `127.0.0.1:PORT`.

`dosbox_ctl.py` is a small synchronous client (Python 3.12, standard library only):

| Call | Debugger command |
| --- | --- |
| `Session(port=0, alive=None, connect_timeout=30, reply_timeout=10)` | listens; `session.port` is the port to pass to DOSBox-X |
| `accept()` | waits for DOSBox-X to connect (`execute` calls it) |
| `execute(cmd) -> list[str]` | any command; `ERR` raises `DosboxError` |
| `key(chord, hold=50)` | `KEY chord hold`; one upper-case letter becomes `lshift+x`; unknown key raises |
| `type(keys, pace=300, hold=50)` | `key()` per key, `pace` ms apart |
| `move(x, y)` / `button(n, down)` | `MOUSEMOVE` / `MOUSEBUTTON n DOWN\|UP` |
| `shot(captures, raw=True, timeout=5) -> Path` | `SCREENSHOT [RAW]`, returns the new PNG |
| `video(start)` | `VIDEOCAPTURE START\|STOP` |
| `wait(seconds)`, `close()` | |

`alive` is a callable polled while waiting (connect, replies, screenshots, `wait`);
returning False raises `Stopped`. Pass e.g. `lambda: proc.poll() is None`.

## Crash diagnostics

In real mode the CPU core keeps the last 64 far control transfers (far call/jump/ret,
interrupt, iret). The first three calls of an unhandled interrupt log, with the
log line prefix `CIVZH: `:

```
CIVZH: int <n> from <cs>:<ip> ds=... ss=... sp=...
CIVZH: ax=... bx=... ...
CIVZH: stack+00: ...            (8 lines)
CIVZH: <C|J|F|I|R> <cs>:<ip> sp=<sp> -> <cs>:<ip>   (64 lines, first time only)
```

A harness can treat `CIVZH: int ` in the log as a crash, next to upstream's
`Rebooting the system`.
