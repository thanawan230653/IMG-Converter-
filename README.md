Image Converter (Single File)
============================

- เลือกได้ทีละ 1 ไฟล์เท่านั้น (ไม่มี list ใหญ่ๆ)
- UI เล็กลง ใช้ง่าย ปุ่มครบ

ไฟล์ในแพ็ก:
- image_converter_gui_singlefile.py   (ตัวโปรแกรม GUI)
- run.bat         (ดับเบิลคลิกบน Windows เพื่อเปิด)
- README.txt

สิ่งที่ต้องมี:
- Python 3.8+ (ติดตั้งจาก python.org)
- Pillow (ติดตั้งครั้งเดียว):
    pip install pillow

วิธีใช้ (Windows):
1) แตก ZIP
2) ดับเบิลคลิก run.bat
3) กด “เลือกไฟล์...” → ตั้งค่า Output/Resize → Convert

หมายเหตุ:
- ถ้าอยากให้เป็น .exe คลิกแล้วรันได้เลย: ทำบน Windows ด้วย PyInstaller (ต้องมีเน็ตเพื่อ pip install)
    pip install pyinstaller
    pyinstaller --noconsole --onefile image_converter_gui_singlefile.py
