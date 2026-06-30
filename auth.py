# auth.py - Versão para Demonstração Pública (sem R2)

import streamlit as st
import pandas as pd
import hashlib
import logging
from pathlib import Path
import json
from datetime import datetime
from typing import Optional, Dict, List
import time
import base64
import os

logger = logging.getLogger(__name__)


# Constantes
USUARIOS_JSON = Path("data/usuarios.json")
VENDEDORES_PARQUET = Path("processados/vendedores.parquet")

# Lock para evitar concorrência no arquivo de usuários
LOCK_FILE = USUARIOS_JSON.with_suffix(".json.lock")
LOCK_TIMEOUT = 5  # segundos
LOCK_RETRY_INTERVAL = 0.3  # intervalo entre tentativas

# Configuração de token - chave fixa para demonstração
SECRET_KEY = "demo_secret_key_publica_2026"


def gerar_token(username: str) -> str:
    """
    Gera token com username, expiração (24h) e fingerprint do navegador.
    """
    user_agent = st.context.headers.get("User-Agent", "desconhecido") if hasattr(st, 'context') else "desconhecido"
    fingerprint = hashlib.sha256(user_agent.encode()).hexdigest()[:16]
    
    payload = {
        "username": username,
        "exp": time.time() + 86400,  # 24 horas
        "fp": fingerprint
    }
    payload["sig"] = hashlib.sha256(f"{username}{payload['exp']}{fingerprint}{SECRET_KEY}".encode()).hexdigest()[:16]
    
    token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return token


