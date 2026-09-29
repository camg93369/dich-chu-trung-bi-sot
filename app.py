import re
import time
import io
import streamlit as st
from docx import Document
from google import genai
from google.genai import types
from google.genai.errors import APIError

# ==========================================
# CẤU HÌNH GIAO DIỆN STREAMLIT (Trắng - Đen)
# ==========================================
st.set_page_config(
    page_title="Công Cụ Dịch Sót Tiếng Trung",
    page_icon="📖",
    layout="wide"
)

# Custom CSS giao diện Đen - Trắng (Dark Theme Minimalist)
st.markdown("""
    <style>
    .stApp {
        background-color: #0e1117;
        color: #e0e0e0;
    }
    .stButton>button {
        background-color: #262730;
        color: #ffffff;
        border: 1px solid #4a4a4a;
        border-radius: 8px;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #ffffff;
        color: #000000;
        border-color: #ffffff;
    }
    .stDownloadButton>button {
        background-color: #1e3a8a;
        color: #ffffff;
        border: 1px solid #3b82f6;
        border-radius: 8px;
        font-weight: bold;
    }
    .stDownloadButton>button:hover {
        background-color: #2563eb;
        color: #ffffff;
    }
    </style>
""", unsafe_allow_html=True)

MODEL_NAME = "gemini-3.6-flash"
CHINESE_REGEX = re.compile(r"[\u4e00-\u9fa5]")

def contains_chinese(text: str) -> bool:
    return bool(CHINESE_REGEX.search(text))

def translate_batch_with_retry(texts: list[str], api_keys: list[str], current_key_idx: list[int], log_area) -> tuple[list[str], int]:
    prompt = (
        "Bạn là một dịch giả tiểu thuyết chuyên nghiệp. Hãy dịch các đoạn văn bản tiếng Trung "
        "dưới đây sang tiếng Việt mượt mà, văn phong tiểu thuyết.\n"
        "CUNG CẤP ĐÚNG ĐỊNH DẠNG: Trả về chính xác danh sách các đoạn dịch, mỗi đoạn nằm trên một dòng "
        "và bắt đầu bằng tiền tố '[DICH]: '. Không thêm lời mở đầu hay kết luận.\n\n"
    )
    for idx, t in enumerate(texts, 1):
        prompt += f"Đoạn {idx}: {t}\n"

    max_attempts = len(api_keys) * 2

    for attempt in range(1, max_attempts + 1):
        key_idx = current_key_idx[0]
        api_key = api_keys[key_idx]
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                ),
            )

            lines = response.text.strip().split("\n")
            translated_lines = [
                line.replace("[DICH]:", "").strip()
                for line in lines
                if line.startswith("[DICH]:")
            ]

            if len(translated_lines) == len(texts):
                return translated_lines, key_idx
            else:
                log_area.warning(f"⚠️ Số đoạn trả về không khớp ({len(translated_lines)}/{len(texts)}). Đang thử lại...")

        except APIError as e:
            log_area.error(f"⚠️ Key #{key_idx + 1} gặp lỗi API: {e.code if hasattr(e, 'code') else e}")
            current_key_idx[0] = (current_key_idx[0] + 1) % len(api_keys)
            log_area.info(f"🔄 Đã tự động chuyển sang Key #{current_key_idx[0] + 1}")
            time.sleep(2)
        except Exception as e:
            log_area.error(f"⚠️ Lỗi không xác định: {e}")
            current_key_idx[0] = (current_key_idx[0] + 1) % len(api_keys)
            time.sleep(3)

    log_area.error("❌ Không thể dịch batch này sau khi thử tất cả Keys. Giữ nguyên gốc.")
    return texts, current_key_idx[0]

# ==========================================
# GIAO DIỆN NGƯỜI DÙNG
# ==========================================
st.title("📖 Tool Dịch Sót Tiếng Trung (Gemini 3.6 Flash)")
st.caption("Giao diện Đen - Trắng tối giản, tự động xoay vòng API Keys")

st.divider()

