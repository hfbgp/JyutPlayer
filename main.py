import os
import sys
import json
import tempfile
from pathlib import Path

# 1. 綁定當前資料夾與 mpv-2.dll
if getattr(sys, "frozen", False):
    CURRENT_DIR = str(Path(sys.executable).resolve().parent)
else:
    CURRENT_DIR = str(Path(__file__).resolve().parent)
src_dll = os.path.join(CURRENT_DIR, "libmpv-2.dll")
dst_dll = os.path.join(CURRENT_DIR, "mpv-2.dll")
if os.path.exists(src_dll) and not os.path.exists(dst_dll):
    try:
        import shutil; shutil.copyfile(src_dll, dst_dll)
    except Exception:
        pass

if hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(CURRENT_DIR)
    except Exception:
        pass
os.environ["PATH"] = CURRENT_DIR + os.pathsep + os.environ.get("PATH", "")

import mpv

from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QRect, QEvent
)
from PyQt6.QtGui import (
    QFont, QPainter, QColor, QFontMetrics, QFontDatabase, QCursor, QPixmap
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QFileDialog, QMenu,
    QSpinBox, QCheckBox, QDialog, QFormLayout, QDialogButtonBox,
    QMessageBox, QListWidget, QListWidgetItem, QComboBox,
    QSplitter, QColorDialog
)

CONFIG_FILE = os.path.join(CURRENT_DIR, "jyutplayer_config.json")

try:
    from blackrenderer.render import renderText
    HAS_BLACKRENDERER = True
except ImportError:
    HAS_BLACKRENDERER = False

COLR_V1_CACHE = {}

def is_colr_v1_font(font_path):
    """檢測字體是否包含 COLR V1 向量彩色表"""
    if not font_path or not os.path.exists(font_path):
        return False
    try:
        with open(font_path, "rb") as f:
            data = f.read(4096)
        if len(data) < 12: return False
        num_tables = int.from_bytes(data[4:6], "big")
        for i in range(num_tables):
            off = 12 + i * 16
            if off + 16 > len(data): break
            if data[off:off+4] == b'COLR':
                colr_off = int.from_bytes(data[off+8:off+12], "big")
                with open(font_path, "rb") as f2:
                    f2.seek(colr_off)
                    ver = int.from_bytes(f2.read(2), "big")
                    return ver == 1
    except Exception:
        pass
    return False

def render_colr_v1_pixmap(font_path, text, font_size_px):
    """使用 Skia 後端精確以物理像素渲染 COLR V1 文字（最佳化無感延遲）"""
    if not HAS_BLACKRENDERER or not font_path or not text:
        return None
    key = (font_path, text, font_size_px)
    if key in COLR_V1_CACHE:
        return COLR_V1_CACHE[key]

    tmp_png = os.path.join(tempfile.gettempdir(), f"_jyut_colr_{abs(hash(key)) % 1000}.png")
    try:
        renderText(font_path, text, tmp_png, fontSize=font_size_px, margin=0, backendName="skia")
        if os.path.exists(tmp_png):
            pm = QPixmap(tmp_png)
            if not pm.isNull():
                if len(COLR_V1_CACHE) > 1000:
                    COLR_V1_CACHE.clear()
                COLR_V1_CACHE[key] = pm
                return pm
    except Exception:
        pass
    return None

# 預設設定：預設粤黑CN V0，包含基礎色(層0)及另外4種COLR顏色層(層1~4)
DEFAULT_CONFIG = {
    "sub1_font_family": "粤黑CN V0",
    "sub1_font_size": 50,
    "sub1_text_color": "#FFFFFF",
    "sub1_color0": "#000000",
    "sub1_color1": "#001eff",
    "sub1_color2": "#0084ff",
    "sub1_color3": "#0084ff",
    "sub1_color4": "#c80000",
    "sub2_font_family": "粤黑CN V0",
    "sub2_font_size": 40,
    "sub2_text_color": "#FFE082",
    "sub2_color0": "#000000",
    "sub2_color1": "#001eff",
    "sub2_color2": "#0084ff",
    "sub2_color3": "#0084ff",
    "sub2_color4": "#c80000",
    "enable_backdrop": False,
    "enable_shadow": True,
    "shadow_offset": 3,
    "volume": 100,
    "last_dir": "",
    "convert_ass_to_srt": True
}

GRAPHIC_SUB_CODECS = {
    "hdmv_pgs_subtitle", "pgs", "dvd_subtitle", "vobsub", "dvd_sub", "dvb_subtitle"
}

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception:
          pass


def find_font_file(family_name):
    """搜尋字型名稱對應的 .ttf/.otf 實體檔案"""
    for ext in ("*.ttf", "*.otf"):
        for f in Path(CURRENT_DIR).glob(ext):
            if family_name.lower() in f.stem.lower():
                return str(f)
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    name, val, _ = winreg.EnumValue(key, i)
                    if family_name.lower() in name.lower():
                        if os.path.isabs(val): return val
                        return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", val)
    except Exception:
        pass
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if fonts_dir.exists():
        for ext in ("*.ttf", "*.otf"):
            for f in fonts_dir.glob(ext):
                if family_name.lower() in f.stem.lower():
                    return str(f)
    return ""


