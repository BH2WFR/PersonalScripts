import sys
import os
import socket
import subprocess
import platform
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from my_utils import *
from datetime import datetime

# pip install boto3
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError

#* 地址信息
BUCKET_NAME = os.getenv("ZL-IP-ADDRESS-S3-BUCKET") or "ip-address-1316772733"
ENDPOINT_URL = os.getenv("ZL-IP-ADDRESS-S3-ENDPOINT") or "https://cos.ap-beijing.myqcloud.com"
ACCESS_ID = os.getenv("ZL-IP-ADDRESS-S3-ID") or "AKIDQxbDgyMfolZCwc6QgzDNZeWEl5C6nGVX"
ACCESS_KEY = os.getenv("ZL-IP-ADDRESS-S3-SECRET") or "taBpJnAMMCwiM1fFfFhx0rVv761iDVaS"


print(f"{FLYellow}=========== UPLOAD IP ADDRESS INFO TO S3 BUCKET ==========={CRst}")


#============ 环境变量检查 ===========
if not ACCESS_ID:
    print(f"{FLRed}ERROR: Environment variable 'ZL-IP-ADDRESS-S3-ID' not set. EXIT...{CRst}\n")
    sys.exit(1)
if not ACCESS_KEY:
    print(f"{FLRed}ERROR: Environment variable 'ZL-IP-ADDRESS-S3-SECRET' not set. EXIT...{CRst}\n")
    sys.exit(1)


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
    sys.exit(1)

if result.returncode != 0:
    print(f"{FLRed}ERROR: Failed to run network command: {result.stderr.strip()}{CRst}\n")
    sys.exit(1)

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
    print(f"{FLRed}ERROR: Invalid credentials. Check ZL-IP-ADDRESS-S3-ID and ZL-IP-ADDRESS-S3-SECRET. EXIT...{CRst}\n")
    sys.exit(1)
except ClientError as e:
    print(f"{FLRed}ERROR: Upload failed: {e}{CRst}\n")
    sys.exit(1)
