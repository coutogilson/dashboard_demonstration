import pandas as pd

# =============================================================================
# CONFIGURAÇÃO DO LOCALE
# =============================================================================
try:
    import locale
    import io
    from pandas.plotting import table
    locales_tentativas = ['pt_BR.UTF-8', 'Portuguese_Brazil.1252', 'pt_BR', 'portuguese', 'pt_PT.UTF-8'
    ]
    
    locale_configurado = False
    for loc in locales_tentativas:
        try:
            locale.setlocale(locale.LC_ALL, loc)
            locale_configurado = True
            break
        except locale.Error:
            continue
    
    USE_LOCALE = locale_configurado
        
except ImportError:
    USE_LOCALE = False

# =============================================================================
# FUNÇÕES DE FORMATAÇÃO
# =============================================================================
def formatar_moeda(valor):
    """Formata valor monetário"""
    try:
        valor = float(valor)
        if valor == 0:
            return "R$ 0,00"
            
        if USE_LOCALE:
            return locale.currency(valor, grouping=True, symbol=True)
        else:
            sinal = '-' if valor < 0 else ''
            valor_abs = abs(valor)
            parte_inteira = int(valor_abs)
            parte_decimal = int(round((valor_abs - parte_inteira) * 100))
            parte_inteira_str = f"{parte_inteira:,}".replace(",", ".")
            return f"{sinal}R$ {parte_inteira_str},{parte_decimal:02d}"
            
    except (ValueError, TypeError):
        return "R$ 0,00"

def formatar_numero(valor, decimais=0):
    """Formata número"""
    try:
        valor = float(valor)
        
        if USE_LOCALE:
            if decimais == 0:
                return locale.format_string('%d', valor, grouping=True)
            else:
                return locale.format_string(f'%.{decimais}f', valor, grouping=True)
        else:
            if decimais == 0:
                return f"{int(valor):,}".replace(",", ".")
            else:
                valor_arredondado = round(valor, decimais)
                parte_inteira = int(valor_arredondado)
                parte_decimal = int(round((valor_arredondado - parte_inteira) * (10 ** decimais)))
                parte_inteira_str = f"{parte_inteira:,}".replace(",", ".")
                parte_decimal_str = f"{parte_decimal:0{decimais}d}"
                return f"{parte_inteira_str},{parte_decimal_str}"
                
    except (ValueError, TypeError):
        return "0" if decimais == 0 else f"0,{'0'*decimais}"
    
def formatar_percentual(valor, casas_decimais=1):
    """
    Formata um valor como percentual com tratamento de erros
    """
    try:
        if pd.isna(valor) or valor is None:
            return "0.0%"
        
        # Converter para float se for string
        if isinstance(valor, str):
            valor = float(valor.replace('%', '').replace(',', '.'))
        
        # Verificar se é infinito ou muito grande
        if abs(valor) == float('inf') or abs(valor) > 1e10:
            return "0.0%"
        
        # Arredondar e formatar
        valor_arredondado = round(valor, casas_decimais)
        return f"{valor_arredondado:.{casas_decimais}f}%"
        
    except (ValueError, TypeError, OverflowError):
        return "0.0%"

def formatar_moeda_abreviada(valor):
    """Formata valor monetário em forma abreviada (K, M, B)"""
    try:
        valor = float(valor)
        if valor == 0:
            return "R$ 0,00"
        
        abs_valor = abs(valor)
        if abs_valor >= 1_000_000_000:
            valor_formatado = valor / 1_000_000_000
            sufixo = 'B'
        elif abs_valor >= 1_000_000:
            valor_formatado = valor / 1_000_000
            sufixo = 'M'
        elif abs_valor >= 1_000:
            valor_formatado = valor / 1_000
            sufixo = 'K'
        else:
            return formatar_moeda(valor)
        
        if USE_LOCALE:
            return f"{locale.currency(valor_formatado, grouping=True, symbol=True)}{sufixo}"
        else:
            sinal = '-' if valor < 0 else ''
            valor_abs = abs(valor_formatado)
            parte_inteira = int(valor_abs)
            parte_decimal = int(round((valor_abs - parte_inteira) * 100))
            parte_inteira_str = f"{parte_inteira:,}".replace(",", ".")
            return f"{sinal}R$ {parte_inteira_str},{parte_decimal:02d}{sufixo}"
            
    except (ValueError, TypeError):
        return "R$ 0,00"