def patch_cpal_font(font_path, output_path, colors, sub_id=1):
    """動態覆寫字型 CPAL 色盤中的層 0~4 顏色，並修改內部名稱以防緩存衝突"""
    try:
        with open(font_path, "rb") as f:
            data = bytearray(f.read())
        if len(data) < 12: return False
        num_tables = int.from_bytes(data[4:6], "big")
        cpal_offset = 0
        name_offset = 0
        for i in range(num_tables):
            off = 12 + i * 16
            magic = data[off:off+4]
            if magic == b'CPAL':
                cpal_offset = int.from_bytes(data[off+8:off+12], "big")
            elif magic == b'name':
                name_offset = int.from_bytes(data[off+8:off+12], "big")
                
        if not cpal_offset: return False
        
        num_entries = int.from_bytes(data[cpal_offset+2:cpal_offset+4], "big")
        records_offset = int.from_bytes(data[cpal_offset+8:cpal_offset+12], "big")
        start = cpal_offset + records_offset
        for idx, color_hex in enumerate(colors):
            if idx >= num_entries: break
            c = QColor(color_hex)
            pos = start + idx * 4
            if pos + 4 <= len(data):
                data[pos] = c.blue()
                data[pos+1] = c.green()
                data[pos+2] = c.red()
                data[pos+3] = 255

        if name_offset:
            count = int.from_bytes(data[name_offset+2:name_offset+4], "big")
            string_offset = name_offset + int.from_bytes(data[name_offset+4:name_offset+6], "big")
            for i in range(count):
                record_offset = name_offset + 6 + i * 12
                if record_offset + 12 > len(data): break
                platform_id = int.from_bytes(data[record_offset:record_offset+2], "big")
                name_id = int.from_bytes(data[record_offset+6:record_offset+8], "big")
                length = int.from_bytes(data[record_offset+8:record_offset+10], "big")
                offset = int.from_bytes(data[record_offset+10:record_offset+12], "big")
                
                # 攔截 Font Family (1), Full Name (4), PostScript (6), Typographic (16)
                if name_id in (1, 4, 6, 16) and length >= 2:
                    str_pos = string_offset + offset
                    if str_pos + length <= len(data):
                        if platform_id in (0, 3) and length >= 2:  # UTF-16BE
                            data[str_pos + length - 2] = 0
                            data[str_pos + length - 1] = 48 + sub_id
                        elif length >= 1:  # ASCII/Mac
                            data[str_pos + length - 1] = 48 + sub_id

        with open(output_path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False

def convert_ass_to_srt_file(ass_path):
    """將 ASS/SSA 字幕檔案轉換為標準 SRT 臨時檔案，去除特效標籤並完整保留文本換行"""
    import re
    try:
        with open(ass_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return ass_path

    events_found = False
    format_indices = {}
    dialogues = []

    for line in lines:
        line_str = line.strip()
        if line_str.lower() == "[events]":
            events_found = True
            continue
        if events_found and line_str.lower().startswith("format:"):
            parts = [p.strip().lower() for p in line_str[7:].split(",")]
            format_indices = {name: idx for idx, name in enumerate(parts)}
            continue
        if events_found and line_str.lower().startswith("dialogue:"):
            content = line[line.find(":") + 1:].strip()
            parts = content.split(",", len(format_indices) - 1) if format_indices else content.split(",", 9)
            start_idx = format_indices.get("start", 1)
            end_idx = format_indices.get("end", 2)
            text_idx = format_indices.get("text", len(parts) - 1)

            if len(parts) > max(start_idx, end_idx, text_idx):
                start = parts[start_idx].strip()
                end = parts[end_idx].strip()
                raw_text = parts[text_idx]

                # 去除 ASS 特效標籤 {\...} 並保留換行符
                clean = re.sub(r'\{.*?\}', '', raw_text)
                clean = clean.replace(r'\N', '\n').replace(r'\n', '\n').strip()
                if clean:
                    dialogues.append((start, end, clean))

    if not dialogues:
        return ass_path

    def to_srt_time(t_str):
        p = t_str.split(":")
        if len(p) == 3:
            h = int(p[0])
            m = int(p[1])
            s, cs = p[2].split(".")
            ms = int(cs.ljust(3, "0")[:3])
            return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"
        return t_str

    tmp_srt = os.path.join(tempfile.gettempdir(), f"jyut_converted_{Path(ass_path).stem}.srt")
    try:
        with open(tmp_srt, "w", encoding="utf-8") as out:
            for idx, (s, e, txt) in enumerate(dialogues, 1):
                out.write(f"{idx}\n{to_srt_time(s)} --> {to_srt_time(e)}\n{txt}\n\n")
        return tmp_srt
    except Exception:
        return ass_path
        
class ClickableSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.width()
            if w > 0:
                pos_x = event.position().toPoint().x()
                ratio = max(0.0, min(1.0, pos_x / float(w)))
                val = int(self.minimum() + (self.maximum() - self.minimum()) * ratio)
                self.setValue(val)
                self.sliderMoved.emit(val)
        super().mousePressEvent(event)


class SubtitleOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JyutPlayer_字幕層")
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.text_primary = ""
        self.text_secondary = ""
        self.cfg = DEFAULT_CONFIG
        self.font1_actual = "粤黑CN V0"
        self.font2_actual = "粤黑CN V0"
        self.font1_path = ""
        self.font2_path = ""
        self.is_v1_sub1 = False
        self.is_v1_sub2 = False

    def update_subtitles(self, text1, text2):
        if self.text_primary != text1 or self.text_secondary != text2:
            self.text_primary = text1
            self.text_secondary = text2
            self.update()

    def set_config(self, cfg):
        self.cfg = cfg
        self._apply_font_colors()
        self.update()

    def _apply_font_colors(self):
        """為字型注入層 0~4 顏色，若為一般輪廓字體則直接套用"""
        self.font1_actual = self.cfg.get("sub1_font_family", "粤黑CN V0")
        self.font2_actual = self.cfg.get("sub2_font_family", "粤黑CN V0")
        tmp_dir = tempfile.gettempdir()

        # 主字幕：嘗試彩色字體 CPAL 注入，傳入 sub_id=1 修改內部名稱
        c1 = [self.cfg.get(f"sub1_color{i}", "#FFFFFF") for i in range(5)]
        f1_path = find_font_file(self.font1_actual)
        self.font1_path = f1_path
        self.is_v1_sub1 = is_colr_v1_font(f1_path)
        if f1_path:
            out1 = os.path.join(tmp_dir, "jyut_colr_sub1.ttf")
            if patch_cpal_font(f1_path, out1, c1, 1):
                self.font1_path = out1
                if getattr(self, 'fid1', -1) != -1:
                    QFontDatabase.removeApplicationFont(self.fid1)
                self.fid1 = QFontDatabase.addApplicationFont(out1)
                fams = QFontDatabase.applicationFontFamilies(self.fid1)
                if fams: self.font1_actual = fams[0]

        # 副字幕：嘗試彩色字體 CPAL 注入，傳入 sub_id=2 修改內部名稱
        c2 = [self.cfg.get(f"sub2_color{i}", "#FFE082") for i in range(5)]
        f2_path = find_font_file(self.font2_actual)
        self.font2_path = f2_path
        self.is_v1_sub2 = is_colr_v1_font(f2_path)
        if f2_path:
            out2 = os.path.join(tmp_dir, "jyut_colr_sub2.ttf")
            if patch_cpal_font(f2_path, out2, c2, 2):
                self.font2_path = out2
                if getattr(self, 'fid2', -1) != -1:
                    QFontDatabase.removeApplicationFont(self.fid2)
                self.fid2 = QFontDatabase.addApplicationFont(out2)
                fams = QFontDatabase.applicationFontFamilies(self.fid2)
                if fams: self.font2_actual = fams[0]

        COLR_V1_CACHE.clear()  # 顏色更新時立即清空圖形快取

    def _wrap_text_lines(self, font, text, max_w):
        """【自動換行演算法】長字幕超出畫面時自動折行，徹底防止超出螢幕與字元被切"""
        fm = QFontMetrics(font)
        final_lines = []
        for paragraph in text.split('\n'):
            if not paragraph:
                final_lines.append("")
                continue
            # 若整段未超過螢幕寬度，保持原樣
            if fm.horizontalAdvance(paragraph) <= max_w:
                final_lines.append(paragraph)
                continue
            # 超出螢幕寬度時，自動逐字計算並折行（支援中文、英文、符號）
            curr = ""
            for ch in paragraph:
                test = curr + ch
                if fm.horizontalAdvance(test) > max_w and curr:
                    final_lines.append(curr)
                    curr = ch
                else:
                    curr = test
            if curr:
                final_lines.append(curr)
        return final_lines

    def _get_balanced_width(self, font, text, max_w):
        """【平衡折行演算法】計算最佳折行寬度，使每行字數長度均勻對稱"""
        from PyQt6.QtGui import QTextLayout, QTextOption
        import math

        fm = QFontMetrics(font)
        paragraphs = text.split('\n')
        line_widths = [fm.horizontalAdvance(p) for p in paragraphs if p]
        if not line_widths:
            return max_w

        max_natural_w = max(line_widths)
        # 如果 SRT 原有各行皆未超出螢幕寬度，嚴格保留原有換行，寬度設為剛好容納最長自然行
        if max_natural_w <= max_w:
            return max_natural_w + 30

        target_lines = math.ceil(max_natural_w / max_w)
        if target_lines <= 1:
            return max_w

        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

        ideal_w = max_natural_w / target_lines
        best_w = max_w
        min_diff = float('inf')

        steps = 25
        step_val = (max_w - ideal_w) / steps if steps > 0 else 1
        for i in range(steps + 1):
            cand_w = ideal_w + i * step_val
            test_layout = QTextLayout(text, font)
            test_layout.setTextOption(opt)
            test_layout.beginLayout()
            lines = []
            while True:
                line = test_layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(cand_w)
                lines.append(line.naturalTextWidth())
            test_layout.endLayout()

            if len(lines) == target_lines:
                diff = max(lines) - min(lines)
                if diff < min_diff:
                    min_diff = diff
                    best_w = int(cand_w) + 20

        return best_w

    def _create_text_layout(self, font, text, max_w, scale_ratio, font_path="", is_v1=False, fsize_px=50):
        """按 SRT 原始段落排版：嚴格保留既有換行，僅在單行超寬時平衡折行"""
        from PyQt6.QtGui import QTextLayout, QTextOption
        from PyQt6.QtCore import QPointF

        fm = QFontMetrics(font)
        line_step = int(fm.height() * 0.85)

        paragraphs = text.split('\n')
        layouts = []
        max_total_w = 0
        total_y = 0.0

        for p in paragraphs:
            if not p:
                total_y += line_step
                continue

            # 針對每一行獨立計算折行寬度（若不超寬則保持單行）
            p_w = self._get_balanced_width(font, p, max_w)
            layout = QTextLayout(p, font)
            opt = QTextOption(Qt.AlignmentFlag.AlignHCenter)
            opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(opt)

            layout.beginLayout()
            y = 0.0
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(p_w)
                line.setPosition(QPointF(0.0, y))
                y += line_step
            layout.endLayout()

            p_h = y
            pixmap = None
            if is_v1 and font_path:
                pixmap = render_colr_v1_pixmap(font_path, p, fsize_px)
                if pixmap:
                    p_w = max(p_w, pixmap.width())
                    p_h = max(p_h, pixmap.height())

            layouts.append((layout, p_w, p_h, total_y, pixmap))
            max_total_w = max(max_total_w, p_w)
            total_y += p_h

        total_h = int(total_y - line_step + fm.height()) if total_y > 0 else 0
        return layouts, max_total_w, total_h

    def paintEvent(self, event):
        if not self.text_primary and not self.text_secondary:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        rect = self.rect()
        h_current = max(100, rect.height())
        scale_ratio = h_current / 720.0
        screen_w = max(200, rect.width())
        max_w = max(200, screen_w - 100)

        fsize1 = max(12, int(self.cfg.get("sub1_font_size", 50) * scale_ratio))
        fsize2 = max(10, int(self.cfg.get("sub2_font_size", 40) * scale_ratio))

        # 【修復切字】加入 NoSubpixelAntialias，消除透明圖層對字元左邊緣的削平裁切
        font1 = QFont(self.font1_actual, fsize1)
        font1.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias | QFont.StyleStrategy.PreferQuality)

        font2 = QFont(self.font2_actual, fsize2)
        font2.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias | QFont.StyleStrategy.PreferQuality)

        layout1, w1, h1 = (None, 0, 0)
        # 計算螢幕 DPI 比例，將點數 (Points) 換算為精確的物理像素 (Pixels) 給 Skia
        screen_dpi = QApplication.primaryScreen().logicalDotsPerInch()
        fsize1_px = int(round(fsize1 * (screen_dpi / 72.0)))
        fsize2_px = int(round(fsize2 * (screen_dpi / 72.0)))

        if self.text_primary:
            layout1, w1, h1 = self._create_text_layout(
                font1, self.text_primary, max_w, scale_ratio,
                self.font1_path, self.is_v1_sub1, fsize1_px
            )

        layout2, w2, h2 = (None, 0, 0)
        if self.text_secondary:
            layout2, w2, h2 = self._create_text_layout(
                font2, self.text_secondary, max_w, scale_ratio,
                self.font2_path, self.is_v1_sub2, fsize2_px
            )

        spacing = max(1, int(1.5 * scale_ratio)) if (h1 and h2) else 0

        total_h = h1 + spacing + h2
        bottom_margin = int(h_current * 0.05)
        base_y = h_current - bottom_margin - total_h

        # 繪製主字幕（平衡居中放置）
        if layout1:
            x1 = (rect.width() - w1) // 2
            color1 = QColor(self.cfg.get("sub1_text_color", "#FFFFFF"))
            self._render_sub_layout(painter, layout1, w1, h1, x1, base_y, color1, scale_ratio)

        # 繪製副字幕
        if layout2:
            x2 = (rect.width() - w2) // 2
            color2 = QColor(self.cfg.get("sub2_text_color", "#FFE082"))
            self._render_sub_layout(painter, layout2, w2, h2, x2, base_y + h1 + spacing, color2, scale_ratio)

    def _render_sub_layout(self, painter, layout, width, height, x_pos, y_pos, font_color, scale_ratio):
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QImage

        if self.cfg.get("enable_backdrop", False):
            pad_x = max(6, int(12 * scale_ratio))
            pad_y = max(2, int(4 * scale_ratio))
            pill = QRect(x_pos - pad_x, y_pos - pad_y, width + pad_x * 2, height + pad_y * 2)
            painter.setBrush(QColor(0, 0, 0, 130))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(pill, 6, 6)

        for item in layout:
            if len(item) == 5:
                sub_layout, lw, lh, rel_y, pixmap = item
            else:
                sub_layout, lw, lh, rel_y = item
                pixmap = None

            lx = x_pos + (width - lw) // 2
            ly = y_pos + int(rel_y)

            # 情況 A：COLR V1 字體，繪製 Skia 渲染的向量彩色點陣圖及陰影
            if pixmap:
                if self.cfg.get("enable_shadow", True):
                    offset = max(1, int(self.cfg.get("shadow_offset", 3) * 0.5 * scale_ratio))
                    p_img = pixmap.toImage()
                    p_shadow = QImage(p_img.size(), QImage.Format.Format_ARGB32_Premultiplied)
                    p_shadow.fill(Qt.GlobalColor.transparent)
                    p_painter = QPainter(p_shadow)
                    p_painter.drawImage(0, 0, p_img)
                    p_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    p_painter.fillRect(p_shadow.rect(), QColor(0, 0, 0, 110))
                    p_painter.end()
                    painter.drawImage(lx + offset, ly + offset, p_shadow)
                painter.drawPixmap(lx, ly, pixmap)
            else:
                # 情況 B：普通輪廓字體或 COLR V0 字體，走原生文字排版繪製
                if self.cfg.get("enable_shadow", True):
                    offset = max(1, int(self.cfg.get("shadow_offset", 3) * 0.5 * scale_ratio))
                    pad = 40
                    img_w = int(lw + pad * 2)
                    img_h = int(lh + pad * 2)
                    img = QImage(img_w, img_h, QImage.Format.Format_ARGB32_Premultiplied)
                    img.fill(Qt.GlobalColor.transparent)

                    p = QPainter(img)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    p.setPen(font_color)
                    sub_layout.draw(p, QPointF(pad, pad))
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    p.fillRect(img.rect(), QColor(0, 0, 0, 90))
                    p.end()

                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (0, 0)):
                        painter.drawImage(lx - pad + offset + dx, ly - pad + offset + dy, img)

                painter.setPen(font_color)
                sub_layout.draw(painter, QPointF(lx, ly))


