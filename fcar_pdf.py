"""Documento de OS em PDF, gerado sem alterar dados da oficina."""
from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
import unicodedata
from xml.sax.saxutils import escape

import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate, CondPageBreak, Frame, Image, KeepTogether, LongTable,
    NextPageTemplate, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parent
REGULAR = 'FCAR-Regular'
BOLD = 'FCAR-Bold'
for name, filename in [(REGULAR, 'DejaVuSans.ttf'), (BOLD, 'DejaVuSans-Bold.ttf')]:
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(ROOT / 'static/fonts' / filename)))
pdfmetrics.registerFontFamily(REGULAR, normal=REGULAR, bold=BOLD, italic=REGULAR, boldItalic=BOLD)

INK = colors.HexColor('#18212e')
MUTED = colors.HexColor('#69778b')
LINE = colors.HexColor('#e5e9ef')
PAPER = colors.HexColor('#f5f7fa')
RED = colors.HexColor('#e63b43')
DARK = colors.HexColor('#111720')
WIDTH, HEIGHT = A4
MARGIN = 35
CONTENT = WIDTH - 2 * MARGIN


def money(value):
    return f'R$ {float(value or 0):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def date_br(value):
    try:
        return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return 'Não informada'


def quantity(value):
    return f'{float(value or 0):g}'.replace('.', ',')


def clean_text(value):
    text = str(value or '')
    # Evita caracteres de controle e glifos ausentes na fonte incorporada.
    cmap = pdfmetrics.getFont(REGULAR).face.charToGlyph
    return ''.join(
        char if ord(char) in cmap or char in '\n\t' else '?'
        for char in text if char in '\n\t' or not unicodedata.category(char).startswith('C')
    )


