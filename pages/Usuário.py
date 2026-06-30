# pages/Usuarios.py
import streamlit as st
from auth import (
    get_usuario_logado, 
    sidebar_usuario, 
    verificar_permissao,
    carregar_usuarios,
    salvar_usuarios,
    hash_senha,
    PERFIS,
    proteger_pagina
)
from utils.log_acesso import registrar_acesso
import pandas as pd
from datetime import datetime
from pathlib import Path

st.set_page_config(
    page_title="Gerenciamento de Usuários",
    page_icon="👥",
    layout="wide"
)

# Proteger página e obter usuário logado
usuario = proteger_pagina()
sidebar_usuario()

# Registrar acesso
registrar_acesso("Usuários")

# Verificar permissão
if not verificar_permissao("gerenciar_usuarios"):
    st.error("❌ Acesso negado. Apenas administradores podem acessar esta página.")
    st.stop()

st.title("👥 Gerenciamento de Usuários")

st.info("🔒 Funcionalidade de gerenciamento de usuários desativada no modo demonstração")
st.write("Esta funcionalidade foi desativada para manter a integridade do ambiente de demonstração.")

# Carregar vendedores para associação
VENDEDORES_PARQUET = Path("processados/vendedores.parquet")
df_vendedores = None
if VENDEDORES_PARQUET.exists():
    try:
        df_vendedores = pd.read_parquet(VENDEDORES_PARQUET)
    except:
        pass

# Carregar fornecedores para associação (com código e nome)
FORNECEDORES_CSV = Path("data/fornecedores_produto.csv")
fornecedores_unicos = []
fornecedores_map = {}  # código -> nome
fornecedores_opcoes = []  # lista de "CÓDIGO - NOME"
if FORNECEDORES_CSV.exists():
    try:
        df_fornecedores = pd.read_csv(FORNECEDORES_CSV, sep=';')
        if 'FORNECEDOR' in df_fornecedores.columns and 'CODFORNEC' in df_fornecedores.columns:
            # Criar mapa código -> nome
            for _, row in df_fornecedores.drop_duplicates(subset=['CODFORNEC']).iterrows():
                cod = row['CODFORNEC']
                nome = row['FORNECEDOR']
                if pd.notna(cod) and pd.notna(nome):
                    cod = int(cod)
                    fornecedores_map[cod] = nome
                    fornecedores_opcoes.append(f"{cod} - {nome}")
            fornecedores_opcoes = sorted(fornecedores_opcoes, key=lambda x: x.split(' - ')[1])
            fornecedores_unicos = sorted(df_fornecedores['FORNECEDOR'].dropna().unique().tolist())
    except Exception as e:
        st.warning(f"⚠️ Erro ao carregar fornecedores: {e}")


tab1, tab2, tab3 = st.tabs(["📋 Lista de Usuários", "➕ Novo Usuário", "📊 Vendedores sem Usuário"])

