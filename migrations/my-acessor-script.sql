CREATE TABLE IF NOT EXISTS categories (
  id           SERIAL PRIMARY KEY,
  name         VARCHAR(64) NOT NULL,             
  description  TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()                        
);

CREATE TABLE IF NOT EXISTS transaction_types (
  id      serial PRIMARY KEY,
  type    TEXT NOT NULL                                        
);

CREATE TABLE IF NOT EXISTS transactions (
  id             BIGSERIAL PRIMARY KEY,
  amount         NUMERIC(14,2) NOT NULL , 	
  type           INT REFERENCES transaction_types(id) NOT NULL DEFAULT 2,          
  category_id    INT REFERENCES categories(id) ON DELETE SET NULL,
  description    TEXT,                                                
  payment_method VARCHAR(32),                                         
  occurred_at    TIMESTAMPTZ NOT NULL,                                
  source_text    TEXT NOT NULL                                        
);

-- Índices úteis para consultas comuns
CREATE INDEX IF NOT EXISTS idx_transactions_occurred_at
  ON transactions (occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_category_time
  ON transactions (category_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_localday
  ON transactions ( ((occurred_at AT TIME ZONE 'America/Sao_Paulo')::date) );

CREATE TABLE IF NOT EXISTS events (
  id           BIGSERIAL PRIMARY KEY,
  title        TEXT NOT NULL,                                          
  start_time   TIMESTAMPTZ NOT NULL,                                   
  end_time     TIMESTAMPTZ,                                            
  location     TEXT,
  notes        TEXT,
  recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),                     
  source_text  TEXT NOT NULL                                           
);

CREATE INDEX IF NOT EXISTS idx_events_start_time
  ON events (start_time DESC);

INSERT INTO transaction_types (type) VALUES
  ('INCOME'),
  ('EXPENSES'),
  ('TRANSFER');

INSERT INTO categories (name) VALUES
  ('comida'),
  ('besteira'),
  ('estudo'),
  ('férias'),
  ('transporte'),
  ('moradia'),
  ('saúde'),
  ('lazer'),
  ('contas'),
  ('investimento'),
  ('presente'),
  ('outros');
