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
    page_title="Công Cụ Sửa Chữ Trung Sót",
    page_icon="📖",
    layout="wide"
)

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
CHINESE_REGEX = re.compile(r"[\u4e00-\u9fa5]+")

def extract_chinese_words(text: str) -> list[str]:
    """Trích xuất tất cả các từ/cụm từ tiếng Trung có trong đoạn văn."""
    return list(set(CHINESE_REGEX.findall(text)))

def translate_terms(terms: list[str], api_keys: list[str], current_key_idx: list[int], log_area) -> dict[str, str]:
    """Gửi danh sách các từ tiếng Trung bị sót để Gemini dịch sang tiếng Việt."""
    prompt = (
        "Bạn là dịch giả tiểu thuyết. Hãy dịch chính xác các từ/cụm từ tiếng Trung dưới đây sang tiếng Việt "
        "(chuẩn Hán Việt hoặc ngữ cảnh tiểu thuyết).\n"
        "ĐỊNH DẠNG TRẢ VỀ CHÍNH XÁC:\n"
        "Mỗi từ dịch nằm trên 1 dòng theo dạng: 'từ_tiếng_trung -> từ_tiếng_việt'\n"
        "Ví dụ: 'Nam Sủng -> Nam Sủng'\n\n"
        "Danh sách từ cần dịch:\n"
    )
    for t in terms:
        prompt += f"- {t}\n"

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
                    temperature=0.1,
                ),
            )

            raw_text = response.text.strip() if response.text else ""
            mapping = {}
            for line in raw_text.split("\n"):
                if "->" in line:
                    parts = line.split("->", 1)
                    cn_word = parts[0].replace("-", "").strip()
                    vi_word = parts[1].strip()
                    if cn_word and vi_word:
                        mapping[cn_word] = vi_word

            if mapping:
                return mapping, key_idx

        except APIError as e:
            log_area.warning(f"⚠️ Key #{key_idx + 1} gặp lỗi API. Đang tự động đổi Key...")
            current_key_idx[0] = (current_key_idx[0] + 1) % len(api_keys)
            time.sleep(1)
        except Exception:
            current_key_idx[0] = (current_key_idx[0] + 1) % len(api_keys)
            time.sleep(1)

    return {}, current_key_idx[0]

# ==========================================
# GIAO DIỆN NGƯỜI DÙNG
# ==========================================
st.title("📖 Tool Sửa Từ Tiếng Trung Sót (Gemini 3.6 Flash)")
st.caption("Giữ nguyên 100% câu chữ tiếng Việt gốc, chỉ dịch và thay thế đúng các chữ Trung bị sót.")

st.divider()

# Sidebar: Cấu hình API Keys & Thông số
with st.sidebar:
    st.header("⚙️ Cấu hình API Keys")
    st.info("Nhập các API Keys (dạng AQ.Ab...), mỗi key trên 1 dòng:")
    
    keys_input = st.text_area("Danh sách API Keys", value="", height=180, placeholder="AQ.Ab...\nAQ.Ab...\nAQ.Ab...")
    api_keys = [k.strip() for k in keys_input.split() if k.strip().startswith("AQ.Ab")]

    st.header("🎛️ Tùy chỉnh tham số")
    batch_terms_count = st.number_input("Số từ gom dịch / 1 lần gọi", min_value=5, max_value=50, value=20)
    delay_time = st.number_input("Thời gian nghỉ (giây)", min_value=0.0, max_value=10.0, value=1.0, step=0.5)

# Main Content: Upload file
uploaded_file = st.file_uploader("Tải lên file Word (.docx) hoặc File văn bản (.txt)", type=["docx", "txt"])

