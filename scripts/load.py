# -*- coding: utf-8 -*-
"""
Batch Typhoon OCR Extractor (TH) — ultra verbose progress
---------------------------------------------------------
- tqdm ซ้อน 2 ชั้น: ชั้นนอก = ไฟล์ทั้งหมด, ชั้นใน = ความคืบหน้าหน้า (pages) ของไฟล์นั้น
- PROBE 5 หน้าแรกเพื่อเช็คสภาพ API
- Adaptive chunk: เริ่ม 25 → ลดเป็น 12 → 10 ถ้าช้า/ล้มเหลว
- Timeout + Retry + Exponential backoff
- Heartbeat ระหว่าง requests.post() (กันความรู้สึกค้าง): พิมพ์ทุก ๆ 2 วินาที
- ถ้าไฟล์ใดล้มเหลว → ข้ามไฟล์นั้น แต่ไฟล์อื่นทำต่อ
- บันทึกผลไว้ที่ data/processed/<stem>_typhoon.txt
"""

import time
import json
import requests
import threading
from pathlib import Path
import pdfplumber
from tqdm import tqdm
from config import Config

# ---------- CONFIGURATION CONSTANTS ----------
# 
CHUNK_SIZE = 25
MIN_CHUNK_SIZE = 10
PROBE_PAGES = 5
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 120
RETRIES = 3
BACKOFF = 2.0  # 2s, 4s, 8s ...
HEARTBEAT_INTERVAL = 2 # วินาที
VERBOSE = True # เปิดข้อความละเอียด 

# ---------- HEARTBEAT CLASS ----------
class Heartbeat:
    """
    แสดงสัญญาณว่ากำลังทำงานอยู่ระหว่างรอ network I/O
    จะพิมพ์ทุก ๆ interval วินาทีด้วย tqdm.write() เพื่อไม่ชนกับ progress bar
    """
    def __init__(self, label: str, interval: float = HEARTBEAT_INTERVAL):
        self.label = label
        self.interval = interval
        self._stop = threading.Event()
        self._thr = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        start = time.time()
        spinner = ["⏳", "⌛", "🔄", "🛰️"]
        i = 0
        while not self._stop.is_set():
            elapsed = time.time() - start
            tqdm.write(f"{spinner[i % len(spinner)]} working… {self.label} | t={elapsed:.1f}s")
            i += 1
            self._stop.wait(self.interval)

    def start(self):
        self._thr.start()

    def stop(self):
        self._stop.set()
        self._thr.join(timeout=1)

