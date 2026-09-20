import pytest

from pipeline.text.vi_normalize import normalize_vi, number_to_vi


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "không"),
        (5, "năm"),
        (10, "mười"),
        (15, "mười lăm"),
        (21, "hai mươi mốt"),
        (24, "hai mươi tư"),
        (25, "hai mươi lăm"),
        (100, "một trăm"),
        (105, "một trăm lẻ năm"),
        (115, "một trăm mười lăm"),
        (1000, "một nghìn"),
        (1005, "một nghìn không trăm lẻ năm"),
        (1500000, "một triệu năm trăm nghìn"),
        (2000000000, "hai tỷ"),
    ],
)
def test_number_to_vi(n, expected):
    assert number_to_vi(n) == expected


def test_currency_time_date_and_contractions():
    s = "Anh nợ em 1.500.000đ từ 21h30 hôm 12/3, ko quên đâu"
    out = normalize_vi(s)
    assert "một triệu năm trăm nghìn đồng" in out
    assert "hai mươi mốt giờ ba mươi" in out
    assert "ngày mười hai tháng ba" in out
    assert "không quên đâu" in out
    assert out.endswith(".")


def test_chat_units_percent_ordinal():
    out = normalize_vi("Giảm 50% cho đơn 200k, lần thứ 4 rồi")
    assert "năm mươi phần trăm" in out
    assert "hai trăm nghìn" in out
    assert "thứ tư" in out


def test_tags_preserved_and_nfc():
    decomposed = "[sighs] Tôi nợ 3 người."  # 'ợ' may be decomposed in real input
    out = normalize_vi(decomposed)
    assert out.startswith("[sighs]")
    assert "ba người" in out


def test_phone_digits():
    out = normalize_vi("gọi 0901234567")
    assert out.startswith("gọi không chín không một")


def test_decimal_comma():
    assert "ba phẩy năm" in normalize_vi("3,5 điểm")
