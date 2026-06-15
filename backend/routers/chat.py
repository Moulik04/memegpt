"""
POST /chat/ — main conversational endpoint, returns Server-Sent Events.

SSE event stream:
  {"type": "thinking", "stage": "analyzing",  "message": "..."}
  {"type": "thinking", "stage": "rendering",  "template_id": "...", "message": "..."}
  {"type": "done",     "conversation_id": "...", "message": {...}, "template_used": "..."}
  {"type": "error",    "message": "..."}
"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from image_processing.compositor import compose_meme
from memory.conversation_store import add_turn, get_recent_templates
from nlp.intent_router import parse_intent
from schemas import ChatMessage, ChatRequest, ChatResponse
from vector_db.chroma_client import log_usage, query_similar_memes

router = APIRouter()


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/")
async def chat(request: ChatRequest):
    """
    Streams SSE events as the meme is being generated:
      1. 'analyzing' — LLM is parsing the user message
      2. 'rendering'  — compositor is drawing the meme
      3. 'done'       — full ChatResponse payload
    """
    async def event_stream():
        conversation_id = request.conversation_id or ""

        yield _sse({
            "type": "thinking",
            "stage": "analyzing",
            "message": "Reading your vibe...",
        })

        # Retrieve recent templates from this conversation to avoid repeats
        recent = get_recent_templates(conversation_id, n=5)

        try:
            intent = await parse_intent(request.message, avoid_templates=recent)
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})
            return

        # RAG context (informational — logged but not yet used in prompt)
        query_similar_memes(request.message, n_results=3)

        friendly_name = intent.template_id.replace("_", " ")
        yield _sse({
            "type": "thinking",
            "stage": "rendering",
            "template_id": intent.template_id,
            "message": f"Crafting the perfect {friendly_name} meme...",
        })

        try:
            meme_url = await compose_meme(
                template_id=intent.template_id,
                texts=intent.texts,
            )
        except FileNotFoundError as exc:
            yield _sse({"type": "error", "message": f"Template not found: {exc}"})
            return

        add_turn(conversation_id, intent.template_id)

        log_usage(
            template_id=intent.template_id,
            top_text=next(iter(intent.texts.values()), ""),
            bottom_text=list(intent.texts.values())[-1] if len(intent.texts) > 1 else "",
            conversation_id=conversation_id,
        )

        reply = ChatMessage(role="assistant", content="", meme_url=meme_url)
        response = ChatResponse(
            conversation_id=conversation_id,
            message=reply,
            template_used=intent.template_id,
        )

        yield _sse({"type": "done", **response.model_dump()})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
