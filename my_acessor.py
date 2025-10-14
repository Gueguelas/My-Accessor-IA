from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    HumanMessagePromptTemplate,
    AIMessagePromptTemplate
    )
from langchain_core.prompts import FewShotChatMessagePromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv
import os
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain.memory import ChatMessageHistory
from langchain.agents import create_tool_calling_agent, AgentExecutor
from pg_tools import TOOLS
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
today = datetime.now(TZ).strftime("%d/%m/%Y")

from dotenv import load_dotenv
import os

load_dotenv()

store = {}

## ================================
## SESSION HISTORY
## ================================
def get_session_history(session_id:int) -> ChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id] 

#  ================= LLM =================
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.7,
    top_p=0.95,
    google_api_key=os.getenv("GEMINI_API_KEY")
)

llm_fast = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    google_api_key=os.getenv("GEMINI_API_KEY")
)

# prompt do agente roteador
with open ("prompt_roteador.txt", "r",encoding="utf-8") as f:
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
    {
        "human": "Qual email do suporte?",
        "ai": "ROUTE=faq\nPERGUNTA_ORIGINAL=Qual email do suporte?\nPERSONA={PERSONA_SISTEMA}\nCLARIFY="
    }
]

fewshots_roteador = FewShotChatMessagePromptTemplate(
    examples=shots_roteador,
    example_prompt=example_prompt_base
)

# -------------------- PROMPTS ESPECIALISTAS --------------------
# prompt do agente financeiro
with open ("prompt_financeiro.txt", "r",encoding="utf-8") as f:
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

############################
# prompt do agente de agenda
with open ("prompt_agenda.txt", "r",encoding="utf-8") as f:
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
    }
]

fewshots_agenda = FewShotChatMessagePromptTemplate(
    examples=shots_agenda,
    example_prompt=example_prompt_base,
)

### Agente orquestrador ####
with open ("prompt_orquestrador.txt", "r",encoding="utf-8") as f:
    system_prompt_orquestrador = f.read()

shots_orquestrador = [
    # 1) Financeiro — consultar
    {
        "human": """ESPECIALISTA_JSON:\n{{"dominio":"financeiro","intencao":"consultar","resposta":"Você gastou R$ 842,75 com 'comida' no mês passado.","recomendacao":"Quer detalhar por estabelecimento?","janela_tempo":{{"de":"2025-08-01","ate":"2025-08-31","rotulo":"mês passado (ago/2025)"}}}}""",
        "ai": "Você gastou R$ 842,75 com 'comida' no mês passado.\n- *Recomendação*:\nQuer detalhar por estabelecimento?"
    },

    # 2) Financeiro — falta dado → esclarecer
    {
        "human": """ESPECIALISTA_JSON:\n{{"dominio":"financeiro","intencao":"resumo","resposta":"Preciso do período para seguir.","recomendacao":"","esclarecer":"Qual período considerar (ex.: hoje, esta semana, mês passado)?"}}""",
        "ai": """Preciso do período para seguir.\n- *Acompanhamento* (opcional):\nQual período considerar (ex.: hoje, esta semana, mês passado)?"""
    },

    # 3) Agenda — criar
    {
        "human": """ESPECIALISTA_JSON:\n{{"dominio":"agenda","intencao":"criar","resposta":"Posso criar 'Reunião com João' amanhã 09:00–10:00.","recomendacao":"Confirmo o envio do convite?","janela_tempo":{{"de":"2025-09-29T09:00","ate":"2025-09-29T10:00","rotulo":"amanhã 09:00–10:00"}},"evento":{{"titulo":"Reunião com João","data":"2025-09-29","inicio":"09:00","fim":"10:00","local":"online"}}}}""",
        "ai": """Posso criar 'Reunião com João' amanhã 09:00–10:00.\n- *Recomendação*:\nConfirmo o envio do convite?"""
    },
]

fewshots_orquestrador = FewShotChatMessagePromptTemplate(
    examples=shots_orquestrador,
    example_prompt=example_prompt_base,
)


## ================================
## PROMPTS
## ================================

prompt_orchestrator = ChatPromptTemplate.from_messages([
    system_prompt_orquestrador,                          # system prompt
    fewshots_orquestrador,                               # Shots human/ai 
    MessagesPlaceholder("chat_history"),                 # memória
    ("human", "{input}"),                                # user prompt
])

prompt_roteador = ChatPromptTemplate.from_messages([
    system_prompt_roteador,                          # system prompt
    fewshots_roteador,                               # Shots human/ai 
    MessagesPlaceholder("chat_history"),             # memória
    ("human", "{input}"),                            # user prompt
]).partial(today_local=today.format())

