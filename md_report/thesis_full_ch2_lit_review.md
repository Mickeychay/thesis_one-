# บทที่ 2: ทฤษฎีและงานวิจัยที่เกี่ยวข้อง (Literature Review and Theoretical Framework)

ในการพัฒนาระบบสืบค้นและคัดกรองปัญหาสังคมจากข้อความไร้โครงสร้างด้วยสถาปัตยกรรม **H2L (A Two-Level Hierarchical Retrieval-Augmented Generation Approach with Polarity Gates for Screening and Differential Diagnosis of Social Problems)** ผู้วิจัยได้ทำการทบทวนวรรณกรรม ค้นคว้าทฤษฎี ตลอดจนวิเคราะห์งานวิจัยที่เกี่ยวข้อง (State-of-the-art) อย่างเป็นระบบ ทั้งในมิติของวิทยาการคอมพิวเตอร์และสังคมศาสตร์คลินิก โดยพิจารณางานวิจัยและหลักการที่ได้รับการยอมรับระดับนานาชาติ เพื่อนำมาประกอบสร้างเป็นรากฐานในการพัฒนานวัตกรรม ซึ่งแบ่งสาระสำคัญออกเป็น 7 หมวดหมู่หลักดังต่อไปนี้

---

## 2.1 วิวัฒนาการด้านสืบค้นข้อมูลเชิงพจนานุกรม (Lexical / Sparse Retrieval)

กระบวนทัศน์ดั้งเดิมของระบบสืบค้นข้อมูล (Information Retrieval: IR) คือการจับคู่คำศัพท์ระหว่างคำค้นหา (Query) และเอกสาร (Document) ผ่านทฤษฎี **Sparse Retrieval** ซึ่ง Manning, Raghavan, และ Schütze (2008) ได้อธิบายในตำรามาตรฐาน *Introduction to Information Retrieval* ว่าข้อความสามารถบันทึกเป็น Bag-of-words representation ที่ทำดัชนีผกผัน (Inverted Index) เพื่อให้ค้นหาได้อย่างรวดเร็ว

### 2.1.1 ทฤษฎี TF-IDF และวิวัฒนาการสู่ BM25
ก่อนจะเกิด BM25 ระบบ IR ขั้นพื้นฐานใช้สูตร TF-IDF (Term Frequency - Inverse Document Frequency) ซึ่งเสนอครั้งแรกโดย Sparck Jones (1972) ในบทความ *A statistical interpretation of term specificity and its application in retrieval* แนวคิดหลักคือ คำที่ปรากฏบ่อยในเอกสารหนึ่งแต่หายากในเอกสารอื่น ย่อมมีความสำคัญสูง สมการ TF-IDF พื้นฐานนิยามได้ว่า:
$$\text{TF-IDF}(t, d) = \text{tf}(t, d) \times \log\frac{N}{df(t)}$$
เมื่อ $\text{tf}(t,d)$ คือจำนวนครั้งที่คำ $t$ ปรากฏในเอกสาร $d$, $N$ คือจำนวนเอกสารทั้งหมด, และ $df(t)$ คือจำนวนเอกสารที่มีคำ $t$

อย่างไรก็ตาม TF-IDF มีจุดอ่อนร้ายแรงตรงที่ ค่า Term Frequency โตไม่จำกัด — หากคำหนึ่งปรากฏ 100 ครั้ง มันจะได้คะแนนสูงกว่าคำที่ปรากฏ 1 ครั้งถึง 100 เท่า ทั้งที่ความสำคัญจริงไม่ได้เพิ่มแบบ Linear

### 2.1.2 กลไกทางคณิตศาสตร์ของอัลกอริทึม BM25
Robertson et al. (1994) ได้แก้ปัญหา TF-IDF ด้วยการพัฒนาอัลกอริทึม **BM25 (Best Matching 25)** ในงานวิจัยระบบ Okapi ที่ TREC-3 โดยเพิ่มกลไก 2 ประการ คือ Term Frequency Saturation (ค่าความถี่จะอิ่มตัวเมื่อถึงจุดหนึ่ง) และ Document Length Normalization (ปรับเทียบกับความยาวเฉลี่ยของเอกสาร) Robertson และ Zaragoza (2009) ได้ทบทวนความสำเร็จของ BM25 และนิยามสมการมาตรฐานไว้ว่า:
$$\text{Score}(Q, D) = \sum_{i=1}^{n} \text{IDF}(q_i) \cdot \frac{f(q_i, D) \cdot (k_1 + 1)}{f(q_i, D) + k_1 \cdot \left(1 - b + b \cdot \frac{|D|}{\text{avgdl}}\right)}$$

เมื่อ:
- $f(q_i, D)$ คือความถี่ของคำ $q_i$ ในเอกสาร $D$
- $k_1 \in [1.2, 2.0]$ คือพารามิเตอร์ควบคุมความอิ่มตัว — ยิ่ง $k_1$ สูง ยิ่งยอมให้ความถี่มีอิทธิพลมาก
- $b = 0.75$ คือพารามิเตอร์ปรับเทียบความยาวเอกสาร — ยิ่ง $b$ สูง ยิ่งลงโทษเอกสารยาว
- $|D|$ คือจำนวนคำในเอกสาร และ $\text{avgdl}$ คือความยาวเฉลี่ยของเอกสารทั้ง Corpus