with tab1:
    dados = carregar_usuarios()
    if dados["usuarios"]:
        usuarios_list = []
        for username, info in dados["usuarios"].items():
            # Verificar bloqueio
            data_bloqueio = info.get("data_bloqueio")
            bloqueado = False
            if data_bloqueio:
                try:
                    data_bloqueio_dt = datetime.fromisoformat(data_bloqueio)
                    if data_bloqueio_dt > datetime.now():
                        bloqueado = True
                except:
                    pass
            
            # Fornecedores
            fornecedores_str = ", ".join(str(f) for f in info.get("fornecedores", [])) if info.get("fornecedores") else "-"

            
            usuarios_list.append({
                "Usuário": username,
                "Nome": info.get("nome", ""),
                "E-mail": info.get("email", "-"),
                "Perfil": PERFIS.get(info.get("perfil", ""), {}).get("nome", ""),
                "Fornecedores": fornecedores_str if info.get("perfil") == "fornecedor" else "-",
                "Cód. Vendedor": info.get("codvendedor", "-"),
                "Ativo": "✅" if info.get("ativo", True) else "❌",
                "Bloqueio": "🔴" if bloqueado else "🟢",
                "Data Criação": info.get("data_criacao", "")[:10] if info.get("data_criacao") else "-"
            })
        
        df_usuarios = pd.DataFrame(usuarios_list)
        st.dataframe(df_usuarios, width='stretch', hide_index=True)
        
        # Gerenciar usuário existente
        st.markdown("---")
        st.subheader("Gerenciar Usuário Existente")
        
        usuarios_ordenados = sorted(dados["usuarios"].keys())
        usuario_selecionado = st.selectbox(
            "Selecione um usuário", 
            usuarios_ordenados,
            key="select_usuario_gerenciar"
        )
        
        if usuario_selecionado:
            info = dados["usuarios"][usuario_selecionado]
            
            data_bloqueio = info.get("data_bloqueio")
            bloqueado = False
            bloqueio_tipo = ""
            if data_bloqueio:
                try:
                    data_bloqueio_dt = datetime.fromisoformat(data_bloqueio)
                    data_bloqueio_permanente = datetime(3000, 1, 1)
                    if data_bloqueio_dt >= data_bloqueio_permanente:
                        bloqueado = True
                        bloqueio_tipo = "🔴 Bloqueio Manual (Permanente)"
                    elif data_bloqueio_dt > datetime.now():
                        bloqueado = True
                        horas_restantes = int((data_bloqueio_dt - datetime.now()).total_seconds() / 3600)
                        bloqueio_tipo = f"🔴 Bloqueio Automático ({horas_restantes}h restantes)"
                except:
                    pass
            
            col1, col2 = st.columns(2)
            
            with col1:
                novo_nome = st.text_input(
                    "Nome", 
                    value=info.get("nome", ""),
                    key=f"edit_nome_{usuario_selecionado}"
                )
                novo_perfil = st.selectbox(
                    "Perfil", 
                    list(PERFIS.keys()),
                    format_func=lambda x: PERFIS[x]["nome"],
                    index=list(PERFIS.keys()).index(info.get("perfil", "vendedor")),
                    key=f"edit_perfil_{usuario_selecionado}"
                )
                novo_email = st.text_input(
                    "E-mail",
                    value=info.get("email", ""),
                    key=f"edit_email_{usuario_selecionado}",
                    placeholder="email@exemplo.com"
                )
            
            with col2:
                nova_senha = st.text_input(
                    "Nova Senha (deixe vazio para não alterar)", 
                    type="password",
                    key=f"edit_senha_{usuario_selecionado}"
                )
                novo_ativo = st.checkbox(
                    "Ativo", 
                    value=info.get("ativo", True),
                    key=f"edit_ativo_{usuario_selecionado}"
                )
                
                if bloqueado:
                    st.markdown(f"**Status:** {bloqueio_tipo}")
                else:
                    st.markdown("**Status:** 🟢 Desbloqueado")
            
            # Multiselect de fornecedores (apenas para perfil fornecedor)
            fornecedores_selecionados = info.get("fornecedores", [])
            if novo_perfil == "fornecedor" and fornecedores_opcoes:
                default_fornecedores = []
                for cod in fornecedores_selecionados:
                    try:
                        cod_int = int(cod) if not isinstance(cod, int) else cod
                        opcao = f"{cod_int} - {fornecedores_map.get(cod_int, 'Desconhecido')}"
                        if opcao in fornecedores_opcoes:
                            default_fornecedores.append(opcao)
                    except (ValueError, TypeError):
                        pass
                
                fornecedores_selecionados_opcoes = st.multiselect(
                    "Fornecedores Permitidos",
                    options=fornecedores_opcoes,
                    default=default_fornecedores,
                    key=f"edit_fornecedores_{usuario_selecionado}",
                )
                fornecedores_selecionados = []
                for opcao in fornecedores_selecionados_opcoes:
                    try:
                        cod = int(opcao.split(' - ')[0])
                        fornecedores_selecionados.append(cod)
                    except (ValueError, IndexError):
                        pass

            
            col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
            
            with col_btn1:
                if st.button("💾 Salvar Alterações", type="primary", key=f"btn_salvar_edicao_{usuario_selecionado}"):
                    dados["usuarios"][usuario_selecionado]["nome"] = novo_nome
                    dados["usuarios"][usuario_selecionado]["perfil"] = novo_perfil
                    dados["usuarios"][usuario_selecionado]["ativo"] = novo_ativo
                    dados["usuarios"][usuario_selecionado]["email"] = novo_email
                    
                    if novo_perfil == "fornecedor":
                        dados["usuarios"][usuario_selecionado]["fornecedores"] = fornecedores_selecionados
                    else:
                        dados["usuarios"][usuario_selecionado].pop("fornecedores", None)
                    
                    if nova_senha:
                        dados["usuarios"][usuario_selecionado]["senha_hash"] = hash_senha(nova_senha)
                    
                    salvar_usuarios(dados)
                    st.success("✅ Usuário atualizado com sucesso!")
                    st.rerun()
            
            with col_btn2:
                if st.button("🔄 Resetar Senha", key=f"btn_resetar_senha_{usuario_selecionado}"):
                    senha_padrao = f"senha{datetime.now().strftime('%d%m')}"
                    dados["usuarios"][usuario_selecionado]["senha_hash"] = hash_senha(senha_padrao)
                    salvar_usuarios(dados)
                    st.success(f"✅ Senha resetada para: {senha_padrao}")
            
            with col_btn3:
                if bloqueado:
                    if st.button("🔓 Desbloquear Usuário", type="secondary", key=f"btn_desbloquear_{usuario_selecionado}"):
                        dados["usuarios"][usuario_selecionado]["data_bloqueio"] = None
                        dados["usuarios"][usuario_selecionado]["tentativas_login"] = 0
                        salvar_usuarios(dados)
                        st.success(f"✅ Usuário {usuario_selecionado} desbloqueado!")
                        st.rerun()
            
            with col_btn4:
                if usuario_selecionado.lower() != "admin":
                    if st.button("🗑️ Excluir Usuário", type="secondary", key=f"btn_excluir_usuario_{usuario_selecionado}"):
                        del dados["usuarios"][usuario_selecionado]
                        salvar_usuarios(dados)
                        st.success(f"✅ Usuário {usuario_selecionado} excluído!")
                        st.rerun()
    else:
        st.info("Nenhum usuário cadastrado")

