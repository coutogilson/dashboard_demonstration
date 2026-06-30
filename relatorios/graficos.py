"""
Módulo de gráficos Plotly para Acompanhamento de Metas.

Responsabilidades:
- criar_grafico_metas: Gauge chart do percentual de meta
- criar_grafico_evolucao_diaria: Evolução diária faturamento vs meta
- criar_grafico_venda_meses: Venda por mês (últimos 2 anos)
- criar_grafico_venda_diaria: Venda diária do mês atual
"""

from datetime import datetime, timedelta
import pandas as pd
import duckdb
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.formatador import formatar_moeda_abreviada
from utils.etl import prepare_for_duckdb


def criar_grafico_metas(metricas, titulo):
    """Cria gauge chart do percentual da meta de valor."""
    fig = go.Figure()
    fig.add_trace(go.Indicator(
        mode="gauge+number+delta",
        value=metricas['percentual_meta_valor'],
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': f"% da Meta de Valor"},
        delta={'reference': 100},
        gauge={
            'axis': {'range': [None, 120]},
            'bar': {'color': "darkgreen"},
            'steps': [
                {'range': [0, 80], 'color': "red"},
                {'range': [80, 100], 'color': "yellow"},
            ],
            'threshold': {
                'line': {'color': "green", 'width': 4},
                'thickness': 0.75,
                'value': 100
            }
        }
    ))
    fig.update_layout(height=300)
    return fig


