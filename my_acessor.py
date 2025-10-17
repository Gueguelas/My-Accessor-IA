from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import (
    ChatPromptTemplate, HumanMessagePromptTemplate, AIMessagePromptTemplate,
    FewShotChatMessagePromptTemplate, MessagesPlaceholder)
import os
from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.runnables import RunnablePassThrough
from operator import itemgetter
from langchain.memory import ChatMessageHistory
from langchain.agents import create_tool_calling_agent, AgentExecutor
from pg_tools import TOOLS_FINANCEIRO, TOOLS_AGENDA
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
today = datetime.now(TZ).date()

 
store = {}
 
def get_session_history(session_id) -> ChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]
 
load_dotenv()

api_key = os.getenv("GOOGLE_GEMINI_API")
 
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.7,
    top_p=0.95,
    google_api_key=api_key
)

llm_fast = ChatGoogleGenerativeAI( 
    model="gemini-2.0-flash", # Modelo baseado em performance
    temperature=0, # Modelo deterministico, não vai ser criativo. Vai ser direto para o usuário evitando modificar qualquer coisa
    google_api_key=api_key
)

# PROMPTS -------------------------------------------------

# Roteador ------------------------------------------------
with open("prompt_roteador.txt", "r") as f:
    system_prompt_roteador = f.read()

example_prompt_base = ChatPromptTemplate.from_messages([
    HumanMessagePromptTemplate.from_template("{human}"),
    AIMessagePromptTemplate.from_template("{ai}"),
])

shots_roteador = [
    # 1) Saudação -> resposta direta
    {
        "human": "Oi, tudo bem?",
        "ai": "Olá! Posso te ajudar com finanças ou agenda; por onde quer começar?"
    },
    # 2) Fora de escopo -> recusar e redirecionar
    {
        "human": "Me conta uma piada.",
        "ai": "Consigo ajudar apenas com finanças ou agenda. Prefere olhar seus gastos ou marcar um compromisso?"
    },
    # 3) Finanças -> encaminhar (protocolo textual)
    {
        "human": "Quanto gastei com mercado no mês passado?",
        "ai": "ROUTE=financeiro\nPERGUNTA_ORIGINAL=Quanto gastei com mercado no mês passado?\nPERSONA={PERSONA_SISTEMA}\nCLARIFY="
    },
    # 4) Ambíguo -> pedir 1 clarificação mínima (texto direto, sem encaminhar)
    {
        "human": "Agendar pagamento amanhã às 9h",
        "ai": "Você quer lançar uma transação (finanças) ou criar um compromisso no calendário (agenda)?"
    },
    # 5) Agenda -> encaminhar (protocolo textual) — exemplo explícito
    {
        "human": "Tenho reunião amanhã às 9h?",
        "ai": "ROUTE=agenda\nPERGUNTA_ORIGINAL=Tenho reunião amanhã às 9h?\nPERSONA={PERSONA_SISTEMA}\nCLARIFY="
    },
]

fewshots_roteador = FewShotChatMessagePromptTemplate(
    examples=shots_roteador,
    example_prompt=example_prompt_base
)


# -------------------- PROMPTS ESPECIALISTAS --------------------

# Agente financeiro ---------------------------------------------
with open("prompt_financeiro.txt", "r") as f:
    system_prompt_financeiro = f.read()

# Especialista financeiro (mesmo example_prompt_pair)
shots_financeiro = [
    {
        "human": "ROUTE=financeiro\nPERGUNTA_ORIGINAL=Quanto gastei com mercado no mês passado?\nPERSONA={PERSONA_SISTEMA}\nCLARIFY=",
        "ai": """{{"dominio":"financeiro","intencao":"consultar","resposta":"Você gastou R$ 842,75 com 'comida' no mês passado.","recomendacao":"Quer detalhar por estabelecimento?","janela_tempo":{{"de":"2025-08-01","ate":"2025-08-31","rotulo":"mês passado (ago/2025)"}}}}"""
    },
    {
        "human": "ROUTE=financeiro\nPERGUNTA_ORIGINAL=Registrar almoço hoje R$ 45 no débito\nPERSONA={PERSONA_SISTEMA}\nCLARIFY=",
        "ai": """{{"dominio":"financeiro","intencao":"inserir","resposta":"Lancei R$ 45,00 em 'comida' hoje (débito).","recomendacao":"Deseja adicionar uma observação?","escrita":{{"operacao":"adicionar","id":2045}}}}"""
    },
    {
        "human": "ROUTE=financeiro\nPERGUNTA_ORIGINAL=Quero um resumo dos gastos\nPERSONA={PERSONA_SISTEMA}\nCLARIFY=",
        "ai": """{{"dominio":"financeiro","intencao":"resumo","resposta":"Preciso do período para seguir.","recomendacao":"","esclarecer":"Qual período considerar (ex.: hoje, esta semana, mês passado)?"}}"""
    },
]

