**BÁO CÁO NGHIÊN CỨU CHUYÊN SÂU MẢNG:**  
**APPLICATION (App Architecture, System & Agent Orchestration)**

*Kiến trúc Hệ thống & Điều phối Đa Agent trong Dự án Emvoox & Hạ tầng V1RON OS*

| Người thực hiện: | Phước (Application & System Lead) |
| :---- | :---- |
| **Dự án:** | Emvoox Studio Engine & V1RON OS Integration |
| **Ngày báo cáo:** | Tháng 10 / 2026 |
| **Trạng thái nghiệm thu:** |  |

# **I. TÓM TẮT ĐIỀU HÀNH & PHẠM VI NGHIÊN CỨU (EXECUTIVE SUMMARY)**

Báo cáo nghiên cứu này xác lập khung kiến trúc mục tiêu và cơ chế điều phối trung tâm (Agent Orchestration Engine) cho dự án Emvoox – Studio giải trí AI sản xuất phim ngắn (Micro-Drama) và video ngắn (Shorts) – theo hướng Agentic Workflow thực thụ: người dùng nêu ý tưởng trong giao diện chat, các Agent tự lập kế hoạch, tự chọn công cụ (Tool) để thực thi và chỉ tạm dừng ở những điểm cần con người quyết định. Hiện trạng của Emvoox Engine là pipeline cố định (Native Async State Machine) với 7 Audio Agents Phase 1; báo cáo mô tả bước chuyển sang kiến trúc lai (Hybrid): đồ thị quy trình (Workflow Graph) chạy trên LangGraph, còn Agent, Hợp đồng Dữ liệu, lớp Provider, sổ chi phí và lưu trữ vẫn là mã nguồn tự chủ của Emvoox, sẵn sàng mở rộng sang 8 Shorts Agents Phase 2 và mô hình B2B SaaS (Pipeline-as-a-Service).

* **Mục tiêu Kỹ thuật Trọng tâm 1:** Xây dựng Agent Runtime dùng chung (Tool-Calling Loop): dựng ngữ cảnh (prompt \+ bộ nhớ \+ lịch sử \+ danh sách tool) \-\> gọi mô hình \-\> mô hình quyết định gọi tool nào \-\> chạy tool \-\> lặp lại cho đến khi mô hình trả lời mà không gọi tool.  
* **Mục tiêu Kỹ thuật Trọng tâm 2:** Xây dựng Tool Registry mà mô hình gọi được (Model-callable), nạp theo nhu cầu (Loaded on demand), để lập trình viên tự thêm Skill và Tool cho từng Agent bằng cấu hình mà không sửa lõi hệ thống.  
* **Mục tiêu Kỹ thuật Trọng tâm 3:** Giữ quy chuẩn Hợp đồng Dữ liệu Cứng (Strict Data Contracts using Pydantic v2) làm schema tham số và kết quả của mọi Tool để triệt tiêu tình trạng trôi dạt định dạng (Schema Drift).  
* **Mục tiêu Kỹ thuật Trọng tâm 4:** Bổ sung cơ chế bộ nhớ gồm lịch sử hội thoại (Conversation History), bộ nhớ dài hạn mà mỗi Agent học được (Long-term Memory, xem và sửa được) và cơ chế nén ngữ cảnh (Compaction).  
* **Mục tiêu Kỹ thuật Trọng tâm 5:** Triển khai Durable Worker kết hợp Checkpoint của LangGraph: một lượt chạy (Run) sống sót qua việc khởi động lại máy chủ, tạm dừng chờ con người nhiều ngày và tiếp tục đúng điểm dừng.  
* **Mục tiêu Kỹ thuật Trọng tâm 6:** Mở rộng vòng lặp tự động kiểm định chất lượng âm thanh và sửa lỗi (QA Retry Loop) với bounded auto-retry (max\_retries \= 3\) xuống cấp độ từng cảnh (Scene), nhiều cảnh chạy song song, và giữ chốt chặn duyệt con người (Showrunner Gate) là bước bắt buộc của đồ thị, không để mô hình bỏ qua.  
* **Mục tiêu Kỹ thuật Trọng tâm 7:** Sẵn sàng B2B SaaS trên V1RON OS (PostgreSQL v1ron\_db \+ MinIO V1RON Media): đa khách hàng (Multi-tenant), phân quyền, ngân sách và đo lường mức dùng theo từng Tenant.

# **PHẦN 1: BENCHMARK CÔNG CỤ & FRAMEWORK ĐIỀU PHỐI (TOOLS & FRAMEWORKS EVALUATION)**

## **1.1 So sánh Chi tiết các Framework Orchestration**

Yêu cầu đã thay đổi so với giai đoạn đầu: sản phẩm bán cho khách hàng B2B chính là quy trình sản xuất (Workflow Pipeline), và trong sản xuất thực tế quy trình không còn tuyến tính: nhiều cảnh chạy song song, mỗi cảnh có vòng lặp riêng (QA \-\> render lại \-\> QA \-\> duyệt) và có thể tạm dừng chờ người. Báo cáo đánh giá lại 4 hướng điều phối theo yêu cầu mới: LangGraph, CrewAI, AutoGen và Native Async State Machine (hiện trạng).

