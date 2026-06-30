"""
Módulo de métricas e consultas DuckDB para Acompanhamento de Metas.

Responsabilidades:
- calcular_metricas_periodo: Métricas principais do dashboard
- obter_detalhes_por_fornecedor: Detalhamento por fornecedor
- obter_clientes_positivados: Análise de clientes positivados
- obter_avaliacao_positivacao: Avaliação de positivação com janela de 6 meses
- obter_detalhamento_cliente: Detalhamento por cliente e fornecedor
- obter_dados_notas_fiscais: Dados de faturamento no nível de nota fiscal
"""

from datetime import datetime, timedelta
import pandas as pd
import duckdb
import streamlit as st

from utils.etl import prepare_for_duckdb


def calcular_metricas_periodo(df_faturamento, df_meta, data_inicio, data_fim, condicoes_where="", filtros_usuario=None):
    """Calcula métricas para o período usando consultas DuckDB com filtros.
    
    Args:
        filtros_usuario: dict opcional com 'codigos_permitidos' para filtrar meta
    """

    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))
    conn.register('df_meta', prepare_for_duckdb(df_meta))

    query_faturamento = f"""
    SELECT
        codvendedor,
        codfornec,
        codigo_cliente,
        valor_faturado,
        valor_troca,
        valor_pedido,
        peso_liquido_total,
        quantidade,
        data,
        tipo_movimento
    FROM df_faturamento
    WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
    AND {condicoes_where}
    """

    df_faturamento_periodo = conn.execute(query_faturamento).df()

    valor_faturado = 0
    valor_pedido = 0
    peso_faturado = 0
    peso_pedido = 0
    clientes_unicos = 0
    clientes_positivados_1kg = 0
    cliente_positivados_1kg_pedido = 0
    faturamento_bruto = 0
    valor_troca_produto = 0
    valor_devolucao_venda = 0
    valor_devolucao_troca = 0

    if not df_faturamento_periodo.empty:
        valor_faturado = df_faturamento_periodo[
            (df_faturamento_periodo['tipo_movimento'] != 'TROCA')
        ]['valor_faturado'].sum()

        valor_pedido = df_faturamento_periodo[
            (df_faturamento_periodo['tipo_movimento'] == 'PEDIDO')
        ]['valor_pedido'].sum()

        peso_faturado = df_faturamento_periodo[
            (df_faturamento_periodo['tipo_movimento'].isin(['VENDA', 'DEVOLUCAO VENDA', 'DEVOLUCAO TROCA']))
        ]['peso_liquido_total'].sum()

        peso_pedido = df_faturamento_periodo[
            (df_faturamento_periodo['tipo_movimento'].isin(['VENDA', 'DEVOLUCAO VENDA', 'DEVOLUCAO TROCA', 'PEDIDO']))
        ]['peso_liquido_total'].sum()

        clientes_unicos = df_faturamento_periodo[
            (df_faturamento_periodo['tipo_movimento'] != 'TROCA') &
            (df_faturamento_periodo['valor_faturado'] > 0)
        ]['codigo_cliente'].nunique()

        clientes_peso_total = df_faturamento_periodo[
            ~df_faturamento_periodo['tipo_movimento'].isin(['TROCA', 'PEDIDO'])
        ].groupby('codigo_cliente')['peso_liquido_total'].sum().reset_index()

        clientes_peso_total_pedido = df_faturamento_periodo[
            df_faturamento_periodo['tipo_movimento'] != 'TROCA'
        ].groupby('codigo_cliente')['peso_liquido_total'].sum().reset_index()

        clientes_positivados_1kg = clientes_peso_total[
            clientes_peso_total['peso_liquido_total'] >= 1
        ]['codigo_cliente'].nunique()

        cliente_positivados_1kg_pedido = clientes_peso_total_pedido[
            clientes_peso_total_pedido['peso_liquido_total'] >= 1
        ]['codigo_cliente'].nunique()

        faturamento_bruto = df_faturamento_periodo[df_faturamento_periodo['tipo_movimento'] == 'VENDA']['valor_faturado'].sum()
        valor_troca_produto = df_faturamento_periodo[df_faturamento_periodo['tipo_movimento'] == 'TROCA']['valor_troca'].sum()
        valor_devolucao_venda = df_faturamento_periodo[df_faturamento_periodo['tipo_movimento'] == 'DEVOLUCAO VENDA']['valor_faturado'].sum()
        valor_devolucao_troca = df_faturamento_periodo[df_faturamento_periodo['tipo_movimento'] == 'DEVOLUCAO TROCA']['valor_faturado'].sum()

    # Query para meta
    # Construir condição para meta baseada em condicoes_where e/ou filtros_usuario
    cond_meta_vendedor = "1=1"
    cond_meta_fornec = "1=1"

    # Extrair condições de vendedor do condicoes_where
    if "codvendedor IN" in condicoes_where:
        try:
            start = condicoes_where.find("codvendedor IN (") + len("codvendedor IN (")
            end = condicoes_where.find(")", start)
            codvendedores_str = condicoes_where[start:end]
            cond_meta_vendedor = f"m.codvendedor IN ({codvendedores_str})"
        except:
            pass
    elif "codvendedor =" in condicoes_where:
        try:
            codvendedor = condicoes_where.split("codvendedor = ")[1].strip()
            cond_meta_vendedor = f"m.codvendedor = {codvendedor}"
        except:
            pass

    # Extrair condições de fornecedor do condicoes_where
    if "codfornec IN" in condicoes_where:
        try:
            start = condicoes_where.find("codfornec IN (") + len("codfornec IN (")
            end = condicoes_where.find(")", start)
            codfornecs_str = condicoes_where[start:end]
            cond_meta_fornec = f"m.codfornec IN ({codfornecs_str})"
        except:
            pass

    # Fallback: se não extraiu nada do condicoes_where, usar filtros_usuario
    if cond_meta_vendedor == "1=1" and filtros_usuario and 'codigos_permitidos' in filtros_usuario:
        codigos_permitidos = filtros_usuario['codigos_permitidos']
        if codigos_permitidos:
            cond_meta_vendedor = f"m.codvendedor IN ({','.join(map(str, codigos_permitidos))})"

    query_meta = f"""
    SELECT
        m.codvendedor,
        m.codfornec,
        COALESCE(m.meta_valor, 0) as meta_valor,
        COALESCE(m.meta_positivacao, 0) as meta_positivacao
    FROM df_meta m
    WHERE EXTRACT(YEAR FROM m.data) = {data_inicio.year}
    AND EXTRACT(MONTH FROM m.data) = {data_inicio.month}
    AND {cond_meta_vendedor}
    AND {cond_meta_fornec}
    """

    df_meta_periodo = conn.execute(query_meta).df()

    if df_meta_periodo.empty:
        meta_valor = 0
        meta_positivacao = 0
    else:
        meta_valor = df_meta_periodo['meta_valor'].sum()
        meta_positivacao = df_meta_periodo['meta_positivacao'].sum()

    percentual_meta_valor = (valor_faturado / meta_valor * 100) if meta_valor > 0 else 0
    percentual_meta_positivacao = (clientes_unicos / meta_positivacao * 100) if meta_positivacao > 0 else 0

    dias_no_mes = (data_fim - data_inicio).days + 1
    dias_totais_mes = (data_fim.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    dias_totais_mes = dias_totais_mes.day

    tendencia_fechamento = (percentual_meta_valor / dias_no_mes) * dias_totais_mes if dias_no_mes > 0 else 0
    ideal_mes = (dias_no_mes / dias_totais_mes) * 100 if dias_totais_mes > 0 else 0

    conn.close()

    return {
        'meta_valor': meta_valor,
        'meta_positivacao': meta_positivacao,
        'valor_faturado': valor_faturado,
        'valor_pedido': valor_pedido,
        'peso_faturado': peso_faturado,
        'peso_pedido': peso_pedido,
        'clientes_ativos': clientes_unicos,
        'clientes_positivados_1kg': clientes_positivados_1kg,
        'cliente_positivados_1kg_pedido': cliente_positivados_1kg_pedido,
        'percentual_meta_valor': percentual_meta_valor,
        'percentual_meta_positivacao': percentual_meta_positivacao,
        'tendencia_fechamento': tendencia_fechamento,
        'ideal_mes': ideal_mes,
        'dias_percorridos': dias_no_mes,
        'dias_totais_mes': dias_totais_mes,
        'faturamento_bruto': faturamento_bruto,
        'valor_troca_produto': valor_troca_produto,
        'valor_devolucao_venda': valor_devolucao_venda,
        'valor_devolucao_troca': valor_devolucao_troca,
        'troca_total': valor_devolucao_troca + valor_troca_produto
    }


def obter_detalhes_por_fornecedor(df_faturamento, df_meta, data_inicio, data_fim, condicoes_where=""):
    """Obtém detalhamento de métricas por fornecedor."""
    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))
    conn.register('df_meta', prepare_for_duckdb(df_meta))

    query = f"""
    WITH faturamento_filtrado AS (
        SELECT
            codvendedor,
            codfornec,
            fornecedor,
            COUNT(DISTINCT codigo_cliente) as clientes_ativos,
            SUM(CASE WHEN tipo_movimento <> 'TROCA' THEN valor_faturado ELSE 0 END) as valor_faturado,
            SUM(valor_troca) as valor_troca_total,
            sum(valor_pedido) as valor_pedido_total
        FROM df_faturamento
        WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
        AND {condicoes_where}
        GROUP BY codvendedor, codfornec, fornecedor
    ),
    meta_agregada AS (
        SELECT
            codvendedor,
            codfornec,
            fornecedor,
            SUM(meta_positivacao) as meta_positivacao,
            SUM(meta_valor) as meta_valor
        FROM df_meta
        WHERE EXTRACT(YEAR FROM data) = {data_inicio.year}
            AND EXTRACT(MONTH FROM data) = {data_inicio.month}
            AND {' AND '.join(
                p for p in condicoes_where.split(' AND ')
                if any(col in p.lstrip() for col in ['codvendedor', 'codfornec', 'fornecedor'])
            ) or '1=1' if condicoes_where else '1=1'}
        GROUP BY codvendedor, codfornec, fornecedor
    )
    SELECT
        COALESCE(m.fornecedor, f.fornecedor) as "Fornecedor",
        SUM(m.meta_positivacao) as "Meta Positivação",
        COALESCE(SUM(f.clientes_ativos), 0) as "Positivação",
        SUM(m.meta_valor) as "Meta Valor",
        COALESCE(SUM(f.valor_faturado), 0) as "Valor Faturado",
        COALESCE(SUM(f.valor_pedido_total), 0) as "Valor Pedido",
        CASE
            WHEN SUM(m.meta_valor) > 0 THEN
                COALESCE(SUM(f.valor_faturado), 0) / SUM(m.meta_valor) * 100
            ELSE 0
        END as "% Meta",
        COALESCE(SUM(f.valor_troca_total)*-1, 0) as "Troca Total",
        CASE
            WHEN COALESCE(SUM(f.valor_faturado), 0) > 0 THEN
                (COALESCE(SUM(f.valor_troca_total)*-1, 0) / COALESCE(SUM(f.valor_faturado), 0) * 100)
            ELSE 0
        END as "% Troca"
    FROM meta_agregada m
    LEFT JOIN faturamento_filtrado f ON m.codvendedor = f.codvendedor
        AND m.codfornec = f.codfornec
        AND COALESCE(m.fornecedor, '') = COALESCE(f.fornecedor, '')
    WHERE m.fornecedor IS NOT NULL
    GROUP BY COALESCE(m.fornecedor, f.fornecedor)
    HAVING COALESCE(m.fornecedor, f.fornecedor) IS NOT NULL
    ORDER BY "Valor Faturado" DESC
    """

    df_detalhes = conn.execute(query).df()

    if not df_detalhes.empty:
        total_row = {
            "Fornecedor": "TOTAL",
            "Meta Positivação": df_detalhes["Meta Positivação"].sum(),
            "Positivação": df_detalhes["Positivação"].sum(),
            "Meta Valor": df_detalhes["Meta Valor"].sum(),
            "Valor Faturado": df_detalhes["Valor Faturado"].sum(),
            "Valor Pedido": df_detalhes["Valor Pedido"].sum(),
            "% Meta": (df_detalhes["Valor Faturado"].sum() / df_detalhes["Meta Valor"].sum() * 100) if df_detalhes["Meta Valor"].sum() > 0 else 0,
            "Troca Total": df_detalhes["Troca Total"].sum(),
            "% Troca": (df_detalhes["Troca Total"].sum() / df_detalhes["Valor Faturado"].sum() * 100) if df_detalhes["Valor Faturado"].sum() > 0 else 0
        }
        df_detalhes = pd.concat([df_detalhes, pd.DataFrame([total_row])], ignore_index=True)

    conn.close()
    return df_detalhes