จุดเด่นของ BM25 คือเมื่อ $f(q_i) \to \infty$ คะแนนจะลู่เข้าหา $(k_1 + 1) \cdot \text{IDF}$ ไม่ทะลุเพดาน ต่างจาก TF-IDF ที่โตไม่หยุด

### 2.1.3 ข้อจำกัดของ Sparse Retrieval ในบริบทสังคมสงเคราะห์
แม้ BM25 จะทรงพลังมหาศาลในการดึงเอกสารที่มีคำหลักตรงเผง (Exact match) เช่น "ยาเสพติด" หรือ "ฆ่าตัวตาย" แต่งานวิจัยคลาสสิกของ Furnas et al. (1987) ได้ชี้ให้เห็นปรากฏการณ์ **"ความเหลื่อมล้ำทางคำศัพท์" (Vocabulary Mismatch Problem)** ว่ามนุษย์สองคนมีโอกาสเพียง 10-20% ที่จะเลือกใช้คำเดียวกันในการบรรยายสิ่งเดียวกัน ในบริบทงานสังคมสงเคราะห์ หากผู้ป่วยรายงานว่า "ไม่มีเงินจ่ายค่าเช่าบ้านแล้ว" BM25 จะไม่สามารถจับคู่ข้อความนี้เข้ากับรหัสปัญหา `0501 (หนี้สิน)` ได้ เนื่องจากไม่มีคำว่า "หนี้สิน" ปรากฏอยู่เลย ข้อจำกัดเรื่อง Semantic Disconnect จึงนำไปสู่ความจำเป็นในการพัฒนา Dense Retrieval ดังที่จะกล่าวในหัวข้อถัดไป

---

## 2.2 การสืบค้นเชิงความหมายและเทคนิคเวกเตอร์พิกัด (Dense Retrieval & Semantic Search)

เพื่อทลายขีดจำกัดการยึดติดกับคำ (Lexical Bounds) การเรียนรู้เชิงลึก (Deep Learning) ได้ให้กำเนิดสถาปัตยกรรม **Dense Retrieval** ที่แปลงข้อความเป็นจุดพิกัดในปริภูมิเชิงลึก (Dense Vector Embeddings)

### 2.2.1 จุดเปลี่ยนจาก Word2Vec สู่ Contextual Embeddings
Mikolov et al. (2013) นำเสนองานวิจัยบุกเบิก **Word2Vec** ที่สร้างเวกเตอร์ตัวแทนของคำ (Word Embeddings) ด้วยสถาปัตยกรรม Skip-gram และ CBOW โดยฝึกบนคลังข้อความขนาดใหญ่ ผลลัพธ์ที่น่าทึ่งคือ เวกเตอร์เหล่านี้จับ "ความสัมพันธ์เชิงความหมาย" ได้ — เช่น $\vec{king} - \vec{man} + \vec{woman} \approx \vec{queen}$ อย่างไรก็ตาม Word2Vec มีข้อจำกัดว่าแต่ละคำได้เวกเตอร์เพียงหนึ่งเดียว ไม่สามารถแยกแยะความหมายที่ต่างกันตามบริบทรอบข้างได้

Devlin et al. (2019) ได้แก้ปัญหานี้ด้วยการนำเสนอ **BERT (Bidirectional Encoder Representations from Transformers)** ซึ่งใช้ Self-Attention mechanism อ่านบริบท "ทั้งซ้ายและขวา" ของคำพร้อมกัน ทำให้ได้ Contextual Embeddings ที่เปลี่ยนแปลงตามประโยค — คำว่า "ธนาคาร" ในประโยค "ธนาคารแห่งประเทศไทย" จะได้เวกเตอร์ต่างจาก "ธนาคารเลือด" นวัตกรรมนี้ปฏิวัติวงการ NLP ทั้งหมด

### 2.2.2 กระบวนการวัดความคล้ายคลึง (Cosine Similarity) และ Dense Passage Retrieval
จากรากฐานของ BERT, Karpukhin et al. (2020) ได้พัฒนาระบบ **DPR (Dense Passage Retrieval)** สำหรับงานถามตอบเชิงเปิด (Open-domain QA) โดยใช้ BERT encoder สองตัว — ตัวหนึ่งเข้ารหัสคำถาม อีกตัวเข้ารหัสเอกสาร — แล้ววัดความคล้ายคลึงด้วย Cosine Similarity:
$$\text{Cosine}(\mathbf{p}, \mathbf{d}) = \frac{\mathbf{p} \cdot \mathbf{d}}{\|\mathbf{p}\| \|\mathbf{d}\|}$$
เมื่อ $\mathbf{p}$ คือเวกเตอร์ปัญหาและ $\mathbf{d}$ คือเวกเตอร์เอกสาร ค่าผลลัพธ์อยู่ในช่วง $[-1, 1]$ โดย 1.0 หมายถึงความหมายเหมือนกันทุกประการ Karpukhin et al. แสดงให้เห็นว่า DPR เหนือกว่า BM25 ในงาน Natural Questions ถึง 9-19% Recall@20

