"""Regenerate the PDF and PNG fixtures (requires Pillow, ReportLab and a Chinese TTF)."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--font', default='/Library/Fonts/Arial Unicode.ttf')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    image = Image.new('RGB', (1080, 420), '#f6f8fc')
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 110, 320, 310), fill='#df4b4b')
    draw.ellipse((440, 110, 640, 310), fill='#397ee8')
    draw.polygon([(860, 100), (750, 310), (970, 310)], fill='#29976b')
    image.save(root / 'shapes.png')
    pdfmetrics.registerFont(TTFont('ExampleChinese', args.font))
    pdf = canvas.Canvas(str(root / 'shapes.pdf'), pagesize=(595, 842), invariant=1)
    pdf.setTitle('几何图形观察 - PDF 示例')
    pdf.setFillColorRGB(.14, .2, .3)
    pdf.setFont('ExampleChinese', 24); pdf.drawString(48, 772, '几何图形观察')
    pdf.setFont('ExampleChinese', 12); pdf.drawString(48, 738, '原始数据集 · PDF 示例')
    pdf.drawImage(str(root / 'shapes.png'), 48, 490, width=499, height=194)
    pdf.setFont('ExampleChinese', 14)
    for y, text in [(450, '观察内容'), (416, '从左到右依次为红色正方形、蓝色圆形、绿色三角形。'),
                    (384, '正方形有四条边；圆形没有顶点；三角形有三条边。'), (328, '数据用途'),
                    (294, '可作为文档解析、图形描述与问答生成的原始材料。'),
                    (262, '同目录包含 PNG 图片、TXT 描述和 CSV 属性表。')]:
        pdf.drawString(48, y, text)
    pdf.setFont('ExampleChinese', 10); pdf.drawString(48, 56, '本地示例文件 / 1')
    pdf.save()


if __name__ == '__main__':
    main()
