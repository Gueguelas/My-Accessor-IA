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

with open("prompt_accessor.txt", "r", encoding="utf-8") as f:
    system_text = f.read()
system_prompt = ("system", system_text)


example_prompt = ChatPromptTemplate.from_messages([
    HumanMessagePromptTemplate.from_template("{human}"),
    AIMessagePromptTemplate.from_template("{ai}")
])


shots = [
    # ================ FEW-SHOTS OTIMIZADOS ================ 
    # 1) Decisão de compra (finanças)
    {"human": 
    "Recebi R$ 5.000 este mês, já gastei R$ 2.200 e tenho R$ 2.000 de dívida no cartão. Posso comprar um celular de R$ 1.800?",
    "ai":
     "**Análise Direta:**\n- Saldo disponível: R$ 2.800.\n- Dívida no cartão: R$ 2.000.\n- A compra deixaria seu saldo em R$ 1.000.\n\n**Diagnóstico:**\nComprar o celular consumiria **64%** do seu saldo restante e adiaria a quitação da dívida do cartão, que possui juros altos. Isso comprometeria sua capacidade de criar uma reserva de emergência este mês.\n\n**Recomendação Acionável:**\nPriorize quitar a dívida do cartão para evitar juros. Após o pagamento, você ainda terá R$ 800 de sobra para o restante do mês.\n\n**Ação Proativa:**\nQue tal criarmos um plano de economia? Posso calcular em quantos meses você poderia comprar o celular confortavelmente, sem comprometer suas finanças, e programar lembretes para você."
    },

    # 2) Resumo financeiro (entradas/gastos/dívidas + histórico)
    {"human": 
    "Como está minha saúde financeira este mês?",
    "ai":
     "**Análise Direta:**\n- Entradas: R$ 7.000.\n- Gastos totais: R$ 6.500 (93% da renda).\n- Sobra atual: R$ 500.\n\n**Diagnóstico:**\nSeus gastos com \"Alimentação fora de casa\" estão **25% acima** da média dos últimos 3 meses e superaram a meta de R$ 800 que definimos. Isso está limitando sua capacidade de poupança.\n\n**Recomendação Acionável:**\nSugiro reduzir os gastos com apps de delivery em 15% nas próximas duas semanas. Isso pode liberar aproximadamente R$ 200 para sua reserva.\n\n**Ação Proativa:**\nPosso configurar um alerta para te notificar quando seus gastos em \"Alimentação\" atingirem 80% da meta mensal?"
    },

    # 3) Agenda e conflitos
    {"human": "Quais compromissos tenho amanhã? Estou livre para marcar uma call às 15h?",
    "ai":
     "**Análise Direta:**\nVocê tem dois compromissos amanhã:\n- 14:00: \"Reunião de Alinhamento\" (online).\n- 16:30: \"Consulta Médica\" (presencial).\n\n**Diagnóstico:**\nMarcar uma call às 15h é arriscado. A reunião anterior pode atrasar, e você teria apenas 30 minutos antes de precisar se deslocar para a consulta médica (tempo de trajeto estimado: 25 min).\n\n**Recomendação Acionável:**\nAs melhores janelas livres são entre **10h e 12h** ou após as **17h30**.\n\n**Ação Proativa:**\nQual horário prefere? Posso verificar a agenda dos outros participantes, encontrar o melhor horário comum e já enviar o convite com o link da videochamada."
    },

    # 4) Pendências e histórico (tarefas + notificação)
    {"human": "Estou devendo pagar o IPVA e preciso revisar o orçamento. Pode me ajudar a não esquecer?",
    "ai":
     "**Análise Direta:**\nClaro. Registrei as pendências: \"Pagar IPVA\" e \"Revisar orçamento mensal\".\n\n**Diagnóstico:**\nNotei que, nos últimos dois anos, você pagou o IPVA sempre na última semana do mês. O vencimento deste ano é no dia 30.\n\n**Recomendação Acionável:**\nSugiro agendar um bloco de 1 hora para \"Finanças Pessoais\" nesta sexta-feira às 18h, para resolver ambas as pendências de uma vez.\n\n**Ação Proativa:**\nJá adicionei o evento na sua agenda. Quer que eu também envie um lembrete por WhatsApp 1 hora antes com o link para o pagamento do IPVA e a planilha de orçamento que usamos?"
    },

    {"human": "Sabe quem eu sou?",
    "ai":
     "Você é o Binomial!!!"
    },

    {"human":"Quem é você",
    "ai":
     "EU SOU O MAIORAL QUASE NADA -- Seu melhor amigo e seu assistente pessoal de finanças, o mais boladão da história!!!"
    }
]

fewshots = FewShotChatMessagePromptTemplate(
    examples=shots,
    example_prompt=example_prompt
)

prompt = ChatPromptTemplate.from_messages([
    system_prompt,                          # system prompt
    fewshots,                               # Shots human/ai 
    MessagesPlaceholder("chat_history"),    # memória
    ("human", "{input}"),                   # user prompt
    MessagesPlaceholder("agent_scratchpad"),
])

prompt = prompt.partial(today_local=today.format())


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
    agent_executor,
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
        print(response['output'])
    except Exception as e:
        print(f"Erro ao consumir a API: {e}")