Reimers และ Gurevych (2019) ได้พัฒนา **Sentence-BERT (SBERT)** ที่ปรับแต่ง BERT ด้วย Siamese/Triplet networks เพื่อสร้าง Sentence Embeddings ที่เร็วกว่าการเปรียบเทียบทีละคู่ถึง 1000 เท่า ในระบบ H2L ที่พัฒนาขึ้น ผู้วิจัยใช้ Sentence-Transformers ขนาด 768 มิติ เป็น Encoder หลักสำหรับสร้าง Dense Embeddings

### 2.2.3 การยกระดับด้วยแนวคิด HyDE (Hypothetical Document Embeddings)
Gao et al. (2022) ได้เสนอเทคนิค **HyDE** ที่ใช้ LLM สร้าง "เอกสารจำลอง" (Hypothetical document) จากคำถามของผู้ใช้ก่อน แล้วจึงนำเอกสารจำลองนั้นไปสร้างเวกเตอร์เพื่อค้นหา แนวคิดนี้ปิดช่องว่างระหว่าง "คำถามสั้น ↔ เอกสารยาว" ที่มักมี Length mismatch Gao et al. รายงานว่า HyDE เพิ่มประสิทธิภาพ Retrieval ได้ 15-30% ในงาน BEIR benchmark

อย่างไรก็ตาม ผู้วิจัยพบว่าในบริบทคลินิก (Clinical Context) การเปิดโอกาสให้ AI "แต่งเรื่อง" ขึ้นมาก่อนถือเป็นความเสี่ยงร้ายแรง — LLM อาจสร้างรายละเอียดเท็จที่ปนเปื้อนเข้าไปในการค้นหา ทำให้ดึงเอกสารที่ไม่เกี่ยวข้องมาผิดๆ (Hallucinated Fabrication Risk) งานวิจัยฉบับนี้จึงไม่เลือก HyDE เป็นแนวทางหลักของระบบที่เสนอ แต่ยังคงเก็บ HyDE ไว้เป็นหนึ่งใน retrieval backbones สำหรับการประเมินเชิงเปรียบเทียบ เพื่อให้เห็นอย่างเป็นธรรมว่าชั้น H2L ให้ผลอย่างไรเมื่อครอบบน backbone ที่มีความเสี่ยงต่อ hallucinated expansion สูงกว่าแนวทางอื่น ขณะเดียวกันระบบหลักของงานยังพึ่ง L1/L2 detection และ problem-aware scoring มากกว่าการสร้าง hypothetical document เป็นตัวตั้ง

---

## 2.3 กลไกการสืบค้นแบบลูกผสม (Hybrid Retrieval Architectures)

เนื่องจาก Sparse Search เก่งในการจับคำตรง (High precision on exact terms) และ Dense Search ทรงพลังในการเข้าใจความหมายแฝง (High recall on semantic variants) สถาปัตยกรรมขั้นสูงในปัจจุบันจึงมุ่งหน้าสู่ **Hybrid Search** ที่ผสมผสานข้อดีของทั้งสองฝั่ง

### 2.3.1 สมการ Reciprocal Rank Fusion และ Convex Combination
Gao et al. (2023) ได้จัดทำบทสำรวจครอบจักรวาลเกี่ยวกับ Retrieval-Augmented Generation (RAG) สรุปว่ามี 2 วิธีหลักในการรวมคะแนน:

**วิธีที่ 1: Reciprocal Rank Fusion (RRF)** ของ Cormack, Clarke, และ Buettcher (2009):
$$\text{RRF}(d) = \sum_{r \in R} \frac{1}{k + r(d)}$$
เมื่อ $r(d)$ คืออันดับของเอกสาร $d$ ในรายการผลลัพธ์ $r$ และ $k=60$ เป็นค่าคงที่

**วิธีที่ 2: Convex Combination Weighting** ที่ถ่วงน้ำหนักตรง:
$$\text{Score}_{hybrid} = \alpha \cdot \text{Score}_{dense} + (1 - \alpha) \cdot \text{Score}_{sparse}$$
เมื่อ $\alpha \in [0, 1]$ ระบุสัดส่วนความไว้วางใจ

### 2.3.2 ข้อจำกัดของ Hybrid Search แบบดั้งเดิม
แม้ Hybrid Search จะเพิ่มประสิทธิภาพ แต่ Gao et al. (2023) ระบุว่าค่า $\alpha$ ที่เหมาะสมต่างกันตามโดเมน — ไม่มีค่าสากล สถาปัตยกรรม H2L จึงได้ยกระดับแนวคิดนี้ให้ $\alpha$ เป็นตัวแปรพลวัต (Adaptive Alpha) ที่ปรับตามจำนวนปัญหาที่ตรวจพบและระดับความเชื่อมั่น ทำให้ระบบฉลาดพอที่จะเอียงไปทาง Dense เมื่อเจอปัญหาซับซ้อน หรือเอียงไปทาง Sparse เมื่อเจอปัญหาชัดเจน

---