fewshots_financeiro = FewShotChatMessagePromptTemplate(
    examples=shots_financeiro,
    example_prompt=example_prompt_base,
)


# Agente de agenda -------------------------------------------------
with open("prompt_agenda.txt", "r") as f:
    system_prompt_agenda = f.read()

shots_agenda = [
    {
        "human": "ROUTE=agenda\nPERGUNTA_ORIGINAL=Tenho janela amanhã à tarde?\nPERSONA={PERSONA_SISTEMA}\nCLARIFY=",
        "ai": """{{"dominio":"agenda","intencao":"disponibilidade","resposta":"Você está livre amanhã das 14:00 às 16:00.","recomendacao":"Quer reservar 15:00–16:00?","janela_tempo":{{"de":"2025-09-29T14:00","ate":"2025-09-29T16:00","rotulo":"amanhã 14:00–16:00"}}}}"""
    },
    {
        "human": "ROUTE=agenda\nPERGUNTA_ORIGINAL=Marcar reunião com João amanhã às 9h por 1 hora\nPERSONA={PERSONA_SISTEMA}\nCLARIFY=",
        "ai": """{{"dominio":"agenda","intencao":"criar","resposta":"Posso criar 'Reunião com João' amanhã 09:00–10:00.","recomendacao":"Confirmo o envio do convite?","janela_tempo":{{"de":"2025-09-29T09:00","ate":"2025-09-29T10:00","rotulo":"amanhã 09:00–10:00"}},"evento":{{"titulo":"Reunião com João","data":"2025-09-29","inicio":"09:00","fim":"10:00","local":"online"}}}}"""
    },
    {
        "human": "ROUTE=agenda\nPERGUNTA_ORIGINAL=Agendar revisão do orçamento na sexta\nPERSONA={PERSONA_SISTEMA}\nCLARIFY=",
        "ai": """{{"dominio":"agenda","intencao":"criar","resposta":"Preciso do horário para agendar.","recomendacao":"","esclarecer":"Qual horário você prefere na sexta?"}}"""
    },
]

fewshots_agenda = FewShotChatMessagePromptTemplate(
    examples=shots_agenda,
    example_prompt=example_prompt_base,
)

### Agente FAQ -----------------------------------------------------
with open("prompt_faq.txt", "r") as f:
    system_prompt_faq = f.read()


### Agente orquestrador --------------------------------------------
with open("prompt_orquestrador.txt", "r") as f:
    system_prompt_orquestrador = f.read()

shots_orquestrador = [
    # 1) Financeiro — consultar
    {
        "human": """ESPECIALISTA_JSON:\n{{"dominio":"financeiro","intencao":"consultar","resposta":"Você gastou R$ 842,75 com 'comida' no mês passado.","recomendacao":"Quer detalhar por estabelecimento?","janela_tempo":{{"de":"2025-08-01","ate":"2025-08-31","rotulo":"mês passado (ago/2025)"}}}}""",
        "ai": "Você gastou R$ 842,75 com 'comida' no mês passado.\n- Recomendação:\nQuer detalhar por estabelecimento?"
    },

    # 2) Financeiro — falta dado → esclarecer
    {
        "human": """ESPECIALISTA_JSON:\n{{"dominio":"financeiro","intencao":"resumo","resposta":"Preciso do período para seguir.","recomendacao":"","esclarecer":"Qual período considerar (ex.: hoje, esta semana, mês passado)?"}}""",
        "ai": """Preciso do período para seguir.\n- Acompanhamento (opcional):\nQual período considerar (ex.: hoje, esta semana, mês passado)?"""
    },

    # 3) Agenda — criar
    {
        "human": """ESPECIALISTA_JSON:\n{{"dominio":"agenda","intencao":"criar","resposta":"Posso criar 'Reunião com João' amanhã 09:00–10:00.","recomendacao":"Confirmo o envio do convite?","janela_tempo":{{"de":"2025-09-29T09:00","ate":"2025-09-29T10:00","rotulo":"amanhã 09:00–10:00"}},"evento":{{"titulo":"Reunião com João","data":"2025-09-29","inicio":"09:00","fim":"10:00","local":"online"}}}}""",
        "ai": """Posso criar 'Reunião com João' amanhã 09:00–10:00.\n- Recomendação:\nConfirmo o envio do convite?"""
    },
]

fewshots_orquestrador = FewShotChatMessagePromptTemplate(
    examples=shots_orquestrador,
    example_prompt=example_prompt_base,
)

