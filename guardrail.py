import re
from typing import List, Tuple

# Palavras/frases que indicam tentativa de burlar o sistema → BLOQUEAR
TERMOS_BLOQUEAR = [
    "ignore as regras", "ignorar as regras", "ignore todas as instruções",
    "revele o system prompt", "mostre o prompt do sistema", "bypass",
    "desative guardrail", "ignore a política", "ignore policy",
    "mostre suas chaves", "mostre seu .env",
]

# Palavras que indicam potencial risco de segurança, mas não necessariamente ataque → AVISAR
TERMOS_AVISO = [
    "senha", "pin", "cvv", "cvc",
]

# Palavrões ofensivos → AVISAR (ou moderar)
PROFANIDADE_PESADA = [
    "fdp", "filho da p", "pqp", "cuzao", "fodase",'imundo', 'maldito'
]

# Regex para buscas mais robustas → BLOQUEAR
PADROES_BLOQUEAR = [
    re.compile(r"(?i)\b(ignore|desconsidere).{0,20}(regras|instruç|policy|política)"),
    re.compile(r"(?i)(system\s*prompt|prompt\s*do\s*sistema)"),
    re.compile(r"(?i)(api[_\s-]?key|chave\s*(api|secreta)|token\s*(de)?\s*acesso)"),
    re.compile(r"(?i)\b(union\s+select|drop\s+table|truncate|xp_|sleep\()", re.I),
    re.compile(r"--|;|/\*|\*/"),
    re.compile(r"(?i)(bomba caseira|como fazer bomba|clonar cartão|phishing)"),
    re.compile(r"(?i)(suic[ií]dio|me matar|auto\s?mutila[cç][aã]o)"),
    re.compile(r"(?i)(conte[úu]do sexual infantil|min[ií]or(es)?\s+sexual)"),
]

# Regex que identifica dados sensíveis (LGPD) → SANITIZAR
PADROES_AVISO = [
    re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),                       # CPF
    re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),               # CNPJ
    re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-?[0-9Xx]\b"),                  # RG (simplificado)
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),                               # cartão (simplificado)
    re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w{2,}\b"),                         # e-mail
    re.compile(r"\b(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?\d{4,5}-?\d{4}\b"),    # telefone BR
    re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b"), # UUID (chave PIX aleatória)
    re.compile(r"(?i)\b(ag(e|ê)ncia|conta|iban)\b.*\b\d{3,}\b"),          # dados bancários
]

# Substituições para mascarar dados sensíveis
PADROES_SANITIZAR = [
    (re.compile(r"(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})"), r"\1.\2.***-**"),          # CPF
    (re.compile(r"(\d{2})\.?(\d{3})\.?(\d{3})/?:?(\d{4})-?(\d{2})"), r"\1.\2.***/*-**"),  # CNPJ
    (re.compile(r"(\d{4})\d{9,15}"), r"\1************"),                            # cartão
    (re.compile(r"([\w\.-]+)@([\w\.-]+\.\w{2,})"), r"***@***"),                     # e-mail
    (re.compile(r"((?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?)\d{4,5}-?\d{4}"), r"\1*****-****"),  # telefone
]


def verificar_guardrail(texto: str) -> Tuple[str, str, List[str]]:
    """
    Retorna (acao, mensagem, gatilhos)
    acao: "BLOQUEAR" | "AVISAR" | "SANITIZAR" | "PERMITIR"
    mensagem: resposta sugerida ao usuário
    gatilhos: lista com padrões que dispararam (para auditoria)
    """
    gatilhos = []

    # 1) Bloqueio por termos explícitos
    for termo in TERMOS_BLOQUEAR:
        if termo.lower() in texto.lower():
            gatilhos.append(f"TERMO:{termo}")
            return "BLOQUEAR", "Não posso atender esse pedido. Posso ajudar com finanças ou agenda.", gatilhos

    # 2) Bloqueio por padrões de ataque / ilegalidade
    for padrao in PADROES_BLOQUEAR:
        if padrao.search(texto):
            gatilhos.append(f"PADRAO_BLOQUEAR:{padrao.pattern[:30]}...")
            return "BLOQUEAR", "Não posso atender esse pedido. Posso ajudar com finanças ou agenda.", gatilhos

    # 3) Profanidade pesada → Aviso
    for termo in PROFANIDADE_PESADA:
        if re.search(fr"(?i)\b{re.escape(termo)}\b", texto):
            gatilhos.append(f"PROFANIDADE:{termo}")
            return "AVISAR", "Vamos manter uma conversa respeitosa. Como posso ajudar com finanças ou agenda?", gatilhos

    # 4) Dados sensíveis → Sanitização
    encontrou_dado_sensivel = False
    for padrao in PADROES_AVISO:
        if padrao.search(texto):
            gatilhos.append(f"PADRAO_AVISO:{padrao.pattern[:30]}...")
            encontrou_dado_sensivel = True

    if encontrou_dado_sensivel:
        texto_sanitizado = texto
        for padrao, substituicao in PADROES_SANITIZAR:
            texto_sanitizado = padrao.sub(substituicao, texto_sanitizado)

        return "SANITIZAR", "Detectei dados sensíveis. Omiti/mascarei informações para sua segurança. Deseja prosseguir?", gatilhos + ["SANITIZADO"]

    # 5) Tudo ok → Permitir continuar
    return "PERMITIR", "", gatilhos