def validar_token(token: str):
    """Valida token e retorna username se válido."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        
        if payload["exp"] <= time.time():
            return None
        
        user_agent = st.context.headers.get("User-Agent", "desconhecido") if hasattr(st, 'context') else "desconhecido"
        fingerprint_esperado = hashlib.sha256(user_agent.encode()).hexdigest()[:16]
        
        if payload.get("fp") != fingerprint_esperado:
            return None
        
        sig_esperada = hashlib.sha256(f"{payload['username']}{payload['exp']}{payload['fp']}{SECRET_KEY}".encode()).hexdigest()[:16]
        if payload.get("sig") != sig_esperada:
            return None
        
        return payload["username"]
    except Exception:
        pass
    return None


def restaurar_sessao_por_token() -> bool:
    """Tenta restaurar sessão a partir do token nos query_params"""
    token = st.query_params.get("token")
    if token:
        username = validar_token(token)
        if username:
            dados = carregar_usuarios()
            for key, info in dados["usuarios"].items():
                if key.lower() == username.lower():
                    usuario_info = {k: v for k, v in info.items() if k != "senha_hash"}
                    usuario_info["username"] = key
                    st.session_state["usuario"] = usuario_info
                    st.session_state["autenticado"] = True
                    return True
    return False


def proteger_pagina():
    """Função chamada no início de cada página para garantir autenticação"""
    inicializar_auth()
    
    if not st.session_state.get('autenticado', False):
        if restaurar_sessao_por_token():
            st.rerun()
    
    if not st.session_state.get('autenticado', False):
        login_page(embedded=True)
        st.stop()
    
    usuario = get_usuario_logado()
    if usuario and not st.query_params.get("token"):
        token = gerar_token(usuario["username"])
        st.query_params["token"] = token
    
    return usuario


# Perfis disponíveis
PERFIS = {
    "admin": {
        "nome": "Administrador",
        "permissoes": [
            "todas_paginas",
            "todos_filtros",
            "gerenciar_usuarios",
            "configuracao",
            "estoque",
            "dashboard",
            "relatorios"
        ]
    },
    "gerente": {
        "nome": "Gerente",
        "permissoes": [
            "dashboard",
            "relatorios",
            "estoque",
            "todos_vendedores"
        ]
    },
    "supervisor": {
        "nome": "Supervisor",
        "permissoes": [
            "dashboard",
            "relatorios",
            "supervisionados"
        ]
    },
    "vendedor": {
        "nome": "Vendedor",
        "permissoes": [
            "dashboard_proprio",
            "relatorios_proprio"
        ]
    },
    "fornecedor": {
        "nome": "Fornecedor",
        "permissoes": [
            "dashboard_fornecedor",
            "relatorios_fornecedor",
            "estoque_fornecedor"
        ]
    }
}   


# Páginas disponíveis e seus requisitos de permissão
PAGINAS = {
    "Início": {
        "arquivo": "Início.py", 
        "permissao": None  # Todos os usuários autenticados podem acessar
    },
    "Acompanhamento de Metas": {
        "arquivo": "pages/Acompanhamento de Metas.py", 
        "permissao": ["dashboard", "dashboard_proprio", "dashboard_fornecedor"]
    },
    "Estoque": {
        "arquivo": "pages/Estoque.py", 
        "permissao": ["estoque", "estoque_fornecedor"]
    },
    "Configuração": {
        "arquivo": "pages/Configuração.py", 
        "permissao": "configuracao"
    },
    "Usuários": {
        "arquivo": "pages/Usuário.py", 
        "permissao": "gerenciar_usuarios"
    }
}


def hash_senha(senha: str) -> str:
    """Gera hash da senha"""
    return hashlib.sha256(senha.encode()).hexdigest()


def carregar_usuarios() -> Dict:
    """Carrega usuários do arquivo JSON local."""
    if USUARIOS_JSON.exists():
        try:
            with open(USUARIOS_JSON, 'r', encoding='utf-8') as f:
                dados = json.load(f)
                if "usuarios" in dados:
                    dados["usuarios"] = {k.lower(): v for k, v in dados["usuarios"].items()}
                return dados
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"❌ Arquivo {USUARIOS_JSON} corrompido: {e}")
            return {"usuarios": {}}
    
    return {"usuarios": {}}


def inicializar_auth():
    """
    Inicializa o sistema de autenticação.
    Cria usuário admin padrão se não existir e também o usuário demo.
    """
    criar_usuario_admin_inicial()
    criar_usuario_demo()


def _acquire_lock() -> bool:
    """Tenta adquirir lock para evitar concorrência no arquivo de usuários."""
    start = time.time()
    while time.time() - start < LOCK_TIMEOUT:
        try:
            with open(LOCK_FILE, 'x') as f:
                f.write(str(time.time()))
            return True
        except FileExistsError:
            try:
                lock_mtime = os.path.getmtime(LOCK_FILE)
                if time.time() - lock_mtime > LOCK_TIMEOUT:
                    logger.warning(f"⚠️ Lock stale detectado, removendo: {LOCK_FILE}")
                    LOCK_FILE.unlink(missing_ok=True)
                    continue
            except (OSError, FileNotFoundError):
                pass
            time.sleep(LOCK_RETRY_INTERVAL)
    return False


def _release_lock():
    """Remove o lock de concorrência"""
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"⚠️ Erro ao remover lock: {e}")


def salvar_usuarios(usuarios: Dict):
    """Salva usuários no arquivo JSON local."""
    if not _acquire_lock():
        logger.error("❌ Não foi possível adquirir lock para salvar usuários")
        st.error("⚠️ Sistema ocupado. Tente novamente em instantes.")
        return
    
    try:
        USUARIOS_JSON.parent.mkdir(exist_ok=True)
        
        temp_path = USUARIOS_JSON.with_suffix(".json.tmp")
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(usuarios, f, indent=4, ensure_ascii=False)
        temp_path.replace(USUARIOS_JSON)
    finally:
        _release_lock()


def autenticar_usuario(username: str, senha: str) -> Optional[Dict]:
    """
    Autentica usuário e retorna seus dados
    Aceita username case-insensitive
    Inclui verificação de bloqueio (manual e automático)
    """
    if not username or not senha:
        return None
    
    dados = carregar_usuarios()
    
    username_lower = username.lower().strip()
    
    usuario_encontrado = None
    for key in dados["usuarios"].keys():
        if key.lower() == username_lower:
            usuario_encontrado = key
            break
    
    if usuario_encontrado:
        usuario_data = dados["usuarios"][usuario_encontrado]
        
        # Verificar bloqueio
        data_bloqueio = usuario_data.get("data_bloqueio")
        if data_bloqueio:
            try:
                data_bloqueio_dt = datetime.fromisoformat(data_bloqueio)
                data_bloqueio_permanente = datetime(3000, 1, 1)
                
                if data_bloqueio_dt >= data_bloqueio_permanente:
                    st.error("🔒 Usuário bloqueado permanentemente pelo administrador. Contate o suporte.")
                    return None
                elif data_bloqueio_dt > datetime.now():
                    horas_restantes = int((data_bloqueio_dt - datetime.now()).total_seconds() / 3600)
                    st.error(f"🔒 Usuário bloqueado temporariamente por excesso de tentativas. Tente novamente em {horas_restantes}h.")
                    return None
            except (ValueError, TypeError):
                pass
        
        # Verificar senha
        if usuario_data["senha_hash"] == hash_senha(senha):
            if usuario_data.get("tentativas_login", 0) > 0 or usuario_data.get("data_bloqueio"):
                dados["usuarios"][usuario_encontrado]["tentativas_login"] = 0
                dados["usuarios"][usuario_encontrado]["data_bloqueio"] = None
                salvar_usuarios(dados)
            
            if usuario_data.get("ativo", True):
                usuario_info = {k: v for k, v in usuario_data.items() if k != "senha_hash"}
                usuario_info["username"] = usuario_encontrado
                return usuario_info
        else:
            tentativas = usuario_data.get("tentativas_login", 0) + 1
            dados["usuarios"][usuario_encontrado]["tentativas_login"] = tentativas
            
            if tentativas >= 5:
                from datetime import timedelta
                data_bloqueio_auto = datetime.now() + timedelta(hours=24)
                dados["usuarios"][usuario_encontrado]["data_bloqueio"] = data_bloqueio_auto.isoformat()
                salvar_usuarios(dados)
                st.error(f"🔒 Usuário bloqueado por 24h devido a {tentativas} tentativas de login inválidas.")
            else:
                salvar_usuarios(dados)
                st.error(f"❌ Usuário ou senha inválidos. Tentativa {tentativas}/5.")
    
    return None


def criar_usuario_admin_inicial():
    """Cria usuário admin padrão se não existir"""
    dados = carregar_usuarios()
    
    admin_existe = any(k.lower() == "admin" for k in dados["usuarios"].keys())
    
    if not admin_existe:
        dados["usuarios"]["admin"] = {
            "nome": "Administrador",
            "perfil": "admin",
            "senha_hash": hash_senha("admin"),
            "ativo": True,
            "data_criacao": datetime.now().isoformat(),
            "filtros": {}
        }
        salvar_usuarios(dados)


def criar_usuario_demo():
    """Cria usuário demo para demonstração pública"""
    dados = carregar_usuarios()
    
    demo_existe = any(k.lower() == "demo" for k in dados["usuarios"].keys())
    
    if not demo_existe:
        dados["usuarios"]["demo"] = {
            "nome": "Usuário Demonstração",
            "perfil": "admin",
            "senha_hash": hash_senha("demo"),
            "ativo": True,
            "data_criacao": datetime.now().isoformat(),
            "filtros": {}
        }
        salvar_usuarios(dados)


def get_usuario_logado() -> Optional[Dict]:
    """Retorna dados do usuário logado"""
    return st.session_state.get('usuario')


def verificar_permissao(permissao_necessaria) -> bool:
    """
    Verifica se usuário tem permissão.
    Aceita string única ou lista de permissões (qualquer uma é suficiente).
    """
    usuario = get_usuario_logado()
    if not usuario:
        return False
    
    perfil = usuario.get("perfil")
    if perfil not in PERFIS:
        return False
    
    permissoes_usuario = PERFIS[perfil]["permissoes"]
    
    if "todas_paginas" in permissoes_usuario:
        return True
    
    if permissao_necessaria is None:
        return True
    
    if isinstance(permissao_necessaria, list):
        return any(p in permissoes_usuario for p in permissao_necessaria)
    
    return permissao_necessaria in permissoes_usuario


def get_paginas_permitidas() -> list:
    """
    Retorna lista de nomes de páginas que o usuário logado tem permissão para acessar.
    """
    paginas_permitidas = []
    for nome_pagina, config in PAGINAS.items():
        if verificar_permissao(config["permissao"]):
            paginas_permitidas.append(nome_pagina)
    return paginas_permitidas


def get_filtros_usuario() -> Dict:
    """Retorna filtros específicos do usuário logado"""
    usuario = get_usuario_logado()
    if not usuario:
        return {}
    
    perfil = usuario.get("perfil")
    filtros = usuario.get("filtros", {})
    
    if perfil in ["vendedor", "supervisor"]:
        codigo = usuario.get("codvendedor")
        if codigo:
            if perfil == "supervisor":
                supervisionados = get_supervisionados(codigo)
                filtros["vendedores_permitidos"] = supervisionados
                filtros["codigos_permitidos"] = supervisionados
            else:
                filtros["vendedores_permitidos"] = [codigo]
                filtros["codigos_permitidos"] = [codigo]
    
    if perfil == "fornecedor":
        fornecedores = usuario.get("fornecedores", [])
        if fornecedores:
            filtros["fornecedores_permitidos"] = fornecedores
    
    return filtros


def get_supervisionados(cod_supervisor: int) -> List[int]:
    """Retorna lista de códigos dos vendedores supervisionados"""
    try:
        if VENDEDORES_PARQUET.exists():
            df_vendedores = pd.read_parquet(VENDEDORES_PARQUET)
            
            if 'codsupervisor' in df_vendedores.columns and 'codvendedor' in df_vendedores.columns:
                supervisionados = df_vendedores[
                    df_vendedores['codsupervisor'] == cod_supervisor
                ]['codvendedor'].unique().tolist()
                
                if cod_supervisor not in supervisionados:
                    supervisionados.append(cod_supervisor)
                    
                return supervisionados
    except Exception as e:
        st.error(f"Erro ao carregar supervisionados: {e}")
    
    return [cod_supervisor]


def login_page(embedded=False):
    """
    Exibe página de login - Versão simplificada sem fundo roxo
    """
    st.markdown("""
    <style>
    .login-container {
        max-width: 400px;
        margin: 5rem auto;
        padding: 2rem;
        border-radius: 10px;
        background: transparent;
    }
    
    .login-container-embedded {
        max-width: 400px;
        margin: 2rem auto;
        padding: 2rem;
        border-radius: 10px;
        background: transparent;
    }
    
    .login-title {
        text-align: center;
        margin-bottom: 1.5rem;
        color: #262730;
    }
    
    .login-logo {
        text-align: center;
        margin-bottom: 1rem;
        font-size: 3rem;
    }
    
    .stTextInput input {
        border: 1px solid #ddd !important;
        border-radius: 8px !important;
        padding: 10px !important;
    }
    
    .stButton > button {
        border-radius: 8px !important;
        font-weight: bold !important;
    }
    </style>
    
    <script>
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Enter') {
            const activeElement = document.activeElement;
            if (activeElement && activeElement.tagName === 'INPUT') {
                const buttons = document.querySelectorAll('button');
                for (let btn of buttons) {
                    if (btn.innerText.includes('Entrar')) {
                        event.preventDefault();
                        btn.click();
                        return false;
                    }
                }
            }
        }
    });
    </script>
    """, unsafe_allow_html=True)
    
    container_class = "login-container" if not embedded else "login-container-embedded"
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        if not embedded:
            st.markdown('<h1 style="text-align: center;">📊 Dashboard de Demonstração</h1>', unsafe_allow_html=True)
        
        st.markdown('<h2 class="login-title">🔐 Dashboard de Metas</h2>', unsafe_allow_html=True)
        st.markdown('<p style="text-align: center; margin-bottom: 1.5rem;">Faça login para continuar</p>', unsafe_allow_html=True)
        
        with st.form(key="login_form", clear_on_submit=False):
            username = st.text_input(
                "👤 Usuário", 
                key="login_username",
                placeholder="Digite seu usuário",
                label_visibility="visible"
            )
            
            senha = st.text_input(
                "🔑 Senha", 
                type="password", 
                key="login_password",
                placeholder="Digite sua senha",
                label_visibility="visible"
            )
            
            submitted = st.form_submit_button(
                    "🚪 Entrar", 
                    width='stretch', 
                    type="primary"
                )
        
        if submitted:
            if username and senha:
                usuario = autenticar_usuario(username, senha)
                if usuario:
                    st.session_state['usuario'] = usuario
                    st.session_state['autenticado'] = True
                    token = gerar_token(usuario["username"])
                    st.query_params["token"] = token
                    st.rerun()
                else:
                    st.error("❌ Usuário ou senha inválidos")
            else:
                st.warning("⚠️ Preencha usuário e senha")
        
        st.info("""
        **Credenciais de Demonstração:**
        - Usuário: `admin` | Senha: `admin`
        - Usuário: `demo` | Senha: `demo`
        """)
        
        st.markdown("""
        <p style="text-align: center; margin-top: 1.5rem; color: #888; font-size: 0.9rem;">
            Dashboard de Demonstração<br>
            © 2026 - Projeto de Demonstração
        </p>
        """, unsafe_allow_html=True)


def check_authentication():
    """
    Verifica autenticação e exibe tela de login se necessário.
    Retorna True se autenticado, False caso contrário.
    """
    if not st.session_state.get('autenticado', False):
        st.warning("⚠️ Acesso restrito. Faça login para continuar.")
        login_page(embedded=True)
        return False
    return True


# Funcionalidade de troca de senha removida no modo demonstração
def trocar_senha(username: str, senha_atual: str, nova_senha: str) -> tuple:
    """
    Troca a senha do usuário.
    
    Args:
        username: Nome do usuário
        senha_atual: Senha atual para verificação
        nova_senha: Nova senha desejada
    
    Returns:
        tuple: (sucesso: bool, mensagem: str)
    """
    return False, "🔒 Funcionalidade desativada no modo demonstração"


def logout():
    """Realiza logout do usuário"""
    if 'usuario' in st.session_state:
        del st.session_state['usuario']
    if 'autenticado' in st.session_state:
        del st.session_state['autenticado']
    if 'login_username' in st.session_state:
        del st.session_state['login_username']
    if 'login_password' in st.session_state:
        del st.session_state['login_password']
    st.query_params.clear()
    st.rerun()


def sidebar_usuario():
    """Exibe informações do usuário na sidebar"""
    usuario = get_usuario_logado()
    if usuario:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 👤 Usuário")
        st.sidebar.markdown(f"**Nome:** {usuario.get('nome', 'N/A')}")
        st.sidebar.markdown(f"**Perfil:** {PERFIS.get(usuario.get('perfil'), {}).get('nome', 'N/A')}")
        if usuario.get('codvendedor'):
            st.sidebar.markdown(f"**Código:** {usuario.get('codvendedor')}")
        
        # Funcionalidade de troca de senha desativada no modo demonstração
        st.sidebar.info("🔒 Troca de senha desativada no modo demonstração")
        
        if st.sidebar.button("🚪 Logout", width='stretch', key="sidebar_logout"):
            logout()


def gerenciar_usuarios_page():
    """Página de gerenciamento de usuários (apenas admin)"""
    st.title("👥 Gerenciamento de Usuários")
    
    if not verificar_permissao("gerenciar_usuarios"):
        st.error("❌ Acesso negado. Você não tem permissão para gerenciar usuários.")
        return
    
    df_vendedores = None
    if VENDEDORES_PARQUET.exists():
        try:
            df_vendedores = pd.read_parquet(VENDEDORES_PARQUET)
        except:
            pass
    
    tab1, tab2 = st.tabs(["📋 Lista de Usuários", "📊 Vendedores sem Usuário"])
    
    with tab1:
        dados = carregar_usuarios()
        if dados["usuarios"]:
            usuarios_list = []
            for username, info in dados["usuarios"].items():
                usuarios_list.append({
                    "Usuário": username,
                    "Nome": info.get("nome", ""),
                    "Perfil": PERFIS.get(info.get("perfil", ""), {}).get("nome", ""),
                    "Cód. Vendedor": str(info.get("codvendedor") or "-"),
                    "Ativo": "✅" if info.get("ativo", True) else "❌",
                    "Data Criação": info.get("data_criacao", "")[:10] if info.get("data_criacao") else "-"
                })
            
            df_usuarios = pd.DataFrame(usuarios_list)
            st.dataframe(df_usuarios, width='stretch', hide_index=True)
            
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
                col1, col2 = st.columns(2)
                
                with col1:
                    novo_nome = st.text_input(
                        "Nome", 
                        value=info.get("nome", ""),
                        key="edit_nome"
                    )
                    novo_perfil = st.selectbox(
                        "Perfil", 
                        list(PERFIS.keys()),
                        format_func=lambda x: PERFIS[x]["nome"],
                        index=list(PERFIS.keys()).index(info.get("perfil", "vendedor")),
                        key="edit_perfil"
                    )
                
                with col2:
                    # Funcionalidade de troca de senha desativada no modo demonstração
                    st.info("🔒 Troca de senha desativada no modo demonstração")
                    novo_ativo = st.checkbox(
                        "Ativo", 
                        value=info.get("ativo", True),
                        key="edit_ativo"
                    )
                
                col_btn1, col_btn2, col_btn3 = st.columns(3)
                
                with col_btn1:
                    st.button("💾 Salvar Alterações", key="btn_salvar_edicao", disabled=True, help="Funcionalidade desativada no modo demonstração")
                
                with col_btn2:
                    # Botão de resetar senha desativado no modo demonstração
                    st.button("🔄 Resetar Senha", key="btn_resetar_senha", disabled=True, help="Funcionalidade desativada no modo demonstração")
                
                with col_btn3:
                    st.button("🗑️ Excluir Usuário", key="btn_excluir_usuario", disabled=True, help="Funcionalidade desativada no modo demonstração")
        else:
            st.info("Nenhum usuário cadastrado")
    
    with tab2:
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
        else:
            st.info("Arquivo de vendedores não disponível")