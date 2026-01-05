from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import (
    ChatPromptTemplate, HumanMessagePromptTemplate, AIMessagePromptTemplate,
    FewShotChatMessagePromptTemplate, MessagesPlaceholder)
import os
from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.runnables import RunnablePassthrough
from operator import itemgetter
from langchain.memory import ChatMessageHistory
from langchain.agents import create_tool_calling_agent, AgentExecutor
from pg_tools import TOOLS_FINANCEIRO
from datetime import datetime
from zoneinfo import ZoneInfo
from faq_tools import get_faq_context
from langgraph.graph import StateGraph, START, END
from guardrail import verificar_guardrail

TZ = ZoneInfo("America/Sao_Paulo")
today = datetime.now(TZ).date()

 
store = {}
 
def get_session_history(session_id) -> ChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]
 
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
 
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
with open("prompt_roteador.txt", "r", encoding="utf-8") as f:
    system_prompt_roteador = f.read()

example_prompt_base = ChatPromptTemplate.from_messages([
    HumanMessagePromptTemplate.from_template("{human}"),
    AIMessagePromptTemplate.from_template("{ai}"),
])

shots_roteador = [
    # 1) Saudação -> resposta direta
    {
        "human": "Oi, tudo bem?",
        "ai": "Eai meu Binomial Junior! Belezinha?? Como posso te ajudar"
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
with open("prompt_financeiro.txt", "r", encoding="utf-8") as f:
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
with open("prompt_agenda.txt", "r", encoding="utf-8") as f:
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
with open("prompt_faq.txt", "r", encoding="utf-8") as f:
    system_prompt_faq = f.read()


### Agente orquestrador --------------------------------------------
with open("prompt_orquestrador.txt", "r", encoding="utf-8") as f:
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

    {"human":"Quem é você",
    "ai":
     "EU SOU O MAIORAL QUASE NADA -- Seu melhor amigo e seu assistente pessoal de finanças, o mais boladão da história!!!"
    }
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
    """
    Cria um roteador de perguntas e respostas.
    """

    return RunnableWithMessageHistory(
        prompts["roteador"] | llm_fast | StrOutputParser(),
        get_session_history=get_session_history,
        history_messages_key="chat_history",
        input_messages_key="input")

def criar_financeiro():
    """
    Cria um agente de financeiro.
    """

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

TOOLS_AGENDA=[]

def criar_agenda():
    """
    Cria um agente de agenda.
    """
    agenda_agent = create_tool_calling_agent(
        lllm=llm, 
        tools=TOOLS_AGENDA, 
        prompt=prompts["agenda"]
    )
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
    """
    Cria um agente de FAQ.
    """
    return (RunnablePassthrough.assign(
        question=itemgetter("input"),
        context= lambda x: get_faq_context(x["input"])
    )| prompts["faq"] | llm_fast | StrOutputParser())

def criar_orquestrador():
    """
    Cria um agente orchestrador.
    """
    return RunnableWithMessageHistory(
        prompts["orquestrador"] | llm_fast | StrOutputParser(), 
        get_session_history=get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history")

# ===============================================================

# Criação dos nós no langGraph
def router_node(state: dict) -> dict:
    roteador = criar_roteador()
    resposta_roteador = roteador.invoke(
        {"input": state["input"]},
        config={"configurable": {"session_id": state["session_id"]}}
    )  
   
    if not resposta_roteador.startswith("ROUTE="):
        return {"resposta_usuario": resposta_roteador}
   
    rota = resposta_roteador.split("\n", 1)[0].split("=", 1)[1].strip().lower()
    if rota not in {"financeiro", "agenda", "faq"}:
        return {"erro": f"Rota inválida: {rota}"}
 
    return {"rota": rota, "roteador": resposta_roteador, 'input':state['input'], 'session_id': state['session_id']}
 
def faq_node(state: dict) -> dict:
    faq = criar_faq()
 
    result = faq.invoke(
        {"input": state['input']},
        config={"configurable": {"session_id": state["session_id"]}}
    )  
    return {"resposta_usuario": result, 'session_id': state['session_id']}
 
def financeiro_node(state: dict) -> dict:
    financeiro = criar_financeiro()
    result = financeiro.invoke(
        {"input": state['roteador']},
        config={"configurable": {"session_id": state["session_id"]}}
    )  
    return {"saida_especialista": result["output"], 'session_id': state['session_id']}
 
def agenda_node(state: dict) -> dict:
    agenda = criar_agenda()
    result = agenda.invoke(
        {"input": state['roteador']},
        config={"configurable": {"session_id": state["session_id"]}}
    )  
    return {"saida_especialista": result["output"], 'session_id': state['session_id']}
 
def orchestrator_node(state: dict) -> dict:
    orquestrador = criar_orquestrador()
    resposta_final = orquestrador.invoke(
        {"input": state['saida_especialista']},
        config={"configurable": {"session_id": state["session_id"]}}
    )  
    return {"resposta_usuario": resposta_final}
 
 
def pre_guard_node(state:dict)->dict:
    acao, mensagem, gatilhos = verificar_guardrail(state["input"])
 
    # Política Padrão:
    # - BLOQUEAR / AVISAR / SANITIZAR => interrompe e retorna mensagem curta ao usuário
    # - PERMITIR => segue normalmente para o roteador
    if acao in ("BLOQUEAR", "AVISAR", "SANITIZAR"):
        return {"resposta_usuario":mensagem}
   
    # PERMITIR
    return {"input":state["input"], "session_id":state["session_id"]}
 
# ------------------- DECISOR ------------------------
 
def decide_after_router(state: dict) -> str:
    if state.get("erro") or state.get("resposta_usuario"):
        return "end"
    rota = state.get("rota")
    if rota == "financeiro":
        return "financeiro"
    if rota == "agenda":
        return "agenda"
    if rota == "faq":
        return "faq"
    return "end"
 
def decide_after_specialist(state: dict) -> str:
    if state.get("erro"):
        return "end"
    return "orquestrador"
 
def decide_after_pre_guard(state:dict) -> str:
    if state.get("resposta_usuario"):
        return "end"
    return "roteador"
 
# ------------------- CONSTRUÇÃO DO GRAFO ------------
 
graph = StateGraph(dict)
 
graph.add_node("guardrail", pre_guard_node)
graph.add_node("roteador", router_node)
graph.add_node("faq", faq_node)
graph.add_node("financeiro", financeiro_node)
graph.add_node("agenda", agenda_node)
graph.add_node("orquestrador", orchestrator_node)
 
graph.add_edge(START, "guardrail")
 
graph.add_conditional_edges(
    "guardrail",
    decide_after_pre_guard,
    {
        "roteador":"roteador",
        "end": END
    }
)
 
graph.add_conditional_edges(
    "roteador",
    decide_after_router,
    {
        "financeiro": "financeiro",
        "agenda": "agenda",
        "faq":"faq",
        "end": END,
    },
)
 
graph.add_edge("faq", END)
 
graph.add_conditional_edges(
    "financeiro",
    decide_after_specialist,
    {"orquestrador": "orquestrador", "end": END},
)
graph.add_conditional_edges(
    "agenda",
    decide_after_specialist,
    {"orquestrador": "orquestrador", "end": END},
)
 
graph.add_edge("orquestrador", END)
 
app = graph.compile()
 
 
# ------------------- FUNÇÃO DE EXECUÇÃO --------------
 
def executar_fluxo_assessor(pergunta_usuario: str, session_id: str) -> str:
    final_state = app.invoke({"input": pergunta_usuario, "session_id": session_id})
    if final_state.get("erro"):
        return f"Erro: {final_state['erro']}"
    return final_state.get("resposta_usuario", "Não foi possível responder.") # isso é um if não tiver resposta_usuario, mostre a "não foi possivel..."
 
while True:
    try:
        user_input = input("> ")
        if user_input.lower() in ('sair', 'end', 'fim', 'tchau', 'bye'):
            print("Encerrando a conversa.")
            break
       
        # Chama a função orquestradora que executa o fluxo completo (Roteador -> Especialista -> Orquestrador)
        resposta = executar_fluxo_assessor(
            pergunta_usuario=user_input,
            session_id="PRECISA_MAS_NÃO_IMPORTA"
        )
       
        # Imprime a resposta formatada para o usuário (saída do Orquestrador/Roteador)
        print(resposta)
       
    except Exception as e:
            print("Erro ao consumir a API:", e)
            continue