import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from dotenv import load_dotenv
 
load_dotenv()
 
def get_faq_context(input: str):
    """
    Busca contexto relevante no PDF de FAQ
    """
    response = ""
    loader = PyPDFLoader('FAQ_assessor_v1.pdf')
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=200)
    parts = splitter.split_documents(docs)
    # print(parts)
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=os.getenv('GEMINI_API_KEY'))
    db = FAISS.from_documents(parts, embeddings)
    result = db.similarity_search(input, 4)
    for doc in result:
        response += doc.page_content + "\n"
    
    return response

 