| Framework | Khả năng Kiểm soát Luồng (Control Flow) | Độ trễ & Hiệu năng (Latency/Async) | Rủi ro Phụ thuộc (Dependencies Risk) | Đánh giá Phù hợp với Emvoox |
| :---- | :---- | :---- | :---- | :---- |
| **LangGraph (Emvoox Choice cho tầng Workflow)** | Rất tốt (State Graph: rẽ nhánh, chạy song song, gộp kết quả, có sẵn checkpoint và interrupt) | Trung bình (Có overhead) | Trung bình (LangChain Ecosystem; giới hạn bằng cách chỉ dùng cho tầng đồ thị, không dùng lớp mô hình của LangChain) | **HƯỚNG ĐỀ XUẤT: LangGraph điều phối đồ thị quy trình, phần còn lại giữ mã nguồn tự chủ** |
| **CrewAI** | Trung bình (Role-based prompt, mô hình tự ủy quyền) | Chậm (Chủ yếu synchronous) | Cao (Dùng lớp LLM riêng, bỏ qua Adapter và sổ chi phí của Emvoox) | Không phù hợp: khó kiểm soát chi phí và tính xác định |
| **AutoGen** | Linh hoạt (Multi-agent chat) | Chậm (Hội thoại lặp vòng) | Cao (Rất khó ép Hợp đồng Pydantic) | Không phù hợp cho quy trình xuất bản thương mại |
| **Native Async State Machine (hiện trạng)** | Tuyệt đối với luồng tuyến tính; phải tự viết xử lý song song, gộp trạng thái và tạm dừng theo nhánh khi quy trình rẽ nhánh | Tối ưu (Native asyncio & event bus) | Thấp (Tự chủ mã nguồn) | Phù hợp với pipeline tuyến tính hiện nay; không còn là lựa chọn tốt nhất khi quy trình rẽ nhánh và chạy song song theo cảnh |

Kết luận Benchmark Framework: Emvoox Engine đề xuất kiến trúc lai giữa LangGraph và mã nguồn tự chủ. LangGraph đảm nhận tầng đồ thị quy trình (Series \-\> Episode \-\> các nhánh Scene, vòng lặp sửa lỗi, tạm dừng chờ duyệt, gộp kết quả) vì các khả năng rẽ nhánh, chạy song song và checkpoint đã có sẵn. Emvoox giữ nguyên các Agent (thân của từng node), Hợp đồng Dữ liệu Pydantic, LLM/TTS Adapters và Mock, sổ chi phí, ngân sách, đa khách hàng và lưu trữ – những phần phải tự làm dù chọn framework nào. Ranh giới này giữ sự phụ thuộc trong một tầng duy nhất, có thể thay thế về sau. Đề xuất cần được xác nhận bằng một bản thử nghiệm ngắn trước khi chuyển đổi toàn bộ (xem mục 3.8).

## **1.2 Benchmark Công cụ Browser Automation & Scrapers**

Market Research Agent yêu cầu công cụ đọc dữ liệu tự động từ các nền tảng tin tức, mạng xã hội và nền tảng phim ngắn (Google, TikTok, YouTube, DramaBox, ReelShort). Trong kiến trúc mới, các công cụ này trở thành Tool trong Registry để Agent tự quyết định tìm gì, mở trang nào và có tìm tiếp hay không. Báo cáo đánh giá 4 công cụ:

* **Playwright (v1ron\_playwright):** Hiệu năng cao nhất, hỗ trợ bất đồng bộ native (asyncio), khả năng giả lập thiết bị di động chuẩn xác và cơ chế tự động chờ phần tử (auto-waiting) giảm thiểu tối đa lỗi flaky element. Tích hợp trực tiếp thành v1ron\_playwright.  
* **Puppeteer (v1ron\_puppeteer):** Ổn định nhưng tiêu tốn bộ nhớ hơn Playwright khi chạy đa luồng. Tích hợp thành v1ron\_puppeteer.  
* **Chrome DevTools Protocol (v1ron\_cdp):** Giao tiếp trực tiếp với Chrome/Chromium qua WebSocket ở mức thấp. Tốc độ thực thi nhanh nhất nhưng phức tạp khi bảo trì. Tích hợp thành v1ron\_cdp.  
* **Search API (bổ sung):** Với Google, trình duyệt headless thường gặp robot check. Hướng đề xuất là dùng Gemini kèm Google Search Grounding hoặc một Search API thay cho việc cào trang kết quả. Trang hiện robot check hoặc tường đăng nhập được ghi nhận là "blocked" và không tìm cách vượt qua.

# **PHẦN 2: KHUNG LÝ THUYẾT & NGUYÊN LÝ KỸ THUẬT ORCHESTRATION (THEORETICAL FRAMEWORK)**

## **2.1 Nguyên lý Agent Runtime & Event Bus**

Emvoox Engine chuyển từ mô hình Trạng thái Bất đồng bộ cố định sang Agent Runtime dùng chung. Mọi Agent đều chạy trên cùng một vòng lặp 5 bước (Agent Loop):

