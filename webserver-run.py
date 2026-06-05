#!/usr/bin/env python3
"""Run a local HTTP server to serve static web tools."""

import os
import sys
import ipaddress
import http.server
import socket

from utils import *


def _resolve_dir(path_str):
    """Resolve a path to a directory. File paths are resolved to their parent."""
    path = os.path.abspath(os.path.expanduser(path_str))
    if os.path.isfile(path):
        return os.path.dirname(path)
    if os.path.isdir(path):
        return path
    Utils.print_error_and_exit(f"Path does not exist: {path_str}")


def _get_local_ip():
    """Return the local network IP, or empty string on failure."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def _validate_bind(bind):
    """Validate that *bind* is a legitimate IP address. Exits on failure."""
    try:
        ipaddress.ip_address(bind)
        return bind
    except ValueError:
        Utils.print_error_and_exit(f"Invalid IP address: {bind}")


def _is_headless() -> bool:
    """Return True if the environment likely has no GUI / display available."""
    if sys.platform != "win32":
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return True
    return False


def _open_browser_safe(url: str) -> None:
    """Open *url* in the default browser, silently skip on headless systems."""
    if _is_headless():
        return
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass  # silently ignore browser-open failures


def _run_server(directory, bind, port, url_path="", quiet=False, open_browser=True):
    """Start the HTTP server. Blocks until KeyboardInterrupt."""
    prev_dir = os.getcwd()
    os.chdir(directory)

    handler = http.server.SimpleHTTPRequestHandler
    if quiet:
        class _QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
        handler = _QuietHandler

    httpd = http.server.ThreadingHTTPServer((bind, port), handler)

    full_url = f"http://127.0.0.1:{port}{url_path}"
    print(f"\n{FLGreen}Serving directory:{CRst} {FGray}{directory}{CRst}")
    print(f"{FLGreen}URL:{CRst}")
    print(f"  http://{bind}:{port}{url_path}")
    if bind == "0.0.0.0":
        print(f"  {full_url}")
        local_ip = _get_local_ip()
        if local_ip:
            print(f"  http://{local_ip}:{port}{url_path}")
    print(f"\n{FGray}Press {FLYellow}Ctrl+C{CRst} to stop.{CRst}\n")

    if open_browser:
        _open_browser_safe(full_url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{FLYellow}Server stopped.{CRst}")
        httpd.server_close()
    finally:
        os.chdir(prev_dir)


def main():
    script_name = os.path.basename(sys.argv[0])

    if "--help" in sys.argv or "-h" in sys.argv:
        print(f"""
{FLYellow}========== WEBSERVER RUNNING TOOL ========={CRst}
==============

{FLYellow}Usage:{CRst}
  python {script_name}                  interactive mode
  python {script_name} --dir <PATH>     serve directory or index.html
  python {script_name} --help           show this help

{FLYellow}Description:{CRst}
  Start a local HTTP server to serve static web tools (HTML, JS, images, etc.).
  Uses Python's built-in http.server with threading enabled.

{FLYellow}Options:{CRst}
  --dir <PATH>       Directory or index.html file to serve
  --bind <IP>        Bind address (default: 0.0.0.0)
  --port <PORT>      Port number (default: 8000)
  --url-path <PATH>  URL path suffix appended after port (e.g. /#/setup?host=...)
  --no-open          Do not open the URL in the default browser
  --quiet            Suppress HTTP request log output
""")
        sys.exit(0)

    print(f"{FLYellow}========= WEBSERVER RUNNING TOOL ========={CRst}")

    # ----- parse optional CLI args -----
    serve_dir: str | None = None
    cli_bind = "0.0.0.0"
    cli_port = 8000
    url_path = ""
    no_open = False
    quiet = False

    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--dir" and i + 1 < len(sys.argv):
            serve_dir = sys.argv[i + 1]
            i += 2
        elif a == "--bind" and i + 1 < len(sys.argv):
            cli_bind = sys.argv[i + 1]
            i += 2
        elif a == "--port" and i + 1 < len(sys.argv):
            try:
                cli_port = int(sys.argv[i + 1])
            except ValueError:
                Utils.print_error_and_exit(f"Invalid port number: {sys.argv[i + 1]}")
            i += 2
        elif a == "--url-path" and i + 1 < len(sys.argv):
            url_path = sys.argv[i + 1]
            i += 2
        elif a == "--no-open":
            no_open = True
            i += 1
        elif a == "--quiet":
            quiet = True
            i += 1
        else:
            i += 1

    # ----- resolve target directory, bind, port -----
    if serve_dir is not None:
        target_dir = _resolve_dir(serve_dir)
        _validate_bind(cli_bind)
        bind = cli_bind
        port = cli_port
    else:
        # fully interactive
        raw_path = Input.resolve_input_path(
            "./",
            prompt="Enter directory or index.html path",
            path_type="any",
        )
        target_dir = _resolve_dir(raw_path)

        bind_options = [
            MenuOption(["0"], "0.0.0.0 (all interfaces)", value="0.0.0.0"),
            MenuOption(["1"], "127.0.0.1 (localhost only)", value="127.0.0.1"),
        ]
        bind = Menu.select(
            bind_options,
            prompt="Bind address",
            default_key="0",
            accept_custom_string=True,
        )
        _validate_bind(bind)

        port_str = input(f"{FLYellow}Port {FGray}[8000]{CRst}{FLYellow}: {CRst}").strip()
        if not port_str:
            port = 8000
        else:
            try:
                port = int(port_str)
            except ValueError:
                Utils.print_error_and_exit(f"Invalid port: {port_str}")

        quiet_resp = input(f"{FLYellow}Suppress server output? {FGray}[n]{CRst}{FLYellow}: {CRst}").strip().lower()
        quiet = quiet_resp == "y"

    _run_server(target_dir, bind, port, url_path=url_path, quiet=quiet, open_browser=not no_open)


if __name__ == "__main__":
    main()