def criar_grafico_evolucao_diaria(df_faturamento, df_meta, data_inicio, data_fim, condicoes_where=""):
    """Cria gráfico de evolução diária do faturamento acumulado vs meta."""
    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))
    conn.register('df_meta', prepare_for_duckdb(df_meta))

    query = f"""
    SELECT
        f.data,
        SUM(f.valor_faturado) as valor_diario
    FROM df_faturamento f
    WHERE f.data BETWEEN '{data_inicio}' AND '{data_fim}'
    AND f.tipo_movimento not in('TROCA')
    AND {condicoes_where}
    GROUP BY f.data
    ORDER BY f.data
    """

    df_evolucao = conn.execute(query).df()

    if condicoes_where != "1=1":
        try:
            cond_meta_vendedor = "1=1"
            cond_meta_fornec = "1=1"

            if "codvendedor IN" in condicoes_where:
                start = condicoes_where.find("codvendedor IN (") + len("codvendedor IN (")
                end = condicoes_where.find(")", start)
                codvendedores_str = condicoes_where[start:end]
                cond_meta_vendedor = f"m.codvendedor IN ({codvendedores_str})"

            if "codfornec IN" in condicoes_where:
                start = condicoes_where.find("codfornec IN (") + len("codfornec IN (")
                end = condicoes_where.find(")", start)
                codfornecs_str = condicoes_where[start:end]
                cond_meta_fornec = f"m.codfornec IN ({codfornecs_str})"

            meta_query = f"""
            SELECT
                SUM(m.meta_valor) as meta_total
            FROM df_meta m
            WHERE EXTRACT(YEAR FROM m.data) = {data_inicio.year}
              AND EXTRACT(MONTH FROM m.data) = {data_inicio.month}
              AND {cond_meta_vendedor}
              AND {cond_meta_fornec}
            """
        except Exception:
            meta_query = f"""
            SELECT
                SUM(m.meta_valor) as meta_total
            FROM df_meta m
            WHERE EXTRACT(YEAR FROM m.data) = {data_inicio.year}
              AND EXTRACT(MONTH FROM m.data) = {data_inicio.month}
            """
    else:
        meta_query = f"""
        SELECT
            SUM(m.meta_valor) as meta_total
        FROM df_meta m
        WHERE EXTRACT(YEAR FROM m.data) = {data_inicio.year}
          AND EXTRACT(MONTH FROM m.data) = {data_inicio.month}
        """

    df_meta_result = conn.execute(meta_query).df()
    meta_total = df_meta_result['meta_total'].iloc[0] if not df_meta_result.empty and df_meta_result['meta_total'].iloc[0] is not None else 0

    conn.close()

    if df_evolucao.empty:
        todas_datas = pd.date_range(start=data_inicio, end=data_fim, freq='D')
        df_evolucao = pd.DataFrame({'data': todas_datas})
        df_evolucao['valor_diario'] = 0
        df_evolucao['acumulado'] = 0
    else:
        df_evolucao['acumulado'] = df_evolucao['valor_diario'].cumsum()

    if meta_total > 0:
        df_evolucao['meta'] = meta_total

    fig = go.Figure()

    if not df_evolucao.empty and df_evolucao['acumulado'].sum() > 0:
        fig.add_trace(go.Scatter(
            x=df_evolucao['data'],
            y=df_evolucao['acumulado'],
            mode='lines+markers',
            name='Faturamento Acumulado',
            line=dict(color='blue', width=3)
        ))

    if 'meta' in df_evolucao.columns and meta_total > 0:
        fig.add_trace(go.Scatter(
            x=df_evolucao['data'],
            y=df_evolucao['meta'],
            mode='lines',
            name='Meta do Mês',
            line=dict(color='red', width=2, dash='dash')
        ))

    if df_evolucao.empty and meta_total == 0:
        fig.add_annotation(
            text="Não há dados de faturamento ou meta para o período",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=16)
        )

    fig.update_layout(
        title='Evolução Diária - Faturamento vs Meta',
        xaxis_title='Data',
        yaxis_title='Valor Acumulado (R$)',
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    return fig


def criar_grafico_venda_meses(df_faturamento, condicoes_where):
    """Cria gráfico de vendas por mês (últimos 2 anos)."""
    conn = duckdb.connect()
    hoje = datetime.now()
    data_inicio = hoje - timedelta(days=730)

    # Preparar DataFrame para compatibilidade com DuckDB
    df_fat = prepare_for_duckdb(df_faturamento)
    conn.register('df_faturamento', df_fat)

    query = f"""
    SELECT
    extract(YEAR FROM data) as ano,
    CASE EXTRACT(MONTH FROM data)
        WHEN 1 THEN 'jan' WHEN 2 THEN 'fev' WHEN 3 THEN 'mar' WHEN 4 THEN 'abr'
        WHEN 5 THEN 'mai' WHEN 6 THEN 'jun' WHEN 7 THEN 'jul' WHEN 8 THEN 'ago'
        WHEN 9 THEN 'set' WHEN 10 THEN 'out' WHEN 11 THEN 'nov' WHEN 12 THEN 'dez'
    END as mes,
    CASE EXTRACT(MONTH FROM data)
        WHEN 1 THEN 'janeiro' WHEN 2 THEN 'fevereiro' WHEN 3 THEN 'março' WHEN 4 THEN 'abril'
        WHEN 5 THEN 'maio' WHEN 6 THEN 'junho' WHEN 7 THEN 'julho' WHEN 8 THEN 'agosto'
        WHEN 9 THEN 'setembro' WHEN 10 THEN 'outubro' WHEN 11 THEN 'novembro' WHEN 12 THEN 'dezembro'
    END as mescompleto,
    EXTRACT(MONTH FROM data) as mes_num,
    SUM(valor_faturado) as valor_total
    FROM df_faturamento
    WHERE tipo_movimento != 'TROCA'
    AND {condicoes_where}
    AND data BETWEEN '{data_inicio.strftime('%Y-%m-%d')}' AND '{hoje.strftime('%Y-%m-%d')}'
    GROUP BY ano, mes_num
    ORDER BY extract(YEAR FROM data), EXTRACT(MONTH FROM data)
    """

    df_venda_meses = conn.execute(query).df()
    conn.close()

    df_venda_meses['ano_mes'] = df_venda_meses['mes'].astype(str) + '/' + df_venda_meses['ano'].astype(str).str[-2:]

    if df_venda_meses.empty:
        return None

    df_venda_meses['valor_formatado'] = df_venda_meses['valor_total'].apply(
        lambda x: f'R$ {x:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    )

    fig = px.bar(
        df_venda_meses,
        x='ano_mes',
        y='valor_total',
        labels={'ano_mes': 'Mês/Ano', 'valor_total': 'Valor Faturado (R$)'},
        title='Venda por Mês'
    )

    fig.update_layout(height=450)
    fig.update_traces(
        text=[formatar_moeda_abreviada(v) for v in df_venda_meses['valor_total']],
        textposition='outside',
        hovertemplate='Mês: %{customdata[0]}<br>Valor: %{customdata[1]}<extra></extra>',
        customdata=df_venda_meses[['mescompleto', 'valor_formatado']].values,
        width=0.25
    )

    return fig


def criar_grafico_venda_diaria(df_faturamento, data_inicio, data_fim, condicoes_where):
    """Cria gráfico de venda diária do período selecionado."""
    conn = duckdb.connect()

    # Preparar DataFrame para compatibilidade com DuckDB
    df_fat = prepare_for_duckdb(df_faturamento)
    conn.register('df_faturamento', df_fat)

    query = f"""
    SELECT
        data,
        SUM(valor_faturado) as valor_total
    FROM df_faturamento
    WHERE tipo_movimento != 'TROCA'
    AND {condicoes_where}
    AND data BETWEEN '{data_inicio.strftime('%Y-%m-%d')}' AND '{data_fim.strftime('%Y-%m-%d')}'
    GROUP BY data
    ORDER BY data
    """

    df_venda_diaria = conn.execute(query).df()
    conn.close()

    if df_venda_diaria.empty:
        return None

    df_venda_diaria['valor_formatado'] = df_venda_diaria['valor_total'].apply(
        lambda x: f'R$ {x:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    )

    fig = px.bar(
        df_venda_diaria,
        x='data',
        y='valor_total',
        labels={'data': 'Data', 'valor_total': 'Valor Faturado (R$)'},
        title='Venda Diária - Mês Atual'
    )

    fig.update_layout(height=450)
    fig.update_traces(
        text=[formatar_moeda_abreviada(v) for v in df_venda_diaria['valor_total']],
        textposition='outside',
        hovertemplate='Data: %{x|%d/%m/%Y}<br>Valor: %{customdata}<extra></extra>',
        customdata=df_venda_diaria['valor_formatado'].values,
        marker_color=df_venda_diaria['valor_total'].apply(
            lambda x: 'green' if x > 10000 else ('yellow' if x > 0 else 'red')
        )
    )

    return fig