* **1\. BUILD\_CONTEXT:** Ghép system prompt của Agent, bộ nhớ dài hạn liên quan, lịch sử hội thoại và danh sách Tool đang nạp.  
* **2\. CALL\_MODEL:** Gọi mô hình qua lớp Provider; câu trả lời được stream về giao diện chat.  
* **3\. PERMISSION\_GATE:** Với mỗi lời gọi Tool, kiểm tra vai trò người dùng có được phép không, tham số có hợp lệ không và Tool có cần người duyệt không.  
* **4\. RUN\_TOOLS:** Chạy Tool và trả kết quả về cho mô hình; Sub-agent có thể chạy song song.  
* **5\. LOOP:** Lặp lại cho đến khi mô hình trả lời mà không gọi Tool. Mỗi lượt đều kiểm tra ngân sách và số bước tối đa.

Agent trở thành cấu hình: một prompt, danh sách nhóm Tool được dùng, phạm vi bộ nhớ, mô hình và ngân sách. Một Producer Agent giữ cuộc hội thoại với người dùng và giao việc cho các Agent chuyên môn (Market Research, Script Writer, Casting, AI Director, Sound Engineer, QA Critic, Publisher) dưới dạng Sub-agent. Bảy trạng thái vòng đời trước đây (RESEARCHING \-\> SCRIPTING \-\> CASTING \-\> DIRECTING \-\> SOUND\_ENGINEERING \-\> QA\_AUDITING \-\> APPROVAL\_GATE / PUBLISHED) vẫn là các giai đoạn của một dự án, nhưng không còn là chuỗi bắt buộc do mã nguồn áp đặt: Agent quyết định đi tiếp, quay lại hay hỏi người dùng.

Ranh giới của tính tự chủ: Vòng lặp Agent được dùng ở nơi đường đi chưa biết trước (nghiên cứu thị trường, phát triển câu chuyện cùng người dùng, lựa chọn diễn viên). Chuỗi sản xuất một tập (DIRECTING \-\> SOUND\_ENGINEERING \-\> QA\_AUDITING \-\> APPROVAL\_GATE) là một đồ thị quy trình xác định chạy trên LangGraph, được Agent gọi như một Tool: mô hình không được bỏ qua QA hay đổi thứ tự master, vì đây là nơi tiêu tiền nhà cung cấp và nơi cam kết chuẩn âm thanh \-16 LUFS.

Song song với Agent Runtime là hệ thống Event Bus. Mọi hoạt động đều phát ra các sự kiện chuẩn hóa (PipelineEvent): step.started, step.finished, step.failed, contract.rejected, qa.flagged, gate.waiting, bổ sung các sự kiện của vòng lặp (tool được gọi, chờ duyệt, chờ người dùng trả lời). Điều này giúp giao diện chat và Dashboard cập nhật trạng thái thời gian thực.

## **2.2 Quy chuẩn Hợp đồng Dữ liệu Cứng (Strict Data Contracts with Pydantic v2)**

Điểm khác biệt cốt lõi giữa Emvoox Engine và các hệ thống AI tự do là nguyên tắc Không truyền Unstructured Text giữa các bước. Trong kiến trúc mới, nguyên tắc này được mở rộng: Hợp đồng Dữ liệu là schema tham số và kết quả của mọi Tool, nên mọi thứ mô hình gửi vào và nhận về đều được kiểm tra bằng Pydantic v2 Schema:

* **1\. TrendBrief:** Chứa topic, target\_audience, format\_spec, theme\_category (Urban CEO, Rebirth, Intellectual Slap), ba thể loại thịnh hành nhất và thể loại được chọn.  
* **2\. StoryInput & SeriesBible:** Chứa cấu trúc danh sách tập, lời thoại gắn ID nhân vật, điểm chỉ số móc câu (cliffhanger score).  
* **3\. ResolvedCast & EnginePolicy:** Bảng ánh xạ Nhân vật \-\> Diễn viên AI IP, cài đặt tham số giọng nói và chỉ định Provider.  
* **4\. DirectedConversationUnits:** Danh sách các đơn vị hội thoại chi tiết gồm speaker\_id, text, cảm xúc và cường độ, khoảng nghỉ, tốc độ.  
* **5\. MasteredEpisode:** Đường dẫn file master âm thanh (.mp3/.wav), thời lượng chính xác, chỉ số âm lượng chuẩn hóa LUFS.  
* **6\. QAReport:** Trạng thái PASS hoặc FLAGGED, điểm số chất lượng (0-100), log lỗi, hướng dẫn sửa đổi.  
* **7\. ReleasePackage:** Gói dữ liệu hoàn chỉnh sẵn sàng xuất bản gồm tệp media master, tiêu đề, mô tả, danh sách hashtag chuẩn SEO YouTube/TikTok.

## **2.3 Vòng lặp Tự động Sửa lỗi & Chốt dừng duyệt Con người (QA Retry Loop & Human Gate)**

Phần này giữ nguyên các nguyên tắc đã kiểm chứng và mở rộng từ cấp độ tập phim xuống cấp độ từng cảnh (Scene), mỗi cảnh là một nhánh của đồ thị và nhiều cảnh chạy song song. Khi QA Critic Agent trả về kết quả FLAGGED cho một cảnh (ví dụ: phát hiện nuốt từ, lệch giọng diễn viên, hoặc tỷ lệ ngắt nghỉ không đạt), hệ thống kích hoạt quy trình Bounded Auto-Retry trên nhánh đó:

* **Cơ chế cách ly lỗi (Isolated Re-render):** Hệ thống không chạy lại toàn bộ kịch bản mà chỉ nhánh của cảnh bị lỗi quay lại Sound Engineer Agent render lại các đơn vị hội thoại (Conversation Units) bị lỗi; các cảnh khác tiếp tục chạy.  
* **Giới hạn Lần thử (max\_retries \= 3):** Mỗi tập phim chỉ được tự động sửa đổi tối đa 3 lần. Mỗi lần thử lại, hệ thống chuyển dần tham số về mức an toàn (Robust Preset: giảm độ biến thiên giọng, tăng độ ổn định TTS).  
* **Chốt dừng Con người (Showrunner Gate):** Nếu sau 3 lần retry vẫn không đạt điểm PASS, nhánh đó kích hoạt chốt dừng an toàn (halt\_on\_qa\_fail \= True), tạm dừng và thông báo cho Showrunner (Human) can thiệp; nhiều cảnh có thể cùng chờ duyệt và được tiếp tục độc lập. Không tập nào được xuất bản khi chưa có người duyệt.  
* **Bước gộp (Join) & Master:** Khi mọi cảnh đã được duyệt, đồ thị gộp các cảnh, master cả tập và kiểm tra chỉ số LUFS một lần trước chốt duyệt tập phim.  
* **Tạm dừng chờ Con người trong vòng lặp Agent (Human Pause):** Ngoài chốt duyệt tập phim, Agent tạm dừng và hỏi người dùng tại các điểm cần quyết định: chọn một trong ba thể loại thịnh hành, duyệt dàn diễn viên, duyệt khoản chi vượt ngân sách.

## **2.4 Case Studies Quốc tế về Hạ tầng AI Studio**

Báo cáo đã tiến hành phân tích 3 đơn vị, mỗi đơn vị minh họa một phần của kiến trúc mục tiêu:

* **HOLYWATER (Ukraina):** Thành lập năm 2020 tại Kyiv, vận hành My Passion (sách), My Drama (phim dọc, ra mắt 2024) và My Muse (series tạo bằng AI, 2025); nhận đầu tư chiến lược từ Fox Entertainment năm 2025 và gọi vốn 22 triệu USD tháng 1/2026. Theo case study của Google Cloud, Holywater dùng Gemini, Veo và Nano Banana, sản xuất series nhanh hơn 8 lần và tạo ra số phút video mỗi tháng gấp 10 lần; phát hành 120–200 series mỗi năm bằng cách dùng dữ liệu khán giả để chọn truyện từ mảng sách rồi chuyển thể. Bài học cho Emvoox: chiến lược phễu tương đồng (truyện \-\> thử nghiệm rẻ \-\> chỉ đầu tư vào tựa thắng), dữ liệu giữ chân khán giả phải quay lại làm đầu vào cho Agent.  
* **VidMuse:** Nền tảng tạo video bằng AI Agent: người dùng mô tả ý tưởng bằng ngôn ngữ tự nhiên, Agent lập kế hoạch toàn bộ video trước khi tạo khung hình đầu tiên (creative brief \-\> tham chiếu \-\> danh sách cảnh \-\> storyboard \-\> tạo video). VidMuse 2.0 (1/6/2026) xây lại nền tảng Agent, thay các pipeline từng bước cứng nhắc – được chính họ mô tả là chậm thích ứng và tốn kém khi mở rộng – bằng cách tiếp cận "Video as Code", đồng thời thêm User Memory, Asset Library và các smart card để người dùng bấm chọn thay vì gõ. Hỗ trợ hơn 20 mô hình ảnh và video, tự định tuyến từng tác vụ đến mô hình phù hợp. Bài học cho Emvoox: đây chính là bước chuyển Emvoox đang thực hiện; nên học giao diện chat kèm thẻ lựa chọn tại các điểm cần người quyết định, bộ nhớ người dùng và lớp định tuyến mô hình.  
* **ZhiHuoLun / 智火轮 AI (Thâm Quyến, Trung Quốc):** Tự giới thiệu là đơn vị triển khai ứng dụng AI tăng trưởng cho doanh nghiệp vừa và nhỏ với 4 nhóm sản phẩm: nhân viên số AI, hệ thống tìm khách hàng bằng AI, sản xuất nội dung bằng AI và Agent bán hàng, định vị là đội "nhân viên số" hoạt động 7×24. Bài học cho Emvoox: mô hình B2B bán Agent theo vai trò nghiệp vụ, gần với hướng Pipeline-as-a-Service. Lưu ý: thông tin công khai về đơn vị này rất ít, chủ yếu từ bài tự giới thiệu, chưa tìm được tài liệu kỹ thuật về kiến trúc; cần bổ sung nguồn trước khi nghiệm thu.

# **PHẦN 3: ĐỀ XUẤT KHUNG THIẾT KẾ CHO EMVOOX & V1RON OS RUNTIME (DESIGN FRAMEWORK FOR EMVOOX)**

## **3.1 Kiến trúc Hệ thống Tổng thể (System Architecture)**

Emvoox Engine được thiết kế theo mô hình Kiến trúc Phân tầng (Layered Architecture):