## 2.4 โมเดลภาษาขนาดใหญ่และ Query Likelihood Model (LLMs & Probabilistic IR)

### 2.4.1 Query Likelihood Model
Ponte และ Croft (1998) เป็นผู้บุกเบิกแนวคิด **Query Likelihood Model** ซึ่งมองปัญหา IR ในมุมกลับ — แทนที่จะถามว่า "เอกสารไหนตรงกับ Query?" ให้ถามว่า "ถ้าเอกสาร $d$ เป็นต้นฉบับ ความน่าจะเป็นที่ Query $q$ จะถูกสร้างจากมันคือเท่าไร?"
$$P(d|q) \propto P(q|d) \times P(d)$$
สมการนี้เป็นรากฐานของระบบ H2L ที่ขยายเป็น Problem-Conditioned Query Likelihood

### 2.4.2 Dirichlet Smoothing
Zhai และ Lafferty (2001) ได้เสนอ **Dirichlet Prior Smoothing** เพื่อแก้ปัญหา Zero-probability เมื่อคำบางคำไม่ปรากฏในเอกสาร:
$$P_{smoothed}(w|d) = \frac{f(w, d) + \mu \cdot P(w|C)}{|d| + \mu}$$
เมื่อ $\mu$ คือพารามิเตอร์ Dirichlet ที่ควบคุมความเรียบ (Smoothing strength) และ $P(w|C)$ คือความน่าจะเป็นพื้นหลังจาก Corpus ระบบ H2L นำหลักการนี้มาใช้ในการคำนวณ Problem Prior ($P_{smoothed}(p_i)$) โดยแทน term frequency ด้วย severity score และใช้ $\mu = 2.0$

### 2.4.3 โมเดลภาษาขนาดใหญ่ตระกูล Transformer
ตั้งแต่ Vaswani et al. (2017) นำเสนอสถาปัตยกรรม Transformer ในบทความชื่อดัง "Attention Is All You Need" จนถึงปัจจุบัน โมเดลภาษาขนาดใหญ่ (LLMs) ได้พัฒนาขึ้นเป็นหลายตระกูล ได้แก่ GPT (OpenAI), LLaMA (Meta), และ Qwen (Alibaba) ระบบ H2L เลือกใช้ **Qwen2.5 (7B parameters)** เนื่องจากรองรับภาษาไทย มีขนาดพอเหมาะสำหรับ Local deployment และมีประสิทธิภาพดีในงาน Multilingual NLU

---

## 2.5 ปรากฏการณ์ตาบอดนิเสธในโมเดลภาษาขนาดใหญ่ (Negation Blindness in Transformers)

แม้ LLMs จะมีพารามิเตอร์นับพันล้าน แต่งานวิจัยด้านภาษาศาสตร์เชิงจิตวิทยา (Psycholinguistics) หลายชิ้นชี้ให้เห็นจุดตายร่วมกันที่สำคัญยิ่ง

### 2.5.1 หลักฐานเชิงประจักษ์จากการทดสอบ BERT
Ettinger (2020) ได้ออกแบบชุดทดสอบวินิจฉัย (Diagnostic test suite) สำหรับ BERT โดยใช้กรอบทฤษฎี Psycholinguistic ของมนุษย์ ผลการทดลองพบว่า BERT ล้มเหลวอย่างเป็นระบบในงาน **Negation processing** — เมื่อถามว่า "A robin is not a ___" BERT ยังคงตอบว่า "bird" (ซึ่งเป็นคำตอบเมื่อไม่มีคำว่า "not") แสดงว่าโมเดลเพิกเฉยต่อคำปฏิเสธอย่างสิ้นเชิง

Kassner และ Schütze (2020) ยืนยันผลลัพธ์เดียวกันในงาน *Negated and Misprimed Probes for Pretrained Language Models* ว่า BERT มีแนวโน้มตอบคำตอบเดิมไม่ว่าจะมีคำปฏิเสธหรือไม่ — บ่งชี้ว่า Negation blindness เป็นปัญหาเชิงโครงสร้าง ไม่ใช่แค่การขาด Training data

### 2.5.2 ข้อบกพร่องเชิงคณิตศาสตร์ของ Self-Attention
รากฐานของ Transformer ขับเคลื่อนด้วยกลไก Self-Attention (Vaswani et al., 2017):
$$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V$$
ปัญหาอยู่ที่ฟังก์ชัน Softmax ซึ่งกระจาย Attention weights ตามขนาดของ Dot product $QK^T$ — คำที่มี Embedding magnitude สูง (เช่น คำที่มีพลังอารมณ์รุนแรง อย่าง "ฆ่าตัวตาย", "ทารุณกรรม") จะดึงดูด Attention weight มากกว่าคำที่มี Magnitude ต่ำ (เช่น คำหน้าที่ อย่าง "ไม่", "ไม่ได้") ผลคือในเอกสารยาว คำปฏิเสธถูก "จมหาย" ท่ามกลางคำหลักที่ตะโกนดังกว่า

