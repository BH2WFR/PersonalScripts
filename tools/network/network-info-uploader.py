#!/usr/bin/env python3
"""Implementation notes.

Read module-owned credentials through ConfigStore/EncryptedValue; never
include secrets in the uploaded diagnostic output or console messages.
"""


import sys
import os
import socket
import subprocess
import platform
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *

HELP = f"""{FLYellow}NETWORK INFO UPLOADER{CRst}

Upload local network-interface information to an S3-compatible bucket.
The upload includes network addresses and interface details.

{FLYellow}Requirements:{CRst}
  boto3, PyYAML, cryptography; ipconfig, ip or ifconfig for the current OS.
  Configure the upload-ipaddress section in the shared user config.yaml.

{FLYellow}Usage:{CRst}
  python network-info-uploader.py
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)

from datetime import datetime

UPLOAD_ENCRYPTION_KEY = b"PwMoFseUfbszDg3JsbCkGEvKgvFbW9uWKOwmkD-sMZ8="

def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:

        print(HELP)
        return 0

    Console.print_banner("NETWORK INFO UPLOADER")

    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError, NoCredentialsError
    except ImportError as exc:
        print(f"{FLRed}Missing dependency: {exc.name}{CRst}")
        print(f"{FGray}Install: pip install boto3 PyYAML cryptography{CRst}")
        return 1

    try:
        settings = ConfigStore().load().get("upload-ipaddress", {})
        if not isinstance(settings, dict):
            raise ValueError("upload-ipaddress must be a mapping")
        settings = EncryptedValue.decrypt_tree(settings, UPLOAD_ENCRYPTION_KEY)
    except (OSError, ValueError) as exc:
        print(f"{FLRed}ERROR: Cannot read user configuration: {exc}{CRst}")
        return 1
    BUCKET_NAME = settings.get("bucket")
    ENDPOINT_URL = settings.get("endpoint")
    ACCESS_ID = settings.get("access-id")
    ACCESS_KEY = settings.get("secret")

    #============ Configuration validation ===========
    _required = [
        ("bucket", BUCKET_NAME),
        ("endpoint", ENDPOINT_URL),
        ("access-id", ACCESS_ID),
        ("secret", ACCESS_KEY),
    ]
    for _name, _val in _required:
        if not isinstance(_val, str) or not _val:
            print(f"{FLRed}ERROR: Configuration value '{_name}' is missing or invalid. EXIT...{CRst}\n")
            return 1

    #============ 获取计算机网络信息 ===========
    computer_name = socket.gethostname()
    print(f"{FLYellow}Computer name: {computer_name}{CRst}")

    print(f"{FLYellow}  -> collecting network info...{CRst}")
    command = ""
    if sys.platform == "win32":
        result = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True, encoding="utf-8")
        command = "ipconfig /all"
    elif sys.platform == "darwin" or sys.platform.startswith("linux"):
        # 优先使用 ip addr，不存在则回退到 ifconfig
        ip_path = shutil.which("ip")
        if ip_path:
            result = subprocess.run([ip_path, "addr"], capture_output=True, text=True, encoding="utf-8")
            command = "ip addr"
        else:
            result = subprocess.run(["ifconfig"], capture_output=True, text=True, encoding="utf-8")
            command = "ifconfig"
    else:
        print(f"{FLRed}ERROR: Unsupported platform: {sys.platform}. EXIT...{CRst}\n")
        return 1

    if result.returncode != 0:
        print(f"{FLRed}ERROR: Failed to run network command: {result.stderr.strip()}{CRst}\n")
        return 1

    network_info = result.stdout
    print(f"{FLGreen}  -> network info collected ({len(network_info)} chars){CRst}, command used: {FGray}{command}{CRst}")

    #============ 上传到 COS ===========
    s3_key = f"{computer_name}.txt"
    print(f"{FLYellow}  -> uploading to COS{CRst}: {FLCyan}{s3_key}{CRst}")

    ## 文件第一行附上时间和系统信息
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os_str = f"System: {platform.system()} {platform.release()}\nKernel: {platform.version()}\nArch: {platform.machine()}\nHostname: {platform.node()}"
    network_info = f"Timestamp: {timestamp}\n{os_str}\n\n{network_info}"
    print(f"{FLGreen}  -> timestamp{CRst}: {FGray}{timestamp}{CRst}")
    print(f"{FLGreen}  -> OS info{CRst}: {FGray}{os_str.replace(chr(10), '; ')}{CRst}")

    try:
        s3_client = boto3.client(
            "s3",
            endpoint_url=ENDPOINT_URL,
            aws_access_key_id=ACCESS_ID,
            aws_secret_access_key=ACCESS_KEY,
            config=Config(s3={"addressing_style": "virtual"}),
        )
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=network_info.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )
        print(f"{FLGreen}Upload SUCCESS{CRst}: {FGray}{ENDPOINT_URL}/{BUCKET_NAME}/{s3_key}{CRst}\n")
    except NoCredentialsError:
        print(f"{FLRed}ERROR: Invalid credentials. Check access-id and secret in user config.yaml. EXIT...{CRst}\n")
        return 1
    except ClientError as e:
        print(f"{FLRed}ERROR: Upload failed: {e}{CRst}\n")
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
