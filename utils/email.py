import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os
from datetime import datetime
import streamlit as st
from utils.etl import prepare_for_duckdb

# =============================================================================
# FUNÇÕES DE ENVIO DE EMAIL
# =============================================================================

def configurar_smtp():
    """Configura as credenciais SMTP a partir das variáveis de ambiente ou inputs do usuário"""
    # Tenta obter do ambiente primeiro
    smtp_server = os.environ.get('SMTP_SERVER', 'smtpi.distribuidoralogicazm.com.br')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_username = os.environ.get('SMTP_USERNAME', '')
    smtp_password = os.environ.get('SMTP_PASSWORD', '')
    
    return smtp_server, smtp_port, smtp_username, smtp_password

def enviar_email_smtp(destinatario, assunto, corpo, anexo_pdf=None, nome_arquivo="relatorio.pdf"):
    """Envia email com anexo via SMTP"""
    try:
        smtp_server, smtp_port, smtp_username, smtp_password = configurar_smtp()
        
        # Verificar se temos credenciais
        if not smtp_username or not smtp_password:
            st.error("❌ Credenciais SMTP não configuradas. Configure as variáveis de ambiente:")
            st.code("""
            SMTP_SERVER=smtpi.distribuidoralogicazm.com.br
            SMTP_PORT=587
            SMTP_USERNAME=seu_email@gmail.com
            SMTP_PASSWORD=sua_senha_app
            """)
            return False
        
        # Criar mensagem
        msg = MIMEMultipart()
        msg['From'] = smtp_username
        msg['To'] = destinatario
        msg['Subject'] = assunto
        
        # Adicionar corpo do email
        msg.attach(MIMEText(corpo, 'html'))
        
        # Adicionar anexo se fornecido
        if anexo_pdf:
            part = MIMEApplication(anexo_pdf.getvalue(), Name=nome_arquivo)
            part['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
            msg.attach(part)
        
        # Conectar e enviar
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Usar TLS
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        return True
        
    except smtplib.SMTPAuthenticationError:
        st.error("❌ Falha na autenticação SMTP. Verifique usuário e senha.")
        return False
    except Exception as e:
        st.error(f"❌ Erro ao enviar email: {e}")
        return False

def enviar_relatorios_por_email(df_faturamento, df_meta, df_clientes, df_vendedores, 
                                data_inicio, data_fim, periodo_str):
    """Envia relatórios PDF por email para todos os vendedores com dados no período"""
    
    if df_vendedores is None or df_vendedores.empty:
        st.error("❌ Dados de vendedores não disponíveis")
        return False, "Dados de vendedores não encontrados"
    
    if 'email' not in df_vendedores.columns:
        st.error("❌ Coluna 'email' não encontrada na tabela de vendedores")
        return False, "Coluna de email não encontrada"
    
    # Filtrar vendedores com email válido
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
    
    # Buscar vendedores com faturamento ou meta no período
    query_vendedores = f"""
    WITH vendedores_faturamento AS (
        SELECT DISTINCT codvendedor, vendedor
        FROM df_faturamento 
        WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
        AND tipo_movimento != 'TROCA'
        AND valor_faturado > 0
    ),
    vendedores_meta AS (
        SELECT DISTINCT codvendedor, vendedor
        FROM df_meta 
        WHERE EXTRACT(YEAR FROM data) = {data_inicio.year}
        AND EXTRACT(MONTH FROM data) = {data_inicio.month}
        AND meta_valor > 0
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
    
    # Juntar com emails
    df_vendedores_periodo = df_vendedores_periodo.merge(
        df_vendedores_validos[['codvendedor', 'email']], 
        on='codvendedor', 
        how='left'
    )
    
    # Filtrar apenas vendedores com email
    df_vendedores_para_envio = df_vendedores_periodo[
        df_vendedores_periodo['email'].notna() & 
        (df_vendedores_periodo['email'] != '')
    ]
    
    if df_vendedores_para_envio.empty:
        return False, "Nenhum vendedor com email encontrado para o período"
    
    # Configurar credenciais SMTP via interface (se não estiverem em variáveis de ambiente)
    st.subheader("🔧 Configuração do Email")
    
    col1, col2 = st.columns(2)
    with col1:
        smtp_server = st.text_input("Servidor SMTP", 
                                   value=os.environ.get('SMTP_SERVER', 'smtp.gmail.com'))
        smtp_username = st.text_input("Email (usuário)", 
                                     value=os.environ.get('SMTP_USERNAME', ''))
    with col2:
        smtp_port = st.number_input("Porta SMTP", 
                                   value=int(os.environ.get('SMTP_PORT', 587)), 
                                   min_value=1, max_value=65535)
        smtp_password = st.text_input("Senha/App Password", 
                                     type="password",
                                     value=os.environ.get('SMTP_PASSWORD', ''))
    
    # Definir variáveis de ambiente temporárias
    os.environ['SMTP_SERVER'] = smtp_server
    os.environ['SMTP_PORT'] = str(smtp_port)
    os.environ['SMTP_USERNAME'] = smtp_username
    os.environ['SMTP_PASSWORD'] = smtp_password
    
    # Testar conexão
    if st.button("🔍 Testar Conexão SMTP"):
        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_username, smtp_password)
            st.success("✅ Conexão SMTP bem-sucedida!")
        except Exception as e:
            st.error(f"❌ Falha na conexão: {e}")
    
    st.divider()
    
    # Template do email
    st.subheader("✏️ Personalizar Email")
    
    col1, col2 = st.columns(2)
    with col1:
        assunto_padrao = f"Relatório de Metas - {periodo_str}"
        assunto = st.text_input("Assunto do Email", value=assunto_padrao)
    
    # Corpo do email com HTML
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
            Sistema de Acompanhamento de Metas
        </p>
    </body>
    </html>
    """
    
    corpo_email = st.text_area("Corpo do Email (HTML)", value=corpo_padrao, height=300)
    
    # Opção de enviar teste
    st.divider()
    
    email_teste = st.text_input("Email para teste (opcional)", 
                               placeholder="email@teste.com")
    
    col_test1, col_test2 = st.columns(2)
    with col_test1:
        if st.button("📤 Enviar Email de Teste", type="secondary"):
            if email_teste and '@' in email_teste:
                with st.spinner("Enviando email de teste..."):
                    # Gerar relatório de exemplo
                    teste_metricas = calcular_metricas_periodo(
                        df_faturamento, df_meta, data_inicio, data_fim, "1=1"
                    )
                    teste_detalhes = obter_detalhes_por_fornecedor(
                        df_faturamento, df_meta, data_inicio, data_fim, "1=1"
                    )
                    teste_clientes = obter_clientes_positivados(
                        df_faturamento, df_clientes, data_inicio, data_fim, "1=1"
                    )
                    
                    pdf_teste = gerar_pdf_relatorio(
                        teste_metricas, teste_detalhes, teste_clientes, 
                        periodo_str, "TESTE", None
                    )
                    
                    sucesso = enviar_email_smtp(
                        email_teste, 
                        f"[TESTE] {assunto}", 
                        corpo_email, 
                        pdf_teste, 
                        f"relatorio_teste_{datetime.now().strftime('%Y%m%d')}.pdf"
                    )
                    
                    if sucesso:
                        st.success(f"✅ Email de teste enviado para {email_teste}")
                    else:
                        st.error("❌ Falha ao enviar email de teste")
            else:
                st.warning("⚠️ Digite um email válido para teste")
    
    # Enviar para todos os vendedores
    st.divider()
    st.subheader(f"📨 Enviar para {len(df_vendedores_para_envio)} Vendedores")
    
    st.info(f"**Vendedores que receberão o email:**")
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
            
            # Atualizar progresso
            progresso = (i + 1) / total
            progress_bar.progress(progresso)
            status_text.text(f"Processando: {vendedor_nome} ({i + 1}/{total})")
            
            try:
                # Gerar relatório específico para o vendedor
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
                
                # Gerar PDF
                pdf_buffer = gerar_pdf_relatorio(
                    metricas_vendedor,
                    df_detalhes_vendedor,
                    df_clientes_vendedor,
                    periodo_str,
                    vendedor_nome=vendedor_nome,
                    fornecedor_nome=None
                )
                
                # Personalizar assunto para o vendedor
                assunto_personalizado = f"{assunto} - {vendedor_nome}"
                
                # Enviar email
                sucesso = enviar_email_smtp(
                    email_vendedor,
                    assunto_personalizado,
                    corpo_email,
                    pdf_buffer,
                    f"relatorio_{vendedor_nome.replace('/', '_').replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
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
        
        # Limpar barra de progresso
        progress_bar.empty()
        status_text.empty()
        
        # Mostrar resultados
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
            st.warning(f"⚠️ {falhas} email(s) não foram enviados. Verifique os logs acima.")
        
        return True, f"Processamento concluído: {sucessos} enviados, {falhas} falhas"
    
    return False, "Aguardando confirmação"

# =============================================================================
# MODIFICAÇÃO DA FUNÇÃO carregar_dados_vendedores
# =============================================================================

def carregar_dados_vendedores():
    """Carrega dados de vendedores com validação de email"""
    try:
        df_vendedores = pd.read_csv(VENDEDORES_CSV)
        
        # Verificar se a coluna email existe
        if 'email' not in df_vendedores.columns:
            st.warning("⚠️ Coluna 'email' não encontrada no arquivo de vendedores")
            
            # Tentar encontrar colunas similares
            colunas_email = [col for col in df_vendedores.columns if 'email' in col.lower() or 'mail' in col.lower()]
            if colunas_email:
                df_vendedores = df_vendedores.rename(columns={colunas_email[0]: 'email'})
                st.info(f"✅ Coluna renomeada: '{colunas_email[0]}' → 'email'")
            else:
                # Criar coluna vazia se não existir
                df_vendedores['email'] = ''
                st.warning("⚠️ Coluna 'email' criada vazia. Adicione emails no arquivo CSV")
        
        # Garantir que codvendedor seja string/número
        if 'codvendedor' in df_vendedores.columns:
            df_vendedores['codvendedor'] = df_vendedores['codvendedor'].astype(str).str.strip()
        
        return df_vendedores
        
    except Exception as e:
        st.error(f"❌ Erro ao carregar dados de vendedores: {e}")
        return None

# =============================================================================
# MODIFICAÇÃO DA INTERFACE PRINCIPAL
# =============================================================================

# Adicionar nova aba/tab no Streamlit (dentro da função main)

# No lugar da criação das tabs, adicionar mais uma tab:
with tab3:
    st.header("Relatórios Personalizados")
    
    col1, col2, col3, col4 = st.columns(4)  # Mudar de 3 para 4 colunas
    
    with col1:
        st.subheader("Gerar Relatório PDF")
        # ... (código existente para gerar PDF individual)
    
    with col2:
        st.subheader("Exportar Dados")
        # ... (código existente para exportar Excel)
    
    with col3:
        st.subheader("Relatórios em Lote")
        # ... (código existente para gerar ZIP)
    
    with col4:
        st.subheader("📧 Enviar por Email")
        
        st.info("Envia relatórios individuais por email para cada vendedor")
        
        # Carregar dados de vendedores (adicionar no início da função main)
        df_vendedores_email = carregar_dados_vendedores()
        
        if df_vendedores_email is not None:
            if st.button("📧 Enviar Relatórios por Email"):
                # Criar nova aba ou expandir para envio de emails
                st.session_state['mostrar_envio_email'] = True
            
            if st.session_state.get('mostrar_envio_email', False):
                periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
                
                sucesso, mensagem = enviar_relatorios_por_email(
                    df_faturamento,
                    df_meta,
                    df_clientes,
                    df_vendedores_email,
                    data_inicio,
                    data_fim,
                    periodo_str
                )
                
                if sucesso:
                    st.success(f"✅ {mensagem}")
                else:
                    st.warning(f"⚠️ {mensagem}")
        else:
            st.warning("⚠️ Dados de vendedores não disponíveis para envio de email")

# =============================================================================
# ADICIONAR NO ARQUIVO VENDEDORES.CSV
# =============================================================================

# Certifique-se de que o arquivo data/vendedores.csv tenha a coluna 'email'
# Exemplo da estrutura esperada:
"""
codvendedor,vendedor,email,telefone,regiao
1,"João Silva","joao@empresa.com","(11) 99999-9999","Sudeste"
2,"Maria Santos","maria@empresa.com","(21) 88888-8888","Sul"
3,"Pedro Oliveira","pedro@empresa.com","(31) 77777-7777","Nordeste"
"""