# ================================================================
# Criação dos prompts
prompts = {
    "roteador": ChatPromptTemplate.from_messages([
        system_prompt_roteador,
        fewshots_roteador,
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ]).partial(today_local = today.isoformat()),
    "financeiro": ChatPromptTemplate.from_messages([
        system_prompt_financeiro,
        fewshots_financeiro,
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad") # llm fazendo um bloco de anotações, dando total liberdade para o agente mudar o promptm, para implementação de tools
    ]).partial(today_local = today.isoformat()),
    "agenda": ChatPromptTemplate.from_messages([
        system_prompt_agenda,
        fewshots_agenda,
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad") # llm fazendo um bloco de anotações, dando total liberdade para o agente mudar o promptm, para implementação de tools
    ]).partial(today_local = today.isoformat()),
    "faq": ChatPromptTemplate.from_messages([
        system_prompt_faq,
        ("human",
        "Pergunta do usuário:\n{question}\n\n"
        "CONTEXTO (trechos do documento):\n{context}\n\n"
        "Responda com base APENAS no CONTEXTO.")
    ]),
    "orquestrador": ChatPromptTemplate.from_messages([
        system_prompt_orquestrador,
        fewshots_orquestrador,
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ]).partial(today_local = today.isoformat()),
}

# ================================================================
# Criação de agentes
def criar_roteador():
    return RunnableWithMessageHistory(
        prompts["roteador"] | llm_fast | StrOutputParser(),
        get_session_history=get_session_history,
        history_messages_key="chat_history",
        input_messages_key="input")

def criar_financeiro():
    financeiro_agent = create_tool_calling_agent(
        llm=llm,
        tools=TOOLS_FINANCEIRO,
        prompt=prompts["financeiro"]
    )
    financeiro_executor_base = AgentExecutor(
        agent=financeiro_agent,
        tools=TOOLS_FINANCEIRO,
        verbose=False,
        handle_parsing_errors=True,
        return_intermediate_steps=False
    )
    financeiro_executor = RunnableWithMessageHistory(
        financeiro_executor_base,
        get_session_history=get_session_history,
        input_messages_key='input',
        history_messages_key='chat_history'
    )

    return financeiro_executor

def criar_agenda():
    agenda_agent = create_tool_calling_agent(llm, TOOLS_AGENDA, prompts["agenda"])
    agenda_executor_base = AgentExecutor(
        agent=agenda_agent,
        tools=TOOLS_AGENDA,
        verbose=False,
        handle_parsing_errors=True,
        return_intermediate_steps=False
    )
    agenda_executor = RunnableWithMessageHistory(
        agenda_executor_base,
        get_session_history=get_session_history,
        input_messages_key='input',
        history_messages_key='chat_history'
    )

    return agenda_executor

def criar_faq():
    return (RunnablePassThrough.assign(
        question=itemgetter("input"),
        context= lambda x: get_faq_context(x["input"])
    )| prompts["faq"] | llm_fast | StrOutputParser())

def criar_orquestrador():
    return RunnableWithMessageHistory(
        prompts["orquestrador"] | llm_fast | StrOutputParser(), 
        get_session_history=get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history")

def rotear_agente(resposta_roteador: str):
    """
    Função responsável por identificar para qual agente a conversa deve ser direcionada.
    Retorna o nome do agente (string) ou None caso não tenha rota.
    """
    if "ROUTE=" not in resposta_roteador:
        return None

    if "financeiro" in resposta_roteador:
        return "financeiro"
    elif "agenda" in resposta_roteador:
        return "agenda"
    elif "faq" in resposta_roteador:
        return "faq"

    return None


def fluxo_conversa(pergunta_usuario: str, session_id: str):
    """
    Fluxo principal da conversa, responsável por:
    1. Invocar o roteador
    2. Direcionar para o agente correto (se houver rota)
    3. Passar pelo orquestrador
    """
    roteador = criar_roteador()
    resposta_roteador = roteador.invoke(
        {"input": pergunta_usuario},
        config={"configurable": {"session_id": session_id}}
    )

    agente_destino = rotear_agente(resposta_roteador)

    if agente_destino is None:
        return resposta_roteador

    # Dicionário de agentes — fácil de manter e escalar
    agentes = {
        "financeiro": criar_financeiro,
        "agenda": criar_agenda,
        "faq": criar_faq
    }

    # Instancia o agente correto dinamicamente
    agente_func = agentes.get(agente_destino)
    if not agente_func:
        return {"output": f"Agente '{agente_destino}' não encontrado."}

    agente = agente_func()
    resposta_agente = agente.invoke(
        {"input": resposta_roteador},
        config={"configurable": {"session_id": session_id}}
    )

    output = resposta_agente["output"]

    # Passa pelo orquestrador para gerar a resposta final
    orquestrador = criar_orquestrador()
    resposta_final = orquestrador.invoke(
        {"input": output},
        config={"configurable": {"session_id": session_id}}
    )

    return resposta_final

    

while True:
    usuario = input("> ")

    if usuario in  ("sair", "tchau", "bye"):
        break

    resposta = fluxo_conversa(usuario, "teste")

    print(f"IA: {resposta}")