class FontSettingDialog(QDialog):
    """
    字幕與 COLR 彩色設定：包含基礎色(層0)及另外 4 種顏色層(層1~4)的獨立選色器
    """
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("字幕與字體設定")
        self.setFixedSize(540, 560)
        self.cfg = cfg.copy()

        self.setStyleSheet("""
            QDialog { background-color: #1a1c24; color: #ffffff; }
            QLabel { color: #f3f4f6; font-size: 13px; font-weight: bold; }
            QComboBox, QSpinBox {
                background-color: #272a37; color: #ffffff;
                border: 1px solid #475569; border-radius: 4px; padding: 5px 8px; font-size: 13px;
            }
            QComboBox QAbstractItemView {
                background-color: #272a37; color: #ffffff;
                selection-background-color: #2563eb; selection-color: #ffffff;
            }
            QCheckBox { color: #f3f4f6; font-size: 13px; font-weight: bold; spacing: 8px; }
            QPushButton {
                background-color: #2563eb; color: #ffffff; border: none;
                padding: 6px 12px; border-radius: 4px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background-color: #3b82f6; }
        """)

        layout = QFormLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(10)

        families = QFontDatabase.families()

        # ================= 主字幕 =================
        layout.addRow(QLabel("【主字幕設定】"))

        self.combo_font1 = QComboBox()
        self.combo_font1.addItems(families)
        idx1 = self.combo_font1.findText(self.cfg.get("sub1_font_family", "粤黑CN V0"))
        if idx1 >= 0:
            self.combo_font1.setCurrentIndex(idx1)
        layout.addRow("主字幕字體:", self.combo_font1)

        self.spin_size1 = QSpinBox()
        self.spin_size1.setRange(10, 1000)
        self.spin_size1.setValue(self.cfg.get("sub1_font_size", 50))
        layout.addRow("基礎字號 (10-1000):", self.spin_size1)

        # 5 種顏色：基礎色(層0) + 4種COLR層(層1~4)
        self.sub1_text_color = self.cfg.get("sub1_text_color", "#FFFFFF")
        self.btn_sub1_tc = QPushButton("前景色/文字顏色(非彩色)")
        self.btn_sub1_tc.setStyleSheet(f"background-color: {self.sub1_text_color}; color: #000000; font-weight: bold;")
        self.btn_sub1_tc.clicked.connect(self.pick_text_color1)
        layout.addRow("前景色/文字顏色:", self.btn_sub1_tc)

        self.sub1_colors = [self.cfg.get(f"sub1_color{i}", "#000000") for i in range(5)]
        self.sub1_btns = []
        row1 = QHBoxLayout()
        for i in range(5):
            btn = QPushButton(f"層 {i}")
            btn.setStyleSheet(f"background-color: {self.sub1_colors[i]}; color: #000000; font-weight: bold;")
            btn.clicked.connect(lambda _, idx=i: self.pick_color1(idx))
            self.sub1_btns.append(btn)
            row1.addWidget(btn)
        layout.addRow("COLR字型顏色層 0~4:", row1)

        layout.addRow(QLabel("---------------------------------------------------------"))

        # ================= 副字幕 =================
        layout.addRow(QLabel("【副字幕設定】"))

        self.combo_font2 = QComboBox()
        self.combo_font2.addItems(families)
        idx2 = self.combo_font2.findText(self.cfg.get("sub2_font_family", "粤黑CN V0"))
        if idx2 >= 0:
            self.combo_font2.setCurrentIndex(idx2)
        layout.addRow("副字幕字體:", self.combo_font2)

        self.spin_size2 = QSpinBox()
        self.spin_size2.setRange(10, 1000)
        self.spin_size2.setValue(self.cfg.get("sub2_font_size", 40))
        layout.addRow("基礎字號 (10-1000):", self.spin_size2)

        self.sub2_text_color = self.cfg.get("sub2_text_color", "#FFE082")
        self.btn_sub2_tc = QPushButton("前景色/文字顏色(非彩色)")
        self.btn_sub2_tc.setStyleSheet(f"background-color: {self.sub2_text_color}; color: #000000; font-weight: bold;")
        self.btn_sub2_tc.clicked.connect(self.pick_text_color2)
        layout.addRow("前景色/文字顏色:", self.btn_sub2_tc)

        self.sub2_colors = [self.cfg.get(f"sub2_color{i}", "#000000") for i in range(5)]
        self.sub2_btns = []
        row2 = QHBoxLayout()
        for i in range(5):
            btn = QPushButton(f"層 {i}")
            btn.setStyleSheet(f"background-color: {self.sub2_colors[i]}; color: #000000; font-weight: bold;")
            btn.clicked.connect(lambda _, idx=i: self.pick_color2(idx))
            self.sub2_btns.append(btn)
            row2.addWidget(btn)
        layout.addRow("COLR字型顏色層 0~4:", row2)

        layout.addRow(QLabel("---------------------------------------------------------"))

        # 陰影與襯板
        self.chk_shadow = QCheckBox("啟用黑色半透明文字陰影")
        self.chk_shadow.setChecked(self.cfg.get("enable_shadow", True))
        layout.addRow("字幕陰影:", self.chk_shadow)

        self.chk_backdrop = QCheckBox("啟用半透明暗底襯板")
        self.chk_backdrop.setChecked(self.cfg.get("enable_backdrop", False))
        layout.addRow("襯板設定:", self.chk_backdrop)

        self.chk_convert_ass = QCheckBox("啟用 ASS/SSA 字幕自動轉換為 SRT 字幕 (去除標籤並保留換行)")
        self.chk_convert_ass.setChecked(self.cfg.get("convert_ass_to_srt", True))
        layout.addRow("字幕格式轉換:", self.chk_convert_ass)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("確定")
        btns.button(QDialogButtonBox.StandardButton.Apply).setText("套用")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply_clicked)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def pick_text_color1(self):
        c = QColorDialog.getColor(QColor(self.sub1_text_color), self, "選擇主字幕前景色/文字顏色")
        if c.isValid():
            self.sub1_text_color = c.name()
            self.btn_sub1_tc.setStyleSheet(f"background-color: {self.sub1_text_color}; color: #000000; font-weight: bold;")

    def pick_text_color2(self):
        c = QColorDialog.getColor(QColor(self.sub2_text_color), self, "選擇副字幕前景色/文字顏色")
        if c.isValid():
            self.sub2_text_color = c.name()
            self.btn_sub2_tc.setStyleSheet(f"background-color: {self.sub2_text_color}; color: #000000; font-weight: bold;")

    def pick_color1(self, idx):
        c = QColorDialog.getColor(QColor(self.sub1_colors[idx]), self, f"選擇主字幕顏色 (層 {idx})")
        if c.isValid():
            self.sub1_colors[idx] = c.name()
            self.sub1_btns[idx].setStyleSheet(f"background-color: {self.sub1_colors[idx]}; color: #000000; font-weight: bold;")

    def pick_color2(self, idx):
        c = QColorDialog.getColor(QColor(self.sub2_colors[idx]), self, f"選擇副字幕顏色 (層 {idx})")
        if c.isValid():
            self.sub2_colors[idx] = c.name()
            self.sub2_btns[idx].setStyleSheet(f"background-color: {self.sub2_colors[idx]}; color: #000000; font-weight: bold;")

    def apply_clicked(self):
        new_cfg = self.get_result()
        if self.parent() and hasattr(self.parent(), "apply_font_settings"):
            self.parent().apply_font_settings(new_cfg)

    def get_result(self):
        self.cfg["sub1_font_family"] = self.combo_font1.currentText()
        self.cfg["sub1_font_size"] = self.spin_size1.value()
        self.cfg["sub1_text_color"] = self.sub1_text_color
        self.cfg["sub1_color0"] = self.sub1_colors[0]
        self.cfg["sub1_color1"] = self.sub1_colors[1]
        self.cfg["sub1_color2"] = self.sub1_colors[2]
        self.cfg["sub1_color3"] = self.sub1_colors[3]
        self.cfg["sub1_color4"] = self.sub1_colors[4]

        self.cfg["sub2_font_family"] = self.combo_font2.currentText()
        self.cfg["sub2_font_size"] = self.spin_size2.value()
        self.cfg["sub2_color0"] = self.sub2_colors[0]
        self.cfg["sub2_color1"] = self.sub2_colors[1]
        self.cfg["sub2_color2"] = self.sub2_colors[2]
        self.cfg["sub2_color3"] = self.sub2_colors[3]
        self.cfg["sub2_color4"] = self.sub2_colors[4]

        self.cfg["enable_shadow"] = self.chk_shadow.isChecked()
        self.cfg["enable_backdrop"] = self.chk_backdrop.isChecked()
        self.cfg["convert_ass_to_srt"] = self.chk_convert_ass.isChecked()
        return self.cfg


class JyutPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.playlist = []
        self.current_index = -1
        self.is_fullscreen = False
        self.duration = 0.0
        self.is_slider_down = False
        self.current_media_path = ""

        # 視窗邊框縮放與拖曳
        self._dragging_window = False
        self._drag_start_pos = QPoint()
        self._resizing_dir = None
        self._resize_start_geom = None
        self._resize_start_mouse = None
        self.BORDER_MARGIN = 8

        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.toggle_play)

        self.sub_tracks = []
        self.primary_sub_idx = -1
        self.secondary_sub_idx = -1

        self.init_ui()
        self.init_mpv()

        # 安裝全域事件監聽，確保滑鼠進入視窗邊緣 8px 立即變為雙箭頭
        QApplication.instance().installEventFilter(self)

        self.sub_timer = QTimer(self)
        self.sub_timer.setInterval(20)
        self.sub_timer.timeout.connect(self.sync_subtitles)
        self.sub_timer.start()

    def init_ui(self):
        self.setWindowTitle("JyutPlayer 播放器")
        self.resize(1150, 700)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAcceptDrops(True)
        self.setStyleSheet("""
            QMainWindow { background-color: #0c0d10; color: #ffffff; }
            QWidget#TopBar, QWidget#BottomBar { background-color: #14161c; }
            QWidget#PlaylistPanel { background-color: #121318; border-left: 1px solid #232733; }
            QPushButton {
                background: transparent; color: #d0d0d0; border: none;
                font-size: 14px; font-weight: bold; padding: 6px; border-radius: 4px;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.15); color: #ffffff; }
            QLabel { color: #cccccc; font-size: 12px; }
            QSlider::groove:horizontal { height: 4px; background: #3a3f4b; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 2px; }
            QSlider::handle:horizontal {
                background: #ffffff; border: 1px solid #3b82f6; width: 12px;
                margin-top: -4px; margin-bottom: -4px; border-radius: 6px;
            }
            QListWidget {
                background-color: transparent; border: none; color: #e0e0e0;
                font-size: 13px; outline: none;
            }
            QListWidget::item { padding: 6px 10px; border-radius: 3px; }
            QListWidget::item:hover { background-color: rgba(255, 255, 255, 0.08); }
            QListWidget::item:selected { background-color: #2563eb; color: #ffffff; }
        """)

        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 頂部列
        self.top_bar = QWidget()
        self.top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(10, 4, 10, 4)

        self.btn_menu = QPushButton("☰")
        self.btn_menu.setToolTip("菜單")
        self.btn_menu.clicked.connect(self.show_main_menu)
        top_layout.addWidget(self.btn_menu)

        self.lbl_title = QLabel("JyutPlayer - 就緒")
        self.lbl_title.setStyleSheet("font-weight: 500; font-size: 13px; color: #aaaaaa;")
        top_layout.addWidget(self.lbl_title)
        top_layout.addStretch()

        self.btn_min = QPushButton("🗕")
        self.btn_min.setToolTip("最小化")
        self.btn_min.clicked.connect(self.showMinimized)
        top_layout.addWidget(self.btn_min)

        self.btn_max = QPushButton("🗖")
        self.btn_max.setToolTip("最大化 / 還原")
        self.btn_max.clicked.connect(self.toggle_maximize)
        top_layout.addWidget(self.btn_max)

        self.btn_close = QPushButton("✕")
        self.btn_close.setToolTip("關閉")
        self.btn_close.clicked.connect(self.close)
        top_layout.addWidget(self.btn_close)
        root_layout.addWidget(self.top_bar)

        # 分割畫面 (影片 + 播放佇列)
        self.center_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.center_splitter.setStyleSheet("QSplitter::handle { background-color: #1a1c23; }")

        self.video_container = QWidget()
        self.video_container.setObjectName("VideoContainer")
        self.video_container.setStyleSheet("background-color: #000000;")
        self.center_splitter.addWidget(self.video_container)

        self.playlist_panel = QWidget()
        self.playlist_panel.setObjectName("PlaylistPanel")
        self.playlist_panel.setFixedWidth(260)
        p_layout = QVBoxLayout(self.playlist_panel)
        p_layout.setContentsMargins(8, 8, 8, 8)

        p_header = QHBoxLayout()
        lbl_p = QLabel("播放佇列")
        lbl_p.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff;")
        p_header.addWidget(lbl_p)
        p_header.addStretch()

        btn_add_p = QPushButton("➕ 添加")
        btn_add_p.clicked.connect(self.add_media_to_playlist_dialog)
        p_header.addWidget(btn_add_p)

        btn_clear_p = QPushButton("🗑 清空")
        btn_clear_p.clicked.connect(self.clear_playlist)
        p_header.addWidget(btn_clear_p)
        p_layout.addLayout(p_header)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.on_playlist_item_double_clicked)
        p_layout.addWidget(self.list_widget)

        self.center_splitter.addWidget(self.playlist_panel)
        self.playlist_panel.hide()
        root_layout.addWidget(self.center_splitter, 1)

        self.sub_overlay = SubtitleOverlay(self)
        self.sub_overlay.set_config(self.cfg)

        # 底部列
        self.bottom_bar = QWidget()
        self.bottom_bar.setObjectName("BottomBar")
        bot_layout = QVBoxLayout(self.bottom_bar)
        bot_layout.setContentsMargins(12, 6, 12, 8)

        slider_row = QHBoxLayout()
        self.lbl_time_cur = QLabel("00:00:00")
        self.slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderPressed.connect(self.on_slider_pressed)
        self.slider.sliderReleased.connect(self.on_slider_released)
        self.slider.sliderMoved.connect(self.on_slider_moved)
        self.lbl_time_total = QLabel("00:00:00")

        slider_row.addWidget(self.lbl_time_cur)
        slider_row.addWidget(self.slider)
        slider_row.addWidget(self.lbl_time_total)
        bot_layout.addLayout(slider_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_prev = QPushButton("⏮")
        self.btn_prev.setToolTip("上一個")
        self.btn_prev.clicked.connect(self.play_previous)
        btn_row.addWidget(self.btn_prev)

        self.btn_play = QPushButton("⏯️")
        self.btn_play.setToolTip("播放 / 暫停")
        self.btn_play.clicked.connect(self.toggle_play)
        btn_row.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setToolTip("停止")
        self.btn_stop.clicked.connect(self.stop)
        btn_row.addWidget(self.btn_stop)

        self.btn_next = QPushButton("⏭")
        self.btn_next.setToolTip("下一個")
        self.btn_next.clicked.connect(self.play_next)
        btn_row.addWidget(self.btn_next)

        btn_row.addSpacing(15)

        self.btn_tracks = QPushButton("🔀 選擇軌道")
        self.btn_tracks.setToolTip("選擇視訊軌、音軌、主字幕與副字幕")
        self.btn_tracks.clicked.connect(self.show_tracks_menu)
        btn_row.addWidget(self.btn_tracks)

        self.btn_sub_settings = QPushButton("⚙ 字幕設定")
        self.btn_sub_settings.setToolTip("選擇系統字體與彩色字體樣式")
        self.btn_sub_settings.clicked.connect(self.show_sub_settings)
        btn_row.addWidget(self.btn_sub_settings)

        self.btn_playlist = QPushButton("📋 播放佇列")
        self.btn_playlist.setToolTip("展開 / 收起播放佇列")
        self.btn_playlist.clicked.connect(self.toggle_playlist_panel)
        btn_row.addWidget(self.btn_playlist)

        btn_row.addStretch()

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setToolTip("全螢幕 (雙擊畫面切換)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        btn_row.addWidget(self.btn_fullscreen)

        # 增加音量控制
        self.lbl_vol = QLabel("🔊")
        btn_row.addWidget(self.lbl_vol)
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(self.cfg.get("volume", 100))
        self.slider_vol.setFixedWidth(80)
        self.slider_vol.valueChanged.connect(self.on_volume_changed)
        btn_row.addWidget(self.slider_vol)

        bot_layout.addLayout(btn_row)
        root_layout.addWidget(self.bottom_bar)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggle_play()
            event.accept()
        elif event.key() == Qt.Key.Key_Left:
            try:
                t = max(0.0, self.player.time_pos - 10) if self.player.time_pos else 0.0
                self.player.seek(t, reference="absolute")
            except Exception:
                pass
            event.accept()
        elif event.key() == Qt.Key.Key_Right:
            try:
                t = min(self.duration, self.player.time_pos + 10) if self.player.time_pos else 0.0
                self.player.seek(t, reference="absolute")
            except Exception:
                pass
            event.accept()
        else:
            super().keyPressEvent(event)

    def seek_relative(self, seconds):
        try:
            cur = self.player.time_pos
            if cur is not None:
                t = max(0.0, min(self.duration, cur + seconds))
                self.player.seek(t, reference="absolute")
        except Exception:
            pass
    def init_mpv(self):
        try:
            self.player = mpv.MPV(
                wid=str(int(self.video_container.winId())),
                vo="gpu-next",
                gpu_context="d3d11",
                target_trc="auto",
                target_colorspace_hint="yes",
                tone_mapping="bt.2390",
                hdr_compute_peak="yes",
                hwdec="auto-safe",
                keep_open="yes"
            )
        except Exception:
            self.player = mpv.MPV(
                wid=str(int(self.video_container.winId())),
                hwdec="auto-safe",
                keep_open="yes"
            )

        self.player.volume = self.cfg.get("volume", 100)
        self.player.sub_auto = "fuzzy"  # 自動掃描同資料夾下的外部字幕檔案
        self.player.sub_visibility = False  # 徹底關閉 MPV 畫布自身字幕繪製，杜絕雙層重影
        self.player.secondary_sub_visibility = False

        from PyQt6.QtGui import QShortcut, QKeySequence
        self.shortcut_space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.shortcut_space.activated.connect(self.toggle_play)
        self.shortcut_left = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        self.shortcut_left.activated.connect(lambda: self.seek_relative(-10))
        self.shortcut_right = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        self.shortcut_right.activated.connect(lambda: self.seek_relative(10))

        @self.player.property_observer("time-pos")
        def on_time_pos(_name, val):
            if val is not None and not self.is_slider_down and self.duration > 0:
                pos = int((val / self.duration) * 1000)
                self.slider.setValue(pos)
                self.lbl_time_cur.setText(self.format_time(val))

        @self.player.property_observer("duration")
        def on_duration(_name, val):
            if val is not None:
                self.duration = val
                self.lbl_time_total.setText(self.format_time(val))

        @self.player.property_observer("pause")
        def on_pause(_name, val):
            self.btn_play.setText("⏯️" if val else "⏸")

        @self.player.property_observer("eof-reached")
        def on_eof(_name, val):
            if val is True:
                if len(self.playlist) > 1 and self.current_index < len(self.playlist) - 1:
                    QTimer.singleShot(100, self.play_next)

        @self.player.event_callback("file-loaded")
        def on_file_loaded(_event):
            QTimer.singleShot(150, self.on_media_loaded)

    # ---------------- 雙箭頭游標與自由邊框縮放 ----------------
    def _get_border_direction(self, pt):
        if self.is_fullscreen or self.isMaximized():
            return None
        x, y = pt.x(), pt.y()
        w, h = self.width(), self.height()
        m = self.BORDER_MARGIN

        left = x < m
        right = x >= w - m
        top = y < m
        bottom = y >= h - m

        if top and left: return "top-left"
        if top and right: return "top-right"
        if bottom and left: return "bottom-left"
        if bottom and right: return "bottom-right"
        if left: return "left"
        if right: return "right"
        if top: return "top"
        if bottom: return "bottom"
        return None

    def _get_cursor_for_direction(self, d):
        if d in ("top-left", "bottom-right"):
            return QCursor(Qt.CursorShape.SizeFDiagCursor)
        elif d in ("top-right", "bottom-left"):
            return QCursor(Qt.CursorShape.SizeBDiagCursor)
        elif d in ("left", "right"):
            return QCursor(Qt.CursorShape.SizeHorCursor)
        elif d in ("top", "bottom"):
            return QCursor(Qt.CursorShape.SizeVerCursor)
        return QCursor(Qt.CursorShape.ArrowCursor)

    def eventFilter(self, watched, event):
        if not self.is_fullscreen and not self.isMaximized():
            if event.type() == QEvent.Type.MouseMove:
                g_pos = event.globalPosition().toPoint()

                # 正在拖曳縮放中
                if self._resizing_dir:
                    delta = g_pos - self._resize_start_mouse
                    g = QRect(self._resize_start_geom)

                    if "left" in self._resizing_dir:
                        new_w = max(640, g.width() - delta.x())
                        g.setLeft(g.right() - new_w)
                    elif "right" in self._resizing_dir:
                        g.setWidth(max(640, g.width() + delta.x()))

                    if "top" in self._resizing_dir:
                        new_h = max(360, g.height() - delta.y())
                        g.setTop(g.bottom() - new_h)
                    elif "bottom" in self._resizing_dir:
                        g.setHeight(max(360, g.height() + delta.y()))

                    self.setGeometry(g)
                    self.sync_overlay_geometry()
                    return True

                # 懸停邊框時即時切換雙箭頭游標
                if self.geometry().contains(g_pos):
                    pt = self.mapFromGlobal(g_pos)
                    d = self._get_border_direction(pt)
                    if d:
                        cur = self._get_cursor_for_direction(d)
                        if QApplication.overrideCursor() is None:
                            QApplication.setOverrideCursor(cur)
                        elif QApplication.overrideCursor().shape() != cur.shape():
                            QApplication.changeOverrideCursor(cur)
                    else:
                        if QApplication.overrideCursor() is not None:
                            QApplication.restoreOverrideCursor()
                else:
                    if QApplication.overrideCursor() is not None:
                        QApplication.restoreOverrideCursor()

            elif event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    g_pos = event.globalPosition().toPoint()
                    if self.geometry().contains(g_pos):
                        pt = self.mapFromGlobal(g_pos)
                        d = self._get_border_direction(pt)
                        if d:
                            self._resizing_dir = d
                            self._resize_start_geom = self.geometry()
                            self._resize_start_mouse = g_pos
                            return True

            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self._resizing_dir:
                    self._resizing_dir = None
                    if QApplication.overrideCursor() is not None:
                        QApplication.restoreOverrideCursor()
                    return True

        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.childAt(event.position().toPoint())
            if not isinstance(w, (QPushButton, QSlider, QListWidget)):
                self._dragging_window = True
                self._drag_start_pos = event.globalPosition().toPoint() - self.pos()
                self._click_origin = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_window and not self.is_fullscreen and not self.isMaximized():
            self.move(event.globalPosition().toPoint() - self._drag_start_pos)
            self.sync_overlay_geometry()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_window:
            self._dragging_window = False
            delta = (event.globalPosition().toPoint() - self._click_origin).manhattanLength()
            if delta < 5:
                pos_in_video = self.video_container.mapFromGlobal(event.globalPosition().toPoint())
                if self.video_container.rect().contains(pos_in_video):
                    self._click_timer.start(QApplication.doubleClickInterval())
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            pos_in_video = self.video_container.mapFromGlobal(event.globalPosition().toPoint())
            if self.video_container.rect().contains(pos_in_video):
                self.toggle_fullscreen()
                return
        super().mouseDoubleClickEvent(event)

    def adjust_window_to_video_ratio(self, vw, vh):
        if self.is_fullscreen or self.isMaximized() or vw <= 0 or vh <= 0:
            return

        screen = QApplication.primaryScreen().availableGeometry()
        max_w = int(screen.width() * 0.85)
        max_h = int(screen.height() * 0.85)
        overhead_h = self.top_bar.height() + self.bottom_bar.height()

        video_ratio = float(vw) / float(vh)
        target_vw = max(640, min(vw, int(max_w * 0.8)))
        target_vh = int(target_vw / video_ratio)

        target_total_h = target_vh + overhead_h
        if target_total_h > max_h:
            target_total_h = max_h
            target_vh = target_total_h - overhead_h
            target_vw = int(target_vh * video_ratio)

        target_total_w = max(640, min(target_vw, max_w))

        cx = self.x() + self.width() // 2
        cy = self.y() + self.height() // 2
        new_x = max(screen.left(), cx - target_total_w // 2)
        new_y = max(screen.top(), cy - target_total_h // 2)

        self.setGeometry(new_x, new_y, target_total_w, target_total_h)
        self.sync_overlay_geometry()

    def sync_overlay_geometry(self):
        if not hasattr(self, "sub_overlay") or not hasattr(self, "video_container"):
            return
        if not self.isVisible() or self.isMinimized():
            self.sub_overlay.hide()
            return

        pt = self.video_container.mapToGlobal(QPoint(0, 0))
        w = self.video_container.width()
        h = self.video_container.height()
        self.sub_overlay.setGeometry(pt.x(), pt.y(), w, h)
        self.sub_overlay.show()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.sync_overlay_geometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_overlay_geometry()

    # ---------------- 換片時 0 秒即時清空並刷新字幕 ----------------
    def on_volume_changed(self, val):
        try:
            self.player.volume = val
            self.cfg["volume"] = val
            save_config(self.cfg)
        except Exception:
            pass

    def on_media_loaded(self):
        if not self.current_media_path or not os.path.exists(self.current_media_path):
            return

        try:
            dw = self.player.dwidth
            dh = self.player.dheight
            if dw and dh:
                self.adjust_window_to_video_ratio(dw, dh)
        except Exception:
            pass

        # 讀取當前新影片的全部字幕軌道
        self.sub_tracks.clear()
        try:
            tracks = self.player.track_list or []
        except Exception:
            tracks = []

        for t in tracks:
            if t.get("type") == "sub":
                tid = t.get("id")
                title = t.get("title") or t.get("lang") or f"字幕_{tid}"
                codec = t.get("codec", "")
                is_ext = t.get("external", False)
                prefix = "[外部]" if is_ext else "[內置]"
                name = f"{prefix} {title}" + (f" ({codec})" if codec else "")
                self.sub_tracks.append({
                    "name": name,
                    "mpv_id": tid,
                    "codec": str(codec).lower()
                })

        # 新影片預設：主字幕選第 1 軌，副字幕關閉
        if self.sub_tracks:
            self.set_primary_sub(0)
        else:
            self.set_primary_sub(-1)
        self.set_secondary_sub(-1)

        self.sync_overlay_geometry()

    def sync_subtitles(self):
        """即時同步 MPV 解碼的主副字幕文字至 HarfBuzz 渲染層"""
        try:
            # 若使用了 COLR v1 字體，啟用 0.18s 延遲補償以抵消 Skia 繪製時間
            is_v1_active = getattr(self.sub_overlay, "is_v1_sub1", False) or getattr(self.sub_overlay, "is_v1_sub2", False)
            self.player.sub_delay = 0.18 if is_v1_active else 0.0

            t1 = ""
            if 0 <= self.primary_sub_idx < len(self.sub_tracks):
                trk = self.sub_tracks[self.primary_sub_idx]
                if not any(g in trk["codec"] for g in GRAPHIC_SUB_CODECS):
                    t1 = self.player.sub_text or ""

            t2 = ""
            if 0 <= self.secondary_sub_idx < len(self.sub_tracks):
                trk = self.sub_tracks[self.secondary_sub_idx]
                if not any(g in trk["codec"] for g in GRAPHIC_SUB_CODECS):
                    t2 = self.player.secondary_sub_text or ""
        except Exception:
            t1, t2 = "", ""
        if self.cfg.get("convert_ass_to_srt", True):
            import re
            if t1:
                t1 = re.sub(r'\{.*?\}', '', t1).replace(r'\N', '\n').replace(r'\n', '\n')
            if t2:
                t2 = re.sub(r'\{.*?\}', '', t2).replace(r'\N', '\n').replace(r'\n', '\n')

        self.sub_overlay.update_subtitles(t1, t2)

    def set_primary_sub(self, idx):
        self.primary_sub_idx = idx
        if 0 <= idx < len(self.sub_tracks):
            trk = self.sub_tracks[idx]
            self.player.sid = trk["mpv_id"]
            if any(g in trk["codec"] for g in GRAPHIC_SUB_CODECS):
                self.player.sub_visibility = True
            else:
                self.player.sub_visibility = False
                self.player.sub_color = "#00000000"
                self.player.sub_border_color = "#00000000"
                self.player.sub_shadow_color = "#00000000"
                self.player.sub_border_size = 0
                self.player.sub_shadow_offset = 0
        else:
            self.player.sid = "no"
        self.sync_overlay_geometry()

    def set_secondary_sub(self, idx):
        self.secondary_sub_idx = idx
        if 0 <= idx < len(self.sub_tracks):
            trk = self.sub_tracks[idx]
            self.player.secondary_sid = trk["mpv_id"]
            if any(g in trk["codec"] for g in GRAPHIC_SUB_CODECS):
                self.player.secondary_sub_visibility = True
            else:
                self.player.secondary_sub_visibility = False
                self.player.secondary_sub_color = "#00000000"
                self.player.secondary_sub_border_color = "#00000000"
                self.player.secondary_sub_shadow_color = "#00000000"
                self.player.secondary_sub_border_size = 0
                self.player.secondary_sub_shadow_offset = 0
        else:
            self.player.secondary_sid = "no"
        self.sync_overlay_geometry()

    def show_tracks_menu(self):
        menu = QMenu(self)

        v_menu = menu.addMenu("🎬 視訊軌道 (Video)")
        try:
            tracks = self.player.track_list or []
        except Exception:
            tracks = []

        v_tracks = [t for t in tracks if t.get("type") == "video"]
        for t in v_tracks:
            act = v_menu.addAction(f"視訊軌 {t.get('id')}: {t.get('title', '視訊')} [{t.get('codec', '')}]")
            act.setCheckable(True)
            act.setChecked(t.get("selected", False))
            act.triggered.connect(lambda _, tid=t.get("id"): self.player._set_property("vid", tid))

        a_menu = menu.addMenu("🔊 音訊軌道 (Audio)")
        a_tracks = [t for t in tracks if t.get("type") == "audio"]
        for t in a_tracks:
            title = t.get("title") or t.get("lang") or f"音軌 #{t.get('id')}"
            act = a_menu.addAction(f"音軌 {t.get('id')}: {title} [{t.get('codec', '')}]")
            act.setCheckable(True)
            act.setChecked(t.get("selected", False))
            act.triggered.connect(lambda _, tid=t.get("id"): self.player._set_property("aid", tid))

        menu.addSeparator()

        # 主字幕
        sub1_menu = menu.addMenu("🔤 主字幕軌道")
        off1 = sub1_menu.addAction("關閉主字幕")
        off1.setCheckable(True)
        off1.setChecked(self.primary_sub_idx == -1)
        off1.triggered.connect(lambda: self.set_primary_sub(-1))

        for idx, trk in enumerate(self.sub_tracks):
            act = sub1_menu.addAction(trk["name"])
            act.setCheckable(True)
            act.setChecked(self.primary_sub_idx == idx)
            act.triggered.connect(lambda _, i=idx: self.set_primary_sub(i))

        # 副字幕
        sub2_menu = menu.addMenu("🔤 副字幕軌道")
        off2 = sub2_menu.addAction("關閉副字幕")
        off2.setCheckable(True)
        off2.setChecked(self.secondary_sub_idx == -1)
        off2.triggered.connect(lambda: self.set_secondary_sub(-1))

        for idx, trk in enumerate(self.sub_tracks):
            act = sub2_menu.addAction(trk["name"])
            act.setCheckable(True)
            act.setChecked(self.secondary_sub_idx == idx)
            act.triggered.connect(lambda _, i=idx: self.set_secondary_sub(i))

        menu.addSeparator()
        add_sub_act = menu.addAction("➕ 載入外部字幕檔...")
        add_sub_act.triggered.connect(self.load_external_sub_dialog)

        menu.exec(self.btn_tracks.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def load_external_sub_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "載入字幕檔案", "", "字幕檔案 (*.srt *.ass *.ssa *.vtt)")
        if path:
            try:
                final_sub = path
                if self.cfg.get("convert_ass_to_srt", True) and path.lower().endswith(('.ass', '.ssa')):
                    final_sub = convert_ass_to_srt_file(path)
                self.player.sub_add(final_sub)
                self.on_media_loaded()
            except Exception as e:
                QMessageBox.warning(self, "錯誤", f"無法載入字幕: {e}")

    def show_sub_settings(self):
        dlg = FontSettingDialog(self.cfg, self)
        if dlg.exec():
            self.cfg = dlg.get_result()
            self.sub_overlay.set_config(self.cfg)
            save_config(self.cfg)

    def apply_font_settings(self, new_cfg):
        self.cfg.update(new_cfg)
        self.sub_overlay.set_config(self.cfg)
        save_config(self.cfg)
    
    def toggle_playlist_panel(self):
        if self.playlist_panel.isVisible():
            self.playlist_panel.hide()
        else:
            self.playlist_panel.show()
        QTimer.singleShot(50, self.sync_overlay_geometry)

    def update_playlist_ui(self):
        self.list_widget.clear()
        for idx, f in enumerate(self.playlist):
            item = QListWidgetItem(f"{idx + 1}. {os.path.basename(f)}")
            item.setToolTip(f)
            self.list_widget.addItem(item)
        if 0 <= self.current_index < self.list_widget.count():
            self.list_widget.setCurrentRow(self.current_index)

    def on_playlist_item_double_clicked(self, item):
        row = self.list_widget.row(item)
        if 0 <= row < len(self.playlist):
            self.current_index = row
            self.play_current()

    def clear_playlist(self):
        self.stop()
        self.playlist.clear()
        self.list_widget.clear()
        self.current_index = -1
        self.lbl_title.setText("JyutPlayer - 就緒")

    def play_current(self):
        if 0 <= self.current_index < len(self.playlist):
            file_path = self.playlist[self.current_index]
            self.current_media_path = file_path
            self.lbl_title.setText(f"JyutPlayer - {os.path.basename(file_path)}")

            # 【關鍵】換片瞬間 0 秒徹底清空所有字幕軌與浮層文字，絕不殘留上一部片
            self.sub_tracks.clear()
            self.primary_sub_idx = -1
            self.secondary_sub_idx = -1
            self.player.sid = "no"
            self.player.secondary_sid = "no"
            self.sub_overlay.update_subtitles("", "")

            self.update_playlist_ui()
            self.player.play(file_path)
            self.sync_overlay_geometry()

    def play_previous(self):
        if self.playlist and self.current_index > 0:
            self.current_index -= 1
            self.play_current()

    def play_next(self):
        if self.playlist and self.current_index < len(self.playlist) - 1:
            self.current_index += 1
            self.play_current()

    def toggle_play(self):
        try:
            self.player.pause = not self.player.pause
        except Exception:
            pass

    def stop(self):
        try:
            self.player.command("stop")
            self.slider.setValue(0)
            self.lbl_time_cur.setText("00:00:00")
            self.sub_overlay.update_subtitles("", "")
        except Exception:
            pass

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.top_bar.hide()
            self.bottom_bar.hide()
            self.playlist_panel.hide()
            self.showFullScreen()
        else:
            self.top_bar.show()
            self.bottom_bar.show()
            self.showNormal()
        QTimer.singleShot(100, self.sync_overlay_geometry)

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        QTimer.singleShot(100, self.sync_overlay_geometry)

    def on_slider_pressed(self):
        self.is_slider_down = True

    def on_slider_released(self):
        self.is_slider_down = False
        target = (self.slider.value() / 1000.0) * self.duration
        self.player.seek(target, reference="absolute")

    def on_slider_moved(self, val):
        target = (val / 1000.0) * self.duration
        self.player.seek(target, reference="absolute")
        self.lbl_time_cur.setText(self.format_time(target))

    def format_time(self, seconds):
        if seconds < 0:
            seconds = 0
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        files = [u.toLocalFile() for u in urls if u.isLocalFile()]
        video_files = [f for f in files if self.is_media_file(f)]
        sub_files = [f for f in files if f.lower().endswith(('.srt', '.ass', '.ssa', '.vtt'))]

        if video_files:
            old_len = len(self.playlist)
            self.playlist.extend(video_files)
            self.update_playlist_ui()
            if self.current_index == -1:
                self.current_index = old_len
                self.play_current()

        for sf in sub_files:
            try:
                final_sub = sf
                if self.cfg.get("convert_ass_to_srt", True) and sf.lower().endswith(('.ass', '.ssa')):
                    final_sub = convert_ass_to_srt_file(sf)
                self.player.sub_add(final_sub)
                self.on_media_loaded()
            except Exception:
                pass

    def is_media_file(self, filename):
        exts = ('.mkv', '.mp4', '.flv', '.rm', '.rmvb', '.avi', '.mov', '.ts', '.m2ts', '.webm', '.flac', '.mp3')
        return filename.lower().endswith(exts)

    def open_media_file_direct(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "打開影音檔案", self.cfg.get("last_dir", ""),
            "影音檔案 (*.mkv *.mp4 *.flv *.rm *.rmvb *.h265 *.ts *.flac *.mp3);;所有檔案 (*.*)"
        )
        if files:
            self.cfg["last_dir"] = str(Path(files[0]).parent)
            save_config(self.cfg)
            self.playlist = files
            self.update_playlist_ui()
            self.current_index = 0
            self.play_current()

    def add_media_to_playlist_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "添加影音檔案至播放佇列", self.cfg.get("last_dir", ""),
            "影音檔案 (*.mkv *.mp4 *.flv *.rm *.rmvb *.h265 *.ts *.flac *.mp3);;所有檔案 (*.*)"
        )
        if files:
            self.cfg["last_dir"] = str(Path(files[0]).parent)
            save_config(self.cfg)
            was_empty = len(self.playlist) == 0
            self.playlist.extend(files)
            self.update_playlist_ui()
            if was_empty:
                self.current_index = 0
                self.play_current()

    def open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇影音資料夾", self.cfg.get("last_dir", ""))
        if folder:
            self.cfg["last_dir"] = folder
            save_config(self.cfg)
            all_files = glob.glob(os.path.join(folder, "*"))
            media = [f for f in all_files if self.is_media_file(f)]
            if media:
                self.playlist = sorted(media)
                self.update_playlist_ui()
                self.current_index = 0
                self.play_current()

    def show_main_menu(self):
        menu = QMenu(self)
        act_open = menu.addAction("打開影音...")
        act_open.triggered.connect(self.open_media_file_direct)

        act_dir = menu.addAction("打開資料夾...")
        act_dir.triggered.connect(self.open_folder_dialog)

        act_playlist = menu.addAction("切換播放佇列")
        act_playlist.triggered.connect(self.toggle_playlist_panel)

        menu.addSeparator()
        act_settings = menu.addAction("字幕與字體設定...")
        act_settings.triggered.connect(self.show_sub_settings)

        menu.addSeparator()
        act_exit = menu.addAction("退出")
        act_exit.triggered.connect(self.close)
        menu.exec(self.btn_menu.mapToGlobal(QPoint(0, self.btn_menu.height())))

    def closeEvent(self, event):
        if hasattr(self, "sub_overlay") and self.sub_overlay:
            self.sub_overlay.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    for ext in ("*.ttf", "*.otf"):
        for font_file in Path(CURRENT_DIR).glob(ext):
            QFontDatabase.addApplicationFont(str(font_file))
    player = JyutPlayer()
    player.show()
    player.sync_overlay_geometry()
    sys.exit(app.exec())