* **1\. Presentation Layer:** Giao diện chat AI-first xây dựng trên Next.js 16 và Ant Design 6. Người dùng nhập ý tưởng, theo dõi Agent làm việc, trả lời câu hỏi và duyệt tại các điểm dừng; các trang hiện có (Approvals, Characters, Costs) trở thành các màn hình mà cuộc hội thoại dẫn tới.  
* **2\. API Layer:** FastAPI Gateway nhận tin nhắn và quyết định duyệt/từ chối, đưa Run vào hàng đợi và stream sự kiện về giao diện.  
* **3\. Orchestration Layer:** Đồ thị quy trình trên LangGraph (Series, Episode, các nhánh Scene song song, vòng lặp sửa lỗi, tạm dừng, checkpoint) và vòng lặp Agent với Permission Gate, kiểm tra ngân sách và Compaction; chạy trong Durable Worker.  
* **4\. Agent Fleet Layer:** Producer Agent và đội ngũ 7 AI Audio Agents Phase 1 dưới dạng cấu hình, là thân của các node trong đồ thị (kết nối mở rộng 8 Shorts Agents Phase 2).  
* **5\. Tool Registry Layer:** Tool theo nhóm, nạp theo nhu cầu, bao gồm Tool "sản xuất một tập" gọi vào đồ thị quy trình.  
* **6\. Provider Abstraction Layer:** Lớp trừu tượng hóa nhà cung cấp LLM Adapters (Gemini, Claude, OpenAI, WaveSpeed, Mock) có thêm khả năng gọi Tool, và TTS Adapters (Gemini TTS, ElevenLabs, WaveSpeed MiniMax, Mock). Mọi lời gọi được ghi vào sổ chi phí.  
* **7\. Memory & State Layer:** Lịch sử hội thoại, bộ nhớ dài hạn, trạng thái Run và nhật ký kiểm toán (Audit Logs).  
* **8\. Repository Data Layer:** Lớp truy xuất dữ liệu trừu tượng (Repository Pattern) kết nối Local Storage hoặc V1RON OS (PostgreSQL & MinIO); mọi khóa và bản ghi đều mang mã Tenant.

## **3.2 Luồng truyền Dữ liệu & Cơ chế Cache Tối ưu (Idempotency)**

Để tối ưu hóa chi phí API (vốn chiếm tỷ trọng lớn trong chi phí vận hành), Emvoox Engine triển khai cơ chế Caching theo Mã băm (Hash-based Idempotency Caching):

Mỗi đơn vị âm thanh được tạo ra sẽ gắn liền với một khóa Hash duy nhất được tính toán từ các tham số: SHA256(provider \+ model \+ voice\_id \+ text \+ speed \+ pitch \+ emotion\_tag).

Trước khi gọi API của nhà cung cấp TTS (như ElevenLabs hay Gemini TTS), Sound Engineer Agent sẽ kiểm tra khóa Hash này trong DocumentStore. Nếu file âm thanh đã tồn tại trong BlobStore, hệ thống tái sử dụng ngay lập tức mà không tiêu tốn thêm bất kỳ ký tự API nào. Điều này giúp giảm 35% \- 50% chi phí khi phải re-render lại kịch bản.

Trong kiến trúc mới, cơ chế này có thêm một vai trò: khi một node của đồ thị chạy lại sau sự cố hoặc sau khi được tiếp tục từ điểm tạm dừng, Tool render không tiêu tiền lần thứ hai.

## **3.3 Tự động hóa Xuất bản & Feedback Loop**

Xuất bản là Tool loại External, luôn cần người duyệt. Sau khi qua bước chốt dừng duyệt (Showrunner Gate), Publisher Agent kích hoạt tiến trình xuất bản đa nền tảng:

* **YouTube Data API v3 Integration:** Sử dụng thư viện chính thức google-api-python-client để tải video/audio master, tạo playlist theo tập phim, thiết lập lịch phát sóng và điền metadata chuẩn SEO.  
* **TikTok Content Posting API:** Tích hợp TikTok Direct Post API để đăng tải video ngắn 9:16, tự động gắn thẻ hashtag xu hướng.  
* **Retention Analytics Feedback Loop:** Hệ thống thu thập các chỉ số (Tỷ lệ giữ chân người xem Retention Rate, điểm bỏ xem Drop-off Point, lượt thích và bình luận). Các chỉ số này trở thành Tool đọc cho Market Research Agent và Script Writer Agent, và là nguồn cho bộ nhớ dài hạn về khán giả.

## **3.4 Định hướng B2B SaaS Ready (Pipeline-as-a-Service)**

Emvoox Engine hướng tới mô hình thương mại B2B SaaS cho phép các Studio đối tác thuê pipeline sản xuất:

* **Multi-tenancy & Isolation:** Phân tách dữ liệu, Voice IP, khóa API nhà cung cấp và bộ nhớ dài hạn giữa các Tenant (Doanh nghiệp B2B) trên cùng hạ tầng V1RON OS.  
* **Users & Roles:** Run chạy dưới danh nghĩa người dùng đã đăng nhập; mỗi vai trò chỉ thấy và gọi được các Tool được cấp.  
* **Developer Extensibility:** Lập trình viên thêm Tool và Agent bằng cấu hình, không sửa lõi Runtime.  
* **Budgets & Concurrency Limits:** Trần chi phí cứng theo Run và theo Tenant, dừng Run khi chạm trần; giới hạn số Run song song theo Tenant thay cho quy tắc "mỗi lần một series" hiện nay.  
* **Usage Metering & Billing Engine:** Hệ thống đo lường chính xác lượng tài nguyên tiêu thụ gồm: số LLM Tokens đã dùng, số ký tự TTS đã render, số phút video export, và dung lượng bộ nhớ MinIO đã lưu trữ.  
* **Cost Logging & Telemetry:** Dashboard hiển thị chi phí thực tế cho từng tập phim, từng Agent và từng lời gọi Tool, giúp nhà quản trị kiểm soát biên lợi nhuận thời gian thực.

