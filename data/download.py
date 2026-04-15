import os
import urllib.request
import urllib.error
import urllib.parse

# 预设的测试视频列表 (涵盖不同分辨率和大小)
video_urls = [
    # W3Schools 和 Cloudinary 提供的可靠测试视频
    "https://www.w3schools.com/html/mov_bbb.mp4",
    "https://res.cloudinary.com/demo/video/upload/glide-over-coastal-beach.mp4",
    "https://res.cloudinary.com/demo/video/upload/v1/dog.mp4",
    
    # Github 上的公开测试视频素材 (Intel IoT 示例)
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/person-bicycle-car-detection.mp4",
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/bottle-detection.mp4",
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/car-detection.mp4",
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/head-pose-face-detection-female.mp4",
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/head-pose-face-detection-male.mp4",
    "https://github.com/intel-iot-devkit/sample-videos/raw/master/store-aisle-detection.mp4",
    
    # 更多链接可按需添加...
]

# 将资源下载到 data/video_assets 目录下
base_dir = os.path.dirname(os.path.abspath(__file__))
assets_dir = os.path.join(base_dir, "video_assets")
os.makedirs(assets_dir, exist_ok=True)

print(f"🚀 开始批量下载 所有 {len(video_urls)} 个视频素材...")
for i, url in enumerate(video_urls):
    # 从 URL 提取原始文件名
    parsed_path = urllib.parse.urlparse(url).path
    original_filename = os.path.basename(parsed_path)
    if not original_filename:
        original_filename = f"test_video_{i+1}.mp4"
        
    filename = os.path.join(assets_dir, original_filename)
    try:
        # 添加 User-Agent 避免被服务器拒绝 (HTTP 403)
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req) as response, open(filename, 'wb') as out_file:
            data = response.read() # Read the whole file
            out_file.write(data)
        print(f"✅ 已完成: {filename}")
    except Exception as e:
        print(f"❌ 失败: {url} | 错误: {e}")

print(f"\n✨ 所有素材已存入 '{assets_dir}' 文件夹。")