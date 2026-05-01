import asyncio

# E-posta gönderim kuyruğu — draft_id (str) öğeleri içerir
email_queue: asyncio.Queue[str] = asyncio.Queue()

# Doküman indeksleme kuyruğu — document_id (str) öğeleri içerir
index_queue: asyncio.Queue[str] = asyncio.Queue()

# Gelen e-posta analiz kuyruğu — incoming_email_id (str)
incoming_analysis_queue: asyncio.Queue[str] = asyncio.Queue()

# Gelen e-posta yanıt gönderim kuyruğu — incoming_email_id (str)
incoming_reply_queue: asyncio.Queue[str] = asyncio.Queue()
