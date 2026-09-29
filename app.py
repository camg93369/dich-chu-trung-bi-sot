import re
import time
import io
import json
import streamlit as st
from docx import Document
from google import genai
from google.genai import types
from google.genai.errors import APIError

# ==========================================
# CẤU HÌNH GIAO DIỆN STREAMLIT (Trắng - Đen)
# ==========================================
st.set_page_config(
    page_title="Tool Sửa Từ Tiếng Trung Sót",
    page_icon="📖",
    layout="wide"
)

# Custom CSS: Hiển thị tự động ngắt dòng đẹp mắt cho API Key
st.markdown("""
    <style>
    [data-testid="stSidebar"] {
        min-width: 420px !important;
        max-width: 420px !important;
    }
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
    
    /* Cho phép chữ ngắt dòng bình thường để thấy trọn vẹn Key */
    textarea[aria-label="Danh sách API Keys"] {
        word-break: break-all !important;
        font-family: monospace !important;
    }
    </style>
""", unsafe_allow_html=True)

MODEL_NAME = "gemini-3.6-flash"
CHINESE_REGEX = re.compile(r"[\u4e00-\u9fa5]+")

def extract_chinese_words(text: str) -> list[str]:
    return list(set(CHINESE_REGEX.findall(text)))

def translate_terms(terms: list[str], api_keys: list[str], current_key_idx: list[int], log_area) -> tuple[dict[str, str], int]:
    sample_json = json.dumps({terms[0]: "dịch_việt"}, ensure_ascii=False) if terms else "{}"
    
    prompt = (
        "Bạn là một dịch giả tiểu thuyết chuyên nghiệp. Hãy dịch các từ/cụm từ tiếng Trung dưới đây sang tiếng Việt "
        "(ưu tiên chuẩn Hán Việt hoặc từ ngữ phù hợp văn phong tiểu thuyết).\n"
        "TRẢ VỀ KẾT QUẢ DƯỚI DẠNG CHUỖI JSON DUY NHẤT (không thêm lời mở đầu hay kết luận):\n"
        f"Mẫu: {sample_json}\n\n"
        "Danh sách từ cần dịch:\n" + "\n".join(terms)
    )

    max_attempts = len(api_keys) * 3

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
            raw_text = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
            raw_text = re.sub(r"^```\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text).strip()

            try:
                mapping = json.loads(raw_text)
                if isinstance(mapping, dict) and len(mapping) > 0:
                    return mapping, key_idx
            except json.JSONDecodeError:
                mapping = {}
                for line in raw_text.split("\n"):
                    if ":" in line or "->" in line:
                        delim = "->" if "->" in line else ":"
                        parts = line.split(delim, 1)
                        cn = parts[0].replace('"', '').replace("'", "").strip()
                        vi = parts[1].replace('"', '').replace("'", "").replace(",", "").strip()
                        if cn and vi:
                            mapping[cn] = vi
                if len(mapping) > 0:
                    return mapping, key_idx

            log_area.warning(f"⚠️ Key #{key_idx + 1}: Format trả về chưa đúng, đang thử lại...")

        except APIError as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                log_area.warning(f"⚠️ Key #{key_idx + 1} chạm giới hạn (Lỗi 429). Đang chờ 5 giây và chuyển Key #{((key_idx + 1) % len(api_keys)) + 1}...")
                time.sleep(5)
            else:
                log_area.warning(f"⚠️ Key #{key_idx + 1} báo lỗi API. Đang đổi sang Key tiếp theo...")
                time.sleep(2)
            current_key_idx[0] = (current_key_idx[0] + 1) % len(api_keys)
        except Exception as e:
            log_area.warning(f"⚠️ Sự cố kết nối Key #{key_idx + 1}. Đang tự động đổi Key...")
            current_key_idx[0] = (current_key_idx[0] + 1) % len(api_keys)
            time.sleep(2)

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
    
    keys_input = st.text_area("Danh sách API Keys", value="", height=200, placeholder="AQ.Ab...\nAQ.Ab...\nAQ.Ab...")
    # Lọc và làm sạch danh sách Key chuẩn 100%
    api_keys = [k.strip() for k in keys_input.split() if k.strip()]

    st.header("🎛️ Tùy chỉnh tham số")
    batch_terms_count = st.number_input("Số từ gom dịch / 1 lần gọi", min_value=5, max_value=50, value=20)
    delay_time = st.number_input("Thời gian nghỉ giữa các đợt (giây)", min_value=1.0, max_value=15.0, value=3.0, step=0.5)

# Main Content: Upload file
uploaded_file = st.file_uploader("Tải lên file Word (.docx) hoặc File văn bản (.txt)", type=["docx", "txt"])

if uploaded_file:
    if not api_keys:
        st.warning("⚠️ Vui lòng nhập ít nhất 1 API Key ở thanh bên trái!")
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
                    st.info(f"🎯 Phát hiện {total_terms} từ/cụm từ tiếng Trung rải rác.")
                    
                    translation_dict = {}
                    total_batches = (total_terms + batch_terms_count - 1) // batch_terms_count

                    for i in range(0, total_terms, batch_terms_count):
                        batch_terms = unique_terms[i : i + batch_terms_count]
                        current_batch_num = (i // batch_terms_count) + 1

                        status_text.text(f"🔄 Đang dịch đợt {current_batch_num}/{total_batches} ({len(batch_terms)} từ) bằng Key #{current_key_idx[0] + 1}...")

                        mapping, new_key_idx = translate_terms(
                            batch_terms, api_keys, current_key_idx, log_area
                        )
                        current_key_idx[0] = new_key_idx
                        translation_dict.update(mapping)

                        progress_bar.progress(current_batch_num / total_batches)

                        if delay_time > 0 and i + batch_terms_count < total_terms:
                            time.sleep(delay_time)

                    if not translation_dict:
                        st.error("❌ Không lấy được bản dịch. Vui lòng kiểm tra lại API Key!")
                    else:
                        for p in target_paragraphs:
                            text_content = p.text
                            for cn_word, vi_word in translation_dict.items():
                                if cn_word in text_content:
                                    text_content = text_content.replace(cn_word, vi_word)
                            p.text = text_content

                        doc.save(output_buffer)
                        output_buffer.seek(0)
                        
                        st.success(f"🎉 Hoàn tất! Đã thay thế thành công {len(translation_dict)} cụm từ bị sót.")
                        
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
                    st.info(f"🎯 Phát hiện {total_terms} từ/cụm từ tiếng Trung rải rác trong file TXT.")
                    
                    translation_dict = {}
                    total_batches = (total_terms + batch_terms_count - 1) // batch_terms_count

                    for i in range(0, total_terms, batch_terms_count):
                        batch_terms = unique_terms[i : i + batch_terms_count]
                        current_batch_num = (i // batch_terms_count) + 1

                        status_text.text(f"🔄 Đang dịch đợt {current_batch_num}/{total_batches} ({len(batch_terms)} từ) bằng Key #{current_key_idx[0] + 1}...")

                        mapping, new_key_idx = translate_terms(
                            batch_terms, api_keys, current_key_idx, log_area
                        )
                        current_key_idx[0] = new_key_idx
                        translation_dict.update(mapping)

                        progress_bar.progress(current_batch_num / total_batches)

                        if delay_time > 0 and i + batch_terms_count < total_terms:
                            time.sleep(delay_time)

                    if not translation_dict:
                        st.error("❌ Không lấy được bản dịch. Vui lòng kiểm tra lại API Key!")
                    else:
                        for idx in target_indices:
                            line_content = lines[idx]
                            for cn_word, vi_word in translation_dict.items():
                                if cn_word in line_content:
                                    line_content = line_content.replace(cn_word, vi_word)
                            lines[idx] = line_content

                        result_txt = "\n".join(lines)
                        
                        st.success(f"🎉 Hoàn tất! Đã thay thế thành công {len(translation_dict)} cụm từ bị sót.")
                        
                        st.download_button(
                            label="📥 Tải về File TXT Đã Sửa (.txt)",
                            data=result_txt,
                            file_name=f"da_sua_{uploaded_file.name}",
                            mime="text/plain"
                        )