## **3.5 Tool Registry: Tool mà mô hình gọi được, nạp theo nhu cầu (Model-callable, Loaded on demand)**

Một Tool là một hàm có schema tham số và schema kết quả (Pydantic), thuộc một nhóm (area) và một loại (kind):

* **Core (luôn nạp):** Điều khiển vòng lặp, ví dụ load\_tools, ask\_user, spawn\_subagent, remember, recall.  
* **Read (chạy ngay):** Ví dụ tìm kiếm, mở trang, đọc TrendBrief, đọc Voice Registry.  
* **Write (cần duyệt ở chế độ Manual):** Ví dụ lưu TrendBrief, sửa SeriesBible, gán diễn viên.  
* **External (luôn cần duyệt):** Ví dụ render TTS tốn phí, xuất bản lên YouTube/TikTok.  
* **Nạp theo nhu cầu:** Chỉ nhóm Core nằm sẵn trong ngữ cảnh; các nhóm khác được nạp khi Agent cần, để danh sách Tool không chiếm hết cửa sổ ngữ cảnh.  
* **Skill hiện có trở thành Tool:** Search Plan, Market Scan, Content Analyze, Story Adapt, Casting… được bọc lại, không viết lại.  
* **Mở rộng bởi lập trình viên:** Thêm Tool \= viết một hàm kèm schema và đăng ký vào một nhóm; thêm Agent \= thêm một cấu hình.

## **3.6 Bộ nhớ & Nén ngữ cảnh (Memory & Compaction)**

Hệ thống bộ nhớ gồm 3 kho tách biệt và cơ chế Compaction 3 mức, áp dụng lần lượt khi ngữ cảnh đầy dần:

* **Conversation History:** Lịch sử hội thoại theo từng thread gồm mọi tin nhắn, lời gọi Tool và kết quả; chỉ ghi thêm.  
* **Long-term Memory:** Bộ nhớ dài hạn theo Tenant và theo Agent, lưu những điều Agent học được về khách hàng và khán giả, ghi qua Tool remember và đọc qua recall. Con người xem, sửa và xóa được; không bao giờ dùng chung giữa các Tenant.  
* **Domain Data:** SeriesBible, Voice Registry, TrendBrief vẫn là nguồn sự thật duy nhất, không sao chép vào bộ nhớ.  
* **Compaction mức 1 (Clear):** Xóa nội dung các kết quả Tool cũ, giữ vài lượt gần nhất.  
* **Compaction mức 2 (Summarize):** Tóm tắt các lượt cũ bằng một lần gọi mô hình và lưu bản tóm tắt.  
* **Compaction mức 3 (Drop):** Bỏ các lượt cũ nhất, là phương án cuối cùng.  
* **Kết quả Tool lớn:** Văn bản của một trang web đã quét được lưu thành blob; hội thoại chỉ giữ trích đoạn và tham chiếu.

## **3.7 Durable Worker & Tạm dừng chờ Con người**

* **Run bền (Durable Run):** Trạng thái của đồ thị được lưu bằng Checkpoint của LangGraph sau mỗi bước. Checkpoint chỉ lưu trạng thái; Emvoox vẫn cần Worker và hàng đợi riêng để chạy và khởi động lại tiến trình. Máy chủ khởi động lại thì Run tiếp tục từ Checkpoint gần nhất.  
* **Tạm dừng (Pause & Resume):** Khi Agent gọi ask\_user hoặc một nhánh gặp bước cần duyệt, nhánh đó tạm dừng (interrupt) và trả Worker về hàng đợi; các nhánh khác tiếp tục. Câu trả lời của người dùng đưa Run trở lại hàng đợi.  
* **An toàn khi chạy lại (Idempotency):** Khi tiếp tục, bước đã tạm dừng chạy lại từ đầu, nên mọi node phải idempotent; cơ chế Cache theo Mã băm ở mục 3.2 đã đáp ứng điều này cho phần âm thanh, các thao tác ghi khác cần được rà soát.  
* **Giới hạn song song theo Provider:** Số cảnh chạy đồng thời bị chặn bởi giới hạn của nhà cung cấp (Rate Limit), nên đồ thị cần giới hạn đồng thời theo từng Provider.  

## **3.8 Lộ trình Triển khai & Các Quyết định còn mở**

Lộ trình đề xuất gồm 7 bước:

* **1\. Bản thử nghiệm LangGraph (Spike):** Chuyển riêng phần đồ thị của một tập phim sang LangGraph phía sau giao diện Engine hiện có và chạy bộ test offline hiện tại. Bốn điều cần xác nhận: cài đặt và chạy được trên Python 3.14 của dự án; các cảnh chạy song song dưới giới hạn theo Provider; hai cảnh cùng tạm dừng chờ duyệt và tiếp tục độc lập; sổ chi phí và sự kiện vẫn ghi đủ mọi lời gọi.  
* **2\. Scene-level Workflow:** Đưa QA và duyệt xuống cấp độ cảnh, thêm bước gộp và master cấp tập; chuyển tiếp cấp Series sang đồ thị.  
* **3\. Durable Worker:** Hàng đợi, Worker và Checkpoint trên cơ sở dữ liệu, có mã Tenant; tạm dừng và tiếp tục.  
* **4\. Tool Calling & Registry:** Thêm khả năng gọi Tool vào LLM Adapters, xây Tool Registry, bọc các Skill hiện có thành Tool; Market Research là Agent đầu tiên chạy theo vòng lặp.  
* **5\. Chat Interface:** Producer Agent và giao diện chat có streaming.  
* **6\. Memory:** Bộ nhớ dài hạn và Compaction.  
* **7\. SaaS:** Xác thực, phân quyền và tài liệu cho lập trình viên thêm Tool và biến thể quy trình.  

Các quyết định cần Lead Architect chốt:

* **1\. Mức độ tự chủ:** Kiến trúc lai (đề xuất) hay Agentic hoàn toàn.  
* **2\. Framework:** Kiến trúc lai LangGraph \+ mã nguồn tự chủ (đề xuất, chờ kết quả bản thử nghiệm ở bước 1) hay tiếp tục tự xây toàn bộ.  
* **3\. Hạ tầng Run:** PostgreSQL \+ hàng đợi Redis, hay đi thẳng lên v1ron\_db \+ MinIO.  
* **4\. Giao diện chat:** Một Producer Agent (đề xuất) hay chat trực tiếp với từng Agent.  
* **5\. Ghi bộ nhớ:** Agent tự ghi và con người sửa sau (đề xuất), hay đề xuất rồi chờ duyệt.  
* **6\. Các quyết định đã khóa cần điều chỉnh:** Bỏ quy tắc mỗi lần một series, chuyển lưu trữ khỏi file cục bộ, thay quyết định không dùng LangGraph (State Machine tự xây làm tầng điều phối).

# **PHẦN 4: ĐÁNH GIÁ RỦI RO, QUẢN TRỊ TUÂN THỦ & KẾ HOẠCH DỰ PHÒNG (RISK & FALLBACK STRATEGY)**

## **4.1 Ma trận Rủi ro & Giải pháp Dự phòng (Technical Risk Matrix)**

| Lĩnh vực Rủi ro | Sự cố Kỹ thuật Tiềm ẩn | Mức độ Báo động | Giải pháp Khắc phục (Fallback Strategy) |
| :---- | :---- | :---- | :---- |
| Agent Loop Cost | Agent gọi mô hình và Tool nhiều lần hơn pipeline cố định, chi phí khó đoán | **CAO** | Trần ngân sách cứng theo Run và theo Tenant, giới hạn số bước; Tool tốn phí luôn cần duyệt |
| API Rate Limit / Outage | Nhà cung cấp TTS/LLM bị quá tải hoặc nghẽn mạng (HTTP 429/503) | **CAO** | Thử lại có giãn cách; chuyển đổi Adapter dự phòng theo Engine Policy (VD: Gemini TTS \-\> WaveSpeed MiniMax \-\> ElevenLabs) |
| Parallel Scene Overload | Nhiều cảnh chạy song song vượt giới hạn của nhà cung cấp, gây lỗi 429 hàng loạt | **CAO** | Giới hạn đồng thời theo từng Provider trong đồ thị; thử lại có giãn cách |
| Wrong Tool Call | Mô hình yếu chọn sai Tool hoặc bịa tham số | **CAO** | Kiểm tra tham số bằng Pydantic Schema, Permission Gate, dùng mô hình đủ mạnh cho các Agent chạy vòng lặp |
| Prompt Injection | Trang web được quét chứa văn bản ra lệnh cho Agent | **CAO** | Coi nội dung quét là dữ liệu, không phải chỉ dẫn; Tool ghi và Tool tốn phí cần người duyệt |
| Tenant Data Leak | Bộ nhớ hoặc dữ liệu của Tenant này lọt sang Tenant khác | **CAO** | Mã Tenant trên mọi khóa và bản ghi; mọi truy vấn lọc theo Tenant; bộ nhớ không dùng chung |
| Worker Crash | Máy chủ khởi động lại khi Run đang chạy | **TRUNG BÌNH** | Checkpoint sau mỗi bước, node idempotent, tự tiếp tục từ Checkpoint gần nhất |
| Framework Dependency | LangGraph thay đổi API hoặc chưa tương thích phiên bản Python của dự án | **TRUNG BÌNH** | Chỉ dùng LangGraph cho tầng đồ thị, Agent là hàm thuần nên thay thế được; xác nhận bằng bản thử nghiệm trước khi chuyển đổi |
| Context Overflow | Hội thoại dài và kết quả Tool lớn vượt cửa sổ ngữ cảnh | **TRUNG BÌNH** | Compaction 3 mức; lưu kết quả lớn thành blob |
| Data Contract Reject | LLM trả về JSON sai định dạng Pydantic Schema | **TRUNG BÌNH** | Kích hoạt Retry; với AI Director, áp dụng chỉ đạo Rule-based sau 2 lần bị từ chối |
| QA Infinite Loop | Giọng AI liên tục bị lỗi khiến QA Re-render lặp vô tận | **TRUNG BÌNH** | Giới hạn cứng max\_retries \= 3\. Tự động chuyển về Robust Preset hoặc đẩy về Showrunner Gate xử lý |
| Platform Anti-bot | Trình duyệt đọc dữ liệu bị chặn khi quét xu hướng | **THẤP** | Ghi nhận là "blocked" và bỏ qua, không tìm cách vượt; dùng Search API hoặc cho phép nhập dữ liệu xu hướng thủ công |

