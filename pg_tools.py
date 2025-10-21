import os
from dotenv import load_dotenv
import psycopg2
from typing import Optional, List
from langchain.tools import tool
from pydantic import BaseModel,Field

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL_ESCOLA")  

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


class UpdateTransactionArgs(BaseModel):
    id: Optional[int] = Field(
        default=None,
        description="ID da transação a atualizar. Se ausente, será feita uma busca por (match_text + date_local)."
    )
    match_text: Optional[str] = Field(
        default=None,
        description="Texto para localizar transação quando id não for informado (busca em source_text/description)."
    )
    date_local: Optional[str] = Field(
        default=None,
        description="Data local (YYYY-MM-DD) em America/Sao_Paulo; usado em conjunto com match_text quando id ausente."
    )
    amount: Optional[float] = Field(default=None, description="Novo valor.")
    type_id: Optional[int] = Field(default=None, description="Novo type_id (1/2/3).")
    type_name: Optional[str] = Field(default=None, description="Novo type_name: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="Nova categoria (id).")
    category_name: Optional[str] = Field(default=None, description="Nova categoria (nome).")
    description: Optional[str] = Field(default=None, description="Nova descrição.")
    payment_method: Optional[str] = Field(default=None, description="Novo meio de pagamento.")
    occurred_at: Optional[str] = Field(default=None, description="Novo timestamp ISO 8601.")

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
                    (amount, type, category_id, category_name, description, payment_method, occurred_at, source_text)
                VALUES
                    (%s, %s, %s, %s ,%s, %s, %s::timestamptz, %s)
                RETURNING id, occurred_at;
                """,
                (amount, resolved_type_id, category_id, category_name, description, payment_method, occurred_at, source_text),
            )
        else:
            cur.execute(
                """
                INSERT INTO transactions
                    (amount, type, category_id, category_name ,description, payment_method, occurred_at, source_text)
                VALUES
                    (%s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id, occurred_at;
                """,
                (amount, resolved_type_id, category_id, category_name ,description, payment_method, source_text),
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
     - Fazer com que ele sempre diga: O que gastou - qual foi o motivo - valor gasto.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        fil = ""
        params = []

        if text:
            if fil: 
                fil += " and "
            fil += "(source_text LIKE %s OR description LIKE %s)"
            like_pattern = f"%{text}%"
            params.append(like_pattern)
            params.append(like_pattern)
        resolved_type_id = _resolve_type_id(cur, None, type_name)

        if resolved_type_id:
            if fil: 
                fil += " and "
            fil += '"type" = %s'
            params.append(resolved_type_id)

        if date_local:
            if fil: 
                fil += " and "
            fil += "(occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s"
            params.append(date_local)

        if date_from_local and date_to_local:
            if fil: 
                fil += " and "
            fil += "(occurred_at AT TIME ZONE 'America/Sao_Paulo')::date between %s and %s"
            params.extend([date_from_local, date_to_local])
        elif date_from_local:
            if fil: 
                fil += " and "
            fil += "(occurred_at AT TIME ZONE 'America/Sao_Paulo')::date >= %s"
            params.append(date_from_local)
        elif date_to_local:
            if fil: 
                fil += " and "
            fil += "(occurred_at AT TIME ZONE 'America/Sao_Paulo')::date <= %s"
            params.append(date_to_local)

        where_clause = fil if fil else "1=1"
        order_clause = "ASC" if date_from_local and date_to_local else "DESC"

        query = f"""
            select 
                id, 
                amount, 
                type,
                category_id,
                description,
                payment_method,
                occurred_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo',
                source_text
            from transactions
            where {where_clause}
            order by occurred_at {order_clause}
            limit %s;
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

def _local_date_filter_sql(field: str = "occurred_at") -> str:
    """
    Retorna um trecho SQL para filtragem por dia local em America/Sao_Paulo.
    Ex.: (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s::date
    """
    return f"(({field} AT TIME ZONE 'America/Sao_Paulo')::date = %s::date)"

@tool("total_balance") 
def total_balance() -> dict:
    """Retorna o saldo total (INCOME - EXPENSES) das transações."""
    conn = get_conn()
    cur = conn.cursor()
    query = """
            with balance as(
                select
                    sum(case when t.type = 1 then t.amount else 0 end) as income,
                    sum(case when t.type = 2 then t.amount else 0 end) as expense
                from transactions t
            ) select
                income,
                expense,
                income - expense as balance
            from balance
            """
    try:
        cur.execute(query)
        row = cur.fetchone()
        total_income, total_expenses, balance = row
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
    query = """
            with balance as(
                select
                    sum(case when t.type = 1 then t.amount else 0 end) as income,
                    sum(case when t.type = 2 then t.amount else 0 end) as expense
                from transactions t
                where (t.occurred_at at time zone 'UTC' at time zone 'America/Sao_Paulo')::date = %s;
            ) select
                income,
                expense,
                income - expense as balance
            from balance
        """
    try:
        cur.execute(query, (date_local,))
        row = cur.fetchone()
        total_income, total_expenses , balance= row
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

@tool("biggest_expenses")
def biggest_expenses(limit:Optional[int] = 5) -> dict:
    """
        Retorna as maiores despesas (EXPENSES) registradas de todas as transactions, limitado pelo parâmetro 'limit'.
        - mostrar: o quanto foi gasto - motivo - data - descrição
        - Da um resumo do que foi gasto e de como melhorar isso
        - Faz uma piada sobre essas despesas 
    """
    conn = get_conn()
    cur = conn.cursor()
    query = """
            select 
                t.id, 
                t.amount, 
                t.description, 
                t.occurred_at at time zone 'UTC' at time zone 'America/Sao_Paulo',
                t.source_text
            from transactions t
            where type = 2
            order by t.amount desc
            limit %s;
        """
    #type 2 é despesa
    try:
        cur.execute(query, (limit,))
        rows = cur.fetchall()
        expenses = []
        for row in rows:
            (tid, amount, description, occurred_local, source_text) = row
            expenses.append({
                "id": tid,
                "amount": float(amount),
                "description": description,
                "occurred_at_local": occurred_local.isoformat(),
                "source_text": source_text
            })
        return {"status": "ok", "expenses": expenses}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

@tool("update_transaction", args_schema=UpdateTransactionArgs)
def update_transaction(
    id: Optional[int] = None,
    match_text: Optional[str] = None,
    date_local: Optional[str] = None,
    amount: Optional[float] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> dict:
    """
    Atualiza uma transação existente.
    Estratégias:
      - Se 'id' for informado: atualiza diretamente por ID.
      - Caso contrário: localiza a transação mais recente que combine (match_text em source_text/description)
        E (date_local em America/Sao_Paulo), então atualiza.
    Retorna: status, rows_affected, id, e o registro atualizado.
    """
    if not any([amount, type_id, type_name, category_id, category_name, description, payment_method, occurred_at]):
        return {"status": "error", "message": "Nada para atualizar: forneça pelo menos um campo (amount, type, category, description, payment_method, occurred_at)."}

    conn = get_conn()
    cur = conn.cursor()
    try:
        # Resolve target_id
        target_id = id
        if target_id is None:
            if not match_text or not date_local:
                return {"status": "error", "message": "Sem 'id': informe match_text E date_local para localizar o registro."}

            # Buscar o mais recente no dia local informado que combine o texto
            cur.execute(
                f"""
                SELECT t.id
                FROM transactions t
                WHERE (t.source_text ILIKE %s OR t.description ILIKE %s)
                  AND {_local_date_filter_sql("t.occurred_at")}
                ORDER BY t.occurred_at DESC
                LIMIT 1;
                """,
                (f"%{match_text}%", f"%{match_text}%", date_local)
            )
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "Nenhuma transação encontrada para os filtros fornecidos."}
            target_id = row[0]

        # Resolver type_id / category_id a partir de nomes, se fornecidos
        resolved_type_id = _resolve_type_id(cur, type_id, type_name) if (type_id or type_name) else None
        resolved_category_id = category_id
        if category_name and not category_id:
            resolved_category_id = _get_category_id(cur, category_name)

        # Montar SET dinâmico
        sets = []
        params: List[object] = []
        if amount is not None:
            sets.append("amount = %s")
            params.append(amount)
        if resolved_type_id is not None:
            sets.append("type = %s")
            params.append(resolved_type_id)
        if resolved_category_id is not None:
            sets.append("category_id = %s")
            params.append(resolved_category_id)
        if description is not None:
            sets.append("description = %s")
            params.append(description)
        if payment_method is not None:
            sets.append("payment_method = %s")
            params.append(payment_method)
        if occurred_at is not None:
            sets.append("occurred_at = %s::timestamptz")
            params.append(occurred_at)

        if not sets:
            return {"status": "error", "message": "Nenhum campo válido para atualizar."}

        params.append(target_id)

        cur.execute(
            f"UPDATE transactions SET {', '.join(sets)} WHERE id = %s;",
            params
        )
        rows_affected = cur.rowcount
        conn.commit()

        # Retornar o registro atualizado
        cur.execute(
            """
            SELECT
              t.id, t.occurred_at, t.amount, tt.type AS type_name,
              c.name AS category_name, t.description, t.payment_method, t.source_text
            FROM transactions t
            JOIN transaction_types tt ON tt.id = t.type
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = %s;
            """,
            (target_id,)
        )
        r = cur.fetchone()
        updated = None
        if r:
            updated = {
                "id": r[0],
                "occurred_at": str(r[1]),
                "amount": float(r[2]),
                "type": r[3],
                "category": r[4],
                "description": r[5],
                "payment_method": r[6],
                "source_text": r[7],
            }

        return {
            "status": "ok",
            "rows_affected": rows_affected,
            "id": target_id,
            "updated": updated
        }

    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

# Exporta a lista de tools
TOOLS_FINANCEIRO = [add_transaction,biggest_expenses, query_transactions, total_balance, daily_balance, update_transaction]