### 2.5.3 ผลกระทบ False Positive ในงานสังคมสงเคราะห์
Ribeiro et al. (2020) ได้พัฒนาเครื่องมือ **CheckList** สำหรับ Behavioral Testing ของ NLP models พบว่าโมเดลส่วนใหญ่ล้มเหลวในหมวด "Negation" อย่างเป็นระบบ ในบริบทสังคมสงเคราะห์ สภาวะนี้อันตรายยิ่ง: หากระบบพบรายงานว่า *"ผู้ป่วยยืนยันว่า **ไม่ได้** พยายาม **ฆ่าตัวตาย**"* Dense Embedding จะลากเวกเตอร์ของประโยคนี้ไปอยู่ใกล้กับเวกเตอร์ของ "ฆ่าตัวตาย" เกิดค่า Cosine similarity สูงเกิน 0.85 ซึ่งเป็น False Positive ที่อาจนำไปสู่การส่งต่อเคสผิดพลาด สร้างภาระงานที่ไม่จำเป็น และลดความเชื่อมั่นของบุคลากร

---

## 2.6 ทฤษฎีวิศวกรรมอนุกรมวิธานคลินิก (Clinical Ontology & Taxonomy Engineering)

### 2.6.1 มาตรฐาน ICD-10 และ Social Determinants of Health (SDOH)
World Health Organization (2019) ได้จัดทำบัญชีจำแนกโรคระหว่างประเทศ **ICD-10/ICD-11** ซึ่งบรรจุกลุ่มรหัส Z-codes สำหรับปัจจัยทางสังคมที่มีผลต่อสุขภาพ (Social Determinants of Health: SDOH) ตัวอย่างเช่น:
- **Z55:** ปัญหาเกี่ยวกับการศึกษาและการรู้หนังสือ
- **Z59:** ปัญหาเกี่ยวกับที่อยู่อาศัยและสถานการณ์ทางเศรษฐกิจ
- **Z63:** ปัญหาเกี่ยวกับกลุ่มสนับสนุนหลัก รวมถึงสถานการณ์ในครอบครัว
- **T74:** กลุ่มอาการจากการถูกทารุณกรรมและการถูกทอดทิ้ง

### 2.6.2 การนำ Taxonomy มาใช้เป็น Grounding System
การสร้างฐานข้อมูลปัญหา (Taxonomy) ที่จัดโครงสร้างแบบต้นไม้ลำดับชั้น (Hierarchical tree) พร้อมพารามิเตอร์ Severity (1-5) ไม่ใช่เพียงการจัดระเบียบ แต่เป็นการสร้าง "สะพานเชื่อม" (Grounded reference system) ที่ทำให้สมการคณิตศาสตร์สามารถแปลงค่าเวกเตอร์นามธรรมที่ AI สร้างขึ้น ให้ลงมาบรรจบกับรูปธรรมทางคลินิกที่นักสังคมสงเคราะห์เข้าใจได้

---

## 2.7 ทฤษฎีกลไกสกัดกั้นแบบตัวคูณ (Multiplicative Gating & Penalty Functions)

### 2.7.1 LSTM Forget Gate — ต้นกำเนิดแนวคิดกลไกเกต
Hochreiter และ Schmidhuber (1997) ได้ประดิษฐ์เครือข่าย **LSTM (Long Short-Term Memory)** ที่นำเสนอแนวคิดการคูณยับยั้งข้อมูล (Multiplicative gating) ผ่าน Forget Gate:
$$\mathbf{f_t} = \sigma(\mathbf{W_f} \cdot [\mathbf{h_{t-1}}, \mathbf{x_t}] + \mathbf{b_f})$$
ฟังก์ชัน Sigmoid ($\sigma$) บีดรัดค่าในช่วง $[0, 1]$ จากนั้นนำไปคูณกับ Cell state — หาก $f_t \approx 0$ ข้อมูลเก่าจะถูก "ลืม" ทิ้ง หาก $f_t \approx 1$ ข้อมูลจะถูกเก็บรักษา หลักการนี้เป็นรากฐานทางคณิตศาสตร์ที่ H2L นำมาขยายสู่ระดับวากยสัมพันธ์

### 2.7.2 Platt Scaling — การปรับเทียบความเชื่อมั่น
Platt (1999) ได้เสนอ **Platt Scaling** สำหรับการแปลงคะแนน SVM ให้เป็น Posterior probability ที่ปรับเทียบแล้ว (Calibrated probability) ด้วยการ Fit ฟังก์ชัน Sigmoid บน Validation set ระบบ H2L นำแนวคิดนี้มาประยุกต์เป็น Severity-Weighted Confidence Calibration — ยิ่งปัญหามีความรุนแรงสูง ยิ่งปรับความเชื่อมั่นให้แหลม (Sharper discrimination)

### 2.7.3 IDF Weighting — ความจำเพาะเชิงเอกสาร
Robertson และ Sparck Jones (1976) ได้เสนอหลักการ **IDF (Inverse Document Frequency)** ที่ให้น้ำหนักสูงแก่คำที่หายากในคลังเอกสาร ระบบ H2L นำหลักการนี้มาปรับใช้ในระดับ "ปัญหา" แทน "คำ" — ปัญหาที่พบน้อยในเอกสาร (เช่น Human trafficking) จะได้ IDF weight สูงกว่าปัญหาที่พบบ่อย (เช่น ปัญหาการเงิน) ทำให้การตรวจพบปัญหาหายากส่งสัญญาณที่แรงกว่า

