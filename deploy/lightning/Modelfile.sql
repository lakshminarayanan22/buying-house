# Registers the fine-tuned SQL writer with Ollama:
#   ollama create ecolink-xiyan-sql -f Modelfile.sql
# Then point the app at it — no code change, the model is already a setting:
#   OLLAMA_SQL_MODEL=ecolink-xiyan-sql
#
# The name matters. uses_xiyan() in app/chat/llm.py decides which prompt layout to send by
# looking for "xiyan" in the model name, and this model was trained on XiYan's template. Call it
# "ecolink-sql" and the app would serve it the generic layout it has never seen.
FROM ./ecolink-xiyan-sql-q4_k_m.gguf

# A query has one right answer, so sampling is not wanted. Matches SQL_TEMPERATURE in the app.
PARAMETER temperature 0.1
PARAMETER num_ctx 16384
