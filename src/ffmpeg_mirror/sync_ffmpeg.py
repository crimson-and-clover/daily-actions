import datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from tenacity import retry, stop_after_attempt, wait_exponential
from urllib3.util.retry import Retry

from ffmpeg_mirror.config import (
    DOWNLOAD_URLS,
    GITHUB_OUTPUT_FILE,
    GITHUB_TOKEN,
    REPO,
    TAG_PREFIX,
    validate_config,
)


def get_session() -> requests.Session:
    """创建并配置支持自动重试的 Session"""
    session = requests.Session()
    retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504], allowed_methods=["POST", "GET"])

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
    )
    return session


session = get_session()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=1.0, max=10.0), reraise=False)
def get_downloaded_versions():
    """获取已有的以 ffmpeg-win- 开头的版本号"""
    url = f"https://api.github.com/repos/{REPO}/releases"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        response = session.get(url, headers=headers)
        response.raise_for_status()
        return [release["tag_name"].replace(TAG_PREFIX, "") for release in response.json() if release["tag_name"].startswith(TAG_PREFIX)]
    except Exception as e:
        print(f"无法获取已发布版本: {e}")
        return []


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=1.0, max=10.0), reraise=False)
def get_remote_version(url):
    """访问 url.ver 获取版本号"""
    ver_url = f"{url}.ver"
    try:
        res = session.get(ver_url)
        res.raise_for_status()
        return res.text.strip()
    except Exception as e:
        print(f"无法获取远程版本号 ({ver_url}): {e}")
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=2.0, max=15.0), reraise=True)
def download_file(url, version):
    """下载文件，并将文件名中的 'release' 替换为版本号"""
    original_filename = url.split("/")[-1]
    # 执行替换：ffmpeg-release-essentials.7z -> ffmpeg-7.1-essentials.7z
    new_filename = original_filename.replace("release", version)
    target_path = Path(new_filename)

    print(f"正在下载: {url} -> {target_path}")
    with session.get(url, stream=True) as r:
        r.raise_for_status()
        with target_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return str(target_path)


def main():
    validate_config()
    existing_versions = get_downloaded_versions()
    print(f"仓库中已存在版本: {existing_versions}")

    processed_files = []
    current_version = None

    for url in DOWNLOAD_URLS:
        remote_ver = get_remote_version(url)
        if not remote_ver:
            break

        if remote_ver in existing_versions:
            print(f"跳过版本 {remote_ver} (标签 {TAG_PREFIX}{remote_ver} 已存在)")
            break

        # 下载并重命名
        saved_file = download_file(url, remote_ver)
        processed_files.append(saved_file)
        current_version = remote_ver

    # 输出结果给 GitHub Actions
    if processed_files:
        tag_name = f"{TAG_PREFIX}{current_version}"
        tz_beijing = datetime.timezone(datetime.timedelta(hours=8))
        now_beijing = datetime.datetime.now(tz_beijing).strftime("%Y-%m-%d %H:%M:%S")

        # 写入环境变量文件 (下载的文件保存在当前工作目录，直接提供文件名即可)
        with GITHUB_OUTPUT_FILE.open("a", encoding="utf-8") as f:
            f.write(f"new_version={current_version}\n")
            f.write(f"tag_name={tag_name}\n")
            f.write("zip_files<<EOF\n")
            for p in processed_files:
                f.write(f"{p}\n")
            f.write("EOF\n")
            f.write(f"sync_time={now_beijing}\n")  # 输出北京时间
        print(f"任务完成。版本: {current_version}, 文件: {processed_files}")
    else:
        print("没有检测到新版本。")


if __name__ == "__main__":
    main()
