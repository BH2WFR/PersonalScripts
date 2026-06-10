#!/usr/bin/env python3
"""Run a local HTTP server to serve static web tools."""

import os
import sys
import ipaddress
import http.server
import socket
from typing import Optional

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
        Utils.open_browser_safe(full_url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{FLYellow}Server stopped.{CRst}")
        httpd.server_close()
    finally:
        os.chdir(prev_dir)


def _prompt_bind(default_bind="0.0.0.0"):
    bind_options = [
        MenuOption(["0"], "0.0.0.0 (all interfaces)", value="0.0.0.0"),
        MenuOption(["1"], "127.0.0.1 (localhost only)", value="127.0.0.1"),
    ]
    default_key = "1" if default_bind == "127.0.0.1" else "0"
    bind = Menu.select(
        bind_options,
        prompt="Bind address",
        default_key=default_key,
        accept_custom_string=True,
    )
    return _validate_bind(bind)


def _prompt_port(default_port=8000):
    port_str = input(f"{FLYellow}Port {FGray}[{default_port}]{CRst}{FLYellow}: {CRst}").strip()
    if not port_str:
        return default_port
    try:
        return int(port_str)
    except ValueError:
        Utils.print_error_and_exit(f"Invalid port: {port_str}")


def _prompt_quiet():
    quiet_resp = input(f"{FLYellow}Suppress server output? {FGray}[n]{CRst}{FLYellow}: {CRst}").strip().lower()
    return quiet_resp == "y"


def main():
    script_name = os.path.basename(sys.argv[0])

    if "--help" in sys.argv or "-h" in sys.argv:
        print(f"""
{FLYellow}========== WEBSERVER RUNNING TOOL ========={CRst}
==============

{FLYellow}Usage:{CRst}
  python {script_name}                  interactive mode
  python {script_name} <PATH>           serve directory or index.html
  python {script_name} <PATH> --bind <IP> --port <PORT>
  python {script_name} --help           show this help

{FLYellow}Description:{CRst}
  Start a local HTTP server to serve static web tools (HTML, JS, images, etc.).
  Uses Python's built-in http.server with threading enabled.

{FLYellow}Options:{CRst}
  <PATH>             Directory or index.html file to serve (positional)
  --bind <IP>        Bind address; with --port, enables non-interactive mode
  --port <PORT>      Port number; with --bind, enables non-interactive mode
  --url-path <PATH>  URL path suffix appended after port (e.g. /#/setup?host=...)
  --no-open          Do not open the URL in the default browser
  --quiet            Suppress HTTP request log output
""")
        sys.exit(0)

    Utils.print_banner("WEBSERVER RUNNING TOOL")

    # ----- parse optional CLI args -----
    serve_dir: Optional[str] = None
    cli_bind = "0.0.0.0"
    cli_port = 8000
    url_path = ""
    no_open = False
    quiet = False
    bind_provided = False
    port_provided = False

    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if not a.startswith("--") and serve_dir is None:
            serve_dir = a
            i += 1
        elif a == "--dir" and i + 1 < len(sys.argv):
            serve_dir = sys.argv[i + 1]
            i += 2
        elif a == "--bind" and i + 1 < len(sys.argv):
            cli_bind = sys.argv[i + 1]
            bind_provided = True
            i += 2
        elif a == "--port" and i + 1 < len(sys.argv):
            try:
                cli_port = int(sys.argv[i + 1])
            except ValueError:
                Utils.print_error_and_exit(f"Invalid port number: {sys.argv[i + 1]}")
            port_provided = True
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

    # ----- resolve target directory -----
    if serve_dir is None:
        raw_path = Input.resolve_input_path(
            "./",
            prompt="Enter directory or index.html path",
            path_type="any",
        )
        target_dir = _resolve_dir(raw_path)
    else:
        target_dir = _resolve_dir(serve_dir)

    # ----- resolve bind / port -----
    if bind_provided and port_provided:
        _validate_bind(cli_bind)
        bind = cli_bind
        port = cli_port
    else:
        bind = cli_bind if bind_provided else _prompt_bind(cli_bind)
        _validate_bind(bind)
        port = cli_port if port_provided else _prompt_port(cli_port)
        if not quiet:
            quiet = _prompt_quiet()

    _run_server(target_dir, bind, port, url_path=url_path, quiet=quiet, open_browser=not no_open)


if __name__ == "__main__":
    raise sys.exit(main())
