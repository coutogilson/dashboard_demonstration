"""
Script para gerar dados sintéticos de demonstração.
Cria arquivos CSV na pasta data/ com dados fictícios.

Uso: python utils/gerar_dados_demo.py
"""

import os
import sys
import io
import random
from pathlib import Path
from datetime import datetime, timedelta

# Forçar UTF-8 no stdout para evitar erro de encoding no Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import numpy as np

# Garantir que o diretório raiz está no path
sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path("data")
PROCESSADOS_DIR = Path("processados")
DATA_DIR.mkdir(exist_ok=True)
PROCESSADOS_DIR.mkdir(exist_ok=True)

random.seed(42)
np.random.seed(42)

# =============================================================================
# DADOS BASE
# =============================================================================

NOMES_VENDEDORES = [
    "Ana Beatriz Costa", "Carlos Eduardo Silva", "Daniela Oliveira Santos",
    "Eduardo Almeida Neto", "Fernanda Lima Souza", "Gabriel Barbosa Rocha",
    "Helena Martins Dias", "Igor Pereira Gomes", "Julia Carvalho Ribeiro",
    "Lucas Fernandes Teixeira", "Mariana Campos Araujo", "Nicolas Moreira Lopes",
    "Patricia Azevedo Castro", "Rafael Monteiro Cardoso", "Sandra Vieira Nunes",
    "Thiago Correia Pinto", "Vanessa Barbosa Melo", "William Santos Cruz",
    "Yara Oliveira Campos", "Bruno Costa Andrade"
]

NOMES_CLIENTES = [
    "Mercado Bom Preço Ltda", "Supermercado Economia Ltda", "Padaria Pão Quente ME",
    "Restaurante Sabor Caseiro Ltda", "Açougue Corte Nobre ME", "Mercearia do João Ltda",
    "Distribuidora Alimentar ABC Ltda", "Comércio de Bebidas Geladas ME",
    "Supermercado Popular Ltda", "Padaria e Confeitaria Doce Pão Ltda",
    "Restaurante Comida Boa Ltda", "Mercado do Bairro Ltda", "Açougue Boi Gordo ME",
    "Distribuidora de Frios Ltda", "Supermercado Ideal Ltda", "Padaria Trigal ME",
    "Restaurante Bem Estar Ltda", "Mercado Central Ltda", "Açougue Rei da Carne ME",
    "Distribuidora de Alimentos Ltda", "Supermercado Maxi Ltda", "Padaria da Vila ME",
    "Restaurante Tempero Caseiro Ltda", "Mercado Nova Era Ltda", "Açougue Primavera ME",
    "Distribuidora de Bebidas Ltda", "Supermercado Bom Jesus Ltda", "Padaria Santo Antônio ME",
    "Restaurante e Lanchonete Top Ltda", "Mercado São José Ltda"
]

CIDADES = [
    "Juiz de Fora", "Ubá", "Viçosa", "Muriaé", "Leopoldina",
    "Cataguases", "Além Paraíba", "São João Nepomuceno", "Bicas", "Matias Barbosa"
]

NOMES_FORNECEDORES = [
    (1, "PANE"), (396, "QUEIJO"), (540, "IOG"), (449, "BRINQUEDOS"),
    (406, "NUMBERONE"), (467, "BARRAS"), (457, "PAÇOCA"),
    (456, "BALA"), (450, "PANINIS"), (642, "QUEIJINHOS"), (681, "LEITECONDENSADO")
]

MARCAS = ["PANE", "PULLMAN", "NUTRELLA", "VITARELLA", "TODDY", "BATAVO", "DANONE", "NESTLÉ"]