with tab2:
    st.subheader("Criar Novo Usuário")
    
    col1, col2 = st.columns(2)
    with col1:
        username = st.text_input("Usuário (login)", key="new_username")
        nome = st.text_input("Nome completo", key="new_nome")
        senha = st.text_input("Senha", type="password", key="new_senha")
        email = st.text_input("E-mail", key="new_email", placeholder="email@exemplo.com")
    
    with col2:
        perfil = st.selectbox(
            "Perfil", 
            list(PERFIS.keys()),
            format_func=lambda x: PERFIS[x]["nome"],
            key="new_perfil"
        )
        ativo = st.checkbox("Ativo", value=True, key="new_ativo")
        
        codvendedor = None
        if perfil in ["vendedor", "supervisor"] and df_vendedores is not None:
            vendedores_opcoes = df_vendedores[['codvendedor', 'vendedor']].drop_duplicates()
            vendedores_opcoes['display'] = vendedores_opcoes['codvendedor'].astype(str) + ' - ' + vendedores_opcoes['vendedor']
            
            vendedor_selecionado = st.selectbox(
                "Associar a Vendedor",
                options=['Nenhum'] + vendedores_opcoes['display'].tolist(),
                key="new_vendedor"
            )
            if vendedor_selecionado != 'Nenhum':
                codvendedor = int(vendedor_selecionado.split(' - ')[0])
        
        # Multiselect de fornecedores para perfil fornecedor
        fornecedores_novo = []
        if perfil == "fornecedor" and fornecedores_opcoes:
            fornecedores_novo_opcoes = st.multiselect(
                "Fornecedores Permitidos",
                options=fornecedores_opcoes,
                default=None,
                key="new_fornecedores",
            )
            fornecedores_novo = []
            for opcao in fornecedores_novo_opcoes:
                try:
                    cod = int(opcao.split(' - ')[0])
                    fornecedores_novo.append(cod)
                except (ValueError, IndexError):
                    pass

    
    if st.button("💾 Salvar Usuário", type="primary", key="btn_salvar_novo"):
        if username and nome and senha:
            dados = carregar_usuarios()
            
            username_existe = any(k.lower() == username.lower() for k in dados["usuarios"].keys())
            
            if username_existe:
                st.error("❌ Usuário já existe")
            else:
                novo_usuario = {
                    "nome": nome,
                    "perfil": perfil,
                    "senha_hash": hash_senha(senha),
                    "ativo": ativo,
                    "email": email,
                    "data_criacao": datetime.now().isoformat(),
                    "codvendedor": codvendedor,
                    "tentativas_login": 0,
                    "data_bloqueio": None,
                    "filtros": {}
                }
                
                if perfil == "fornecedor":
                    novo_usuario["fornecedores"] = fornecedores_novo
                
                dados["usuarios"][username] = novo_usuario
                salvar_usuarios(dados)
                st.success(f"✅ Usuário {username} criado com sucesso!")
                st.rerun()
        else:
            st.error("❌ Preencha todos os campos obrigatórios")

