from dotenv import load_dotenv
import os
import google.generativeai as genai
load_dotenv()

def question_model(question: str) -> str:
    genai.api_key = os.getenv("GENAI_API_KEY")
    genai.configure(
        api_key=genai.api_key
    )

    llm = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config=genai.types.GenerationConfig(
            temperature=0.7,
            top_p=0.95
        )
    )
    try:
        return llm.generate_content(question).text
    except Exception as e:
        print(e)
        return None


print(question_model("Eiii....!!! Como que eu faço um pão com ovo?"))