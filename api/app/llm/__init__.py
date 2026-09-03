"""Análisis de menciones con LLM (Etapa 2): cliente de Groq, prompt,
modelos de request/response y la orquestación de batching (ver
app/llm/{client,prompts,models,service}.py).

Subpaquete aparte de app/sources/ a propósito: son las dos mitades del
dominio (capturar / analizar) y no comparten código, solo el objeto
`Mention` que produce una y consume la otra en forma de copy_text.
"""
