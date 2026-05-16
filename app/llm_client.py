import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3"

def explain_document_with_chunks(chunks: list[str], question: str) -> str:
    """
    Usa o modelo llama3 local via Ollama para gerar uma explicação breve do documento,
    usando apenas os 4 chunks mais similares e a pergunta do usuário.
    """
    # Monta o contexto para a IA
    context = "\n\n".join(f"Chunk {i+1}: {chunk}" for i, chunk in enumerate(chunks))
    prompt = (
        "Você é um assistente que explica documentos. "
        "Com base APENAS nos trechos abaixo, responda de forma breve e objetiva: "
        f'"{question}"\n'
        "Se não for possível responder com base nesses trechos, diga explicitamente que não há informação suficiente. "
        "Não invente nada, não faça suposições.\n"
        f"Trechos:\n{context}"
    )
    data = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }
    try:
        response = requests.post(OLLAMA_URL, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        # Ollama retorna 'message' ou 'choices', depende da versão
        if "message" in result and "content" in result["message"]:
            return result["message"]["content"].strip()
        elif "choices" in result and result["choices"]:
            return result["choices"][0]["message"]["content"].strip()
        else:
            return "[Erro: resposta inesperada do modelo]"
    except Exception as exc:
        return f"[Erro ao consultar o modelo local: {exc}]"