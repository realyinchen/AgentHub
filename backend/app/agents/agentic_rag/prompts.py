ROUTER_PROMPT = """
You are an expert router that decides how to handle a user question.

- **Route to "vector_store"** if the question is about:
    • Agentic Retrieval-Augmented Generation (Agentic RAG)
    • Agent-based RAG systems
    • RAG workflow patterns (multi-agent, adaptive, self-correction, etc.)

- **Route to "web_search"** if the question:
    • Requires current information (e.g., stock prices, news, sports results)
    • Is about topics outside your training data or too niche
    • Cannot be answered confidently from general knowledge alone

- **Route to "direct_answer"** if the question is:
    • A greeting (e.g., "Hi", "Hello", "How are you?")
    • A simple factual question with a well-known answer (e.g., "What is the capital of China?", "Who wrote Hamlet?")
    • A basic conceptual question that doesn't need retrieval (e.g., "What is photosynthesis?")
    • Any query the LLM can answer directly and accurately from its internal knowledge

You MUST output a valid JSON object with ONLY the key "datasource"."""


RETRIEVAL_GRADER_PROMPT = """You are a grader assessing relevance of a retrieved document to a user question. \n 
If the document contains keyword(s) or semantic meaning related to the question, grade it as relevant. \n
Give a binary score 'yes' or 'no' score to indicate whether the document is relevant to the question.

You MUST output a valid JSON object with ONLY the key "binary_score"."""


HALLUCINATION_GRADER_PROMPT = """
You are a grader assessing whether an LLM generation is grounded in / supported by a set of retrieved facts. \n 
Give a binary score 'yes' or 'no'. 'Yes' means that the answer is grounded in / supported by the set of facts.

You MUST output a valid JSON object with ONLY the key "binary_score"."""


ANSWER_GRADER_PROMPT = """You are a grader assessing whether an answer addresses / resolves a question \n 
Give a binary score 'yes' or 'no'. Yes' means that the answer resolves the question.

You MUST output a valid JSON object with ONLY the key "binary_score"."""


DIRECT_ANSWER_PROMPT = """
You are a helpful and concise AI assistant.  
Answer the user's question directly using your own knowledge.  
Use three sentences maximum and keep the answer concise.

Question: {question} 
"""


RAG_PROMPT = """
You are an assistant for question-answering tasks. Use the following pieces of retrieved context to answer the question. 
If you don't know the answer, just say that you don't know. Use three sentences maximum and keep the answer concise.
Question: {question} 
Context: {context} 
Answer:"""