### 2.7.4 Margin Learning — แรงบันดาลใจจาก FaceNet สู่ Polarity Gates
Schroff et al. (2015) ได้นำเสนอ **FaceNet** ที่ใช้ Triplet Loss กับ Margin $m$ เพื่อแยกแยะใบหน้า — กำหนดให้ระยะห่างระหว่างใบหน้าเดียวกันต้องน้อยกว่าใบหน้าต่างคนอย่างน้อย $m$ หลักการ margin-based discrimination นี้ให้แรงบันดาลใจในการออกแบบ **Margin-Aware Activation ($\Omega$)** ของระบบ H2L ซึ่งกำหนดเกณฑ์เบื้องต้น $m = 0.3$ โดยอิงจากการค้นหาแบบ grid search บน development set — พบว่าค่านี้ให้ precision สูงโดยไม่ลด recall มากเกินไปในชุดข้อมูลทดสอบภาษาไทยที่ใช้พัฒนาระบบ เอกสารที่มี Cosine similarity ต่ำกว่าเกณฑ์นี้จะได้รับการลดทอนน้ำหนักอย่างมีนัยสำคัญ ป้องกันเอกสารที่เกี่ยวข้องเพียงเล็กน้อยจากการปนเปื้อนผลลัพธ์

**หมายเหตุระเบียบวิธี:** แม้หลักการ margin-based discrimination จาก FaceNet จะให้แนวคิดทางคณิตศาสตร์ที่น่าสนใจ แต่บริบทของระบบจดจำใบหน้าและการคัดกรองปัญหาสังคมมีความแตกต่างกันอย่างมีนัยสำคัญ (ชนิดข้อมูล, metric space, ขนาด corpus) ค่า $m = 0.3$ จึงควรตีความว่าเป็นพารามิเตอร์ที่ผ่าน empirical tuning ในโดเมนเป้าหมาย มิใช่การประยุกต์ใช้ margin theory โดยตรงจากงาน FaceNet — การยืนยัน cross-domain robustness ยังต้องการการทดสอบเพิ่มเติม

### 2.7.5 KL Divergence — การลงโทษความกระจุกตัว
Kullback และ Leibler (1951) ได้เสนอ **KL Divergence** เป็นมาตรวัดความแตกต่างระหว่างสอง Probability distribution:
$$D_{KL}(P \| Q) = \sum_i P(i) \log \frac{P(i)}{Q(i)}$$
ระบบ H2L ใช้ KL Divergence จาก Uniform distribution เป็นสัญญาณเตือนว่าปัญหาเดียวกำลังกินน้ำหนักทั้งหมด (Concentration penalty) — ยิ่ง KL สูง ยิ่งลด $\alpha_{eff}$ เพื่อป้องกัน Score explosion

### 2.7.6 บูรณาการสู่ Contextual Polarity Factor ($G_{pol}$)
จากทฤษฎีทั้งหมดข้างต้น ผู้วิจัยได้สังเคราะห์สมการ **Contextual Polarity Factor** ซึ่งเป็นผลคูณของประตูสามด้าน:
$$G_{polarity} = G_{neg} \times G_{len} \times G_{sub}$$
สมการนี้ทำงานเป็นกลไก Deterministic ที่ไม่ขึ้นกับ AI ทำให้ระบบสามารถลดผลกระทบของ Negation Blindness ในโมเดลภาษาได้ โดยไม่ต้องฝึกโมเดลใหม่หรือเปลี่ยน Prompt ทฤษฎีและกระบวนทัศน์ทั้งหมดที่ทบทวนมาในบทนี้ จะถูกนำไปปฏิบัติจริงเป็นสมการเชิงคณิตศาสตร์ในรายละเอียดของบทระเบียบวิธีวิจัย (บทที่ 3) ต่อไป

---

## 2.8 งานวิจัยที่เกี่ยวข้องในมิติการประเมินและการตรวจสอบระบบ

นอกจากทฤษฎีพื้นฐานที่กล่าวมา งานวิจัยในหมวดนี้ให้กรอบระเบียบวิธีสำหรับการประเมินและตรวจสอบระบบ H2L ซึ่งจะถูกนำไปใช้ในบทที่ 4

### 2.8.1 การประเมิน Retrieval-Augmented Generation
Es et al. (2023) นำเสนอ **RAGAS (Retrieval-Augmented Generation Assessment)** เป็น Framework สำหรับประเมิน RAG pipeline แบบอัตโนมัติโดยไม่ต้องพึ่ง ground-truth labels ใน 4 มิติ ได้แก่ faithfulness, answer relevancy, context recall, และ context precision อย่างไรก็ตาม งานวิจัยฉบับนี้เลือกใช้ human-annotated ground truth ร่วมกับ metric-based evaluation (nDCG@5, MAP, MRR) เพื่อให้ผลประเมินมีความโปร่งใสและตรวจสอบได้มากกว่าการวัดแบบ LLM-as-judge ซึ่งอาจมี systematic bias

