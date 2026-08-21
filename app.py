import streamlit as st
from PIL import Image
import os
import shutil
import tempfile
import zipfile
import re
import gc
from concurrent.futures import ThreadPoolExecutor

Image.MAX_IMAGE_PIXELS = None
VALID_EXTS = ('.png', '.jpg', '.jpeg', '.webp')

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def process_single_chapter(chap_name, image_paths, output_folder, max_height, quality):
    if not image_paths:
        return chap_name, 0

    chap_output_dir = os.path.join(output_folder, chap_name)
    os.makedirs(chap_output_dir, exist_ok=True)

    try:
        with Image.open(image_paths[0]) as first_img:
            target_w = first_img.width
    except Exception:
        target_w = 800

    current_strip = []
    current_height = 0
    part_idx = 1
    slices_count = 0

    def flush_strip():
        nonlocal current_strip, current_height, part_idx, slices_count
        if not current_strip:
            return
        
        canvas = Image.new('RGB', (target_w, current_height), (255, 255, 255))
        y = 0
        for img in current_strip:
            canvas.paste(img, (0, y))
            y += img.height
            img.close()
        
        suffix = f"_p{part_idx}" if part_idx > 1 or len(image_paths) > len(current_strip) else ""
        out_path = os.path.join(chap_output_dir, f"{chap_name}{suffix}.jpg")
        canvas.save(out_path, format='JPEG', quality=quality, optimize=True)
        canvas.close()

        current_strip = []
        current_height = 0
        part_idx += 1
        slices_count += 1
        gc.collect()

    for p in image_paths:
        try:
            im = Image.open(p).convert('RGB')
            if im.width != target_w:
                new_h = int(im.height * (target_w / im.width))
                im = im.resize((target_w, new_h), Image.Resampling.BILINEAR)

            if current_height + im.height > max_height and current_strip:
                flush_strip()

            current_strip.append(im)
            current_height += im.height
        except Exception:
            continue

    if current_strip:
        flush_strip()

    return chap_name, slices_count

st.set_page_config(page_title="Ultra Raw Stitcher", layout="centered", page_icon="⚡")
st.title("⚡ Ultra Batch Raw Stitcher")
st.caption("Ghép raw manga/manhwa đa luồng song song - Tối ưu chống tràn RAM")

st.sidebar.header("⚙️ Cấu hình xuất")
max_height_input = st.sidebar.number_input(
    "Chiều cao tối đa 1 trang (px):",
    min_value=5000,
    max_value=60000,
    value=25000,
    step=2000
)
jpg_quality = st.sidebar.slider("Chất lượng JPG:", 70, 95, 88)
thread_count = st.sidebar.selectbox("Số luồng xử lý song song:", [2, 3, 4], index=1)

uploaded_file = st.file_uploader("Kéo thả file .ZIP raw:", type=["zip"])

if uploaded_file and st.button("🚀 Bắt đầu ghép đa luồng", type="primary"):
    progress_bar = st.progress(0)
    status_text = st.empty()

    temp_dir = tempfile.mkdtemp()
    extracted_dir = os.path.join(temp_dir, "extracted")
    output_dir = os.path.join(temp_dir, "output")
    os.makedirs(extracted_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    try:
        status_text.text("📦 Đang giải nén dữ liệu vào bộ đệm...")
        with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
            zip_ref.extractall(extracted_dir)

        chapters = {}
        for root, _, files in os.walk(extracted_dir):
            rel_path = os.path.relpath(root, extracted_dir)
            if rel_path == "." or rel_path.startswith("__MACOSX"):
                continue
            
            valid_imgs = [os.path.join(root, f) for f in files if f.lower().endswith(VALID_EXTS)]
            if valid_imgs:
                chap_name = os.path.basename(root)
                chapters[chap_name] = sorted(valid_imgs, key=natural_sort_key)

        chap_keys = sorted(list(chapters.keys()), key=natural_sort_key)
        total_chaps = len(chap_keys)

        if total_chaps == 0:
            st.error("❌ Không tìm thấy thư mục chap bên trong file ZIP.")
            st.stop()

        status_text.text(f"🚀 Đang chạy {thread_count} luồng song song cho {total_chaps} chap...")

        completed = 0
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [
                executor.submit(
                    process_single_chapter,
                    chap,
                    chapters[chap],
                    output_dir,
                    max_height_input,
                    jpg_quality
                )
                for chap in chap_keys
            ]

            for future in futures:
                chap_name, count = future.result()
                completed += 1
                progress_bar.progress(completed / total_chaps)
                status_text.text(f"Đã xong [{completed}/{total_chaps}]: {chap_name}")
                gc.collect()

        status_text.text("🗜️ Đang đóng gói kết quả...")
        final_zip_path = os.path.join(temp_dir, f"stitched_{uploaded_file.name}")
        shutil.make_archive(final_zip_path.replace(".zip", ""), 'zip', output_dir)

        status_text.text("✨ Hoàn tất toàn bộ!")
        st.success(f"🎉 Đã ghép xong toàn bộ {total_chaps} chap!")

        with open(final_zip_path, "rb") as f:
            st.download_button(
                label="📥 Tải xuống File ZIP hoàn chỉnh",
                data=f.read(),
                file_name=f"stitched_{uploaded_file.name}",
                mime="application/zip",
                type="primary"
            )

    except Exception as e:
        st.error(f"Lỗi: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
