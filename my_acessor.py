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


from dotenv import load_dotenv
import os

load_dotenv()


#  ================= LLM =================
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.7,
    top_p=0.95,
    google_api_key=os.getenv("GEMINI_API_KEY")
)

#  ================= HISTORY =================
store = {}
def get_session_history(session_id:int) -> ChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id] 


#  ================= PROMPT =================
## COLOQUE O SEU TXT COM SEU PROPRIO PROMPT, SALVE EM "My-Accessor\prompt_accessor.txt"
## O MEU ESTÁ VERSIONADO COMO EXEMPLO A SEGUIR, MAS É MUITO MELHOR USAR O SEU

with open("My-Accessor\prompt_accessor.txt", "r", encoding="utf-8") as f:
    system_text = f.read()
system_prompt = ("system", system_text)


example_prompt = ChatPromptTemplate.from_messages([
    HumanMessagePromptTemplate.from_template("{human}"),
    AIMessagePromptTemplate.from_template("{ai}")
])


shots = [
    # ================ FEW-SHOTS ================
    # 1) Decisão de compra (finanças)
    {"human": 
    "Recebi R$X.XXXX este mês, já gastei R$X.XXX e tenho R$XX.XXX de dívida no cartão. Posso comprar um celular de R$XX.XXX?",
    "ai":
     "- Sua sobra atual é ~R$600 e há dívida ativa de R$200.\n"
     "- *Recomendação*: \nNão recomendo a compra agora; priorize quitar a dívida e manter reserva mínima para o mês.\n"
    },

    # 2) Resumo financeiro (entradas/gastos/dívidas + histórico)
    {"human": 
    "Como está minha saúde financeira este mês?",
    "ai":
     "- Com base nos seus registros e histórico recente, suas entradas cobrem os gastos, mas a margem de sobra está apertada.\n"
     "- *Recomendação*: \nReduza 10–15% nas despesas variáveis desta semana e reforce a meta de poupança mínima.\n"
    },

    # 3) Agenda e conflitos
    {"human": "Quais compromissos tenho amanhã? Estou livre para marcar uma call às 15h?",
    "ai":
     "- Há duas reuniões agendadas; identifico potencial conflito por proximidade entre 14h e 16h.\n"
     "- *Recomendação*: \nEvite marcar às 15h; melhor janela: 16h30–17h30.\n"
     "- *Acompanhamento*: \nQuer que eu envie convite para 16h30 e ative lembrete por WhatsApp 30 min antes?"
    },

    # 4) Pendências e histórico (tarefas + notificação)
    {"human": "Estou devendo pagar o IPVA e revisar o orçamento; pode me lembrar?",
    "ai":
     "- Encontrei pendências similares no seu histórico deste período.\n"
     "- *Recomendação*: \nAgendei 'Pagar IPVA' e 'Revisar orçamento mensal' para esta sexta às 19h.\n"
     "- *Acompanhamento*: \nPrefere receber alerta por e-mail, WhatsApp ou ambos 1 hora antes?"
    },

    {"human": "Sabe quem eu sou?",
    "ai":
     "Você é o Binomial!!!"
    },
]

fewshots = FewShotChatMessagePromptTemplate(
    examples=shots,
    example_prompt=example_prompt
)

prompt = ChatPromptTemplate.from_messages([
    system_prompt,                          # system prompt
    fewshots,                               # Shots human/ai 
    MessagesPlaceholder("chat_history"),    # memória
    ("human", "{input}")                  # user prompt
    MessagesPlaceholder("agent_scratchpad"),
])


#  ================= CHAIN =================
agent = create_tool_calling_agent(
    llm,
    TOOLS,
    prompt
)

agent_executor = AgentExecutor(
    agent=agent,
    tools=TOOLS,
    prompt=prompt,
    verbose=False
)

chain = RunnableWithMessageHistory(
    agent,
    get_session_history=get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history"
)


while True:
    user_input = input("> ")
    if user_input.lower() in ["sair", "end", "fim", "tchau", "bye"]:
        print("Encerrando a conversa.")
        break
    try:
        response = chain.invoke(
            {"input": user_input},
            config={"configurable": {"session_id": "PRECISA_MAS_NAO_IMPORTA"}}
        )
        print(response)
    except Exception as e:
        print(f"Erro ao consumir a API: {e}")