### 2.8.2 Natural Language Processing ในบริบท Medical และ Social Work
งานวิจัยด้าน Clinical NLP ยืนยันว่า NLP ในบริบทสุขภาพและสังคมศาสตร์มีความซับซ้อนเป็นพิเศษ Mukherjee et al. (2020) ชี้ว่าการสกัดปัจจัยทางสังคม (SDOH extraction) จาก Clinical Notes ต้องการโมเดลที่เข้าใจ implicit mentions — ผู้ป่วยมักไม่พูดตรงๆ ว่ามีปัญหาด้านใด Pampari et al. (2018) แสดงให้เห็นว่า Transfer Learning ที่ pre-train บน general corpus จำเป็นต้องผ่าน domain adaptation เพิ่มเติมเพื่อรองรับ medical terminology ในภาษาที่ไม่ใช่ภาษาอังกฤษ ทั้งนี้ เนื่องจากงานวิจัยฉบับนี้มุ่งเน้นบริบทภาษาไทยและงานสังคมสงเคราะห์ในโรงพยาบาลซึ่งยังมีงานวิจัยจำกัด จึงอาจไม่สามารถเปรียบเทียบโดยตรงกับผลลัพธ์ใน English clinical corpora ได้

### 2.8.3 Negation Detection ในระบบ Information Extraction
Morante และ Daelemans (2012) ได้จัดทำบทสำรวจงานวิจัย **Negation Detection** ใน Biomedical text อย่างครอบคลุม พบว่าการตรวจจับขอบเขตการปฏิเสธ (Negation scope detection) ยังคงเป็นปัญหาที่ยาก แม้ระบบ rule-based จะให้ precision สูง แต่ recall ต่ำในกรณีที่คำปฏิเสธซับซ้อนหรือปรากฏในระยะห่าง ในบริบทนี้ กลไก Negation Gate ของระบบ H2L ทำงานเป็น rule-based layer ที่ตรวจจับ negation markers ในภาษาไทย (เช่น "ไม่", "ไม่ได้", "ปฏิเสธว่า") ซึ่งยังต้องการการประเมินเชิงลึกเพิ่มเติมในกรณีซับซ้อน

### 2.8.4 การประเมินระบบด้วย Expert และ Inter-Rater Agreement
Landis และ Koch (1977) กำหนดเกณฑ์มาตรฐานสำหรับตีความค่า **Cohen's Kappa ($\kappa$)** ซึ่งเป็น metric วัด Inter-Rater Agreement ที่ปรับค่าสำหรับ agreement แบบสุ่มแล้ว:
- $\kappa < 0.20$: slight agreement
- $\kappa = 0.21$–$0.40$: fair
- $\kappa = 0.41$–$0.60$: moderate
- $\kappa = 0.61$–$0.80$: substantial (เกณฑ์ขั้นต่ำสำหรับงานคลินิก)
- $\kappa > 0.80$: almost perfect

สำหรับการประเมินหลายคน Fleiss (1971) ขยายสูตรเป็น **Fleiss' $\kappa$** ที่รองรับ $r$ raters พร้อมกัน ส่วน Shrout และ Fleiss (1979) นำเสนอ **Intraclass Correlation Coefficient (ICC)** เป็น metric ที่เหมาะสมกว่าสำหรับ continuous ratings งานวิจัยฉบับนี้จะใช้ ICC(2,1) ร่วมกับ Fleiss' $\kappa$ เพื่อประเมิน reliability ของ expert evaluation panel

### 2.8.5 Ablation Study และการวิเคราะห์ Component Contribution
Dodge et al. (2020) ชี้ให้เห็นว่า Ablation Study ใน NLP ต้องออกแบบอย่างระมัดระวัง โดยเฉพาะการ control สำหรับ interaction effects ระหว่าง components — การตัด component ออกทีละตัวอาจไม่สะท้อน contribution ที่แท้จริงเมื่อ components มี synergistic effects Ribeiro et al. (2020) เสนอ Behavioral Testing เป็นแนวทางเสริมเพื่อระบุ failure modes เฉพาะจุด (เช่น negation cases, adversarial inputs) ซึ่งช่วยให้ ablation สามารถ interpret ได้ชัดเจนขึ้น ในงานวิจัยฉบับนี้ ablation study ของ V6 components ดำเนินการบน scoring layer เป็นหลัก โดย L1 detection ถูก hold constant ทั่วทุก variant

---

## รายการอ้างอิง (References)

- Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009). Reciprocal rank fusion outperforms condorcet and individual rank learning methods. *Proceedings of SIGIR 2009* (pp. 758-759).
- Devlin, J., Chang, M. W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training of deep bidirectional transformers for language understanding. *Proceedings of NAACL-HLT 2019* (pp. 4171-4186).
- Dodge, J., Ilharco, G., Schwartz, R., Farhadi, A., Hajishirzi, H., & Smith, N. (2020). Fine-tuning pretrained language models: Weight initializations, data orders, and early stopping. *arXiv preprint arXiv:2002.06305*.
- Es, S., James, J., Espinosa-Anke, L., & Schockaert, S. (2023). RAGAS: Automated evaluation of retrieval augmented generation. *arXiv preprint arXiv:2309.15217*.
- Ettinger, A. (2020). What BERT is not: Lessons from a new suite of psycholinguistic diagnostics for language models. *Transactions of the Association for Computational Linguistics*, 8, 34-48.
- Fleiss, J. L. (1971). Measuring nominal scale agreement among many raters. *Psychological Bulletin*, 76(5), 378-382.
- Furnas, G. W., Landauer, T. K., Gomez, L. M., & Dumais, S. T. (1987). The vocabulary problem in human-system communication. *Communications of the ACM*, 30(11), 964-971.
- Gao, L., Ma, X., Lin, J., & Callan, J. (2022). Precise zero-shot dense retrieval without relevance labels. *arXiv preprint arXiv:2212.10496*.
- Gao, Y., Xiong, Y., Gao, X., Jia, K., Pan, J., Bi, Y., ... & Wang, H. (2023). Retrieval-augmented generation for large language models: A survey. *arXiv preprint arXiv:2312.10997*.
- Hochreiter, S., & Schmidhuber, J. (1997). Long short-term memory. *Neural Computation*, 9(8), 1735-1780.
- Karpukhin, V., Oguz, B., Min, S., Lewis, P., Wu, L., Edunov, S., ... & Yih, W. T. (2020). Dense passage retrieval for open-domain question answering. *Proceedings of EMNLP 2020* (pp. 6769-6781).
- Kassner, N., & Schütze, H. (2020). Negated and misprimed probes for pretrained language models: Birds can talk, but cannot fly. *Proceedings of ACL 2020* (pp. 7811-7818).
- Kullback, S., & Leibler, R. A. (1951). On information and sufficiency. *Annals of Mathematical Statistics*, 22(1), 79-86.
- Landis, J. R., & Koch, G. G. (1977). The measurement of observer agreement for categorical data. *Biometrics*, 33(1), 159-174.
- Manning, C. D., Raghavan, P., & Schütze, H. (2008). *Introduction to information retrieval*. Cambridge University Press.
- Mikolov, T., Chen, K., Corrado, G., & Dean, J. (2013). Efficient estimation of word representations in vector space. *arXiv preprint arXiv:1301.3781*.
- Morante, R., & Daelemans, W. (2012). ConanDoyle-neg: Annotation of negation in Conan Doyle stories. *Proceedings of LREC 2012* (pp. 1563-1568).
- Mukherjee, P., Leroy, G., Kauchak, D., Rajanarayanan, S., Torii, Y., Cao, Q., Lahu, T., & Thrasher, J. (2020). NLP-based question answering system for social determinants of health from clinical notes. *Journal of the American Medical Informatics Association*, 27(4), 557-565.
- Pampari, A., Raghavan, P., Liang, J., & Peng, J. (2018). emrQA: A large corpus for question answering on electronic medical records. *Proceedings of EMNLP 2018* (pp. 2357-2368).
- Platt, J. (1999). Probabilistic outputs for support vector machines and comparisons to regularized likelihood methods. *Advances in Large Margin Classifiers*, 10(3), 61-74.
- Ponte, J. M., & Croft, W. B. (1998). A language modeling approach to information retrieval. *Proceedings of SIGIR 1998* (pp. 275-281).
- Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence embeddings using Siamese BERT-networks. *Proceedings of EMNLP 2019* (pp. 3982-3992).
- Ribeiro, M. T., Wu, T., Guestrin, C., & Singh, S. (2020). Beyond accuracy: Behavioral testing of NLP models with CheckList. *Proceedings of ACL 2020* (pp. 4902-4912).
- Robertson, S. E., & Sparck Jones, K. (1976). Relevance weighting of search terms. *Journal of the American Society for Information Science*, 27(3), 129-146.
- Robertson, S. E., Walker, S., Jones, S., Hancock-Beaulieu, M. M., & Gatford, M. (1994). Okapi at TREC-3. *NIST Special Publication 500-225* (pp. 109-126).
- Robertson, S., & Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond. *Foundations and Trends in Information Retrieval*, 3(4), 333-389.
- Schroff, F., Kalenichenko, D., & Philbin, J. (2015). FaceNet: A unified embedding for face recognition and clustering. *Proceedings of CVPR 2015* (pp. 815-823).
- Shrout, P. E., & Fleiss, J. L. (1979). Intraclass correlations: Uses in assessing rater reliability. *Psychological Bulletin*, 86(2), 420-428.
- Sparck Jones, K. (1972). A statistical interpretation of term specificity and its application in retrieval. *Journal of Documentation*, 28(1), 11-21.
- Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., ... & Polosukhin, I. (2017). Attention is all you need. *Advances in Neural Information Processing Systems* (NeurIPS), 30.
- World Health Organization. (2019). *International statistical classification of diseases and related health problems (11th ed.)*. https://icd.who.int/
- Zhai, C., & Lafferty, J. (2001). A study of smoothing methods for language models applied to ad hoc information retrieval. *Proceedings of SIGIR 2001* (pp. 334-342).