def obter_clientes_positivados(df_faturamento, df_clientes, data_inicio, data_fim, condicoes_where="1=1", fornecedores_selecionados=None):
    """Obtém análise de clientes positivados com janela de 3 meses.
    
    Args:
        fornecedores_selecionados: lista opcional de nomes de fornecedores para filtrar.
            Se None ou vazio, usa a lista padrão de fornecedores.
    """
    primeiro_dia_mes_atual = data_inicio.replace(day=1)

    if primeiro_dia_mes_atual.month <= 3:
        ano = primeiro_dia_mes_atual.year - 1
        mes = 12 + (primeiro_dia_mes_atual.month - 3)
    else:
        ano = primeiro_dia_mes_atual.year
        mes = primeiro_dia_mes_atual.month - 3

    data_inicio_3meses = primeiro_dia_mes_atual.replace(year=ano, month=mes, day=1)

    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))
    conn.register('df_clientes', prepare_for_duckdb(df_clientes))

    fornecedores_padrao = ['PANES', 'IOG', 'QUEIJINHOS', 'PAÇOCA']
    
    # Usar fornecedores selecionados se fornecidos, senão usar lista padrão
    if fornecedores_selecionados and len(fornecedores_selecionados) > 0:
        fornecedores_alvo = [f for f in fornecedores_padrao if f in fornecedores_selecionados]
        if not fornecedores_alvo:
            fornecedores_alvo = fornecedores_padrao
    else:
        fornecedores_alvo = fornecedores_padrao
    
    # Extrair apenas condições aplicáveis a df_clientes (cod_vendedor)
    # Ignorar codfornec, rede, etc. que não existem na tabela de clientes
    condicoes_clientes = []
    if condicoes_where and condicoes_where != "1=1":
        if "codvendedor IN" in condicoes_where:
            start = condicoes_where.find("codvendedor IN (") + len("codvendedor IN (")
            end = condicoes_where.find(")", start)
            codvendedores_str = condicoes_where[start:end]
            condicoes_clientes.append(f"cod_vendedor IN ({codvendedores_str})")
        elif "codvendedor =" in condicoes_where:
            codvendedor = condicoes_where.split("codvendedor = ")[1].strip()
            condicoes_clientes.append(f"cod_vendedor = {codvendedor}")
    
    condicao_clientes_final = " AND ".join(condicoes_clientes) if condicoes_clientes else "1=1"

    colunas_fornecedores = []
    for fornec in fornecedores_alvo:
        colunas_fornecedores.append(f"""
        CASE
            WHEN EXISTS (
                SELECT 1 FROM df_faturamento
                WHERE codigo_cliente = cf.codcliente
                AND fornecedor = '{fornec}'
                AND data BETWEEN '{data_inicio}' AND '{data_fim}'
                AND tipo_movimento = 'VENDA'
                AND valor_faturado > 0
            ) THEN 'OK'
            WHEN EXISTS (
                SELECT 1 FROM df_faturamento
                WHERE codigo_cliente = cf.codcliente
                AND fornecedor = '{fornec}'
                AND data BETWEEN '{data_inicio_3meses}' AND '{data_fim}'
                AND tipo_movimento = 'VENDA'
                AND valor_faturado > 0
            ) THEN 'POSITIVAR'
            ELSE 'X'
        END AS "{fornec}"
        """)

    query = f"""
    WITH clientes_filtrados AS (
        SELECT DISTINCT codcliente, nome, cidade
        FROM df_clientes
        WHERE {condicao_clientes_final}
    ),
    clientes_com_compras AS (
        SELECT DISTINCT f.codigo_cliente
        FROM df_faturamento f
        INNER JOIN clientes_filtrados cf ON f.codigo_cliente = cf.codcliente
        WHERE f.data BETWEEN '{data_inicio_3meses}' AND '{data_fim}'
        AND f.tipo_movimento = 'VENDA'
        AND f.valor_faturado > 0
        AND f.fornecedor IN {tuple(fornecedores_alvo)}
    )
    SELECT
        cf.codcliente AS "Código",
        cf.nome AS "Cliente",
        cf.cidade AS "Cidade",
        {', '.join(colunas_fornecedores)}
    FROM clientes_filtrados cf
    INNER JOIN clientes_com_compras ccc ON cf.codcliente = ccc.codigo_cliente
    ORDER BY cf.cidade, cf.nome
    """

    try:
        df_resultado = conn.execute(query).df()
        for fornec in fornecedores_alvo:
            if fornec not in df_resultado.columns:
                df_resultado[fornec] = 'X'
    except Exception as e:
        st.error(f"❌ Erro na consulta de clientes positivados: {e}")
        colunas_base = ["Código", "Cliente", "Cidade"] + fornecedores_alvo
        df_resultado = pd.DataFrame(columns=colunas_base)

    conn.close()
    return df_resultado


