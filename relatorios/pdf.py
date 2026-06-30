"""
Módulo de geração de PDF e exportação para Acompanhamento de Metas.

Responsabilidades:
- gerar_pdf_relatorio: Geração do PDF completo com ReportLab
- formatar_celula_pdf: Formatação de células para tabelas do PDF
- criar_botao_download_pdf: Botão de download para PDF
- criar_botao_download_zip: Botão de download para ZIP
- exportar_relatorios_todos_vendedores: Geração de ZIP com relatórios em lote
- exibir_grid_avaliacao_positivacao: Grid AgGrid para avaliação de positivação
"""

from datetime import datetime
import io
import zipfile
import base64
import pandas as pd
import streamlit as st
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors

from utils.formatador import formatar_moeda, formatar_numero, formatar_moeda_abreviada, formatar_percentual
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

from relatorios.metricas import (
    calcular_metricas_periodo,
    obter_detalhes_por_fornecedor,
    obter_clientes_positivados,
    obter_detalhamento_cliente,
    obter_dados_notas_fiscais,
)


def formatar_celula_pdf(valor, formato='R$'):
    """Formata valor para exibição em células do PDF."""
    if valor == 0:
        return ""
    if formato == 'R$':
        return formatar_moeda(valor)
    elif formato == '%':
        return formatar_percentual(valor)
    elif formato == 'num':
        return formatar_numero(valor)
    else:
        return str(valor)