if uploaded_file:
    if not api_keys:
        st.warning("⚠️ Vui lòng nhập ít nhất 1 API Key hợp lệ ở thanh bên trái!")
    else:
        file_type = uploaded_file.name.split(".")[-1].lower()
        
        if st.button("🚀 Bắt đầu quét & sửa chữ sót"):
            log_area = st.empty()
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            current_key_idx = [0]
            output_buffer = io.BytesIO()

            if file_type == "docx":
                doc = Document(uploaded_file)
                
                # BƯỚC 1: Quét toàn bộ từ tiếng Trung bị sót trong file
                all_chinese_terms = set()
                target_paragraphs = []
                for p in doc.paragraphs:
                    if p.text:
                        terms = extract_chinese_words(p.text)
                        if terms:
                            target_paragraphs.append(p)
                            all_chinese_terms.update(terms)

                unique_terms = list(all_chinese_terms)
                total_terms = len(unique_terms)

                if total_terms == 0:
                    st.success("✅ File Word hoàn toàn sạch sẽ, không có chữ Trung nào bị sót!")
                else:
                    st.info(f"🎯 Phát hiện {total_terms} từ/cụm từ tiếng Trung bị dính rải rác trong {len(target_paragraphs)} đoạn.")
                    
                    # BƯỚC 2: Gom các từ tiếng Trung gửi Gemini dịch sang tiếng Việt
                    translation_dict = {}
                    total_batches = (total_terms + batch_terms_count - 1) // batch_terms_count

                    for i in range(0, total_terms, batch_terms_count):
                        batch_terms = unique_terms[i : i + batch_terms_count]
                        current_batch_num = (i // batch_terms_count) + 1

                        status_text.text(f"🔄 Đang dịch cụm từ đợt {current_batch_num}/{total_batches} bằng Key #{current_key_idx[0] + 1}...")

                        mapping, new_key_idx = translate_terms(
                            batch_terms, api_keys, current_key_idx, log_area
                        )
                        current_key_idx[0] = new_key_idx
                        translation_dict.update(mapping)

                        progress_bar.progress(current_batch_num / total_batches)

                        if delay_time > 0 and i + batch_terms_count < total_terms:
                            time.sleep(delay_time)

                    # BƯỚC 3: Thay thế các từ đã dịch trực tiếp vào đúng vị trí cũ trong đoạn
                    for p in target_paragraphs:
                        text_content = p.text
                        for cn_word, vi_word in translation_dict.items():
                            if cn_word in text_content:
                                text_content = text_content.replace(cn_word, vi_word)
                        p.text = text_content

                    doc.save(output_buffer)
                    output_buffer.seek(0)
                    
                    st.success("🎉 Hoàn tất! Đã thay thế sạch sẽ tất cả chữ Trung bị sót.")
                    
                    st.download_button(
                        label="📥 Tải về File Word Đã Sửa (.docx)",
                        data=output_buffer,
                        file_name=f"da_sua_{uploaded_file.name}",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )

            elif file_type == "txt":
                content = uploaded_file.read().decode("utf-8")
                lines = content.split("\n")
                
                all_chinese_terms = set()
                target_indices = []
                for idx, line in enumerate(lines):
                    if line:
                        terms = extract_chinese_words(line)
                        if terms:
                            target_indices.append(idx)
                            all_chinese_terms.update(terms)

                unique_terms = list(all_chinese_terms)
                total_terms = len(unique_terms)

                if total_terms == 0:
                    st.success("✅ File TXT hoàn toàn sạch sẽ, không có chữ Trung bị sót!")
                else:
                    st.info(f"🎯 Phát hiện {total_terms} từ/cụm từ tiếng Trung rải rác.")
                    
                    translation_dict = {}
                    total_batches = (total_terms + batch_terms_count - 1) // batch_terms_count

                    for i in range(0, total_terms, batch_terms_count):
                        batch_terms = unique_terms[i : i + batch_terms_count]
                        current_batch_num = (i // batch_terms_count) + 1

                        status_text.text(f"🔄 Đang dịch đợt {current_batch_num}/{total_batches} bằng Key #{current_key_idx[0] + 1}...")

                        mapping, new_key_idx = translate_terms(
                            batch_terms, api_keys, current_key_idx, log_area
                        )
                        current_key_idx[0] = new_key_idx
                        translation_dict.update(mapping)

                        progress_bar.progress(current_batch_num / total_batches)

                        if delay_time > 0 and i + batch_terms_count < total_terms:
                            time.sleep(delay_time)

                    # Thay thế trực tiếp vào dòng
                    for idx in target_indices:
                        line_content = lines[idx]
                        for cn_word, vi_word in translation_dict.items():
                            if cn_word in line_content:
                                line_content = line_content.replace(cn_word, vi_word)
                        lines[idx] = line_content

                    result_txt = "\n".join(lines)
                    
                    st.success("🎉 Hoàn tất! Đã thay thế sạch sẽ tất cả chữ Trung bị sót.")
                    
                    st.download_button(
                        label="📥 Tải về File TXT Đã Sửa (.txt)",
                        data=result_txt,
                        file_name=f"da_sua_{uploaded_file.name}",
                        mime="text/plain"
                    )