PRODUTOS = [
    (1001, "Pão de Forma Integral", "PANE", 0.450, 12),
    (1002, "Pão de Leite", "PULLMAN", 0.400, 10),
    (1003, "Bolo de Chocolate", "PANE", 0.350, 8),
    (1004, "Torrada Integral", "VITARELLA", 0.200, 24),
    (1005, "Biscoito Recheado", "NESTLÉ", 0.150, 36),
    (1006, "Iogurte Natural", "BATAVO", 1.000, 12),
    (1007, "Leite Longa Vida", "NESTLÉ", 1.000, 12),
    (1008, "Margarina", "BATAVO", 0.500, 20),
    (1009, "Requeijão Cremoso", "BATAVO", 0.200, 24),
    (1010, "Mussarela Fatiada", "DANONE", 0.300, 15),
    (1011, "Presunto Cozido", "NESTLÉ", 0.300, 15),
    (1012, "Suco de Laranja", "NUMBERONE", 1.500, 6),
    (1013, "Refrigerante Cola", "NUMBERONE", 2.000, 6),
    (1014, "Água Mineral", "NUMBERONE", 1.500, 12),
    (1015, "Arroz Tipo 1", "PANINIS", 5.000, 5),
    (1016, "Feijão Carioca", "PANINIS", 1.000, 10),
    (1017, "Açúcar Refinado", "PANINIS", 5.000, 5),
    (1018, "Óleo de Soja", "PAÇOCA", 0.900, 15),
    (1019, "Molho de Tomate", "PAÇOCA", 0.340, 24),
    (1020, "Maionese", "PAÇOCA", 0.500, 20),
    (1021, "Creme de Leite", "IOG", 0.200, 24),
    (1022, "Leite Condensado", "IOG", 0.395, 24),
    (1023, "Doce de Leite", "IOG", 0.400, 12),
    (1024, "Queijo Minas", "IOG", 0.500, 10),
    (1025, "Manteiga", "QUEIJINHOS", 0.200, 30),
    (1026, "Iogurte Grego", "QUEIJINHOS", 0.150, 24),
    (1027, "Bebida Láctea", "QUEIJINHOS", 1.000, 12),
    (1028, "Pão de Queijo", "BRINQUEDOS", 0.300, 20),
    (1029, "Salgadinho de Queijo", "BRINQUEDOS", 0.100, 40),
    (1030, "Biscoito Cream Cracker", "QUEIJO", 0.200, 30),
]

# Mapear fornecedor para cada produto
FORNECEDOR_PRODUTO = {
    1001: 1, 1002: 1, 1003: 1, 1004: 1, 1005: 406,
    1006: 642, 1007: 406, 1008: 642, 1009: 642, 1010: 642,
    1011: 406, 1012: 406, 1013: 406, 1014: 406, 1015: 450,
    1016: 450, 1017: 450, 1018: 457, 1019: 457, 1020: 457,
    1021: 540, 1022: 540, 1023: 540, 1024: 540, 1025: 642,
    1026: 642, 1027: 642, 1028: 449, 1029: 449, 1030: 396,
}

# =============================================================================
# FUNÇÕES DE GERAÇÃO
# =============================================================================

def gerar_vendedores():
    """Gera CSV de vendedores"""
    dados = []
    for i, nome in enumerate(NOMES_VENDEDORES, 1):
        tipo = 'S' if i <= 4 else 'V'  # 4 supervisores
        codsupervisor = None if tipo == 'S' else random.choice([1, 2, 3, 4])
        dados.append({
            'codvendedor': i,
            'vendedor': nome,
            'tipo': tipo,
            'codsupervisor': codsupervisor if codsupervisor != i else None,
            'email': f"vendedor{i}@exemplo.com"
        })
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "vendedores.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ vendedores.csv gerado com {len(df)} registros")
    return df

def gerar_clientes():
    """Gera CSV de clientes"""
    dados = []
    for i, nome in enumerate(NOMES_CLIENTES, 1):
        cidade = random.choice(CIDADES)
        cod_vendedor = random.randint(1, len(NOMES_VENDEDORES))
        cnpj = f"{random.randint(10,99)}.{random.randint(100,999)}.{random.randint(100,999)}/0001-{random.randint(10,99)}"
        dados.append({
            'codcliente': i,
            'nome': nome,
            'cidade': cidade,
            'cod_vendedor': cod_vendedor,
            'CNPJ': cnpj,
            'Vendedor': NOMES_VENDEDORES[cod_vendedor - 1],
        })
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "clientes.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ clientes.csv gerado com {len(df)} registros")
    return df

def gerar_fornecedores():
    """Gera CSV de fornecedores"""
    dados = [{'codfornec': cod, 'fornecedor': nome} for cod, nome in NOMES_FORNECEDORES]
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "fornecedores.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ fornecedores.csv gerado com {len(df)} registros")
    return df

def gerar_fornecedores_produto():
    """Gera CSV de fornecedores_produto"""
    dados = []
    for cod_prod, _, _, _, _ in PRODUTOS:
        cod_forn = FORNECEDOR_PRODUTO[cod_prod]
        nome_forn = dict(NOMES_FORNECEDORES)[cod_forn]
        dados.append({
            'CODPRODUTO': cod_prod,
            'CODFORNEC': cod_forn,
            'FORNECEDOR': nome_forn,
        })
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "fornecedores_produto.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ fornecedores_produto.csv gerado com {len(df)} registros")
    return df

