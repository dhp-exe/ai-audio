# Nghiên cứu chi phí và giá TTS: ElevenLabs, MiniMax và Gemini

| | |
|---|---|
| Mục đích | Chọn nhà cung cấp TTS và gói dịch vụ để sản xuất mỗi ngày một truyện audio dài 30 phút bằng pipeline của chúng ta |
| Ngày | 22-09-2026 (giá và giới hạn kiểm tra ngày 21-09-2026 trên trang của các nhà cung cấp; xem mục Nguồn) |
| Phụ trách | Nhóm sản phẩm / pipeline |
| Trạng thái | Đề xuất sẵn sàng để quyết định (mục 8) |

Bản tiếng Anh: `Cost_and_Pricing_Research.md`.

---

## 1. Tóm tắt

- **Gemini TTS rẻ nhất, cách biệt rất xa**: khoảng 0,50 đến 0,95 USD cho một ngày 30 phút (14 đến 28 USD một tháng) khi đã bật thanh toán. Gói miễn phí không đủ cho mục tiêu hằng ngày (10 yêu cầu mỗi ngày cho mỗi model).
- **ElevenLabs biểu cảm nhất và là nơi duy nhất đang có giọng của các Character IP**, khoảng 3,20 USD một ngày. Nhịp sản xuất hằng ngày cần **gói Pro (99 USD/tháng)**; tùy cách tính hạn mức của gói (xem 3.1), chi phí thực mỗi tháng là 99 đến khoảng 165 USD.
- **MiniMax ở giữa** (1,90 đến 3,20 USD một ngày, 58 đến 96 USD một tháng trả theo dùng), có khả năng đặt khoảng nghỉ chính xác tốt nhất và nhân bản giọng rẻ nhất, nhưng **hiện chưa được tích hợp trong pipeline** (adapter đã gỡ ngày 20-09-2026).
- **Cấu hình tối ưu**: sản xuất các tập hằng ngày trên **Gemini 2.5 Flash TTS (gói trả phí)**, khoảng 14 USD một tháng. Mỗi series chỉ render đúng một lần, trên một engine được chọn trước khi bắt đầu sản xuất; ElevenLabs Pro dành cho series bắt buộc phải ra mắt bằng giọng Character IP ngay từ tập đầu. Chi tiết ở mục 8.

---

## 2. Quy mô cần tính

Các con số dưới đây lấy từ sổ ghi (ledger) của chính pipeline trên hai series đã sản xuất.

| Đại lượng | Giá trị | Cơ sở |
|---|---|---|
| Audio hoàn thiện mỗi ngày | 1.800 giây (30 phút) | mục tiêu |
| Số từ mỗi giây của bản master | 3,3 đến 3,8 | đo thực tế |
| Ký tự TTS mỗi giây của bản master (gồm tag) | 15 đến 18 | đo thực tế |
| **Ký tự mỗi ngày** | **≈ 32.000** (28k đến 35k kể cả thử lại) | suy ra |
| Ký tự mỗi tháng (30 ngày) | ≈ 1.000.000 | suy ra |
| Audio mỗi tháng | 15 giờ | suy ra |
| Số câu thoại mỗi ngày | ≈ 500 | 8 đến 12 câu cho mỗi tập 60 giây |
| Số yêu cầu mỗi ngày, Gemini gộp theo cảnh | 60 đến 90 | 1 đến 3 cho mỗi tập |
| Số yêu cầu mỗi ngày, ElevenLabs theo từng câu | ≈ 500 (≈ 80 đến 100 với Text to Dialogue, dự kiến) | |
| Chi phí LLM (outline, draft, direct trên gemini-3.1-flash-lite) | ≈ 5 USD mỗi tháng | ledger |

Stem được cache theo hash nội dung, nên chạy lại một tập không đổi không tốn gì; chỉ khi sửa lời thoại hoặc đổi giọng mới tốn thêm.

---

## 3. Cách tính tiền của từng nhà cung cấp

### 3.1 ElevenLabs

