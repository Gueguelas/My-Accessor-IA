import os
from dotenv import load_dotenv
import psycopg2
from typing import Optional
from langchain.tools import tool
from pydantic import BaseModel,Field

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL_CASA")  # ou DATABASE_URL_ESCOLA, conforme o ambiente

def get_conn():
    return psycopg2.connect(DATABASE_URL)

# Essa classe garante que o objeto de Python passe todos esses campos
class AddTransactionArgs(BaseModel):
    amount: float = Field(..., description="Valor da transação (use positivo).")
    source_text: str = Field(..., description="Texto original do usuário.")
    occurred_at: Optional[str] = Field(
        default=None,
        description="Timestamp ISO 8601; se ausente, usa NOW() no banco."
    )
    category_name: Optional[str] = Field(default=None, description="Nome da categoria (opcional).""Caso não seja informado, coloque a que mais se enquadra, entre comida, besteira, estudo, transporte, lazer, constas, investimento, outros")
    type_id: Optional[int] = Field(default=None, description="ID em transaction_types (1=INCOME, 2=EXPENSES, 3=TRANSFER).")
    type_name: Optional[str] = Field(default=None, description="Nome do tipo: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="FK de categories (opcional).")
    description: Optional[str] = Field(default=None, description="Descrição (opcional).")
    payment_method: Optional[str] = Field(default=None, description="Forma de pagamento (opcional).")

class QueryTransactionsArgs(BaseModel):
    text: Optional[str] = Field(default=None, description="texto com contexto para buscar em source_text ou description (opcional).")
    type_name: Optional[str] = Field(default=None, description="Nome do tipo: INCOME | EXPENSES | TRANSFER (opcional).")
    date_local: Optional[str] = Field(default=None, description="Data local (YYYY-MM-DD) para filtrar (opcional).")
    date_from_local: Optional[str] = Field(default=None, description="Data local inicial (YYYY-MM-DD) para filtrar (opcional).")
    date_to_local: Optional[str] = Field(default=None, description="Data local final (YYYY-MM-DD) para filtrar (opcional).")
    limit: int = Field(default=20, description="Número máximo de transações a retornar.")

#Garante que o campo type da tabela transactions receba um id válido (1=INCOME, 2=EXPENSES, 3=TRANSFER)
    

TYPE_ALIASES = {
    "INCOME": "INCOME",
    "ENTRADA": "INCOME",
    "RECEITA": "INCOME",
    "SALÁRIO": "INCOME",
    "SALARY": "INCOME",
    "EXPENSE": "EXPENSES",
    "DESPESA": "EXPENSES",
    "DESPESAS": "EXPENSES",
    "TRANSFER": "TRANSFER",
    "TRANSFERENCIA":"TRANSFER",
    "CAIU":"INCOME",
    "SAIU":"EXPENSES"
}
def _resolve_type_id(cur, type_id: Optional[int], type_name: Optional[str]) -> Optional[int]:
    if type_name:
        t = type_name.strip().upper()
        if t in TYPE_ALIASES:
            t = TYPE_ALIASES[t]
        cur.execute("SELECT id FROM transaction_types WHERE UPPER(type)=%s LIMIT 1;", (t,))
        row = cur.fetchone()
        return row[0] if row else None
    if type_id:
        return int(type_id)
    return 2

def _get_category_id(cur, category_name: Optional[str]) -> Optional[int]:
    if not category_name:
        return None
    cur.execute("SELECT id FROM categories WHERE name=%s LIMIT 1;", (category_name,))
    row = cur.fetchone()
    return row[0] if row else None 

# Tool: add_transaction
@tool("add_transaction", args_schema=AddTransactionArgs)
def add_transaction(
    amount: float,
    source_text: str,
    occurred_at: Optional[str] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
) -> dict:
    """Insere uma transação financeira no banco de dados Postgres.""" # docstring obrigatório da @tools do langchain (estranho, mas legal né?)
    conn = get_conn()
    cur = conn.cursor()
    try:
        resolved_type_id = _resolve_type_id(cur, type_id, type_name)
        if not resolved_type_id:
            return {"status": "error", "message": "Tipo inválido (use type_id ou type_name: INCOME/EXPENSES/TRANSFER)."}
        
        if not category_id :
            category_id = _get_category_id(cur, category_name) if not category_id else category_name

        if occurred_at:
            cur.execute(
                """
                INSERT INTO transactions
                    (amount, "type", category_id, description, payment_method, occurred_at, source_text)
                VALUES
                    (%s, %s, %s, %s, %s, %s::timestamptz, %s)
                RETURNING id, occurred_at;
                """,
                (amount, resolved_type_id, category_id, description, payment_method, occurred_at, source_text),
            )
        else:
            cur.execute(
                """
                INSERT INTO transactions
                    (amount, "type", category_id, description, payment_method, occurred_at, source_text)
                VALUES
                    (%s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id, occurred_at;
                """,
                (amount, resolved_type_id, category_id, description, payment_method, source_text),
            )


        new_id, occurred = cur.fetchone()
        conn.commit()
        return {"status": "ok", "id": new_id, "occurred_at": str(occurred)}

    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@tool("query_transactions", args_schema=QueryTransactionsArgs)
def query_transactions(
    text: Optional[str] = None,
    type_name: Optional[str] = None,
    date_local: Optional[str] = None,
    date_from_local: Optional[str] = None,
    date_to_local: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """
    Consulta transações com filtros por texto (source_text/description), tipo e data locais (America/Sao_Paulo).
    Os dados devem vir na seguinte ordem:
     - intervalo(date_from_local, date_to_local) ASC(cronológico)
     - Caso contrário: DESC (mais recentes primeiro).
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        filters = []
        params = []

        if text:
            filters.append("(source_text ILIKE %s OR description ILIKE %s)")
            like_pattern = f"%{text}%"
            params.extend([like_pattern, like_pattern])

        resolved_type_id = _resolve_type_id(cur, None, type_name)
        if resolved_type_id:
            filters.append('"type" = %s')
            params.append(resolved_type_id)

        if date_local:
            filters.append("DATE(occurred_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = %s")
            params.append(date_local)

        if date_from_local and date_to_local:
            filters.append("DATE(occurred_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') BETWEEN %s AND %s")
            params.extend([date_from_local, date_to_local])
        elif date_from_local:
            filters.append("DATE(occurred_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') >= %s")
            params.append(date_from_local)
        elif date_to_local:
            filters.append("DATE(occurred_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') <= %s")
            params.append(date_to_local)

        where_clause = " AND ".join(filters) if filters else "1=1"
        
        order_clause = "ASC" if date_from_local and date_to_local else "DESC"

        query = f"""
            SELECT id, amount, "type", category_id, description, payment_method,
                   occurred_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo' AS occurred_local,
                   source_text
            FROM transactions
            WHERE {where_clause}
            ORDER BY occurred_at {order_clause}
            LIMIT %s;
        """
        params.append(limit)

        cur.execute(query, tuple(params))
        rows = cur.fetchall()

        transactions = []
        for row in rows:
            (tid, amount, ttype, category_id, description, payment_method, occurred_local, source_text) = row
            transactions.append({
                "id": tid,
                "amount": float(amount),
                "type": ttype,
                "category_id": category_id,
                "description": description,
                "payment_method": payment_method,
                "occurred_at_local": occurred_local.isoformat(),
                "source_text": source_text
            })
        return {"status": "ok", "transactions": transactions}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
    
@tool("total_balance") 
def total_balance() -> dict:
    """Retorna o saldo total (INCOME - EXPENSES) das transações."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN t.type = 1 THEN t.amount ELSE 0 END), 0) AS total_income,
                COALESCE(SUM(CASE WHEN t.type = 2 THEN t.amount ELSE 0 END), 0) AS total_expenses
            FROM transactions t;
        """)
        row = cur.fetchone()
        total_income, total_expenses = row
        balance = total_income - total_expenses
        return {
            "status": "ok",
            "total_income": float(total_income),
            "total_expenses": float(total_expenses),
            "balance": float(balance)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

@tool("daily_balance")
def daily_balance(date_local: str) -> dict:
    """Retorna o saldo (INCOME - EXPENSES) das transações para uma data específica (YYYY-MM-DD)."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN t.type = 1 THEN t.amount ELSE 0 END), 0) AS total_income,
                COALESCE(SUM(CASE WHEN t.type = 2 THEN t.amount ELSE 0 END), 0) AS total_expenses
            FROM transactions t
            WHERE DATE(t.occurred_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo') = %s;
        """, (date_local,))
        row = cur.fetchone()
        total_income, total_expenses = row
        balance = total_income - total_expenses
        return {
            "status": "ok",
            "date": date_local,
            "total_income": float(total_income),
            "total_expenses": float(total_expenses),
            "balance": float(balance)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
# Exporta a lista de tools
TOOLS = [add_transaction, query_transactions, total_balance, daily_balance, ]