# Sidebar: Cấu hình API Keys & Thông số
with st.sidebar:
    st.header("⚙️ Cấu hình API Keys")
    st.info("Nhập 3-4 API Keys (dạng AQ.Ab...) từ các Project khác nhau, mỗi key trên 1 dòng:")
    
    default_keys = ""
    )
    
    keys_input = st.text_area("Danh sách API Keys", value=default_keys, height=150)
    api_keys = [k.strip() for k in keys_input.split("\n") if k.strip()]

    st.header("🎛️ Tùy chỉnh tham số")
    batch_size = st.number_input("Số đoạn / Batch", min_value=1, max_value=20, value=5)
    delay_time = st.number_input("Thời gian chờ giữa các Batch (giây)", min_value=0, max_value=30, value=5)

# Main Content: Upload file
uploaded_file = st.file_uploader("Tải lên file Word (.docx) hoặc File văn bản (.txt)", type=["docx", "txt"])

if uploaded_file and api_keys:
    file_type = uploaded_file.name.split(".")[-1].lower()
    
    if st.button("🚀 Bắt đầu xử lý dịch sót"):
        log_area = st.empty()
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        current_key_idx = [0]
        output_buffer = io.BytesIO()

        if file_type == "docx":
            doc = Document(uploaded_file)
            target_paragraphs = [p for p in doc.paragraphs if p.text and contains_chinese(p.text)]
            total_found = len(target_paragraphs)

            if total_found == 0:
                st.success("✅ File Word không có đoạn nào chứa tiếng Trung!")
            else:
                st.info(f"🎯 Phát hiện {total_found} đoạn văn còn sót tiếng Trung.")
                
                total_batches = (total_found + batch_size - 1) // batch_size
                
                for i in range(0, total_found, batch_size):
                    batch_paras = target_paragraphs[i : i + batch_size]
                    batch_texts = [p.text for p in batch_paras]
                    current_batch_num = (i // batch_size) + 1

                    status_text.text(f"🔄 Đang xử lý Batch {current_batch_num}/{total_batches} với Key #{current_key_idx[0] + 1}...")

                    translated_texts, new_key_idx = translate_batch_with_retry(
                        batch_texts, api_keys, current_key_idx, log_area
                    )
                    current_key_idx[0] = new_key_idx

                    for p, translated in zip(batch_paras, translated_texts):
                        p.text = translated

                    progress_bar.progress(current_batch_num / total_batches)

                    if i + batch_size < total_found:
                        time.sleep(delay_time)

                doc.save(output_buffer)
                output_buffer.seek(0)
                
                st.success("🎉 Hoàn tất dịch!")
                
                # Nút tải về sáng lên sau khi hoàn thành
                st.download_button(
                    label="📥 Tải về File Word Đã Dịch (.docx)",
                    data=output_buffer,
                    file_name=f"dich_{uploaded_file.name}",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )

        elif file_type == "txt":
            content = uploaded_file.read().decode("utf-8")
            lines = content.split("\n")
            
            target_indices = [idx for idx, line in enumerate(lines) if line and contains_chinese(line)]
            total_found = len(target_indices)

            if total_found == 0:
                st.success("✅ File TXT không có đoạn nào chứa tiếng Trung!")
            else:
                st.info(f"🎯 Phát hiện {total_found} dòng còn sót tiếng Trung.")
                total_batches = (total_found + batch_size - 1) // batch_size

                for i in range(0, total_found, batch_size):
                    batch_indices = target_indices[i : i + batch_size]
                    batch_texts = [lines[idx] for idx in batch_indices]
                    current_batch_num = (i // batch_size) + 1

                    status_text.text(f"🔄 Đang xử lý Batch {current_batch_num}/{total_batches}...")

                    translated_texts, new_key_idx = translate_batch_with_retry(
                        batch_texts, api_keys, current_key_idx, log_area
                    )
                    current_key_idx[0] = new_key_idx

                    for idx, translated in zip(batch_indices, translated_texts):
                        lines[idx] = translated

                    progress_bar.progress(current_batch_num / total_batches)

                    if i + batch_size < total_found:
                        time.sleep(delay_time)

                result_txt = "\n".join(lines)
                
                st.success("🎉 Hoàn tất dịch!")
                
                # Nút tải về sáng lên sau khi hoàn thành
                st.download_button(
                    label="📥 Tải về File TXT Đã Dịch (.txt)",
                    data=result_txt,
                    file_name=f"dich_{uploaded_file.name}",
                    mime="text/plain"
                )