# ---------- UTILITIES ----------
def get_pdf_page_count(pdf_path: Path):
    """นับจำนวนหน้าใน PDF"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            if total == 0:
                tqdm.write(f"⚠️ ไม่มีหน้าในไฟล์ {pdf_path.name}")
                return None
            return total
    except Exception as e:
        tqdm.write(f"⚠️ อ่านจำนวนหน้าไม่ได้: {e}")
        return None

def yield_chunks(total_pages: int, chunk_size: int, start_page: int = 1):
    """คืนช่วงหน้าเป็นลิสต์ [start..end] ทีละก้อน"""
    start = start_page
    while start <= total_pages:
        end = min(start + chunk_size - 1, total_pages)
        yield list(range(start, end + 1))
        start = end + 1

# ---------- CORE OCR FUNCTION ----------
def extract_text_from_image(
    file_path,
    api_key,
    task_type="default",
    max_tokens=16000,
    temperature=0.1,
    top_p=0.6,
    repetition_penalty=1.2,
    pages=None,
    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    retries=RETRIES,
    backoff=BACKOFF,
    hb_label=None,
):
    """เรียก Typhoon OCR API เพื่อสกัดข้อความ (รองรับหลายหน้าในคำขอเดียว)"""
    url = "https://api.opentyphoon.ai/v1/ocr"

    if pages is None and str(file_path).lower().endswith(".pdf"):
        total = get_pdf_page_count(Path(file_path))
        if not total:
            return None
        pages = list(range(1, total + 1))

    attempt = 0
    while attempt <= retries:
        hb = Heartbeat(
            hb_label or f"POST Typhoon pages {pages[0]}-{pages[-1]} (attempt {attempt+1}/{retries+1})",
            interval=HEARTBEAT_INTERVAL
        )
        try:
            hb.start()
            with open(file_path, "rb") as f:
                files = {"file": f}
                data = {
                    "task_type": task_type,
                    "max_tokens": str(max_tokens),
                    "temperature": str(temperature),
                    "top_p": str(top_p),
                    "repetition_penalty": str(repetition_penalty),
                }
                if pages:
                    data["pages"] = json.dumps(pages)

                if VERBOSE:
                    tqdm.write(f"→ POST {Path(file_path).name} pages {pages[0]}-{pages[-1]} (len={len(pages)}), attempt {attempt+1}/{retries+1}")

                resp = requests.post(
                    url,
                    files=files,
                    data=data,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=timeout,
                )
        except requests.exceptions.Timeout:
            hb.stop()
            attempt += 1
            if attempt > retries:
                tqdm.write("❌ Timeout ซ้ำหลายครั้ง → ยอมแพ้ก้อนนี้")
                return None
            wait = backoff ** attempt
            tqdm.write(f"⏱️ Timeout → รอ {wait:.1f}s แล้วลองใหม่ (attempt {attempt+1}/{retries+1})")
            time.sleep(wait)
            continue
        except requests.exceptions.RequestException as e:
            hb.stop()
            attempt += 1
            if attempt > retries:
                tqdm.write(f"❌ Network error ซ้ำหลายครั้ง: {e} → ยอมแพ้ก้อนนี้")
                return None
            wait = backoff ** attempt
            tqdm.write(f"🌐 Network error: {e} → รอ {wait:.1f}s แล้วลองใหม่ (attempt {attempt+1}/{retries+1})")
            time.sleep(wait)
            continue
        finally:
            try:
                hb.stop()
            except Exception:
                pass

        # จัดการ HTTP
        if 200 <= resp.status_code < 300:
            try:
                result = resp.json()
            except ValueError:
                tqdm.write("❌ ได้ response 2xx แต่ parse JSON ไม่ได้ → ยอมแพ้ก้อนนี้")
                return None

            texts = []
            for page_result in result.get("results", []):
                if not page_result.get("success"):
                    if VERBOSE:
                        tqdm.write(f"❌ หน้าใดหน้าหนึ่งล้มเหลว: {page_result.get('error','Unknown error')}")
                    return None
                content = page_result["message"]["choices"][0]["message"]["content"]
                try:
                    parsed = json.loads(content)
                    text = parsed.get("natural_text", content)
                except json.JSONDecodeError:
                    text = content
                texts.append(text)
            return "\n".join(texts)

        # 429/5xx → retry
        if resp.status_code in (429, 500, 502, 503, 504):
            attempt += 1
            if attempt > retries:
                tqdm.write(f"❌ API {resp.status_code} ซ้ำหลายครั้ง → ยอมแพ้ก้อนนี้")
                return None
            wait = backoff ** attempt
            tqdm.write(f"📶 API {resp.status_code} → รอ {wait:.1f}s แล้วลองใหม่ (attempt {attempt+1}/{retries+1})")
            time.sleep(wait)
            continue

        # อื่น ๆ ไม่ retry
        if VERBOSE:
            tqdm.write(f"❌ API error {resp.status_code}: {resp.text[:200]}")
        return None

# ---------- OCR FOR SINGLE PDF ----------
def ocr_one_pdf(pdf_path: Path, api_key: str):
    total_pages = get_pdf_page_count(pdf_path)
    if not total_pages:
        tqdm.write(f"⚠️ ข้ามไฟล์ (อ่านจำนวนหน้าไม่ได้): {pdf_path.name}")
        return

    texts = []
    chunk_size = CHUNK_SIZE

    # PROBE
    probe_pages = list(range(1, min(PROBE_PAGES, total_pages) + 1))
    tqdm.write(f"\n📘 {pdf_path.name} | pages={total_pages}")
    tqdm.write(f"   • PROBE {probe_pages[0]}–{probe_pages[-1]} ก่อนเริ่มจริง")
    t0 = time.time()
    probe_text = extract_text_from_image(
        file_path=str(pdf_path),
        api_key=api_key,
        task_type="default",
        pages=probe_pages,
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        retries=RETRIES,
        backoff=BACKOFF,
        hb_label=f"{pdf_path.name} PROBE {probe_pages[0]}–{probe_pages[-1]}"
    )
    probe_sec = time.time() - t0
    if not probe_text:
        tqdm.write(f"   ✗ PROBE ล้มเหลวใน {probe_sec:.1f}s → ลด chunk เป็น {MIN_CHUNK_SIZE} และจะลองแยกย่อย")
        start_page = 1
        initial_processed = 0
        chunk_size = MIN_CHUNK_SIZE
    else:
        texts.append(probe_text)
        tqdm.write(f"   ✓ PROBE สำเร็จใน {probe_sec:.1f}s → ไปต่อจากหน้า {probe_pages[-1]+1}")
        start_page = probe_pages[-1] + 1
        initial_processed = len(probe_pages)

    if start_page > total_pages:
        out_dir = Path("data/processed"); out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{pdf_path.stem}_typhoon.txt"
        out_path.write_text("\n\n".join(texts), encoding="utf-8")
        tqdm.write(f"✅ เสร็จสิ้น (ทั้งไฟล์เสร็จในขั้น PROBE): {pdf_path.name} → {out_path}")
        return

    # Progress bar ต่อไฟล์ (ชั้นใน)
    with tqdm(total=total_pages, desc=f"{pdf_path.name}", unit="p", leave=False) as pbar:
        pbar.update(initial_processed)
        start_time_file = time.time()

        for pages in list(yield_chunks(total_pages, chunk_size, start_page=start_page)):
            start, end = pages[0], pages[-1]
            t1 = time.time()

            text = extract_text_from_image(
                file_path=str(pdf_path),
                api_key=api_key,
                task_type="default",
                pages=pages,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                retries=RETRIES,
                backoff=BACKOFF,
                hb_label=f"{pdf_path.name} {start}–{end}"
            )

            if text:
                texts.append(text)
                pbar.update(len(pages))
                pbar.set_postfix({"chunk": f"{start}-{end}", "status": "ok", "sec": f"{time.time()-t1:.1f}"})
                continue

            # ลด chunk แล้วแตกย่อย
            if chunk_size > MIN_CHUNK_SIZE:
                new_chunk = max(MIN_CHUNK_SIZE, chunk_size // 2)
                tqdm.write(f"     ↘️ ลด chunk {chunk_size} → {new_chunk} สำหรับช่วง {start}-{end}")
                for sub in yield_chunks(end - start + 1, new_chunk, start_page=start):
                    sub_start, sub_end = sub[0], sub[-1]
                    t2 = time.time()
                    sub_text = extract_text_from_image(
                        file_path=str(pdf_path),
                        api_key=api_key,
                        task_type="default",
                        pages=list(range(sub_start, sub_end + 1)),
                        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                        retries=RETRIES,
                        backoff=BACKOFF,
                        hb_label=f"{pdf_path.name} {sub_start}–{sub_end}"
                    )
                    if sub_text:
                        texts.append(sub_text)
                        pbar.update(len(sub))
                        pbar.set_postfix({"chunk": f"{sub_start}-{sub_end}", "status": "ok*", "sec": f"{time.time()-t2:.1f}"})
                    else:
                        pbar.set_postfix({"chunk": f"{sub_start}-{sub_end}", "status": "fail"})
                        tqdm.write(f"❌ ข้ามไฟล์ (ล้มเหลวที่หน้า {sub_start}–{sub_end}): {pdf_path.name}")
                        return
                chunk_size = new_chunk
            else:
                pbar.set_postfix({"chunk": f"{start}-{end}", "status": "fail"})
                tqdm.write(f"❌ ข้ามไฟล์ (ล้มเหลวแม้ลด chunk ถึง {MIN_CHUNK_SIZE}): {pdf_path.name}")
                return

        # บันทึกเมื่อเสร็จทั้งไฟล์
        if texts:
            out_dir = Path("data/processed"); out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{pdf_path.stem}_typhoon.txt"
            out_path.write_text("\n\n".join(texts), encoding="utf-8")
            tqdm.write(f"✅ เสร็จสิ้น: {pdf_path.name} | pages={total_pages} | time={time.time()-start_time_file:.1f}s → {out_path}")
        else:
            tqdm.write(f"⚠️ ไม่มีข้อความที่จะบันทึก: {pdf_path.name}")

# ---------- MAIN SCRIPT ----------
if __name__ == "__main__":
    # ดึงค่า API Key จาก Config class โดยตรง
    api_key = Config.OCR_TYPHOON_API_KEY
    if not api_key:
        print("❌ OCR_TYPHOON_API_KEY is not set in your .env file or config.py!")
        exit(1)

    # กำหนดโฟลเดอร์เอกสาร (ถ้าไม่ได้ตั้งใน Config จะใช้ 'docs' เป็นค่าเริ่มต้น)
    docs_dir = getattr(Config, "DOCS_DIR", Path("docs"))
    docs_dir.mkdir(exist_ok=True) # สร้างโฟลเดอร์ docs หากยังไม่มี
    pdf_files = sorted(Path(docs_dir).glob("*.pdf"))

    if not pdf_files:
        print(f"⚠️ ไม่พบไฟล์ PDF ในโฟลเดอร์ '{docs_dir.resolve()}'")
    else:
        print(f"🔍 พบไฟล์ PDF {len(pdf_files)} ไฟล์ใน '{docs_dir.resolve()}'")
        for pdf in tqdm(pdf_files, desc="ทั้งหมด", unit="ไฟล์"):
            ocr_one_pdf(pdf, api_key)
        print("\n🎯 เสร็จสิ้นการประมวลผลทุกไฟล์")