- **Đơn vị**: số ký tự gửi đi, tính bằng credit. Trên Eleven v3 và Multilingual v2, 1 ký tự = 1 credit (0,10 USD cho 1.000 ký tự). Flash v2.5 và Turbo v2.5 tốn 0,5 credit mỗi ký tự (0,05 USD cho 1.000). Các audio tag như `[sighs]` cũng tính là ký tự (khoảng 8 phần trăm lượng chữ của chúng ta).
- **Mô hình**: thuê bao tháng kèm hạn mức credit, cộng phí vượt mức trên các gói trả phí (khoảng 0,17 đến 0,20 USD cho 1.000 credit tùy gói). Thanh toán theo năm rẻ hơn khoảng 17 phần trăm.
- **Giới hạn theo gói**: giọng thư viện và giọng nhân bản qua API cần gói trả phí (khóa Free của chúng ta nhận `402 paid_plan_required`, đã thấy thực tế). Professional Voice Cloning bắt đầu từ Creator. Xuất PCM/WAV 44,1 kHz và MP3 192 kbps cần Pro trở lên (adapter của chúng ta tự chuyển sang MP3 128 kbps ở gói thấp hơn).
- **Điểm chưa khớp cần xác nhận khi thanh toán**: trang giá API liệt kê hạn mức theo *ký tự* (Starter 60.000; Creator 220.000; Pro 990.000) trong khi trang gói chung liệt kê theo *credit* (Starter 30.000; Creator khoảng 100.000 đến 121.000; Pro 600.000; Scale 1.800.000). Tài liệu này ghi cả hai ở những chỗ làm thay đổi kết luận. Khi đã đăng ký, endpoint thuê bao mà trang Usage đọc là nguồn chuẩn.

| Gói | Giá tháng | Hạn mức (trang API, ký tự) | Hạn mức (trang gói, credit) | Điểm đáng chú ý |
|---|---|---|---|---|
| Free | 0 USD | 10.000 | 10.000 | Chỉ giọng có sẵn qua API; không có giấy phép thương mại |
| Starter | 6 USD | 60.000 | 30.000 | Giấy phép thương mại, Instant Voice Cloning |
| Creator | 22 USD (11 USD tháng đầu) | 220.000 | ~100.000 | Professional Voice Cloning (1 chỗ), MP3 192 kbps |
| Pro | 99 USD | 990.000 | 600.000 | PCM 44,1 kHz qua API, PVC (1) |
| Scale | 299 USD | 2.990.000 | 1.800.000 | PVC (3), 3 chỗ ngồi |
| Business | 990 USD | 9.900.000 | 6.000.000 | PVC (10), 10 chỗ ngồi |

### 3.2 Gemini TTS (Gemini API)

