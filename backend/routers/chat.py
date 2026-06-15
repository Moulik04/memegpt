from fastapi import APIRouter, HTTPException

from image_processing.compositor import compose_meme
from nlp.intent_router import parse_intent
from schemas import ChatRequest, ChatResponse, ChatMessage
from vector_db.chroma_client import log_usage, query_similar_memes

router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Main conversational endpoint.

    Flow:
      1. NLP layer parses the user message into a structured IntentResponse
         with per-template text box labels (e.g. rejected_option, approved_option).
      2. ChromaDB is queried for contextually similar past memes (RAG context).
      3. Pillow compositor renders the meme using the template's layout config.
      4. Usage is logged back to ChromaDB for future retrieval.
    """
    intent = await parse_intent(request.message)

    _context = query_similar_memes(request.message, n_results=3)

    try:
        meme_url = await compose_meme(
            template_id=intent.template_id,
            texts=intent.texts,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    log_usage(
        template_id=intent.template_id,
        top_text=next(iter(intent.texts.values()), ""),
        bottom_text=list(intent.texts.values())[-1] if len(intent.texts) > 1 else "",
        conversation_id=request.conversation_id or "",
    )

    reply = ChatMessage(
        role="assistant",
        content="",       # frontend shows only the meme image
        meme_url=meme_url,
    )

    return ChatResponse(
        conversation_id=request.conversation_id or "",
        message=reply,
        template_used=intent.template_id,
    )