def gerar_produtos():
    """Gera CSV de produtos"""
    dados = []
    for cod_prod, nome, marca, peso, qtde_conv in PRODUTOS:
        cod_forn = FORNECEDOR_PRODUTO[cod_prod]
        dados.append({
            'codproduto': cod_prod,
            'produto': nome,
            'marca': marca,
            'pesoliq': peso,
            'pesobruto': round(peso * 1.1, 3),
            'codfornec': cod_forn,
            'qtde_conv': qtde_conv,
            'un': 'UN',
        })
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "produtos.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ produtos.csv gerado com {len(df)} registros")
    return df

def gerar_meta():
    """Gera CSV de meta (últimos 12 meses + próximos 3)"""
    dados = []
    hoje = datetime.now()
    for mes_offset in range(-12, 3):  # 12 meses atrás até 3 meses à frente
        data_base = hoje.replace(day=1) + timedelta(days=32 * mes_offset)
        data_base = data_base.replace(day=1)
        
        for cod_vendedor in range(1, len(NOMES_VENDEDORES) + 1):
            for cod_forn, nome_forn in NOMES_FORNECEDORES:
                meta_valor = random.uniform(2000, 20000)
                meta_pos = random.randint(10, 50)
                dados.append({
                    'data': data_base.strftime('%Y-%m-%d'),
                    'codvendedor': cod_vendedor,
                    'vendedor': NOMES_VENDEDORES[cod_vendedor - 1],
                    'codfornec': cod_forn,
                    'fornecedor': nome_forn,
                    'meta_valor': round(meta_valor, 2),
                    'meta_positivacao': meta_pos,
                })
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "meta.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ meta.csv gerado com {len(df)} registros")
    return df

def gerar_faturamento():
    """Gera CSV de faturamento (últimos 12 meses)"""
    dados = []
    hoje = datetime.now()
    
    # Gerar ~500 notas fiscais por mês
    for mes_offset in range(-12, 1):
        data_base = hoje.replace(day=1) + timedelta(days=32 * mes_offset)
        mes = data_base.month
        ano = data_base.year
        
        num_notas = random.randint(300, 3000)
        for _ in range(num_notas):
            cod_vendedor = random.randint(1, len(NOMES_VENDEDORES))
            cod_cliente = random.randint(1, len(NOMES_CLIENTES))
            cod_produto, nome_produto, _, peso, _ = random.choice(PRODUTOS)
            cod_forn = FORNECEDOR_PRODUTO[cod_produto]
            nome_forn = dict(NOMES_FORNECEDORES)[cod_forn]
            
            dia = random.randint(1, 28)
            data = datetime(ano, mes, dia)
            qtde = random.randint(10, 200)
            preco_unit = random.uniform(5, 80)
            valor_total = round(qtde * preco_unit, 2)
            peso_total = round(qtde * peso, 3)
            
            # 80% venda, 5% devolução, 5% troca, 10% pedido
            tipo = random.choices(
                ['VENDA', 'DEVOLUCAO VENDA', 'TROCA', 'PEDIDO', 'DEVOLUCAO TROCA'],
                weights=[80, 5, 5, 10, 0.5]
            )[0]
            
            valor_faturado = valor_total if tipo in ['VENDA', 'DEVOLUCAO VENDA', 'DEVOLUCAO TROCA'] else 0
            if tipo in ['DEVOLUCAO VENDA', 'DEVOLUCAO TROCA']:
                valor_faturado = -valor_total
                peso_total = -peso_total
            
            valor_troca = -valor_total if tipo == 'TROCA' else 0
            valor_pedido = valor_total if tipo == 'PEDIDO' else 0
            
            peso_bruto = round(peso_total * 1.1, 3)
            dados.append({
                'data': data.strftime('%Y-%m-%d'),
                'codigo_cliente': cod_cliente,
                'nome_cliente': NOMES_CLIENTES[cod_cliente - 1],
                'codvendedor': cod_vendedor,
                'vendedor': NOMES_VENDEDORES[cod_vendedor - 1],
                'codfornec': cod_forn,
                'fornecedor': nome_forn,
                'codproduto': cod_produto,
                'descricao_produto': nome_produto,
                'tipo_movimento': tipo,
                'valor_faturado': round(valor_faturado, 2),
                'valor_troca': round(valor_troca, 2),
                'valor_pedido': round(valor_pedido, 2),
                'peso_liquido_total': round(peso_total, 3),
                'peso_bruto_total': round(peso_bruto, 3),
                'quantidade': qtde,
                'numero_nota': random.randint(10000, 99999),
                'rede': random.choice(['VAREJO', 'ATACADO', 'INDÚSTRIA', 'SERVICO']),
                'codrede': random.randint(1, 4),
            })
    
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "faturamento.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ faturamento.csv gerado com {len(df)} registros")
    return df