prompt_agenda = ChatPromptTemplate.from_messages([
    system_prompt_agenda,                          # system prompt
    fewshots_agenda,                               # Shots human/ai 
    MessagesPlaceholder("chat_history"),           # memória
    ("human", "{input}"),                          # user prompt
    MessagesPlaceholder("agent_scratchpad"),
    #A possibilidade do agente mudar o prompt do jeito que ele precisar para melhorar sua capacidade
]).partial(today_local=today.format())

prompt_financeiro = ChatPromptTemplate.from_messages([
    system_prompt_financeiro,                          # system prompt
    fewshots_financeiro,                               # Shots human/ai 
    MessagesPlaceholder("chat_history"),               # memória
    ("human", "{input}"),                              # user prompt
    MessagesPlaceholder("agent_scratchpad"),
    #A possibilidade do agente mudar o prompt do jeito que ele precisar para melhorar sua capacidade
]).partial(today_local=today.format())

## ================================
## AGENTS
## ================================


## FINANCEIRO

financeiro_agente = create_tool_calling_agent(
    # Conceito de alterar a o prompt, vc joga o cerebro, as ferramentas e o prompt e da a possibilidade de alterar
    llm,
    TOOLS,
    prompt_financeiro
)
financeiro_executor_base = AgentExecutor( # Isso é a chain -> uma pipeline 
    agent=financeiro_agente,
    tools=TOOLS,
    verbose=False,
    return_intermediate_steps=True
)

financeiro_executor = RunnableWithMessageHistory(
    # Agora sim o objeto rodável do agente, com histórico
    financeiro_executor_base, # CHAIN
    get_session_history=get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history"  
)

## AGENDA

TOOLS_AGENDA=[]

agenda_agente = create_tool_calling_agent( 
    # Conceito de alterar a o prompt, vc joga o cerebro, as ferramentas e o prompt e da a possibilidade de alterar
    llm,
    TOOLS_AGENDA,
    prompt_agenda
)
agenda_executor_base = AgentExecutor( # Isso é a chain -> uma pipeline 
    agent=agenda_agente,
    tools=TOOLS,
    verbose=False,
    return_intermediate_steps=True
)
agenda_executor = RunnableWithMessageHistory( 
    # Agora sim o objeto rodável do agente, com histórico
    agenda_executor_base,  # CHAIN
    get_session_history=get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history"  
)

## ROTEADOR

router_chain = RunnableWithMessageHistory(
    # Agora sim o objeto rodável do agente, com histórico
    prompt_roteador | llm_fast | StrOutputParser(),
    get_session_history=get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history"
)

## ORQUESTRADOR

orchestrator_chain = RunnableWithMessageHistory(
    # Agora sim o objeto rodável do agente, com histórico
    prompt_orchestrator | llm_fast | StrOutputParser(),
    get_session_history=get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history"
)


def executar_fluxo_assesor(pergunta_user:str, session_id="precisa_mas_nao_importa") ->  str:
    response = ''
    response_roteador = router_chain.invoke(
        {"input": pergunta_user},
        config={"configurable": 
                {"session_id": "PRECISA_MAS_NAO_IMPORTA"}}
    )
    if "ROUTE=" not in response_roteador: 
        #Hard code para detectar se ele encaminha para um agente especialista ou nao, caso não ja volta a resposta do roteadot
        response = response_roteador
    
    if "ROUTE=financeiro" in response_roteador:
        #Hard code para detectar se ele encaminha para um agente especialista ou nao, caso não ja volta a resposta do roteadot
        resposta_financeiro = financeiro_executor.invoke(
            {"input": response_roteador},
            config={"configurable": 
                    {"session_id": "PRECISA_MAS_NAO_IMPORTA"}}
        )
        response = orchestrator_chain.invoke(
            #Chamando o orchestrador para uma respostinha cria
            {"input": resposta_financeiro},
            config={"configurable": 
                    {"session_id": "PRECISA_MAS_NAO_IMPORTA"}}
        )
        
    
    if "ROUTE=agenda" in response_roteador:
        #Hard code para detectar se ele encaminha para um agente especialista ou nao, caso não ja volta a resposta do roteadot
        response_agenda = agenda_executor.invoke(
            {"input": response_roteador},
            config={"configurable": 
                    {"session_id": "PRECISA_MAS_NAO_IMPORTA"}}
        )

        response = orchestrator_chain.invoke(
            #Chamando o orchestrador para uma respostinha cria
            {"input": response_agenda},
            config={"configurable": 
                    {"session_id": "PRECISA_MAS_NAO_IMPORTA"}}
        )
    
    return response


while True:
    user_input = input("> ")
    if user_input.lower() in ["sair", "end", "fim", "tchau", "bye"]:
        print("Encerrando a conversa.")
        break
    try:
        response = executar_fluxo_assesor(
            pergunta_user=user_input,
            session_id="precisa_mas_nao_importa"
        )
        print(response)
    except Exception as e:
        print(f"Erro ao consumir a API: {e}")


