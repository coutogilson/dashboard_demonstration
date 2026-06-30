"""
Módulo de envio de email para Acompanhamento de Metas.

Responsabilidades:
- configurar_smtp: Configuração SMTP a partir de variáveis de ambiente
- enviar_email_smtp: Envio de email com anexo PDF
- testar_conexao_smtp: Teste de conexão SMTP
- enviar_relatorios_por_email: Envio em lote para vendedores
- carregar_dados_vendedores: Carregamento com validação de email
"""

import os
import smtplib
from datetime import datetime
import io
import pandas as pd
import streamlit as st
import duckdb
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from relatorios.metricas import (
    calcular_metricas_periodo,
    obter_detalhes_por_fornecedor,
    obter_clientes_positivados,
    obter_detalhamento_cliente
)
from relatorios.pdf import gerar_pdf_relatorio
from relatorios.dados import VENDEDORES_PARQUET, carregar_dados_vendedores_df
from utils.etl import prepare_for_duckdb, convert_to_numpy_dtypes


def configurar_smtp():
    """Configura as credenciais SMTP a partir das variáveis de ambiente."""
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_username = os.environ.get('SMTP_USERNAME', '')
    return smtp_server, smtp_port, smtp_username


def enviar_email_smtp(destinatario, assunto, corpo, anexo_pdf=None, nome_arquivo="relatorio.pdf", smtp_password=""):
    """Envia email com anexo PDF via SMTP."""
    try:
        smtp_server, smtp_port, smtp_username = configurar_smtp()

        if not smtp_username or not smtp_password:
            st.error("❌ Credenciais SMTP não configuradas")
            return False

        msg = MIMEMultipart()
        msg['From'] = smtp_username
        msg['To'] = destinatario
        msg['Subject'] = assunto
        msg.attach(MIMEText(corpo, 'html'))

        if anexo_pdf:
            part = MIMEApplication(anexo_pdf.getvalue(), Name=nome_arquivo)
            part['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
            msg.attach(part)

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=60) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(msg)
            return True
        else:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=60) as server:
                if smtp_port == 587:
                    server.starttls()
                server.login(smtp_username, smtp_password)
                server.send_message(msg)
            return True

    except Exception as e:
        st.error(f"❌ Erro ao enviar email: {e}")
        return False


def testar_conexao_smtp(smtp_server, smtp_port, smtp_username, smtp_password):
    """Testa a conexão SMTP com as credenciais fornecidas."""
    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
            if smtp_password:
                server.login(smtp_username, smtp_password)
            server.quit()
            return True, "✅ Conexão SSL bem-sucedida!"
        elif smtp_port == 587:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
            server.starttls()
            if smtp_password:
                server.login(smtp_username, smtp_password)
            server.quit()
            return True, "✅ Conexão TLS bem-sucedida!"
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
            if smtp_password:
                server.login(smtp_username, smtp_password)
            server.quit()
            return True, f"✅ Conexão na porta {smtp_port} bem-sucedida!"
    except Exception as e:
        return False, f"❌ Erro: {str(e)}"


def carregar_dados_vendedores():
    """Carrega dados de vendedores com validação de email."""
    try:
        df_vendedores = pd.read_parquet(VENDEDORES_PARQUET)
        df_vendedores = convert_to_numpy_dtypes(df_vendedores)

        if 'código' in df_vendedores.columns:
            df_vendedores = df_vendedores.rename(columns={'código': 'codvendedor'})
        if 'nome' in df_vendedores.columns:
            df_vendedores = df_vendedores.rename(columns={'nome': 'vendedor'})

        if 'email' not in df_vendedores.columns:
            colunas_email = [col for col in df_vendedores.columns if 'email' in col.lower() or 'mail' in col.lower()]
            if colunas_email:
                df_vendedores = df_vendedores.rename(columns={colunas_email[0]: 'email'})
            else:
                df_vendedores['email'] = ''

        if 'codvendedor' in df_vendedores.columns:
            df_vendedores['codvendedor'] = df_vendedores['codvendedor'].astype(str).str.strip()

        return df_vendedores

    except Exception as e:
        st.error(f"❌ Erro ao carregar dados de vendedores: {e}")
        return None