def obter_avaliacao_positivacao(df_faturamento, df_clientes, data_inicio, data_fim, condicoes_where="1=1", fornecedores_selecionados=None):
    """
    Obtém avaliação de positivação dos clientes com janela de 6 meses.

    Filtros aplicados via condicoes_where (já construído com supervisor/vendedor/rede).
    Filtro de fornecedor aplicado via fornecedores_selecionados (para colunas).
    """

    data_inicio_periodo = data_inicio
    data_fim_periodo = data_fim
    data_inicio_6meses = data_inicio_periodo - timedelta(days=180)

    meses_diff = (data_fim_periodo.year - data_inicio_6meses.year) * 12 + (data_fim_periodo.month - data_inicio_6meses.month) + 1
    meses_diff = max(1, meses_diff)

    fornecedores_padrao = ['PANES', 'IOG', 'QUEIJINHOS','PAÇOCA']

    if fornecedores_selecionados and len(fornecedores_selecionados) > 0:
        fornecedores_alvo = [f for f in fornecedores_padrao if f in fornecedores_selecionados]
        if not fornecedores_alvo:
            fornecedores_alvo = fornecedores_padrao
    else:
        fornecedores_alvo = fornecedores_padrao

    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))
    conn.register('df_clientes', prepare_for_duckdb(df_clientes))

    # Extrair códigos de vendedor da condicoes_where para filtrar clientes
    condicoes_clientes = []
    if condicoes_where and condicoes_where != "1=1":
        if "codvendedor IN" in condicoes_where:
            start = condicoes_where.find("codvendedor IN (") + len("codvendedor IN (")
            end = condicoes_where.find(")", start)
            codvendedores_str = condicoes_where[start:end]
            condicoes_clientes.append(f"cf.cod_vendedor IN ({codvendedores_str})")
        elif "codvendedor =" in condicoes_where:
            codvendedor = condicoes_where.split("codvendedor = ")[1].strip()
            condicoes_clientes.append(f"cf.cod_vendedor = {codvendedor}")

    condicao_clientes_final = " AND ".join(condicoes_clientes) if condicoes_clientes else "1=1"

    # Colunas de status
    colunas_fornecedores_status = []
    for fornec in fornecedores_alvo:
        colunas_fornecedores_status.append(f"""
        CASE
            WHEN EXISTS (
                SELECT 1 FROM df_faturamento f2
                WHERE f2.codigo_cliente = cf.codcliente
                AND f2.fornecedor = '{fornec}'
                AND f2.data BETWEEN '{data_inicio_periodo.strftime('%Y-%m-%d')}' AND '{data_fim_periodo.strftime('%Y-%m-%d')}'
                AND f2.tipo_movimento IN ('VENDA', 'DEVOLUCAO VENDA', 'DEVOLUCAO TROCA')
                AND {condicoes_where}
                GROUP BY f2.codigo_cliente, f2.fornecedor
                HAVING SUM(f2.peso_liquido_total) >= 1
            ) THEN 'OK'
            WHEN EXISTS (
                SELECT 1 FROM df_faturamento f2
                WHERE f2.codigo_cliente = cf.codcliente
                AND f2.fornecedor = '{fornec}'
                AND f2.data BETWEEN '{data_inicio_6meses.strftime('%Y-%m-%d')}' AND '{data_fim_periodo.strftime('%Y-%m-%d')}'
                AND f2.tipo_movimento IN ('VENDA', 'DEVOLUCAO VENDA', 'DEVOLUCAO TROCA')
                AND {condicoes_where}
                GROUP BY f2.codigo_cliente, f2.fornecedor
                HAVING SUM(f2.peso_liquido_total) >= 1
            ) THEN 'POSITIVAR'
            ELSE 'X'
        END AS "{fornec}"
        """)

    # Colunas de valor (para Excel)
    colunas_fornecedores_valor = []
    for fornec in fornecedores_alvo:
        colunas_fornecedores_valor.append(f"""
        COALESCE((
            SELECT ROUND(SUM(
                CASE
                    WHEN f2.tipo_movimento = 'VENDA' THEN f2.valor_faturado
                    WHEN f2.tipo_movimento IN ('DEVOLUCAO VENDA', 'DEVOLUCAO TROCA') THEN f2.valor_faturado
                    ELSE 0
                END
            ), 2)
            FROM df_faturamento f2
            WHERE f2.codigo_cliente = cf.codcliente
            AND f2.fornecedor = '{fornec}'
            AND f2.data BETWEEN '{data_inicio_periodo.strftime('%Y-%m-%d')}' AND '{data_fim_periodo.strftime('%Y-%m-%d')}'
            AND f2.tipo_movimento IN ('VENDA', 'DEVOLUCAO VENDA', 'DEVOLUCAO TROCA')
            AND {condicoes_where}
        ), 0) AS "VALOR_{fornec}"
        """)

    colunas_fornecedores_media = []
    for fornec in fornecedores_alvo:
        colunas_fornecedores_media.append(f"""
        COALESCE((
            SELECT ROUND(SUM(
                CASE
                    WHEN f2.tipo_movimento = 'VENDA' THEN f2.valor_faturado
                    WHEN f2.tipo_movimento IN ('DEVOLUCAO VENDA', 'DEVOLUCAO TROCA') THEN f2.valor_faturado
                    ELSE 0
                END
            ) / {meses_diff}, 2)
            FROM df_faturamento f2
            WHERE f2.codigo_cliente = cf.codcliente
            AND f2.fornecedor = '{fornec}'
            AND f2.data BETWEEN '{data_inicio_6meses.strftime('%Y-%m-%d')}' AND '{data_fim_periodo.strftime('%Y-%m-%d')}'
            AND f2.tipo_movimento IN ('VENDA', 'DEVOLUCAO VENDA', 'DEVOLUCAO TROCA')
            AND {condicoes_where}
        ), 0) AS "MEDIA_{fornec}"
        """)

    query = f"""
    WITH clientes_filtrados AS (
        SELECT DISTINCT
            cf.codcliente,
            cf.nome,
            COALESCE(CAST(cf."CNPJ" AS VARCHAR), 'N/A') as cnpj,
            COALESCE(cf."Vendedor", 'Sem vendedor') as vendedor,
            COALESCE(cf.cidade, 'N/A') as cidade,
            cf.cod_vendedor
        FROM df_clientes cf
        WHERE {condicao_clientes_final}
    ),
    rede_cliente AS (
        SELECT DISTINCT
            codigo_cliente,
            FIRST(rede) as rede
        FROM df_faturamento
        WHERE data BETWEEN '{data_inicio_6meses.strftime('%Y-%m-%d')}' AND '{data_fim_periodo.strftime('%Y-%m-%d')}'
        AND {condicoes_where}
        GROUP BY codigo_cliente
    ),
    clientes_com_historico AS (
        SELECT DISTINCT f.codigo_cliente
        FROM df_faturamento f
        INNER JOIN clientes_filtrados cf ON f.codigo_cliente = cf.codcliente
        WHERE f.data BETWEEN '{data_inicio_6meses.strftime('%Y-%m-%d')}' AND '{data_fim_periodo.strftime('%Y-%m-%d')}'
        AND f.tipo_movimento IN ('VENDA', 'DEVOLUCAO VENDA', 'DEVOLUCAO TROCA')
        AND f.fornecedor IN {tuple(fornecedores_alvo)}
        AND {condicoes_where}
    )
    SELECT
        cf.codcliente AS "Código",
        cf.nome AS "Cliente",
        cf.cnpj AS "CNPJ",
        cf.vendedor AS "RCA",
        cf.cidade AS "Cidade",
        COALESCE(rc.rede, 'N/A') as "Rede",
        {', '.join(colunas_fornecedores_status)},
        {', '.join(colunas_fornecedores_valor)},
        {', '.join(colunas_fornecedores_media)}
    FROM clientes_filtrados cf
    LEFT JOIN rede_cliente rc ON cf.codcliente = rc.codigo_cliente
    INNER JOIN clientes_com_historico cch ON cf.codcliente = cch.codigo_cliente
    ORDER BY cf.cidade, cf.nome
    """

    try:
        df_resultado = conn.execute(query).df()

        for fornec in fornecedores_alvo:
            if fornec not in df_resultado.columns:
                df_resultado[fornec] = 'X'
            if f"VALOR_{fornec}" not in df_resultado.columns:
                df_resultado[f"VALOR_{fornec}"] = 0.0
            if f"MEDIA_{fornec}" not in df_resultado.columns:
                df_resultado[f"MEDIA_{fornec}"] = 0.0

    except Exception as e:
        st.error(f"❌ Erro na consulta de avaliação de positivação: {e}")
        colunas_base = ["Código", "Cliente", "CNPJ", "RCA", "Cidade", "Rede"]
        colunas_status = fornecedores_alvo
        colunas_valor = [f"VALOR_{f}" for f in fornecedores_alvo]
        colunas_media = [f"MEDIA_{f}" for f in fornecedores_alvo]
        df_resultado = pd.DataFrame(columns=colunas_base + colunas_status + colunas_valor + colunas_media)

    conn.close()

    # Dataframe para grid (apenas status)
    colunas_grid = ["Código", "Cliente", "CNPJ", "RCA", "Cidade", "Rede"] + fornecedores_alvo
    colunas_existentes_grid = [c for c in colunas_grid if c in df_resultado.columns]
    df_grid = df_resultado[colunas_existentes_grid].copy()

    # Dataframe para Excel (com valores)
    df_excel = df_resultado.copy()
    rename_dict = {}
    for fornec in fornecedores_alvo:
        if f"VALOR_{fornec}" in df_excel.columns:
            rename_dict[f"VALOR_{fornec}"] = f"Faturado {fornec} (R$)"
        if f"MEDIA_{fornec}" in df_excel.columns:
            rename_dict[f"MEDIA_{fornec}"] = f"Média Mensal {fornec} (R$)"
    df_excel = df_excel.rename(columns=rename_dict)

    return df_grid, df_excel, fornecedores_alvo


