# Ollama HTTP 클라이언트 + 단일 요청 큐 (INFR-03, INFR-05)
# 실제 구현: 01-05-PLAN

class OllamaRunner:
    def __init__(self, model: str = 'gemma4:26b'):
        raise NotImplementedError('01-05-PLAN에서 구현 예정')

    async def start(self):
        raise NotImplementedError

    async def stop(self):
        raise NotImplementedError

    async def generate(self, prompt: str) -> str:
        raise NotImplementedError