def build_order_pdf(data, public_url):
    """Recebe o mesmo conteúdo mostrado na OS; devolve bytes de um PDF A4."""
    order = data['o']
    number = f"{int(order['id']):06d}"
    output = BytesIO()
    styles = {
        'body': ParagraphStyle('body', fontName=REGULAR, fontSize=8.7, leading=13, textColor=INK, splitLongWords=True),
        'small': ParagraphStyle('small', fontName=REGULAR, fontSize=7.2, leading=11, textColor=MUTED),
        'label': ParagraphStyle('label', fontName=BOLD, fontSize=6.9, leading=10, textColor=MUTED, spaceAfter=5),
        'name': ParagraphStyle('name', fontName=BOLD, fontSize=12.2, leading=18, textColor=INK, splitLongWords=True),
        'section': ParagraphStyle('section', fontName=BOLD, fontSize=10.2, leading=14, textColor=INK, spaceBefore=15, spaceAfter=9),
        'tabletitle': ParagraphStyle('tabletitle', fontName=BOLD, fontSize=10.2, leading=14, textColor=INK),
        'tablehead': ParagraphStyle('tablehead', fontName=BOLD, fontSize=6.8, leading=9, textColor=MUTED),
        'right': ParagraphStyle('right', fontName=REGULAR, fontSize=8.4, leading=12, textColor=INK, alignment=TA_RIGHT),
        'rightbold': ParagraphStyle('rightbold', fontName=BOLD, fontSize=8.6, leading=12, textColor=INK, alignment=TA_RIGHT),
        'total': ParagraphStyle('total', fontName=BOLD, fontSize=15.5, leading=23, textColor=colors.white, alignment=TA_RIGHT),
        'white': ParagraphStyle('white', fontName=BOLD, fontSize=8.5, leading=13, textColor=colors.white),
    }

    def para(value, style='body'):
        return Paragraph(escape(clean_text(value)).replace('\n', '<br/>'), styles[style])

    def field(label, value, prominent=False):
        return [para(label.upper(), 'label'), para(value or 'Não informado', 'name' if prominent else 'body')]

    logo = ROOT / 'static/logo.png'
    reference = date_br(order.get('os_date') or order.get('created_at'))
    status = order.get('status') or 'Aberta'
    payment = {'Pendente':'A receber', 'Efetivado':'Recebido', 'Pago':'Recebido', 'Recebido':'Recebido', 'Cancelado':'Cancelado'}.get(order.get('pay_status'), order.get('pay_status') or 'A receber')
    vehicle = order.get('model') or 'Veículo não informado'
    plate = order.get('plate') or 'Sem placa'

    def first_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(DARK)
        canvas.rect(0, HEIGHT-113, WIDTH, 113, fill=1, stroke=0)
        canvas.setFillColor(RED)
        canvas.rect(0, HEIGHT-116, WIDTH, 3, fill=1, stroke=0)
        if logo.exists():
            canvas.drawImage(ImageReader(str(logo)), MARGIN, HEIGHT-87, width=148, height=67, preserveAspectRatio=True, mask='auto')
        canvas.setFont(BOLD, 7)
        canvas.setFillColor(colors.HexColor('#b4bfce'))
        canvas.drawRightString(WIDTH-MARGIN, HEIGHT-29, 'ORDEM DE SERVIÇO')
        canvas.setFont(BOLD, 25)
        canvas.setFillColor(colors.white)
        canvas.drawRightString(WIDTH-MARGIN, HEIGHT-59, '#' + number)
        canvas.setFont(REGULAR, 8)
        canvas.setFillColor(colors.HexColor('#d5dce7'))
        canvas.drawRightString(WIDTH-MARGIN, HEIGHT-79, reference + '  |  ' + clean_text(status))
        canvas.restoreState()
        footer(canvas, doc)

    def later_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(DARK)
        canvas.rect(0, HEIGHT-57, WIDTH, 57, fill=1, stroke=0)
        canvas.setFillColor(RED)
        canvas.rect(0, HEIGHT-60, WIDTH, 3, fill=1, stroke=0)
        canvas.setFont(BOLD, 9)
        canvas.setFillColor(colors.white)
        canvas.drawString(MARGIN, HEIGHT-34, 'FCAR REPARAÇÃO AUTOMOTIVA')
        canvas.drawRightString(WIDTH-MARGIN, HEIGHT-34, 'OS #' + number + '  |  CONTINUAÇÃO')
        canvas.restoreState()
        footer(canvas, doc)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(MARGIN, 33, WIDTH-MARGIN, 33)
        canvas.setFillColor(MUTED)
        canvas.setFont(REGULAR, 6.6)
        canvas.drawString(MARGIN, 20, 'FCAR Reparação Automotiva  |  OS #' + number)
        canvas.drawRightString(WIDTH-MARGIN, 20, f'Página {doc.page}')
        canvas.restoreState()

    doc = BaseDocTemplate(output, pagesize=A4, title=f'FCAR - Ordem de Serviço #{number}',
        author='FCAR Reparação Automotiva', leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=137, bottomMargin=47, pageCompression=1)
    first = Frame(MARGIN, 47, CONTENT, HEIGHT-183, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    later = Frame(MARGIN, 47, CONTENT, HEIGHT-127, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id='first', frames=[first], onPage=first_page),
                          PageTemplate(id='later', frames=[later], onPage=later_page)])

    story = [NextPageTemplate('later')]
    identity = Table([[field('Cliente', order.get('client_name'), True),
                       field('Veículo', vehicle, True)]], colWidths=[CONTENT*.52, CONTENT*.48])
    identity.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'), ('BACKGROUND',(0,0),(-1,-1),PAPER),
        ('BOX',(0,0),(-1,-1),.5,LINE), ('LINEAFTER',(0,0),(0,-1),.5,LINE),
        ('LEFTPADDING',(0,0),(-1,-1),14), ('RIGHTPADDING',(0,0),(-1,-1),14),
        ('TOPPADDING',(0,0),(-1,-1),13), ('BOTTOMPADDING',(0,0),(-1,-1),14),
    ]))
    story += [identity, Spacer(1, 14)]
    details = Table([[field('Placa',plate), field('Responsável',order.get('mech') or 'Não definido'),
                      field('Pagamento',payment + ' · ' + (order.get('pay_method') or 'Não informado'))]],
                    colWidths=[CONTENT*.24,CONTENT*.36,CONTENT*.4])
    details.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),
                                ('RIGHTPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    story += [details]

    def item_section(title, items):
        if not items:
            return
        rows = [[para(title,'tabletitle'),'','',''],
                [para('DESCRIÇÃO','tablehead'),para('QTD.','tablehead'),para('UNITÁRIO','tablehead'),para('TOTAL','tablehead')]]
        for item in items:
            rows.append([para(item.get('description') or 'Item sem descrição'),para(quantity(item.get('qty')),'right'),
                         para(money(item.get('unit_price')),'right'),para(money(item.get('total')),'rightbold')])
        table = LongTable(rows, colWidths=[CONTENT*.53,CONTENT*.09,CONTENT*.19,CONTENT*.19],
                          repeatRows=2, splitByRow=1, splitInRow=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),('SPAN',(0,0),(-1,0)),
            ('BACKGROUND',(0,1),(-1,1),PAPER),
            ('ROWBACKGROUNDS',(0,2),(-1,-1),[colors.white,colors.HexColor('#fbfcfe')]),
            ('LINEBELOW',(0,1),(-1,1),.7,LINE),('LINEBELOW',(0,2),(-1,-1),.35,LINE),
            ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),
            ('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),
            ('LEFTPADDING',(0,0),(-1,0),0),('TOPPADDING',(0,0),(-1,0),15),
        ]))
        story.append(table)

    item_section('Peças e materiais', data['pecas'])
    services = list(data['servicos_itens'])
    if data['mao_obra']:
        services.insert(0, dict(description='Mão de obra adicional',qty=1,unit_price=data['mao_obra'],total=data['mao_obra']))
    item_section('Mão de obra e serviços',services)
    if not data['pecas'] and not services:
        story += [Spacer(1,18),para('Atendimento sem itens detalhados.', 'small')]

    summary = Table([
        [para('Peças e materiais'),para(money(data['pecas_total']),'right')],
        [para('Mão de obra e serviços'),para(money(data['servicos_total']),'right')],
        [para('TOTAL DA OS','white'),para(money(data['total']),'total')],
    ],colWidths=[142,133],hAlign='RIGHT')
    summary.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),7),
        ('BOTTOMPADDING',(0,0),(-1,-1),7),('LEFTPADDING',(0,0),(-1,-1),12),
        ('RIGHTPADDING',(0,0),(-1,-1),12),('BACKGROUND',(0,0),(-1,1),PAPER),
        ('BACKGROUND',(0,2),(-1,2),RED),('LINEBELOW',(0,0),(-1,0),.35,LINE),
    ]))
    story.append(KeepTogether([Spacer(1,17),summary]))

    if order.get('notes'):
        story += [CondPageBreak(65),para('Observações do atendimento','section'),para(order['notes'])]

    closing_width = CONTENT - (88 if public_url else 0)
    sign_width = (closing_width - 24) / 2
    signatures = Table([
        [para(order.get('mech') or 'Responsável pelo atendimento','small'), '', para(order.get('client_name') or 'Cliente','small')],
        [para('Responsável pelo atendimento','label'), '', para('Cliente','label')],
    ], colWidths=[sign_width,24,sign_width],hAlign='LEFT')
    signatures.setStyle(TableStyle([
        ('LINEABOVE',(0,0),(0,0),.5,colors.HexColor('#b7c1cf')),
        ('LINEABOVE',(2,0),(2,0),.5,colors.HexColor('#b7c1cf')),
        ('TOPPADDING',(0,0),(-1,0),7),('BOTTOMPADDING',(0,0),(-1,-1),2),
        ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
    ]))
    if public_url:
        qr_buffer = BytesIO()
        qrcode.make(public_url).save(qr_buffer,format='PNG')
        qr_buffer.seek(0)
        qr = Image(qr_buffer,width=64,height=64)
        link = Paragraph('<link href="'+escape(public_url, {'"':'&quot;'})+'" color="#69778b">'+escape(clean_text(public_url))+'</link>', styles['small'])
        access = Table([[[signatures,Spacer(1,11),para('Consulte a OS e salve o PDF pelo QR Code ou pelo link.','small'),link],qr]],
                       colWidths=[closing_width,88])
        access.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
            ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),
        ]))
        story.append(KeepTogether([Spacer(1,27),access]))
    else:
        story.append(KeepTogether([Spacer(1,27),signatures]))

    doc.build(story)
    output.seek(0)
    return output
