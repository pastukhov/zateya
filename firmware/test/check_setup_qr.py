"""Run after native test_screen_ui; requires Pillow and zxing-cpp."""
from PIL import Image
import zxingcpp

screen = Image.open("/tmp/zateya-setup-screen.ppm")
expected = "WIFI:T:nopass;S:Zateya-Setup-80;;"
for angle in (0, 90, 180, 270):
    result = zxingcpp.read_barcode(screen.rotate(angle, expand=True))
    assert result is not None and result.text == expected, (angle, result)
print("Setup Wi-Fi QR decoded correctly at all four rotations")
screen.resize((405, 720), Image.Resampling.NEAREST).save("/tmp/zateya-setup-qr.png")