def gerar_pdf_relatorio(metricas, df_detalhes_fornecedor, df_clientes_positivados,
                        df_detalhamento_cliente, periodo, vendedor_nome=None,
                        fornecedor_nome=None, df_notas_fiscais=None):
    """Gera o relatório PDF completo com todas as seções."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []

    titulo_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=14,
        spaceAfter=20,
        alignment=1
    )

    titulo_texto = "RELATÓRIO DE ACOMPANHAMENTO DE METAS"
    if vendedor_nome:
        titulo_texto += f"<br/>Vendedor: {vendedor_nome}"
    if fornecedor_nome:
        titulo_texto += f"<br/>Fornecedor: {fornecedor_nome}"

    titulo = Paragraph(titulo_texto, titulo_style)
    story.append(titulo)

    periodo_para = Paragraph(f"Período: {periodo}", styles['Normal'])
    story.append(periodo_para)
    story.append(Paragraph(f"Dias: {formatar_numero(metricas['dias_percorridos'])}/{formatar_numero(metricas['dias_totais_mes'])}", styles['Normal']))
    story.append(Spacer(1, 15))

    story.append(Paragraph("RESUMO GERAL", styles['Heading2']))
    story.append(Spacer(1, 10))

    metricas_data = [
        ['Indicador', 'Meta', 'Realizado', 'Pedido', '% Atingido', 'Tendência'],
        [
            'Valor',
            formatar_moeda(metricas['meta_valor']),
            formatar_moeda(metricas['valor_faturado']),
            formatar_moeda(metricas['valor_pedido']),
            formatar_percentual(metricas['percentual_meta_valor']),
            formatar_percentual(metricas['tendencia_fechamento'])
        ]
    ]

    table = Table(metricas_data, colWidths=[80, 90, 90, 80, 80, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#580C59')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8F9FA')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
    ]))

    story.append(table)
    story.append(Spacer(1, 15))

    # Seção: Detalhamento por Fornecedor
    if not df_detalhes_fornecedor.empty:
        story.append(Paragraph("DETALHAMENTO POR FORNECEDOR", styles['Heading2']))
        story.append(Spacer(1, 10))

        detalhes_data = [['Fornecedor', 'Meta Posit', 'Posit', 'Meta R$', 'Faturado', 'Pedido', '% Meta', 'Troca', '% Troca']]

        for _, row in df_detalhes_fornecedor.iterrows():
            detalhes_data.append([
                str(row['Fornecedor']),
                formatar_numero(row['Meta Positivação']),
                formatar_numero(row['Positivação']),
                formatar_moeda(row['Meta Valor']),
                formatar_moeda(row['Valor Faturado']),
                formatar_moeda(row['Valor Pedido']),
                formatar_percentual(row['% Meta']),
                formatar_moeda(row['Troca Total']),
                formatar_percentual(row['% Troca'])
            ])

        detalhes_table = Table(detalhes_data, colWidths=[60, 40, 40, 70, 70, 60, 60, 60, 60])
        detalhes_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#A23B72')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (0, 1), (-1, -2), colors.white),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#2E86AB')),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))

        story.append(detalhes_table)
        story.append(Spacer(1, 15))

    # Seção: Análise de Clientes
    if not df_clientes_positivados.empty:
        story.append(Paragraph("ANÁLISE DE CLIENTES", styles['Heading2']))
        story.append(Spacer(1, 5))

        legenda_style = ParagraphStyle('Legenda', parent=styles['Normal'], fontSize=7, spaceAfter=5)
        legenda_text = ("Legenda: VERDE (OK) = compras no mês || "
                        "AMARELO (POSITIVAR) = Clientes sem compra no mês || "
                        "VERMELHO (X) = Não comprou nos últimos 3 meses")
        legenda = Paragraph(legenda_text, legenda_style)
        story.append(legenda)
        story.append(Spacer(1, 5))

        # Detectar colunas de fornecedores dinamicamente
        colunas_fixas = {"Código", "Cliente", "Cidade"}
        fornecedores_lista = [
            col for col in df_clientes_positivados.columns
            if col not in colunas_fixas
        ]
        cabecalho_clientes = ['Código', 'Cliente', 'Cidade'] + fornecedores_lista
        clientes_data = [cabecalho_clientes]
        # Larguras: código=25, cliente=80, cidade=60, cada fornecedor=32
        col_widths = [25, 80, 60] + [32] * len(fornecedores_lista)

        estilo_celula = ParagraphStyle('CelulaTabela', parent=styles['Normal'],
                                       fontSize=5, leading=5, alignment=1, wordWrap='LTR')
        styles.add(estilo_celula, 'estilo_celula')

        for _, row in df_clientes_positivados.head(200).iterrows():
            linha = [
                str(row['Código']),
                Paragraph(str(row['Cliente'])[:50], styles['estilo_celula']),
                Paragraph(str(row['Cidade'])[:40], styles['estilo_celula'])
            ]
            for fornec in fornecedores_lista:
                status = row.get(fornec, 'X')
                linha.append(status)
            clientes_data.append(linha)

        clientes_table = Table(clientes_data, colWidths=col_widths, repeatRows=1)

        estilo_tabela = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e86ab')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 5),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            ('LEADING', (0, 0), (-1, 0), 6),
            ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 6),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('WORDWRAP', (1, 1), (1, -1), True),
            ('WORDWRAP', (2, 1), (2, -1), True),
        ]

        for i in range(1, len(clientes_data)):
            for j in range(3, len(clientes_data[0])):
                status = clientes_data[i][j]
                if status == 'OK':
                    estilo_tabela.append(('BACKGROUND', (j, i), (j, i), colors.green))
                    estilo_tabela.append(('TEXTCOLOR', (j, i), (j, i), colors.white))
                    estilo_tabela.append(('FONTNAME', (j, i), (j, i), 'Helvetica-Bold'))
                elif status == 'POSITIVAR':
                    estilo_tabela.append(('BACKGROUND', (j, i), (j, i), colors.yellow))
                    estilo_tabela.append(('FONTSIZE', (j, i), (j, i), 4))
                elif status == 'X':
                    estilo_tabela.append(('BACKGROUND', (j, i), (j, i), colors.red))
                    estilo_tabela.append(('TEXTCOLOR', (j, i), (j, i), colors.white))

        clientes_table.setStyle(TableStyle(estilo_tabela))
        story.append(clientes_table)
        story.append(Spacer(1, 10))

        total_clientes = len(df_clientes_positivados)
        # Detectar dinamicamente as colunas de fornecedores (excluir colunas fixas)
        colunas_fixas = {"Código", "Cliente", "Cidade"}
        fornecedores_lista = [
            col for col in df_clientes_positivados.columns
            if col not in colunas_fixas
        ]
        clientes_com_compra = df_clientes_positivados[fornecedores_lista].apply(
            lambda row: any(status in ['OK', 'POSITIVAR'] for status in row), axis=1
        ).sum()
        clientes_sem_compra = df_clientes_positivados[fornecedores_lista].apply(
            lambda row: all(status in ('X', 'POSITIVAR') for status in row), axis=1
        ).sum()

        resumo_style = ParagraphStyle('Resumo', parent=styles['Normal'], fontSize=7, spaceAfter=3)
        resumo_text = (f"Total de Clientes: {total_clientes} | "
                       f"Clientes Ativos: {clientes_com_compra} | "
                       f"Clientes Inativos: {total_clientes - clientes_com_compra} | "
                       f"Clientes sem Compra no Mês: {clientes_sem_compra}")
        resumo = Paragraph(resumo_text, resumo_style)
        story.append(resumo)

    # Seção: Detalhamento por Fornecedor e Cliente
    if not df_detalhamento_cliente.empty:
        story.append(Paragraph("DETALHAMENTO POR FORNECEDOR E CLIENTE", styles['Heading2']))
        story.append(Spacer(1, 10))

        detalhamento_data = [['Fornecedor', 'Código', 'Cliente', 'Venda',
                              'Dev. Venda', 'Dev. Troca', 'Troca', 'Total Faturado', 'Pedido']]
        df_detalhamento_cliente = df_detalhamento_cliente.sort_values(['Fornecedor', 'Cliente'])

        fornecedor_atual = None
        total_fornecedor = {'venda': 0, 'devol_venda': 0, 'devol_troca': 0,
                            'troca': 0, 'total': 0, 'pedido': 0}

        # Estilo para célula de cliente no detalhamento
        estilo_cliente_detalhe = ParagraphStyle(
            'ClienteDetalhe',
            parent=styles['Normal'],
            fontSize=6,
            leading=7,
            alignment=0,
            wordWrap='CJK'
        )

        for _, row in df_detalhamento_cliente.iterrows():
            fornecedor = str(row['Fornecedor'])
            codigo = str(row['Código Cliente'])
            cliente_nome = str(row['Cliente'])

            # Quebrar nome do cliente se necessário (máx ~25 caracteres por linha)
            if len(cliente_nome) > 25:
                partes = []
                resto = cliente_nome
                while len(resto) > 25:
                    espaco = resto.rfind(' ', 0, 25)
                    if espaco > 0:
                        partes.append(resto[:espaco])
                        resto = resto[espaco+1:]
                    else:
                        partes.append(resto[:25])
                        resto = resto[25:]
                partes.append(resto)
                cliente = '<br/>'.join(partes)
            else:
                cliente = cliente_nome

            if fornecedor_atual is not None and fornecedor != fornecedor_atual:
                detalhamento_data.append([
                    "SUBTOTAL", "", "",
                    formatar_moeda(total_fornecedor['venda']),
                    formatar_moeda(total_fornecedor['devol_venda']),
                    formatar_moeda(total_fornecedor['devol_troca']),
                    formatar_moeda(total_fornecedor['troca']),
                    formatar_moeda(total_fornecedor['total']),
                    formatar_moeda(total_fornecedor['pedido'])
                ])
                detalhamento_data.append([])
                total_fornecedor = {k: 0 for k in total_fornecedor}

            fornecedor_atual = fornecedor

            venda_valor = float(row['Venda (Faturado)'])
            devol_venda_valor = float(row['Devolução Venda'])
            devol_troca_valor = float(row['Devolução Troca'])
            troca_valor = float(row['Troca'])
            total_valor = float(row['Total Faturado'])
            pedido_valor = float(row['Valor Pedido'])

            detalhamento_data.append([
                fornecedor, codigo,
                Paragraph(cliente, estilo_cliente_detalhe),
                formatar_celula_pdf(venda_valor, 'R$'),
                formatar_celula_pdf(devol_venda_valor, 'R$'),
                formatar_celula_pdf(devol_troca_valor, 'R$'),
                formatar_celula_pdf(troca_valor, 'R$'),
                formatar_celula_pdf(total_valor, 'R$'),
                formatar_celula_pdf(pedido_valor, 'R$')
            ])

            total_fornecedor['venda'] += venda_valor
            total_fornecedor['devol_venda'] += devol_venda_valor
            total_fornecedor['devol_troca'] += devol_troca_valor
            total_fornecedor['troca'] += troca_valor
            total_fornecedor['total'] += total_valor
            total_fornecedor['pedido'] += pedido_valor

        if fornecedor_atual is not None:
            detalhamento_data.append([
                "SUBTOTAL", "", "",
                formatar_moeda(total_fornecedor['venda']),
                formatar_moeda(total_fornecedor['devol_venda']),
                formatar_moeda(total_fornecedor['devol_troca']),
                formatar_moeda(total_fornecedor['troca']),
                formatar_moeda(total_fornecedor['total']),
                formatar_moeda(total_fornecedor['pedido'])
            ])

        total_geral = {
            'venda': df_detalhamento_cliente['Venda (Faturado)'].sum(),
            'devol_venda': df_detalhamento_cliente['Devolução Venda'].sum(),
            'devol_troca': df_detalhamento_cliente['Devolução Troca'].sum(),
            'troca': df_detalhamento_cliente['Troca'].sum(),
            'total': df_detalhamento_cliente['Total Faturado'].sum(),
            'pedido': df_detalhamento_cliente['Valor Pedido'].sum()
        }

        detalhamento_data.append([])
        detalhamento_data.append([
            "TOTAL GERAL", "", "",
            formatar_moeda(total_geral['venda']),
            formatar_moeda(total_geral['devol_venda']),
            formatar_moeda(total_geral['devol_troca']),
            formatar_moeda(total_geral['troca']),
            formatar_moeda(total_geral['total']),
            formatar_moeda(total_geral['pedido'])
        ])

        detalhamento_table = Table(detalhamento_data, colWidths=[60, 25, 120, 45, 45, 45, 45, 45, 45])
        detalhamento_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#79D0F6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F8F9FA')),
            ('BACKGROUND', (0, -2), (-1, -2), colors.HexColor('#FFE0B2')),
        ]))

        story.append(detalhamento_table)
        story.append(Spacer(1, 15))

    # Seção: Acompanhamento por Nota Fiscal
    if df_notas_fiscais is not None and not df_notas_fiscais.empty:
        story.append(Paragraph("ACOMPANHAMENTO POR NOTA FISCAL", styles['Heading2']))
        story.append(Spacer(1, 10))

        notas_data = gerar_tabela_acompanhamento_notas(df_notas_fiscais, styles)
        story.append(notas_data)
        story.append(Spacer(1, 15))

    story.append(Spacer(1, 15))
    data_geracao = Paragraph(f"Relatório gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal'])
    story.append(data_geracao)

    doc.build(story)
    buffer.seek(0)
    return buffer


def gerar_tabela_acompanhamento_notas(df_notas, styles):
    """Gera a tabela de acompanhamento por nota fiscal para o PDF.

    Args:
        df_notas: DataFrame com colunas data, nome_cliente, numero_nota,
                  tipo_movimento, valor_faturado, valor_troca
        styles: SampleStyleSheet do ReportLab

    Returns:
        Table do ReportLab pronta para ser adicionada ao story
    """
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle

    # Estilo para células da tabela
    estilo_celula = ParagraphStyle(
        'CelulaNotaFiscal',
        parent=styles['Normal'],
        fontSize=6,
        leading=7,
        alignment=1,
        wordWrap='CJK'
    )

    estilo_cliente = ParagraphStyle(
        'ClienteNotaFiscal',
        parent=styles['Normal'],
        fontSize=6,
        leading=7,
        alignment=0,
        wordWrap='CJK'
    )

    estilo_subtotal = ParagraphStyle(
        'SubtotalNotaFiscal',
        parent=styles['Normal'],
        fontSize=6,
        leading=7,
        alignment=1,
        wordWrap='CJK',
        fontName='Helvetica-Bold'
    )

    # Cabeçalho
    cabecalho = [
        Paragraph('Data', estilo_celula),
        Paragraph('Cliente', estilo_celula),
        Paragraph('Nº Nota', estilo_celula),
        Paragraph('Tipo Movimento', estilo_celula),
        Paragraph('Valor Faturado\n(Venda/Devolução)', estilo_celula),
        Paragraph('Troca', estilo_celula),
    ]

    dados_tabela = [cabecalho]

    # Preparar dados agrupados
    df = df_notas.copy()
    df['data'] = pd.to_datetime(df['data']).dt.strftime('%d/%m/%Y')

    # Variáveis de controle para agrupamento
    data_anterior = None
    cliente_anterior = None
    total_dia_valor_faturado = 0.0
    total_dia_valor_troca = 0.0
    total_geral_valor_faturado = 0.0
    total_geral_valor_troca = 0.0

    # Lista para armazenar linhas de subtotal (índices)
    linhas_subtotal = []

    for idx, (_, row) in enumerate(df.iterrows()):
        data_atual = str(row['data'])
        cliente_atual = str(row['nome_cliente']) if pd.notna(row['nome_cliente']) else ''
        numero_nota = str(int(row['numero_nota'])) if pd.notna(row['numero_nota']) and row['numero_nota'] != '' else '-'
        tipo_mov = str(row['tipo_movimento']) if pd.notna(row['tipo_movimento']) else ''
        valor_fat = float(row['valor_faturado']) if pd.notna(row['valor_faturado']) else 0.0
        valor_troc = float(row['valor_troca']) if pd.notna(row['valor_troca']) else 0.0

        # Acumular totais do dia
        total_dia_valor_faturado += valor_fat
        total_dia_valor_troca += valor_troc
        total_geral_valor_faturado += valor_fat
        total_geral_valor_troca += valor_troc

        # Determinar se exibe data e cliente (merge visual)
        exibir_data = data_atual if data_atual != data_anterior else ''
        exibir_cliente = cliente_atual if (cliente_atual != cliente_anterior or data_atual != data_anterior) else ''

        # Formatar valores
        if valor_fat < 0:
            texto_valor_fat = f'<font color="red">{formatar_moeda(valor_fat)}</font>'
        else:
            texto_valor_fat = formatar_moeda(valor_fat) if valor_fat != 0 else ''

        if valor_troc < 0:
            texto_valor_troc = f'<font color="red">{formatar_moeda(valor_troc)}</font>'
        else:
            texto_valor_troc = formatar_moeda(valor_troc) if valor_troc != 0 else ''

        # Quebrar nome do cliente se necessário (máx ~35 caracteres por linha)
        cliente_exibicao = exibir_cliente
        if len(cliente_exibicao) > 35:
            # Tentar quebrar em espaço próximo
            partes = []
            resto = cliente_exibicao
            while len(resto) > 35:
                # Encontrar último espaço antes de 35
                espaco = resto.rfind(' ', 0, 35)
                if espaco > 0:
                    partes.append(resto[:espaco])
                    resto = resto[espaco+1:]
                else:
                    partes.append(resto[:35])
                    resto = resto[35:]
            partes.append(resto)
            cliente_exibicao = '<br/>'.join(partes)

        dados_tabela.append([
            Paragraph(exibir_data, estilo_celula),
            Paragraph(cliente_exibicao, estilo_cliente),
            Paragraph(numero_nota, estilo_celula),
            Paragraph(tipo_mov, estilo_celula),
            Paragraph(texto_valor_fat, estilo_celula),
            Paragraph(texto_valor_troc, estilo_celula),
        ])

        # Verificar se é o último registro ou mudou de data
        proximo_idx = idx + 1
        mudou_data = False
        if proximo_idx < len(df):
            prox_data = str(df.iloc[proximo_idx]['data'])
            if prox_data != data_atual:
                mudou_data = True
        else:
            mudou_data = True

        # Linha de subtotal do dia
        if mudou_data:
            if total_dia_valor_faturado < 0:
                texto_sub_fat = f'<font color="red">{formatar_moeda(total_dia_valor_faturado)}</font>'
            else:
                texto_sub_fat = formatar_moeda(total_dia_valor_faturado)

            if total_dia_valor_troca < 0:
                texto_sub_troc = f'<font color="red">{formatar_moeda(total_dia_valor_troca)}</font>'
            else:
                texto_sub_troc = formatar_moeda(total_dia_valor_troca)

            dados_tabela.append([
                Paragraph(f'Subtotal<br/>{data_atual}', estilo_subtotal),
                Paragraph('', estilo_subtotal),
                Paragraph('', estilo_subtotal),
                Paragraph('', estilo_subtotal),
                Paragraph(texto_sub_fat, estilo_subtotal),
                Paragraph(texto_sub_troc, estilo_subtotal),
            ])
            linhas_subtotal.append(len(dados_tabela) - 1)

            # Resetar totais do dia
            total_dia_valor_faturado = 0.0
            total_dia_valor_troca = 0.0

        data_anterior = data_atual
        cliente_anterior = cliente_atual

    # Linha de total geral
    if total_geral_valor_faturado < 0:
        texto_total_fat = f'<font color="red">{formatar_moeda(total_geral_valor_faturado)}</font>'
    else:
        texto_total_fat = formatar_moeda(total_geral_valor_faturado)

    if total_geral_valor_troca < 0:
        texto_total_troc = f'<font color="red">{formatar_moeda(total_geral_valor_troca)}</font>'
    else:
        texto_total_troc = formatar_moeda(total_geral_valor_troca)

    dados_tabela.append([
        Paragraph('TOTAL GERAL', estilo_subtotal),
        Paragraph('', estilo_subtotal),
        Paragraph('', estilo_subtotal),
        Paragraph('', estilo_subtotal),
        Paragraph(texto_total_fat, estilo_subtotal),
        Paragraph(texto_total_troc, estilo_subtotal),
    ])
    linha_total_geral = len(dados_tabela) - 1

    # Criar a tabela
    larguras = [55, 130, 45, 65, 65, 65]
    tabela = Table(dados_tabela, colWidths=larguras, repeatRows=1)

    # Construir estilo
    estilo_lista = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#7B2D8E')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEADING', (0, 0), (-1, -1), 7),
    ]

    # Destacar linhas de subtotal
    for linha_idx in linhas_subtotal:
        estilo_lista.append(('BACKGROUND', (0, linha_idx), (-1, linha_idx), colors.HexColor('#F0F0F0')))
        estilo_lista.append(('FONTNAME', (0, linha_idx), (-1, linha_idx), 'Helvetica-Bold'))

    # Destacar total geral
    estilo_lista.append(('BACKGROUND', (0, linha_total_geral), (-1, linha_total_geral), colors.HexColor("#79D0F6")))
    estilo_lista.append(('TEXTCOLOR', (0, linha_total_geral), (-1, linha_total_geral), colors.whitesmoke))
    estilo_lista.append(('FONTNAME', (0, linha_total_geral), (-1, linha_total_geral), 'Helvetica-Bold'))

    tabela.setStyle(TableStyle(estilo_lista))

    return tabela


def _limpar_colunas_agrid(df):
    """Remove colunas internas do AgGrid/índice de um DataFrame."""
    colunas_remover = [
        col for col in df.columns
        if col.startswith(('auto_', '_', 'Unnamed:', '::'))
        or col.lower() in ['index', 'level_0']
    ]
    if colunas_remover:
        df = df.drop(columns=colunas_remover)
    return df


def gerar_pdf_tabela(df, titulo, periodo):
    """Gera PDF simples com uma tabela formatada a partir de um DataFrame.

    Args:
        df: DataFrame com os dados da tabela
        titulo: Título do relatório
        periodo: String com o período (ex: "01/01/2024 a 31/01/2024")

    Returns:
        BytesIO buffer com o PDF gerado
    """
    # Remover colunas internas do AgGrid/índice
    df = _limpar_colunas_agrid(df)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, leftMargin=0.4*inch, rightMargin=0.4*inch)
    styles = getSampleStyleSheet()
    story = []

    titulo_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=13,
        spaceAfter=12,
        alignment=1
    )

    story.append(Paragraph(titulo, titulo_style))
    story.append(Paragraph(f"Período: {periodo}", styles['Normal']))
    story.append(Spacer(1, 12))

    if df.empty:
        story.append(Paragraph("Nenhum dado disponível.", styles['Normal']))
        doc.build(story)
        buffer.seek(0)
        return buffer

    # Converter DataFrame para dados da tabela
    cabecalho = [str(col) for col in df.columns]
    dados = [cabecalho]
    for _, row in df.iterrows():
        dados.append([str(val) if pd.notna(val) else '' for val in row])

    # Calcular largura das colunas proporcionalmente
    largura_disponivel = A4[0] - 0.8*inch  # ~175mm
    num_cols = len(cabecalho)
    col_widths = [largura_disponivel / num_cols] * num_cols

    # Para colunas com texto longo, dar mais espaço
    for i, col in enumerate(cabecalho):
        max_len = max(len(str(row[i])) if pd.notna(row[i]) else 0 for row in dados[1:]) if len(dados) > 1 else 0
        header_len = len(col)
        max_content = max(max_len, header_len)
        if max_content > 20:
            col_widths[i] = max(col_widths[i], largura_disponivel * 0.25)
        elif max_content < 8:
            col_widths[i] = min(col_widths[i], largura_disponivel * 0.10)

    # Normalizar para caber na página
    total = sum(col_widths)
    if total > largura_disponivel:
        col_widths = [w * largura_disponivel / total for w in col_widths]

    # Estilo para células com texto longo
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=6,
        leading=7,
        alignment=1,
        wordWrap='CJK'
    )

    # Preparar dados com Paragraph para texto longo
    dados_formatados = [cabecalho]
    for row in dados[1:]:
        linha_formatada = []
        for i, val in enumerate(row):
            if len(val) > 25:
                linha_formatada.append(Paragraph(val, cell_style))
            else:
                linha_formatada.append(val)
        dados_formatados.append(linha_formatada)

    tabela = Table(dados_formatados, colWidths=col_widths, repeatRows=1)

    estilo_tabela = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#580C59')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEADING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]

    # Destacar linhas alternadas
    for i in range(2, len(dados_formatados), 2):
        if i < len(dados_formatados):
            estilo_tabela.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F8F9FA')))

    tabela.setStyle(TableStyle(estilo_tabela))
    story.append(tabela)

    story.append(Spacer(1, 15))
    story.append(Paragraph(f"Relatório gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))

    doc.build(story)
    buffer.seek(0)
    return buffer


def gerar_excel_tabelas(dict_dfs, periodo):
    """Gera arquivo Excel com múltiplas abas a partir de um dicionário.

    Args:
        dict_dfs: Dicionário {nome_aba: dataframe}
        periodo: String com o período (usado no nome da planilha)

    Returns:
        BytesIO buffer com o arquivo Excel gerado
    """
    # Remover colunas internas do AgGrid/índice de todos os DataFrames
    dict_dfs = {nome: _limpar_colunas_agrid(df) for nome, df in dict_dfs.items()}

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book

        # Formato para cabeçalho
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'vcenter',
            'align': 'center',
            'fg_color': '#580C59',
            'font_color': 'white',
            'border': 1,
            'font_size': 10,
        })

        # Formato para células de moeda
        moeda_format = workbook.add_format({
            'num_format': 'R$ #.##0,00',
            'border': 1,
        })

        # Formato para percentual
        pct_format = workbook.add_format({
            'num_format': '0.0%',
            'border': 1,
        })

        # Formato para número
        num_format = workbook.add_format({
            'num_format': '#,##0',
            'border': 1,
        })

        # Formato padrão
        cell_format = workbook.add_format({
            'border': 1,
        })

        for nome_aba, df in dict_dfs.items():
            # Limitar nome da aba a 31 caracteres (limite do Excel)
            nome_aba_clean = nome_aba[:31]
            df.to_excel(writer, sheet_name=nome_aba_clean, index=False, startrow=0)

            worksheet = writer.sheets[nome_aba_clean]

            # Formatar cabeçalho
            for col_idx, col_name in enumerate(df.columns):
                worksheet.write(0, col_idx, col_name, header_format)

            # Ajustar largura das colunas
            for col_idx, col_name in enumerate(df.columns):
                max_len = max(
                    df[col_name].astype(str).map(len).max() if not df.empty else 0,
                    len(str(col_name))
                )
                worksheet.set_column(col_idx, col_idx, min(max_len + 3, 40))

            # Formatar células de dados
            for row_idx in range(len(df)):
                for col_idx, col_name in enumerate(df.columns):
                    valor = df.iloc[row_idx, col_idx]
                    cell_value = df.iloc[row_idx, col_idx]

                    # Detectar tipo de formatação pelo nome da coluna
                    if 'R$' in str(col_name) or 'Valor' in str(col_name) or 'Faturado' in str(col_name) or 'Meta' in str(col_name) or 'Pedido' in str(col_name) or 'Troca' in str(col_name) or 'Diferença' in str(col_name):
                        # Tentar converter para número
                        try:
                            if isinstance(valor, str):
                                # Remover formatação brasileira
                                valor_clean = valor.replace('R$ ', '').replace('.', '').replace(',', '.').strip()
                                cell_value = float(valor_clean)
                            worksheet.write(row_idx + 1, col_idx, cell_value, moeda_format)
                        except (ValueError, TypeError):
                            worksheet.write(row_idx + 1, col_idx, valor, cell_format)
                    elif '%' in str(col_name):
                        try:
                            if isinstance(valor, str):
                                valor_clean = valor.replace('%', '').replace(',', '.').strip()
                                cell_value = float(valor_clean) / 100
                            worksheet.write(row_idx + 1, col_idx, cell_value, pct_format)
                        except (ValueError, TypeError):
                            worksheet.write(row_idx + 1, col_idx, valor, cell_format)
                    elif 'Clientes' in str(col_name) or 'Positivação' in str(col_name) or 'Positivados' in str(col_name):
                        try:
                            if isinstance(valor, str):
                                valor_clean = valor.replace('.', '').strip()
                                cell_value = int(valor_clean)
                            worksheet.write(row_idx + 1, col_idx, cell_value, num_format)
                        except (ValueError, TypeError):
                            worksheet.write(row_idx + 1, col_idx, valor, cell_format)
                    else:
                        worksheet.write(row_idx + 1, col_idx, valor, cell_format)

    output.seek(0)
    return output


def criar_botao_download_pdf(pdf_buffer, filename):
    """Cria botão de download HTML para PDF."""
    b64_pdf = base64.b64encode(pdf_buffer.getvalue()).decode()
    href = (f'<a href="data:application/pdf;base64,{b64_pdf}" '
            f'download="{filename}" target="_blank" '
            f'style="display: inline-block; padding: 0.5rem 1rem; '
            f'background-color: #4CAF50; color: white; text-decoration: none; '
            f'border-radius: 4px; font-weight: bold;">📥 {filename}</a>')
    st.markdown(href, unsafe_allow_html=True)


def criar_botao_download_zip(zip_buffer, filename):
    """Cria botão de download HTML para ZIP."""
    b64_zip = base64.b64encode(zip_buffer.getvalue()).decode()
    href = (f'<a href="data:application/zip;base64,{b64_zip}" '
            f'download="{filename}" '
            f'style="display: inline-block; padding: 0.5rem 1rem; '
            f'background-color: #2196F3; color: white; text-decoration: none; '
            f'border-radius: 4px; font-weight: bold;">📦 {filename}</a>')
    st.markdown(href, unsafe_allow_html=True)


def exportar_relatorios_todos_vendedores(df_faturamento, df_meta, df_clientes,
                                         data_inicio, data_fim, periodo_str,
                                         condicoes_where="1=1",
                                         filtros_usuario=None):
    """Exporta relatórios PDF individuais em ZIP para vendedores com dados no período.
    
    Args:
        filtros_usuario: dict opcional com 'codigos_permitidos' para filtrar vendedores
    """
    import duckdb
    from utils.etl import prepare_for_duckdb

    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))
    conn.register('df_meta', prepare_for_duckdb(df_meta))

    # Construir condição para meta baseada em condicoes_where e/ou filtros_usuario
    cond_meta = condicoes_where
    if cond_meta == "1=1" and filtros_usuario and 'codigos_permitidos' in filtros_usuario:
        codigos_permitidos = filtros_usuario['codigos_permitidos']
        if codigos_permitidos:
            cond_meta = f"codvendedor IN ({','.join(map(str, codigos_permitidos))})"

    query_vendedores = f"""
    WITH vendedores_faturamento AS (
        SELECT DISTINCT codvendedor, vendedor
        FROM df_faturamento
        WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
        AND tipo_movimento != 'TROCA'
        AND valor_faturado > 0
        AND {condicoes_where}
    ),
    vendedores_meta AS (
        SELECT DISTINCT codvendedor, vendedor
        FROM df_meta
        WHERE EXTRACT(YEAR FROM data) = {data_inicio.year}
        AND EXTRACT(MONTH FROM data) = {data_inicio.month}
        AND meta_valor > 0
        AND {cond_meta}
    )
    SELECT
        COALESCE(f.codvendedor, m.codvendedor) as codvendedor,
        COALESCE(f.vendedor, m.vendedor) as vendedor
    FROM vendedores_faturamento f
    FULL OUTER JOIN vendedores_meta m ON f.codvendedor = m.codvendedor
    WHERE COALESCE(f.vendedor, m.vendedor) IS NOT NULL
    ORDER BY vendedor
    """

    df_vendedores = conn.execute(query_vendedores).df()
    conn.close()

    if df_vendedores.empty:
        return None, "Nenhum vendedor encontrado com faturamento ou meta no período selecionado"

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        total_vendedores = len(df_vendedores)
        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, (_, row) in enumerate(df_vendedores.iterrows()):
            codvendedor = row['codvendedor']
            vendedor_nome = row['vendedor']

            progresso = (i + 1) / total_vendedores
            progress_bar.progress(progresso)
            status_text.text(f"Gerando relatório para: {vendedor_nome} ({i + 1}/{total_vendedores})")

            try:
                condicoes_vendedor = f"codvendedor = {codvendedor}"

                metricas_vendedor = calcular_metricas_periodo(
                    df_faturamento, df_meta, data_inicio, data_fim, condicoes_vendedor
                )

                df_detalhes_fornecedor = obter_detalhes_por_fornecedor(
                    df_faturamento, df_meta, data_inicio, data_fim, condicoes_vendedor
                )

                df_clientes_positivados = obter_clientes_positivados(
                    df_faturamento, df_clientes, data_inicio, data_fim, condicoes_vendedor
                )

                df_detalhamento_cliente = obter_detalhamento_cliente(
                    df_faturamento, data_inicio, data_fim, condicoes_vendedor
                )

                df_notas_fiscais = obter_dados_notas_fiscais(
                    df_faturamento, data_inicio, data_fim, condicoes_vendedor
                )

                pdf_buffer = gerar_pdf_relatorio(
                    metricas_vendedor,
                    df_detalhes_fornecedor,
                    df_clientes_positivados,
                    df_detalhamento_cliente,
                    periodo_str,
                    vendedor_nome=vendedor_nome,
                    fornecedor_nome=None,
                    df_notas_fiscais=df_notas_fiscais
                )

                nome_arquivo = f"relatorio_{vendedor_nome.replace('/', '_').replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
                zip_file.writestr(nome_arquivo, pdf_buffer.getvalue())

            except Exception as e:
                st.warning(f"Erro ao gerar relatório para {vendedor_nome}: {str(e)}")
                continue

        progress_bar.empty()
        status_text.empty()

    zip_buffer.seek(0)
    return zip_buffer, f"Relatórios gerados para {len(df_vendedores)} vendedores"


def exibir_grid_avaliacao_positivacao(df_grid, fornecedores_alvo):
    """
    Exibe o grid de avaliação de positivação com cores condicionais.
    Usa AgGrid com JsCode para colorir células (OK=verde, POSITIVAR=amarelo, X=vermelho).
    """
    if df_grid.empty:
        st.warning("⚠️ Nenhum cliente encontrado para os filtros selecionados")
        return None

    gb = GridOptionsBuilder.from_dataframe(df_grid)

    gb.configure_pagination(paginationAutoPageSize=True, paginationPageSize=50)
    gb.configure_side_bar()
    gb.configure_default_column(
        groupable=True,
        value=True,
        enableRowGroup=True,
        editable=False,
        autoSize=True,
        filter=True,
        resizable=True
    )

    # Configuração específica para colunas de STATUS dos fornecedores (com cores)
    for fornec in fornecedores_alvo:
        if fornec in df_grid.columns:
            cell_style_jscode = JsCode("""
            function(params) {
                if (params.value === 'OK') {
                    return {
                        'color': 'white',
                        'backgroundColor': '#28a745',
                        'fontWeight': 'bold',
                        'textAlign': 'center'
                    };
                } else if (params.value === 'POSITIVAR') {
                    return {
                        'color': '#856404',
                        'backgroundColor': '#ffc107',
                        'fontWeight': 'bold',
                        'fontSize': '10px',
                        'textAlign': 'center'
                    };
                } else if (params.value === 'X') {
                    return {
                        'color': 'white',
                        'backgroundColor': '#dc3545',
                        'fontWeight': 'bold',
                        'textAlign': 'center'
                    };
                }
                return {'textAlign': 'center'};
            }
            """)

            gb.configure_column(
                fornec,
                cellStyle=cell_style_jscode,
                width=90,
                headerTooltip=f"Status de positivação - {fornec}"
            )

    gb.configure_column("Código", width=70)
    gb.configure_column("Cliente", width=200)
    gb.configure_column("CNPJ", width=130)
    gb.configure_column("RCA", width=130)
    gb.configure_column("Cidade", width=120)
    gb.configure_column("Rede", width=90)

    gb.configure_selection(selection_mode="multiple", use_checkbox=True)
    gridOptions = gb.build()

    num_linhas = len(df_grid)
    altura_grid = min(600, max(300, 35 + num_linhas * 28))

    grid_response = AgGrid(
        df_grid,
        gridOptions=gridOptions,
        enable_enterprise_modules=True,
        allow_unsafe_jscode=True,
        theme="streamlit",
        fit_columns_on_grid_load=True,
        height=altura_grid
    )

    return grid_response
