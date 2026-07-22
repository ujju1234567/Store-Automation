import pypdfium2 as pdfium
from PIL import Image, ImageDraw
import numpy as np

def pdf_to_images(pdf_path, dpi=150):
    """Convert each PDF page to a PIL Image."""
    doc = pdfium.PdfDocument(pdf_path)
    images = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            scale = dpi / 72          # pdfium default is 72 dpi
            bitmap = page.render(scale=scale, rotation=0)
            pil_img = bitmap.to_pil()
            images.append(pil_img)
    finally:
        doc.close()
    return images

def draw_ocr_boxes(image: Image.Image, boxes) -> Image.Image:
    """
    Draws bounding boxes on a PIL image.
    boxes is expected to be a list of [[x1, y1], [x2, y2], [x3, y3], [x4, y4]] points.
    """
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)
    
    for box in boxes:
        # box is typically 4 points: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
        points = [(pt[0], pt[1]) for pt in box]
        # Append the first point to close the polygon
        points.append(points[0])
        draw.line(points, fill="red", width=2)
        
    return img_copy

def draw_single_box(image: Image.Image, box) -> Image.Image:
    """
    Draw a single bounding box highlighted (e.g. green) and crop/zoom if needed.
    """
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)
    points = [(pt[0], pt[1]) for pt in box]
    points.append(points[0])
    draw.line(points, fill="green", width=4)
    return img_copy