def obter_detalhamento_cliente(df_faturamento, data_inicio, data_fim, condicoes_where="1=1"):
    """Obtém detalhamento de faturamento por cliente e fornecedor."""
    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))

    query = f"""
    WITH faturamento_cliente AS (
        SELECT
            codigo_cliente,
            nome_cliente,
            fornecedor,
            SUM(CASE WHEN tipo_movimento = 'VENDA' THEN valor_faturado ELSE 0 END) as venda_faturado,
            SUM(CASE WHEN tipo_movimento = 'DEVOLUCAO VENDA' THEN valor_faturado ELSE 0 END) as devolucao_venda,
            SUM(CASE WHEN tipo_movimento = 'DEVOLUCAO TROCA' THEN valor_faturado ELSE 0 END) as devolucao_troca,
            SUM(CASE WHEN tipo_movimento = 'TROCA' THEN valor_troca ELSE 0 END) as troca_produto,
            SUM(CASE WHEN tipo_movimento = 'PEDIDO' THEN valor_pedido ELSE 0 END) as valor_pedido
        FROM df_faturamento
        WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
        AND {condicoes_where}
        GROUP BY codigo_cliente, nome_cliente, fornecedor
    )
    SELECT
        fornecedor as "Fornecedor",
        codigo_cliente as "Código Cliente",
        nome_cliente as "Cliente",
        ROUND(venda_faturado, 2) as "Venda (Faturado)",
        ROUND(devolucao_venda, 2) as "Devolução Venda",
        ROUND(devolucao_troca, 2) as "Devolução Troca",
        ROUND(troca_produto, 2) as "Troca",
        ROUND(venda_faturado + devolucao_venda + devolucao_troca, 2) as "Total Faturado",
        ROUND(valor_pedido, 2) as "Valor Pedido"
    FROM faturamento_cliente
    WHERE ROUND(venda_faturado + devolucao_venda + devolucao_troca, 2) != 0
       OR ROUND(valor_pedido, 2) != 0
    ORDER BY fornecedor, nome_cliente
    """

    df_detalhamento = conn.execute(query).df()
    conn.close()
    return df_detalhamento


def obter_dados_notas_fiscais(df_faturamento, data_inicio, data_fim, condicoes_where="1=1"):
    """Obtém dados de faturamento no nível de nota fiscal para acompanhamento por nota.

    Agrupa por data, cliente, número da nota e tipo de movimento,
    retornando os valores de valor_faturado e valor_troca.
    """
    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))

    query = f"""
    SELECT
        data,
        nome_cliente,
        numero_nota,
        tipo_movimento,
        ROUND(SUM(valor_faturado), 2) as valor_faturado,
        ROUND(SUM(valor_troca), 2) as valor_troca
    FROM df_faturamento
    WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
    AND {condicoes_where}
    AND tipo_movimento IN ('VENDA', 'DEVOLUCAO VENDA', 'DEVOLUCAO TROCA')
    GROUP BY data, nome_cliente, numero_nota, tipo_movimento
    ORDER BY data, nome_cliente, numero_nota
    """

    df_notas = conn.execute(query).df()
    conn.close()
    return df_notas