def enviar_relatorios_por_email(df_faturamento, df_meta, df_clientes, df_vendedores,
                                data_inicio, data_fim, periodo_str, condicoes_where="1=1"):
    """Envia relatórios PDF por email para vendedores com dados no período, respeitando filtros."""

    if df_vendedores is None or df_vendedores.empty:
        st.error("❌ Dados de vendedores não disponíveis")
        return False, "Dados de vendedores não encontrados"

    if 'email' not in df_vendedores.columns:
        st.error("❌ Coluna 'email' não encontrada")
        return False, "Coluna de email não encontrada"

    df_vendedores_validos = df_vendedores[
        (df_vendedores['email'].notna()) &
        (df_vendedores['email'] != '') &
        (df_vendedores['email'].str.contains('@', na=False))
    ].copy()

    if df_vendedores_validos.empty:
        st.warning("⚠️ Nenhum vendedor com email válido encontrado")
        return False, "Nenhum email válido encontrado"

    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))
    conn.register('df_meta', prepare_for_duckdb(df_meta))

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
        AND {condicoes_where.replace('codvendedor', 'codvendedor').replace('codfornec', 'codfornec')}
    )
    SELECT
        COALESCE(f.codvendedor, m.codvendedor) as codvendedor,
        COALESCE(f.vendedor, m.vendedor) as vendedor
    FROM vendedores_faturamento f
    FULL OUTER JOIN vendedores_meta m ON f.codvendedor = m.codvendedor
    WHERE COALESCE(f.vendedor, m.vendedor) IS NOT NULL
    ORDER BY vendedor
    """

    df_vendedores_periodo = conn.execute(query_vendedores).df()
    conn.close()

    if df_vendedores_periodo.empty:
        return False, "Nenhum vendedor com faturamento ou meta no período selecionado"

    df_vendedores_periodo['codvendedor'] = df_vendedores_periodo['codvendedor'].astype(int)
    df_vendedores_validos['codvendedor'] = df_vendedores_validos['codvendedor'].astype(int)

    df_vendedores_para_envio = df_vendedores_periodo.merge(
        df_vendedores_validos[['codvendedor', 'email']],
        on='codvendedor',
        how='inner'
    )

    if df_vendedores_para_envio.empty:
        return False, "Nenhum vendedor com email encontrado para o período"

    st.subheader("🔧 Configuração do Email")
    st.caption("⚠️ As credenciais são usadas apenas durante esta sessão e não são armazenadas.")

    col1, col2 = st.columns(2)
    with col1:
        smtp_server = st.text_input(
            "Servidor SMTP",
            value=os.environ.get('SMTP_SERVER', 'smtp.gmail.com'),
        )
        smtp_username = st.text_input("Email (usuário)", value=os.environ.get('SMTP_USERNAME', ''))
    with col2:
        smtp_port = st.number_input("Porta SMTP", value=int(os.environ.get('SMTP_PORT', 587)), min_value=1, max_value=65535)
        smtp_password = st.text_input("Senha/App Password", type="password", placeholder="Digite a senha")

    os.environ['SMTP_SERVER'] = smtp_server
    os.environ['SMTP_PORT'] = str(smtp_port)
    os.environ['SMTP_USERNAME'] = smtp_username

    if st.button("🔍 Testar Conexão SMTP", type="secondary"):
        sucesso, mensagem = testar_conexao_smtp(smtp_server, smtp_port, smtp_username, smtp_password)
        if sucesso:
            st.success(mensagem)
        else:
            st.error(mensagem)

    st.divider()
    st.subheader("✏️ Personalizar Email")

    col1, col2 = st.columns(2)
    with col1:
        assunto_padrao = f"Relatório de Metas - {periodo_str}"
        assunto = st.text_input("Assunto do Email", value=assunto_padrao)

    corpo_padrao = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6;">
        <h2 style="color: #2E86AB;">Relatório de Acompanhamento de Metas</h2>
        <p>Prezado(a) Vendedor(a),</p>
        <p>Segue em anexo o relatório de acompanhamento de metas referente ao período:</p>
        <div style="background-color: #f4f4f4; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <p><strong>Período:</strong> {periodo_str}</p>
            <p><strong>Data de emissão:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
        </div>
        <p>O relatório contém:</p>
        <ul>
            <li>Resumo geral de metas</li>
            <li>Detalhamento por fornecedor</li>
            <li>Análise de clientes positivados</li>
        </ul>
        <p>Para dúvidas ou mais informações, entre em contato.</p>
        <hr style="border: none; border-top: 1px solid #ddd;">
        <p style="color: #666; font-size: 12px;">
            Este é um email automático. Por favor, não responda a esta mensagem.<br>
            Sistema de Acompanhamento de Metas - Demonstração
        </p>
    </body>
    </html>
    """

    corpo_email = st.text_area("Corpo do Email (HTML)", value=corpo_padrao, height=300)

    st.divider()
    st.subheader(f"📨 Enviar para {len(df_vendedores_para_envio)} Vendedores")
    st.dataframe(df_vendedores_para_envio[['vendedor', 'email']], width='stretch')

    if st.button("🚀 Enviar Relatórios para Todos Vendedores", type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        resultados = []

        total = len(df_vendedores_para_envio)
        for i, (_, row) in enumerate(df_vendedores_para_envio.iterrows()):
            codvendedor = row['codvendedor']
            vendedor_nome = row['vendedor']
            email_vendedor = row['email']

            progresso = (i + 1) / total
            progress_bar.progress(progresso)
            status_text.text(f"Processando: {vendedor_nome} ({i + 1}/{total})")

            try:
                condicoes_vendedor = f"codvendedor = {codvendedor}"

                metricas_vendedor = calcular_metricas_periodo(
                    df_faturamento, df_meta, data_inicio, data_fim, condicoes_vendedor
                )

                df_detalhes_vendedor = obter_detalhes_por_fornecedor(
                    df_faturamento, df_meta, data_inicio, data_fim, condicoes_vendedor
                )

                df_clientes_vendedor = obter_clientes_positivados(
                    df_faturamento, df_clientes, data_inicio, data_fim, condicoes_vendedor
                )

                df_detalhamento_cliente = obter_detalhamento_cliente(
                    df_faturamento, data_inicio, data_fim, condicoes_vendedor
                )

                pdf_buffer = gerar_pdf_relatorio(
                    metricas_vendedor,
                    df_detalhes_vendedor,
                    df_clientes_vendedor,
                    df_detalhamento_cliente,
                    periodo_str,
                    vendedor_nome=vendedor_nome,
                    fornecedor_nome=None
                )

                assunto_personalizado = f"{assunto} - {vendedor_nome}"

                sucesso = enviar_email_smtp(
                    email_vendedor,
                    assunto_personalizado,
                    corpo_email,
                    pdf_buffer,
                    f"relatorio_{vendedor_nome.replace('/', '_').replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                    smtp_password=smtp_password
                )

                resultados.append({
                    'vendedor': vendedor_nome,
                    'email': email_vendedor,
                    'status': '✅ Sucesso' if sucesso else '❌ Falha'
                })

            except Exception as e:
                resultados.append({
                    'vendedor': vendedor_nome,
                    'email': email_vendedor,
                    'status': f'❌ Erro: {str(e)[:50]}'
                })

        progress_bar.empty()
        status_text.empty()

        st.divider()
        st.subheader("📋 Resultados do Envio")

        df_resultados = pd.DataFrame(resultados)
        st.dataframe(df_resultados, width='stretch')

        sucessos = len([r for r in resultados if '✅' in r['status']])
        falhas = len(resultados) - sucessos

        col_res1, col_res2 = st.columns(2)
        with col_res1:
            st.metric("Emails Enviados", sucessos)
        with col_res2:
            st.metric("Falhas", falhas)

        if falhas > 0:
            st.warning(f"⚠️ {falhas} email(s) não foram enviados.")

        return True, f"Processamento concluído: {sucessos} enviados, {falhas} falhas"

    return False, "Aguardando confirmação"