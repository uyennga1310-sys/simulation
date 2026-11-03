# Mô phỏng cảm biến dòng điện xoáy mạch in — AEDT 2021 R1

Chạy `ECT_Maxwell_2021R1.py` bằng **Tools → Run Script** trong Ansys Electronics Desktop, với IronPython đi kèm. Không chạy script bằng Python thông thường. Message Manager phải hiện phiên bản `PCB-FREQ-2021R1-1`.

## Thông số lấy từ PowerPoint

Tài liệu `hieu [Autosaved].pptx` hướng dẫn một cuộn dây khối và mẫu có khuyết tật, không phải bản thông số chế tạo PCB. Các ảnh có nhãn 2022 R2, nên chưa xác nhận được mọi API trên 2021 R1.

| Nội dung | Tài liệu | Áp dụng trong mã |
|---|---|---|
| Bộ giải | Transient, slide 4 | Giữ tùy chọn; mặc định đổi sang EddyCurrent để quét điều hòa |
| Vật liệu | Copper và C45/aluminum, slide 9 | Hỗ trợ cả hai loại mẫu; không đoán mẫu tên `specimen` là thép |
| Terminal | Section YZ/XZ, separate bodies, giữ một mặt cắt; slide 12–13 | Cần mặt cắt thực sự của đường dẫn dòng; không dùng mặt PCB bất kỳ |
| Kích thích | `pwl(vuong, Time)`, slide 14/ảnh winding | Không tái tạo dữ liệu xung từ ảnh; file dữ liệu đầy đủ chưa được cung cấp |
| Lưới cuộn | 0,03 mm; giới hạn thêm 20000 phần tử, slide 15 | Mốc 0,03 mm; tự làm nhỏ theo độ sâu thấm/độ dày đồng; không áp giới hạn 20000 vì dễ chặn tinh chỉnh |
| Thời gian | Dừng 0,005 s; bước 200 µs, ảnh setup | Không dùng để mô phỏng 100 kHz: bước lớn hơn chu kỳ. Transient sinus dùng 100 bước/chu kỳ và 10 chu kỳ, cần kiểm tra ổn định |
| Trường | MagB và Bz, slide 19–23 | Có thể xem tại từng nghiệm tần số; pha phải thống nhất khi so sánh |

Ảnh kích thước có một thao tác cylinder (R=5 mm, chiều cao −0,66 mm, tâm 0/7/3 mm), không đủ định nghĩa toàn bộ cảm biến PCB. Mã giữ hình học nhập từ CAD, không thay bằng cuộn khối đó.

## Mặc định đề xuất — không phải thông số đo trong PowerPoint

- 9 điểm cách đều theo logarithm từ **10 kHz đến 1 MHz**; chỉnh `SWEEP_START_HZ`, `SWEEP_STOP_HZ`, `SWEEP_POINTS` nếu cần.
- Nguồn dòng 0,1 A, pha 0°. Giữ nguyên quy ước biên độ của AEDT, không tự đổi peak/RMS.
- Đồng dày **0,035 mm là giả định để đặt lưới**. `COPPER_THICKNESS_MM` phải khớp CAD/stackup; biến này không thay đổi hình học.
- Copper: σ=5,8e7 S/m. C45: μr=100 và σ=4e6 S/m, tuyến tính. Aluminum: σ=3,5e7 S/m, không đại diện chính xác mọi hợp kim. FR4: εr=4,4. Các giá trị này cần thay bằng dữ liệu vật liệu thực tế khi định lượng.
- Mỗi tần số có setup `Freq_001`…`Freq_009` riêng: sai số mục tiêu 1%, tối đa 10 adaptive passes. Tới giới hạn pass không có nghĩa là hội tụ.
- Giới hạn chiều dài lưới đồng là min(0,03 mm, chiều dày/2, skin depth/2). Mẫu dùng min(0,03 mm, skin depth/2), tính ở tần số cao nhất.