- **Đơn vị**: token. Văn bản đầu vào 0,50 đến 1,00 USD cho một triệu token; audio đầu ra 10 đến 20 USD cho một triệu *audio token*, trong đó 1 giây audio = 25 token. Vậy 30 phút audio = 45.000 token đầu ra.
- **Mô hình**: trả theo dùng, không thuê bao; phải bật thanh toán trên dự án Google Cloud. Bậc Batch API (bất đồng bộ) rẻ hơn 50 phần trăm nhưng pipeline của chúng ta render đồng bộ.
- **Gói miễn phí**: cả hai model Flash TTS miễn phí khi chưa bật thanh toán nhưng giới hạn khoảng 3 yêu cầu mỗi phút và **10 yêu cầu mỗi ngày cho mỗi model** (đã thấy thực tế dưới tên `GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Với gộp theo cảnh, tức là 3 đến 10 tập mỗi ngày, không phải 30. Giới hạn của các bậc trả phí hiển thị theo dự án trong AI Studio; Bậc 1 mở ngay khi liên kết thanh toán.
- **Trạng thái**: cả ba model TTS đều là bản "preview".

| Model | Gói miễn phí | Trả phí: chữ vào / audio ra cho 1 triệu token | Ghi chú |
|---|---|---|---|
| gemini-2.5-flash-preview-tts | có (10 yêu cầu/ngày) | 0,50 / 10 USD | giọng thế hệ trước, rẻ nhất |
| gemini-3.1-flash-tts-preview | có (10 yêu cầu/ngày) | 1,00 / 20 USD | mặc định hiện tại của pipeline, giọng mới nhất, hỗ trợ tag trong dòng |
| gemini-2.5-pro-preview-tts | không | 1,00 / 20 USD | chất lượng cao nhất của dòng |

### 3.3 MiniMax (Speech API)

- **Đơn vị**: ký tự, trả theo dùng: **speech-2.8-turbo 60 USD cho một triệu ký tự, speech-2.8-hd 100 USD cho một triệu** (các thế hệ 2.6 và 02 cùng giá). Nhân bản giọng thu phí một lần cho mỗi giọng: Rapid Voice Cloning 1,50 USD, Voice Design 3,00 USD.
- **Thuê bao ("audio points")**: gói tháng với hạn mức điểm và giới hạn yêu cầu mỗi phút (RPM). MiniMax không công bố tỷ lệ quy đổi điểm sang ký tự cho HD so với Turbo; gói miễn phí "10.000 điểm ≈ 12 phút audio HD" ngụ ý khoảng 1 điểm mỗi ký tự trên HD. Credit đã mua nay hết hạn sau hai tháng.

| Gói | Giá tháng | Audio points | RPM | Số giọng |
|---|---|---|---|---|
| Free | 0 USD | 10.000 | | 3 |
| Starter | 5 USD | 100.000 | 10 | 10 |
| Standard | 30 USD | 300.000 | 50 | 100 |
| Pro | 99 USD | 1.100.000 | 200 | 250 |
| Scale | 249 USD | 3.300.000 | 500 | 500 |
| Business | 999 USD | 20.000.000 | 800 | 800 |

Các bản tổng hợp của bên thứ ba ghi giá gói hơi khác (Standard 17 USD, Pro 38 USD); bảng trên dùng tài liệu chính thức của MiniMax.

---

## 4. Chất lượng đầu ra và mức độ điều khiển cảm xúc

Điều quan trọng với micro-drama của chúng ta: hỗ trợ tiếng Việt, cách chỉ đạo diễn xuất (tag, prompt, tham số số học), render hội thoại nhiều giọng trong một yêu cầu, và giọng có thể là *của chúng ta* hay không (nhân bản). Đạo diễn AI của pipeline đã sinh cảm xúc, cường độ 1 đến 10, nhịp, âm lượng, tag và ghi chú diễn xuất tự do cho từng câu; câu hỏi là mỗi engine tận dụng được bao nhiêu trong số đó.

| Khả năng | ElevenLabs Eleven v3 | ElevenLabs Flash v2.5 | Gemini 3.1 / 2.5 Flash TTS | MiniMax speech-2.8 |
|---|---|---|---|---|
| Tiếng Việt | có (hơn 70 ngôn ngữ) | có (32 ngôn ngữ) | có (hơn 80 ngôn ngữ) | có (~40 ngôn ngữ, `language_boost: Vietnamese`) |
| Chỉ đạo cảm xúc | audio tag trong dòng (`[sighs]`, `[whispers]`, `[crying]`, `[shouting]`…); cách đọc bám theo dấu câu và ngữ cảnh | không có gì ngoài văn bản | ghi chú đạo diễn bằng ngôn ngữ tự nhiên (phong cách, bối cảnh, nhịp) cộng tag trong dòng (`[whispers]`, `[laughs]`, `[sighs]`, `[gasp]`) | tham số `emotion` với 9 giá trị (happy, sad, angry, fearful, disgusted, surprised, calm, fluent, whisper) cộng tag cảm thán (`(laughs)`, `(sighs)`) trên 2.8 |
| Tham số số học | stability (Creative / Natural / Robust), similarity | stability, similarity, style, speed | không (chỉ prompt) | speed 0,5 đến 2, volume, pitch −12 đến +12 |
| Khoảng nghỉ chính xác | không (chỉ tag; pipeline chèn khoảng lặng khi dựng) | không | không (pipeline chèn khoảng lặng) | **có**: đánh dấu nghỉ trong dòng `<#1.5#>` |
| Nhiều giọng trong một yêu cầu | Text to Dialogue: tối đa 10 giọng, 2.000 ký tự, mốc thời gian theo từng câu | không | tối đa 2 người nói mỗi yêu cầu | không (một giọng mỗi yêu cầu) |
| Giọng | hàng nghìn (thư viện cần gói trả phí), nhân bản tức thì và chuyên nghiệp | như trên | 30 giọng có sẵn, không nhân bản | giọng hệ thống, nhân bản 1,50 USD mỗi giọng, thiết kế giọng 3 USD |
| Văn bản tối đa mỗi yêu cầu | 5.000 ký tự | 40.000 | phiên 32k token | 10.000 ký tự |
| Độ biểu cảm (đánh giá của chúng ta) | cao nhất: đã kiểm chứng dải cảm xúc tiếng Việt trên các giọng tạm của IP | thấp, đều đều | cao theo phong cách prompt, có nhịp phản ứng bên trong một chunk; đã kiểm chứng chỉ dẫn không bị đọc thành tiếng | trung bình đến cao; danh sách cảm xúc thô nhưng ổn định, khoảng nghỉ chính xác |
| Trạng thái trong pipeline | đã tích hợp, đã kiểm chứng thực tế | đã tích hợp (cùng adapter) | đã tích hợp, gộp theo cảnh, đã kiểm chứng thực tế với một người nói | chưa tích hợp (gỡ ngày 20-09-2026; adapter mất 1 đến 2 ngày) |

Hai sự thật làm thay đổi lựa chọn model:

- **ElevenLabs Multilingual v2 không liệt kê tiếng Việt.** Đây đang là model dự phòng cùng giọng của chúng ta. Flash v2.5 hỗ trợ tiếng Việt và rẻ bằng nửa; nên dùng làm dự phòng.
- **Bản sắc giọng chính là sản phẩm.** Chỉ ElevenLabs (hiện tại) và MiniMax (giá rẻ) mới mang được giọng Character IP nhân bản. 30 giọng cố định của Gemini đủ cho sản xuất hằng ngày nhưng không thể trở thành tài sản IP. Vì vậy engine được chọn cho từng series trước khi bắt đầu sản xuất: một series chỉ render một lần, trên một engine, và không bao giờ render lại trên engine khác.

---

## 5. Chi phí mỗi ngày và mỗi tháng với 30 phút mỗi ngày

Mọi con số tính cho ≈ 32.000 ký tự và 1.800 giây audio mỗi ngày; chi phí LLM (≈ 5 USD mỗi tháng) giống nhau cho mọi phương án nên không tính vào.

| Nhà cung cấp và model | Mỗi ngày | Mỗi tháng (30 ngày) | Gói hoặc thanh toán cần có | Đủ cho nhịp hằng ngày? |
|---|---|---|---|---|
| Gemini 2.5 Flash TTS (trả phí) | 0,47 USD | **14 USD** | bật thanh toán, trả theo dùng | có |
| Gemini 3.1 Flash TTS (trả phí) | 0,93 USD | **28 USD** | như trên | có |
| Gemini 2.5 Pro TTS (trả phí) | 0,93 USD | 28 USD | như trên | có |
| Gemini Flash TTS (gói miễn phí) | 0 USD | 0 USD | không cần | **không**: 3 đến 10 tập mỗi ngày |
| Gemini, bậc Batch API | 0,24 đến 0,47 USD | 7 đến 14 USD | thanh toán; render bất đồng bộ (chưa triển khai) | phương án tương lai |
| MiniMax speech-2.8-turbo (trả theo dùng) | 1,92 USD | **58 USD** | trả theo dùng | có (cần adapter) |
| MiniMax speech-2.8-hd (trả theo dùng) | 3,20 USD | **96 USD** | trả theo dùng | có (cần adapter) |
| MiniMax thuê bao Pro | | 99 USD | 1,1 triệu điểm; giả định ≈ 1 điểm mỗi ký tự | có, quy đổi chưa kiểm chứng |
| ElevenLabs Flash v2.5 | 1,60 USD | 48 USD | Creator (220k ký tự) không đủ; cần Pro | chất lượng quá đều đều cho kịch |
| ElevenLabs Eleven v3 | 3,20 USD | **96 USD mức dùng** | Pro 99 USD (đủ nếu 990k ký tự; nếu 600k credit thì Pro + ≈ 65 USD vượt mức ≈ 165 USD, hoặc Scale 299 USD) | có |
| ElevenLabs Eleven v3 gói Free | | | 10.000 credit ≈ 8 phút mỗi tháng; giọng thư viện bị chặn | không |

Cách tính số của Gemini: 1.800 giây × 25 token = 45.000 audio token mỗi ngày; ở mức 10 USD cho một triệu là 0,45 USD (2.5 Flash), hoặc 0,90 USD ở mức 20 USD cho một triệu (3.1 Flash, 2.5 Pro). Văn bản đầu vào khoảng 30.000 token mỗi ngày kể cả phần chỉ dẫn đầu mỗi chunk, 0,015 đến 0,03 USD.

### Các kịch bản theo tháng

Mỗi series chỉ render một lần; các kịch bản chỉ khác nhau ở engine được chọn trước khi sản xuất.

| Kịch bản | Chạy gì ở đâu | Chi phí TTS mỗi tháng |
|---|---|---|
| A. Toàn bộ Gemini | mọi tập trên 2.5 Flash TTS (hoặc 3.1) | 14 đến 28 USD |
| B. Toàn bộ ElevenLabs v3 | mọi tập trên giọng IP | 99 đến 165 USD |
| C. Toàn bộ MiniMax turbo | mọi tập, giọng nhân bản | 58 USD (+ 1,50 USD một lần cho mỗi giọng) |
| D. Phân vai hỗn hợp | vai chính trên ElevenLabs v3, vai phụ trên Gemini, trong cùng một series | ≈ 55 đến 70 USD |
| E. Chọn theo từng series | phần lớn series trên Gemini; series bắt buộc ra mắt bằng giọng IP thì sản xuất trên ElevenLabs từ tập 1 | 14 đến 28 USD trong tháng chỉ có Gemini; 99 đến 165 USD trong tháng có series ElevenLabs |

---

## 6. Kết luận theo từng nhà cung cấp

**ElevenLabs.** Dải diễn xuất tốt nhất và là engine duy nhất đang chứa giọng IP của chúng ta cùng nhân bản chuyên nghiệp mà nhánh giọng nói cần. Đắt hơn Gemini khoảng 3,5 đến 7 lần. Chỉ mua Pro cho tháng có series được sản xuất bằng giọng IP ngay từ tập đầu; Creator (22 USD, 220k ký tự) đủ cho khoảng 7 tập hằng ngày mỗi tháng cộng PVC và là gói phù hợp cho chính các thí nghiệm nhân bản.

**Gemini TTS.** Đường sản xuất rẻ nhất, chênh cả một bậc, và đã là mặc định của pipeline với gộp theo cảnh. Hạn chế: model preview, 30 giọng cố định, hai người nói mỗi yêu cầu, không nhân bản, hạn mức chỉ hữu dụng khi bật thanh toán. Lựa chọn đúng cho sản xuất hằng ngày, nơi sản lượng quan trọng hơn bản sắc giọng. Ưu tiên 2.5 Flash TTS với giá bằng nửa, trừ khi nghe thử cho thấy giọng của 3.1 tốt hơn.

**MiniMax.** Đáng giữ trong danh sách nhờ hai tính năng không ai khác có ở mức giá này: khoảng nghỉ chính xác trong dòng và nhân bản giọng 1,50 USD. Phù hợp làm nơi chứa giọng tùy chỉnh giá rẻ cho nhánh nhân bản nếu PVC của ElevenLabs quá đắt cho mỗi chỗ. Chi phí tiếp nhận là một adapter và kiểm định lại ánh xạ cảm xúc; chưa cần cho kế hoạch hiện tại.

---

## 7. Rủi ro và những điều cần xác minh trước khi chi tiền

1. Hạn mức gói ElevenLabs: xác nhận khi thanh toán Pro gồm 990k ký tự hay 600k credit; điều này quyết định 99 hay khoảng 165 USD mỗi tháng.
2. Giới hạn yêu cầu bậc trả phí của Gemini chỉ thấy trong AI Studio sau khi bật thanh toán; xác nhận cho phép 60 đến 90 yêu cầu TTS mỗi ngày trước khi lên lịch.
3. Chunk nhiều người nói của Gemini chưa được kiểm chứng thực tế (hạn mức miễn phí đã cạn); một ngày thử có trả phí sẽ giải quyết.
4. Quy đổi điểm sang ký tự của MiniMax chưa công bố; nếu có lúc cân nhắc thuê bao, chạy thử 1.000 ký tự rồi đọc số dư.
5. Model preview có thể đổi chất lượng giọng mà không báo trước; giữ các clip thử trong `library/previews/` làm mốc tham chiếu.

---

## 8. Đề xuất

1. **Bật thanh toán trên dự án Gemini ngay** và chạy nhịp 30 phút hằng ngày trên **gemini-2.5-flash-preview-tts** với gộp theo cảnh. Ngân sách: khoảng 14 USD một tháng (khoảng 28 USD nếu sau khi nghe thử chọn 3.1 Flash). Việc này mở khóa mục tiêu hằng ngày ngay lập tức mà không cần đổi mã.
2. **Lấy ElevenLabs Creator (22 USD) cho nhánh nhân bản giọng** (Professional Voice Cloning, giọng thư viện, 220k ký tự để thử giọng) và **chỉ nâng lên Pro (99 USD) trong tháng có series được sản xuất bằng giọng IP ngay từ tập đầu**. Đổi model dự phòng cùng giọng từ Multilingual v2 sang Flash v2.5.
3. **Chưa đưa MiniMax trở lại.** Xem xét lại nếu nhánh nhân bản cần nhiều giọng tùy chỉnh giá rẻ hoặc khoảng nghỉ chính xác trong dòng trở thành yêu cầu chất lượng; chi phí adapter nhỏ.
4. **Quyết định engine cho từng series trước khi sản xuất và không bao giờ render một series hai lần.** Lồng lại giọng cho một series đã xong trên engine khác sẽ nhân đôi chi phí TTS của series đó; cache theo hash của pipeline đã bảo đảm một tập không đổi không bao giờ bị render lại trên cùng engine.

Chi phí ổn định dự kiến theo kế hoạch này: **khoảng 14 đến 28 USD một tháng** cho sản xuất hằng ngày trên Gemini, chỉ tăng lên 99 đến 165 USD trong tháng có series ElevenLabs, so với 100 đến 165 USD mỗi tháng nếu sản xuất toàn bộ trên ElevenLabs.

---

## Nguồn

- Giá API ElevenLabs: https://elevenlabs.io/pricing/api
- Các gói ElevenLabs: https://elevenlabs.io/pricing
- Model và hỗ trợ ngôn ngữ ElevenLabs: https://elevenlabs.io/docs/overview/models
- Khả năng chuyển văn bản thành giọng nói ElevenLabs: https://elevenlabs.io/docs/overview/capabilities/text-to-speech
- Giá Gemini API: https://ai.google.dev/gemini-api/docs/pricing
- Giới hạn tốc độ Gemini API: https://ai.google.dev/gemini-api/docs/rate-limits
- Hướng dẫn tạo giọng nói Gemini: https://ai.google.dev/gemini-api/docs/speech-generation
- Giải thích giá Gemini 3.1 Flash TTS (audio token mỗi giây): https://www.nemovideo.com/blog/gemini-3-1-flash-tts-pricing
- Giá trả theo dùng MiniMax: https://platform.minimax.io/docs/guides/pricing-paygo.md
- Thuê bao audio MiniMax: https://platform.minimax.io/docs/guides/pricing-speech.md
- Tài liệu API chuyển văn bản thành giọng nói MiniMax: https://platform.minimax.io/docs/api-reference/speech-t2a-http
- Đánh giá MiniMax Speech (tổng hợp gói của bên thứ ba): https://knowara.com/ai-tools/voice/minimax-speech-review/
- Số đo của pipeline: `series/*/run.log.jsonl`, `series/*/scripts/parsed/*.json`, thời lượng master qua ffprobe (21-09-2026)