with tab3:
    st.subheader("Vendedores sem Usuário")
    
    if df_vendedores is not None:
        dados = carregar_usuarios()
        
        codigos_com_usuario = set()
        for info in dados["usuarios"].values():
            if info.get("codvendedor"):
                codigos_com_usuario.add(info["codvendedor"])
        
        vendedores_sem_usuario = df_vendedores[
            ~df_vendedores['codvendedor'].isin(codigos_com_usuario)
        ][['codvendedor', 'vendedor', 'tipo']].drop_duplicates()
        
        if not vendedores_sem_usuario.empty:
            st.info(f"{len(vendedores_sem_usuario)} vendedores sem usuário")
            st.dataframe(vendedores_sem_usuario, width='stretch', hide_index=True)
            
            col_btn1, col_btn2 = st.columns(2)
            
            with col_btn1:
                if st.button("🔄 Criar Usuários para Todos", type="primary", key="btn_criar_todos"):
                    criados = 0
                    for _, row in vendedores_sem_usuario.iterrows():
                        username = f"vendedor_{row['codvendedor']}".lower()
                        if username not in dados["usuarios"]:
                            perfil = "supervisor" if str(row.get('tipo', '')).upper() == 'S' else "vendedor"
                            dados["usuarios"][username] = {
                                "nome": row['vendedor'],
                                "perfil": perfil,
                                "senha_hash": hash_senha(f"venda{row['codvendedor']}"),
                                "ativo": True,
                                "email": "",
                                "data_criacao": datetime.now().isoformat(),
                                "codvendedor": int(row['codvendedor']),
                                "tentativas_login": 0,
                                "data_bloqueio": None,
                                "filtros": {}
                            }
                            criados += 1
                    
                    salvar_usuarios(dados)
                    st.success(f"✅ {criados} usuários criados!")
                    st.rerun()
            
            with col_btn2:
                if st.button("📋 Mostrar Senhas Padrão", key="btn_mostrar_senhas"):
                    st.info("""
                    **Senhas padrão:** `venda[CODIGO]`
                    
                    Exemplos:
                    - Vendedor 76: `venda76`
                    - Vendedor 131: `venda131`
                    """)
        else:
            st.success("✅ Todos os vendedores já possuem usuário!")
    else:
        st.warning("⚠️ Arquivo de vendedores não encontrado")