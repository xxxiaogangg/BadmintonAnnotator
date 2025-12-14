import cv2
import imageio
import os
import base64
import io

def create_gifs_and_divs(video_path, target_frames, output_txt, output_folder='output_gifs'):
    """
    从视频生成GIF，并生成对应的HTML div代码方便复制。
    """
    
    # 确保 target_frames 是列表
    if isinstance(target_frames, int):
        target_frames = [target_frames]
        
    # 创建输出目录
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # 打开视频
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"无法打开视频: {video_path}")
        return
        
    # 获取文件名信息
    video_name_with_ext = os.path.basename(video_path)
    video_name = os.path.splitext(video_name_with_ext)[0]

    # 获取视频总帧数
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"视频加载成功: {video_name}")
    print(f"总帧数: {total_frames}")

    # 用于存储生成的 HTML 代码片段
    html_snippets = []

    # 遍历每一个目标帧
    for target in target_frames:
        start_frame = target - 14
        end_frame = target + 15
        
        # 边界检查
        if start_frame < 0: start_frame = 0
        if end_frame >= total_frames: end_frame = total_frames - 1
            
        print(f"处理帧 {target}: [{start_frame} - {end_frame}]")

        frames_list = []
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        for i in range(start_frame, end_frame + 1):
            ret, frame = cap.read()
            if not ret: break
            
            # 转 RGB 并缩放
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # 缩放以减小体积，根据需要开启
            # rgb_frame = cv2.resize(rgb_frame, (480, 270)) 
            frames_list.append(rgb_frame)

        # 生成 GIF 和 DIV
        if len(frames_list) > 0:
            gif_filename = f"{video_name}_frame_{target}.gif"
            output_path = os.path.join(output_folder, gif_filename)
            
            # 1. 保存 GIF
            imageio.mimsave(output_path, frames_list, duration=0.033, loop=0)
            print(f"  -> GIF生成成功: {output_path}")
                
            if output_txt:
                # 2. 在内存中生成 GIF（不保存到硬盘）
                # 使用 io.BytesIO 作为内存缓冲区
                buffer = io.BytesIO()
                # duration=0.033 约等于 30fps
                imageio.mimsave(buffer, frames_list, format='GIF', duration=0.033, loop=0)
                
                # 3. 转 Base64 字符串
                gif_data = buffer.getvalue()
                b64_str = base64.b64encode(gif_data).decode('utf-8')
                
                # 4. 拼接 HTML 字符串
                # data:image/gif;base64, 是固定前缀
                img_src = f"data:image/gif;base64,{b64_str}"
                
                div_code = f"""
            <!-- Base64 卡片: 帧 {target} -->
            <div class="gif-card">
                <img src="{img_src}" alt="帧 {target}">
                <div class="gif-info">
                    <div class="gif-title">示例: 帧 {target}</div>
                    <div class="gif-desc">
                        在此处添加描述（该图片已内嵌，无需外部文件）
                    </div>
                </div>
            </div>
                """
                html_snippets.append(div_code)
                print(" -> 完成")
                    

    cap.release()

    # 将生成的 DIV 代码写入文本文件
    if output_txt:
        if html_snippets:
            with open(output_txt, "w", encoding="utf-8") as f:
                f.write("\n".join(html_snippets))
            print(f"\n成功！HTML代码已保存到: {output_txt}")
            print("请打开该文件，复制内容到你的 HTML 指南中。")
        else:
            print("\n未生成任何内容。")

# ================= 使用示例 =================
if __name__ == "__main__":
    # 1. 替换成你的视频路径
    my_video = "/home/gang/gang_study/Data/Badminton_data/InHome/BWF/女单/2025年韩国羽毛球公开赛-山口茜vs安洗莹.mp4" 
    # 2. 目标帧号列表
    # 25全英女单-安vs王 Set3 rally12 144921 击球前帧数缺失
    targets = [16560, 28089, 29925, 39596, 68605, 72991, 144921] 
    targets = [13277, 14809, 23351, 26468, 27640, 28397, 33460, 40044, 45586, 53442, 65622, 66766, 79325]
    
    # 3. 运行
    create_gifs_and_divs(my_video, targets, output_txt=0)