## Cách chạy

1. Tải script mới, chạy trong AEDT và chọn `.x_t` hoặc `.x_b`.
2. Script nhận diện vật liệu từ tên/vật liệu nhập. Nếu không rõ, hộp chọn yêu cầu xác định vai trò ngay trong AEDT; không cần sửa tên trong mã. Chọn C45 chỉ khi mẫu thực sự là C45.
3. Chọn đúng mặt cắt TX. Mặc định quét chỉ hỗ trợ **một cuộn dẫn thực với một terminal cross-section**, như ví dụ một cuộn trong tài liệu. Các vòng đã có trong CAD nên không nhân thêm số vòng. Chế độ EddyCurrent dùng nguồn dòng trực tiếp và `SensorMatrix`; không dùng API coil terminal của Transient.
4. Nếu CAD không chứa mặt cắt terminal, cần bổ sung mặt cắt vào đầu vào CAD (bảo đảm xuất được sheet), hoặc chuẩn bị mô hình/terminal trong AEDT theo slide 12 rồi yêu cầu chỉnh script để dùng design hiện có. Script hiện tạo design mới; tạo sheet trong một design khác rồi chạy lại sẽ không tự mang sheet sang. Chưa có file `.x_t` trong chat nên chưa thể tự chọn mặt hoặc hướng dòng theo hình học thật.
5. Project mới được lưu cạnh CAD với tên có thời gian, không ghi đè project cũ. Validation phải qua trước khi giải. `AUTO_SOLVE=False`: kiểm tra mô hình rồi chọn **Analyze All**; hoặc đặt True để script chạy lần lượt các setup đã tạo.
6. Trong Results, tạo báo cáo EddyCurrent/Data Table, chọn **SensorMatrix**, lấy R và L của TX_Current cho từng setup/tần số. Tính `Z = R + j·2πfL` (L đổi về H). Mã chưa tự xuất CSV hay tính ΔZ.
7. Chạy hai hình học cùng điều kiện (có/không khuyết tật), so sánh ΔR, ΔL hoặc ΔZ. Xem MagB/Bz với cùng tần số, pha và thang màu.

## Giới hạn cần kiểm tra

Lưới thể tích nhỏ trên toàn mẫu có thể rất tốn RAM, nhất là C45 ở 1 MHz. Mặc định chưa tự giải; hãy kiểm tra kích thước mẫu và tài nguyên. Khi tối ưu bằng skin-depth mesh/lưới cục bộ, phải kiểm chứng hội tụ trước khi dùng kết quả. Chưa có kích thước CAD nên không thể bảo đảm chi phí giải.

Quét EddyCurrent là mô hình gần đúng từ trường biến thiên chậm, không mô tả điện dung ký sinh giữa các vòng, tự cộng hưởng, bức xạ hay đường truyền PCB. Đặt FR4 không làm xuất hiện các hiệu ứng đó. Nếu cần vùng cộng hưởng/RF, dùng HFSS hoặc mô hình điện từ–mạch phù hợp; không chỉ tăng tần số của Maxwell.

Không xem kết quả TX/RX riêng là đã được xác minh: chế độ quét hiện chặn RX terminal thay vì trả điện áp thu giả định. Nhánh Transient còn giữ cấu hình winding TX/RX nhưng chưa được kiểm chứng trên AEDT. Xung thực nghiệm cần file dữ liệu, không thể khôi phục đủ từ ảnh PPT.

## Kiểm tra đã thực hiện

`python3 -m unittest discover -s tests -v`: kiểm tra dải quét, dữ liệu không hợp lệ, công thức skin depth, phân biệt vật liệu và tạo một setup cho mỗi tần số. Đây là kiểm tra offline; không xác minh COM API, import CAD, mesh hay kết quả vật lý trên Ansys 2021 R1. Cần chạy thực tế trên máy có AEDT và hình học của bạn.