def gerar_estoque():
    """Gera CSV de estoque"""
    dados = []
    for cod_prod, nome_prod, marca, peso, qtde_conv in PRODUTOS:
        cod_forn = FORNECEDOR_PRODUTO[cod_prod]
        estoque_atual = random.randint(50, 5000)
        disponivel = estoque_atual - random.randint(0, int(estoque_atual * 0.3))
        dados.append({
            'CODPRODUTO': cod_prod,
            'PRODUTO': nome_prod,
            'MARCA': marca,
            'CODFORNEC': cod_forn,
            'UNIDADE': 'UN',
            'UN': 'UN',
            'QTDE_CONV': qtde_conv,
            'PESOLIQ': peso,
            'ESTOQUEATUAL': estoque_atual,
            'DISPONIVEL': max(0, disponivel),
            'CUSTO_TOTAL': round(estoque_atual * random.uniform(3, 20), 2),
        })
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "estoque.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ estoque.csv gerado com {len(df)} registros")
    return df

def gerar_cortes():
    """Gera CSV de cortes analítico"""
    dados = []
    hoje = datetime.now()
    for mes_offset in range(-3, 0):
        data_base = hoje.replace(day=1) + timedelta(days=32 * mes_offset)
        mes = data_base.month
        ano = data_base.year
        
        for _ in range(200):
            cod_cliente = random.randint(1, len(NOMES_CLIENTES))
            cod_prod = random.choice([p[0] for p in PRODUTOS])
            dia = random.randint(1, 28)
            dados.append({
                'data': datetime(ano, mes, dia).strftime('%Y-%m-%d'),
                'codcliente': cod_cliente,
                'codproduto': cod_prod,
                'qtdecorte': random.randint(1, 20),
            })
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "cortes-analitico.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ cortes-analitico.csv gerado com {len(df)} registros")
    return df

def gerar_pedidos():
    """Gera CSV de pedidos"""
    dados = []
    hoje = datetime.now()
    for mes_offset in range(-2, 1):
        data_base = hoje.replace(day=1) + timedelta(days=32 * mes_offset)
        mes = data_base.month
        ano = data_base.year
        
        for _ in range(100):
            cod_cliente = random.randint(1, len(NOMES_CLIENTES))
            cod_vendedor = random.randint(1, len(NOMES_VENDEDORES))
            dia = random.randint(1, 28)
            dados.append({
                'data': datetime(ano, mes, dia).strftime('%Y-%m-%d'),
                'codigo_cliente': cod_cliente,
                'codvendedor': cod_vendedor,
                'valor_total': round(random.uniform(500, 15000), 2),
                'situacao': random.choice(['PENDENTE', 'APROVADO', 'FATURADO']),
            })
    df = pd.DataFrame(dados)
    df.to_csv(DATA_DIR / "pedidos.csv", sep=';', index=False, encoding='utf-8')
    print(f"✅ pedidos.csv gerado com {len(df)} registros")
    return df

def gerar_usuarios_json():
    """Gera JSON de usuários"""
    usuarios = {
        "usuarios": {
            "admin": {
                "nome": "Administrador",
                "perfil": "admin",
                "senha_hash": hashlib.sha256("admin".encode()).hexdigest(),
                "ativo": True,
                "data_criacao": datetime.now().isoformat(),
                "filtros": {}
            },
            "demo": {
                "nome": "Usuário Demonstração",
                "perfil": "admin",
                "senha_hash": hashlib.sha256("demo".encode()).hexdigest(),
                "ativo": True,
                "data_criacao": datetime.now().isoformat(),
                "filtros": {}
            }
        }
    }
    import json
    with open(DATA_DIR / "usuarios.json", 'w', encoding='utf-8') as f:
        json.dump(usuarios, f, indent=4, ensure_ascii=False)
    print("✅ usuarios.json gerado com admin/demo")

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import hashlib
    
    print("=" * 50)
    print("Gerando dados sinteticos de demonstracao...")
    print("=" * 50)
    
    gerar_vendedores()
    gerar_clientes()
    gerar_fornecedores()
    gerar_fornecedores_produto()
    gerar_produtos()
    gerar_meta()
    gerar_faturamento()
    gerar_estoque()
    gerar_cortes()
    gerar_pedidos()
    gerar_usuarios_json()
    
    print("=" * 50)
    print("Todos os dados de demonstracao foram gerados!")
    print("Pasta data/ populada com CSVs sinteticos")
    print("=" * 50)