## **4.2 Khung Tuân thủ Pháp lý AI tại Việt Nam**

Nhằm bảo đảm Emvoox vận hành hoàn toàn hợp pháp khi xuất bản nội dung tại thị trường Việt Nam, hệ thống tích hợp các cổng kiểm soát tuân thủ nghiêm ngặt:

* **1\. Quy định Gắn nhãn Nội dung AI (AI Watermarking):** Tự động chèn Watermark hình ảnh/âm thanh nhận diện sản phẩm AI và gắn Metadata C2PA (Machine-readable AI labeling) theo đúng quy định của Luật AI 2026 và Nghị định 142/2026/NĐ-CP.  
* **2\. Cơ chế Con người Giám sát (Showrunner QA Gatekeeper):** Mọi sản phẩm trước khi xuất bản đều phải đi qua bước chốt duyệt của Showrunner để đảm bảo nội dung không vi phạm thuần phong mỹ tục, không vi phạm bản quyền và tuân thủ các quy định quản lý thông tin trên mạng. Trong kiến trúc Agent, điều này được bảo đảm bằng việc xếp Tool xuất bản vào loại luôn cần duyệt.  
* **3\. Quy trình Gỡ bỏ Khẩn cấp (24h Kill-Switch SLA):** Tích hợp tính năng Kill-Switch trên Dashboard, cho phép gỡ bỏ toàn bộ sản phẩm trên tất cả các kênh xuất bản (YouTube, TikTok) trong vòng dưới 24 giờ khi có yêu cầu từ cơ quan quản lý nhà nước theo Luật Điện ảnh 2022\.  
* **4\. Nhật ký Kiểm toán (Audit Logs):** Mọi lời gọi Tool, mọi quyết định duyệt/từ chối và mọi thao tác ghi đều được lưu để rà soát.

# **PHỤ LỤC & ĐẦU RA NGHIỆM THU (ACCEPTANCE CRITERIA)**

## **Phụ lục 1: Bảng Tính toán Chi phí Điện toán Hệ thống (Cost per Minute Analysis)**

Dưới đây là bảng phân tích chi phí vận hành chi tiết của chuỗi sản xuất xác định trong Emvoox Engine cho mỗi 1 phút âm thanh phim ngắn hoàn chỉnh (Audio Mastered Episode):

| Thành phần Tài nguyên | Đơn vị Tiêu tốn (cho 1 phút Audio) | Đơn giá API / Hạ tầng | Chi phí Ước tính (VNĐ / Phút) |
| :---- | :---- | :---- | :---- |
| LLM Tokens (Script & Directing) | \~4,000 Input Tokens \+ 1,200 Output Tokens (Gemini 2.5 Flash) | 0.075\$ / 1M Input, 0.30\$ / 1M Output | \~35 VNĐ |
| TTS Generation (Voice Stems) | \~900 Ký tự chữ (Gemini TTS / WaveSpeed MiniMax) | 15\$ / 1M Ký tự (Gemini TTS) | \~340 VNĐ |
| Server & Processing (Local/Cloud) | \~0.05 Giờ CPU \+ Bandwidth Storage (MinIO) | Server dùng chung | \~120 VNĐ |
| **TỔNG CHI PHÍ VẬN HÀNH / PHÚT** | **1 Phút Audio Mastered Hoàn chỉnh** | **Tối ưu hóa nhờ Hash Cache** | **\~495 VNĐ / Phút** |

Bảng trên chưa gồm chi phí của vòng lặp Agent (hội thoại với người dùng, nghiên cứu thị trường nhiều lượt, tóm tắt khi Compaction). Khoản này phụ thuộc vào mô hình được chọn và số lượt mỗi Run, cần đo trên Run thật sau khi hoàn thành bước 4 của lộ trình; trần ngân sách ở mục 3.4 là cơ chế kiểm soát.

## **Phụ lục 2: Nguồn tham khảo cho Case Studies**

* **Holywater:** [Google Cloud customer story](https://cloud.google.com/customers/holywater), [Wikipedia – Holywater Tech](https://en.wikipedia.org/wiki/Holywater_Tech), [CEETV](https://ceetv.net/readItem?id=77185).  
* **VidMuse:** [VidMuse 2.0 release](https://vidmuse.ai/blog/vidmuse-2-0-release), [What is VidMuse](https://vidmuse.ai/docs/getting-started/what-is-vidmuse.md), [Music-Native AI Video Agent](https://vidmuse.ai/feature/music-to-video-ai).  
* **ZhiHuoLun / 智火轮 AI:** [Bài tự giới thiệu trên Zhihu](https://zhuanlan.zhihu.com/p/2062152526040978242).
